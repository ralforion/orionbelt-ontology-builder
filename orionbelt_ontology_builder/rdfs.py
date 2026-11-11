"""The RDFS closure, computed natively instead of by owlrl.

owlrl applies its rules by walking every triple of the graph once per cycle,
cycling until a cycle adds nothing, and the app repeats that until a whole
run adds nothing (see ``reason_to_fixpoint``). Before each run it also pairs
every literal with every other one. On a 43k-triple ontology one RDFS run
took about 100 s, and the full closure 160 s.

This computes the same closure with a worklist: each triple, given or
derived, is joined once against indexes of the triples before it, in each
role it can play in each rule. That is the usual semi-naive evaluation, and
it reaches the same least fixpoint, since every rule here joins at most two
triples. The rules are owlrl's ``RDFS_Semantics`` as the app runs it, with
no axiomatic triples:

* rdf1: the predicate of every triple is an ``rdf:Property``;
* rdfs2, rdfs3: a property's domain and range type its subjects and objects;
* rdfs4a, rdfs4b: everything a triple mentions is an ``rdfs:Resource``;
* rdfs5, rdfs11: ``subPropertyOf`` and ``subClassOf`` are transitive;
* rdfs6, rdfs10: a property and a class are each their own sub-property and
  subclass;
* rdfs7, rdfs9: a triple holds of every super-property, an instance of
  every superclass;
* rdfs8, rdfs12, rdfs13: a class is a subclass of ``rdfs:Resource``, a
  container membership property a sub-property of ``rdfs:member``, a
  datatype a subclass of ``rdfs:Literal``;
* owlrl's "hidden sameAs" on literals: a triple whose object is a literal is
  copied to every other literal object with an equal ``Literal.value``.
  That compares Python values, so ``"abc"``, ``"abc"@en`` and
  ``"abc"^^xsd:string`` count as one, and so do ``1``, ``1.0`` and
  ``true``. It is kept, so the closure stays the one owlrl computes.

``lean`` leaves out what every RDFS graph implies whatever it says: rdf1,
rdfs4a/b, rdfs6, rdfs8, rdfs10 and the literal copies. Those are most of
what a closure adds (typing every node an ``rdfs:Resource`` and every
predicate an ``rdf:Property``), and an editor that writes them into the
ontology buries what the ontology's own terms imply: types from domains,
ranges and superclasses, and the closed hierarchies.

A derived triple with a literal predicate is dropped, as owlrl drops it, and
so are triples with a literal subject, which no RDF syntax can write (the
app drops those after an owlrl run too). tests/test_rdfs.py checks the
result against owlrl run to a fixpoint on the bundled samples.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any

from rdflib import Literal
from rdflib.namespace import RDF, RDFS
from rdflib.term import Node

_Triple = tuple[Node, Node, Node]

_TYPE = RDF.type
_SUBCLASS = RDFS.subClassOf
_SUBPROPERTY = RDFS.subPropertyOf
_DOMAIN = RDFS.domain
_RANGE = RDFS.range


def rdfs_closure(triples: Iterable[_Triple], *, lean: bool = False) -> set[_Triple]:
    """The triples RDFS entailment adds to ``triples``, as owlrl's RDFS run to
    a fixpoint adds them, or with ``lean`` only what the ontology's own terms
    imply (see the module docstring)."""
    known: set[_Triple] = set()
    queue: deque[_Triple] = deque()

    def add(triple: _Triple) -> None:
        if triple not in known and not isinstance(triple[1], Literal):
            known.add(triple)
            queue.append(triple)

    for triple in triples:
        add(triple)
    given = set(known)

    by_predicate: defaultdict[Node, set[tuple[Node, Node]]] = defaultdict(set)
    domains: defaultdict[Node, set[Node]] = defaultdict(set)
    ranges: defaultdict[Node, set[Node]] = defaultdict(set)
    super_properties: defaultdict[Node, set[Node]] = defaultdict(set)
    sub_properties: defaultdict[Node, set[Node]] = defaultdict(set)
    super_classes: defaultdict[Node, set[Node]] = defaultdict(set)
    sub_classes: defaultdict[Node, set[Node]] = defaultdict(set)
    instances: defaultdict[Node, set[Node]] = defaultdict(set)
    pointing_at: defaultdict[Literal, set[tuple[Node, Node]]] = defaultdict(set)
    equal_literals = _EqualLiterals()

    while queue:
        s, p, o = queue.popleft()
        if not lean:
            add((p, _TYPE, RDF.Property))  # rdf1
            add((s, _TYPE, RDFS.Resource))  # rdfs4a
            add((o, _TYPE, RDFS.Resource))  # rdfs4b
        by_predicate[p].add((s, o))

        # rdfs2, rdfs3: this triple as the declaration, then as the data.
        if p == _DOMAIN:
            domains[s].add(o)
            for subject, _ in list(by_predicate[s]):
                add((subject, _TYPE, o))
        if p == _RANGE:
            ranges[s].add(o)
            for _, obj in list(by_predicate[s]):
                add((obj, _TYPE, o))
        for cls in domains[p]:
            add((s, _TYPE, cls))
        for cls in ranges[p]:
            add((o, _TYPE, cls))

        # rdfs5, rdfs7: this triple as the hierarchy, then as the data.
        if p == _SUBPROPERTY:
            super_properties[s].add(o)
            sub_properties[o].add(s)
            for above in list(super_properties[o]):
                add((s, _SUBPROPERTY, above))
            for below in list(sub_properties[s]):
                add((below, _SUBPROPERTY, o))
            for subject, obj in list(by_predicate[s]):
                add((subject, o, obj))
        for above in list(super_properties[p]):
            add((s, above, o))

        if p == _TYPE:
            instances[o].add(s)
            if o == RDF.Property and not lean:
                add((s, _SUBPROPERTY, s))  # rdfs6
            elif o == RDFS.Class and not lean:
                add((s, _SUBCLASS, RDFS.Resource))  # rdfs8
                add((s, _SUBCLASS, s))  # rdfs10
            elif o == RDFS.ContainerMembershipProperty:
                add((s, _SUBPROPERTY, RDFS.member))  # rdfs12
            elif o == RDFS.Datatype:
                add((s, _SUBCLASS, RDFS.Literal))  # rdfs13
            for above in list(super_classes[o]):
                add((s, _TYPE, above))  # rdfs9, as the instance

        # rdfs9, rdfs11: this triple as the hierarchy.
        if p == _SUBCLASS:
            super_classes[s].add(o)
            sub_classes[o].add(s)
            for instance in list(instances[s]):
                add((instance, _TYPE, o))
            for above in list(super_classes[o]):
                add((s, _SUBCLASS, above))
            for below in list(sub_classes[s]):
                add((below, _SUBCLASS, o))

        # owlrl's sameAs on literals of equal value.
        if isinstance(o, Literal) and not lean:
            pointing_at[o].add((s, p))
            newcomer, others = equal_literals.join(o)
            for other in others:
                add((s, p, other))
                if newcomer:
                    for subject, predicate in list(pointing_at[other]):
                        add((subject, predicate, o))

    return {t for t in known - given if not isinstance(t[0], Literal)}


class _EqualLiterals:
    """Literals grouped by ``Literal.value``, as owlrl compares them.

    owlrl pairs every literal with every other one and compares their values
    with ``==``. Grouping by value does that in linear time: values that are
    equal hash alike, across ``int``, ``float``, ``Decimal`` and ``bool`` too.
    A value that cannot be hashed is compared one by one, as owlrl would.
    """

    def __init__(self) -> None:
        self._groups: dict[Any, list[Literal]] = {}
        self._unhashable: list[Literal] = []
        self._seen: set[Literal] = set()

    def join(self, literal: Literal) -> tuple[bool, list[Literal]]:
        """Note ``literal``; return whether it is new, and the others of equal
        value."""
        value = literal.value
        if value is None:
            return False, []
        newcomer = literal not in self._seen
        try:
            group = self._groups.setdefault(value, [])
        except TypeError:
            group = [other for other in self._unhashable if other.value == value]
            if newcomer:
                self._unhashable.append(literal)
        else:
            if newcomer:
                group.append(literal)
        self._seen.add(literal)
        return newcomer, [other for other in group if other != literal]

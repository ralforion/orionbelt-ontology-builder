"""What the rules share, worked out once per run.

Most of all, *which resources are this ontology's own*. An ontology that merged
gist in is not the place to report gist's modelling, so by default a rule only
looks at the ontology's own classes and properties (``include_imports`` turns
that off). And *how classes connect*: real ontologies state much of their
structure through anonymous class expressions, which a reading of plain
``rdfs:subClassOf`` edges misses.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from functools import cached_property
from typing import TYPE_CHECKING, Any

from rdflib import BNode, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS
from rdflib.term import Node

from ..ontology_manager import _DOMAIN_INCLUDES, _RANGE_INCLUDES
from .models import QualityFinding, Severity
from .registry import OWL_PROFILE, SKOS_PROFILE

if TYPE_CHECKING:
    from ..ontology_manager import OntologyManager

_KIND_BY_TYPE = {
    OWL.Class: "Class",
    OWL.ObjectProperty: "Object Property",
    OWL.DatatypeProperty: "Data Property",
}

#: Where an anonymous class expression names a class: a restriction's filler,
#: a complement, or a member of an intersection or union list.
_EXPRESSION_TARGETS = (
    OWL.someValuesFrom,
    OWL.allValuesFrom,
    OWL.onClass,
    OWL.complementOf,
    RDF.first,
)

#: How a named class is tied to an anonymous expression that names others:
#: through a subclass or equivalence axiom, or (OWL 1 style) by being defined
#: as an intersection, union or complement itself.
_EXPRESSION_LINKS = (
    RDFS.subClassOf,
    OWL.equivalentClass,
    OWL.intersectionOf,
    OWL.unionOf,
    OWL.complementOf,
)


class QualityContext:
    """What several checks share, worked out once per run."""

    def __init__(self, ont: OntologyManager, include_imports: bool = False):
        self.ont = ont
        self.graph = ont.graph
        self.include_imports = include_imports

    @cached_property
    def vocabularies(self) -> frozenset[str]:
        """Which vocabularies the graph uses, for rule applicability."""
        used = set()
        if any(
            True
            for rdf_type in (*_KIND_BY_TYPE, RDFS.Class)
            for _ in self.graph.subjects(RDF.type, rdf_type)
        ):
            used.add(OWL_PROFILE)
        if next(self.graph.subjects(RDF.type, SKOS.Concept), None) is not None:
            used.add(SKOS_PROFILE)
        return frozenset(used)

    def finding(
        self,
        rule_id: str,
        severity: Severity,
        uri: str,
        message: str,
        *,
        evidence: dict[str, Any] | None = None,
        suggestion: str | None = None,
        related: Iterable[str] = (),
    ) -> QualityFinding:
        return QualityFinding(
            rule_id=rule_id,
            severity=severity,
            resource=uri,
            resource_kind=self.kind(uri),
            message=message,
            evidence=evidence or {},
            suggestion=suggestion,
            related_resources=tuple(related),
        )

    def in_scope(self, uri: str) -> bool:
        """Whether ``uri`` belongs to the ontology being assessed.

        An ontology that merged gist in is not the place to report gist's
        modelling, so by default only its own entities count: those in its
        base namespace, and those ``rdfs:isDefinedBy`` the ontology. A merge
        records nowhere where a triple came from, so this is what there is to
        go on. When it matches nothing at all (gist itself names its ontology
        ``…/ontology/gistCore`` but its classes ``…/ns/ontology/gist/…``),
        the whole graph is the ontology.
        """
        if self.include_imports or not self._has_own_entities:
            return True
        return self._is_own(uri)

    @cached_property
    def _defined_here(self) -> set[str]:
        return {
            str(s) for s in self.graph.subjects(RDFS.isDefinedBy, self.ont.ontology_uri)
        }

    def _is_own(self, uri: str) -> bool:
        return uri.startswith(self.ont.base_uri) or uri in self._defined_here

    @cached_property
    def _has_own_entities(self) -> bool:
        return any(
            isinstance(s, URIRef) and self._is_own(str(s))
            for rdf_type in _KIND_BY_TYPE
            for s in self.graph.subjects(RDF.type, rdf_type)
        )

    def _declared(self, rdf_type: URIRef) -> set[str]:
        return {
            str(s)
            for s in self.graph.subjects(RDF.type, rdf_type)
            if isinstance(s, URIRef) and self.in_scope(str(s))
        }

    @cached_property
    def classes(self) -> set[str]:
        """Named, in-scope ``owl:Class`` declarations."""
        return self._declared(OWL.Class)

    @cached_property
    def properties(self) -> set[str]:
        """Named, in-scope object and data properties."""
        return self._declared(OWL.ObjectProperty) | self._declared(OWL.DatatypeProperty)

    @cached_property
    def parents(self) -> dict[str, list[str]]:
        """``child -> named parents`` over ``rdfs:subClassOf``, ``owl:Thing`` left out.

        Every class is a subclass of ``owl:Thing``, so saying so is neither a
        second parent nor a link to anything.
        """
        thing = str(OWL.Thing)
        return {
            child: [p for p in ps if p != thing]
            for child, ps in self.ont._class_parent_map().items()
            if child != thing
        }

    @cached_property
    def in_hierarchy(self) -> set[str]:
        """Classes with a named superclass or subclass.

        A named member of an intersection counts as a superclass: ``A ≡ B ⊓ R``
        makes ``B`` a superclass of ``A`` as surely as ``A ⊑ B`` does, and gist
        states most of its hierarchy that way.
        """
        result: set[str] = set()
        for child, ps in self.parents.items():
            if ps:
                result.add(child)
                result.update(ps)
        for cls, members in self._intersections():
            named = [str(m) for m in self.graph.items(members) if isinstance(m, URIRef)]
            if named:
                result.add(str(cls))
                result.update(named)
        return result

    def _intersections(self) -> Iterator[tuple[URIRef, Node]]:
        """``(class, intersection list)`` for each intersection a class is defined by.

        Stated through ``owl:equivalentClass`` or ``rdfs:subClassOf`` to an
        anonymous class, or, OWL 1 style as in the wine ontology, straight on
        the named class.
        """
        for cls, members in self.graph.subject_objects(OWL.intersectionOf):
            if isinstance(cls, URIRef):
                yield cls, members
        for pred in (RDFS.subClassOf, OWL.equivalentClass):
            for cls, expression in self.graph.subject_objects(pred):
                if isinstance(cls, URIRef) and isinstance(expression, BNode):
                    for members in self.graph.objects(expression, OWL.intersectionOf):
                        yield cls, members

    @cached_property
    def cycle_members(self) -> set[str]:
        return {uri for cycle in self.ont._cycles_in(self.parents) for uri in cycle}

    @cached_property
    def names(self) -> dict[str, str]:
        """URI -> display name, unique among every class and property in the graph."""
        uris: set[str] = set(self.parents)
        for rdf_type in _KIND_BY_TYPE:
            uris.update(
                str(s)
                for s in self.graph.subjects(RDF.type, rdf_type)
                if isinstance(s, URIRef)
            )
        return self.ont._display_names(uris)

    def name(self, uri: str) -> str:
        return self.names.get(uri) or self.ont._local_name(URIRef(uri))

    def kind(self, uri: str) -> str:
        for rdf_type, kind in _KIND_BY_TYPE.items():
            if (URIRef(uri), RDF.type, rdf_type) in self.graph:
                return kind
        return "Class"

    @cached_property
    def validation_issues(self) -> list[dict[str, str]]:
        """``validate()``'s findings, for the checks that reuse them."""
        return self.ont.validate(check_missing_domain_range=True)

    def _class_targets(self, subject, predicates: Iterable[URIRef]) -> set[str]:
        """The named classes ``subject`` points at, through anonymous ones too.

        GoodRelations, for one, states a domain as an ``owl:unionOf`` list.
        """
        targets: set[str] = set()
        for pred in predicates:
            for obj in self.graph.objects(subject, pred):
                if isinstance(obj, URIRef):
                    targets.add(str(obj))
                elif isinstance(obj, BNode):
                    targets |= self._expression_targets(obj)
        return targets

    def domains(self, prop: URIRef) -> set[str]:
        return self._class_targets(prop, (RDFS.domain, *_DOMAIN_INCLUDES))

    def ranges(self, prop: URIRef) -> set[str]:
        return self._class_targets(prop, (RDFS.range, *_RANGE_INCLUDES))

    def _expression_targets(self, expression: BNode) -> set[str]:
        """Every named class an anonymous class expression mentions."""
        targets: set[str] = set()
        seen = {expression}
        queue = deque([expression])
        while queue:
            node = queue.popleft()
            for pred, obj in self.graph.predicate_objects(node):
                if isinstance(obj, BNode):
                    if obj not in seen:
                        seen.add(obj)
                        queue.append(obj)
                elif isinstance(obj, URIRef) and pred in _EXPRESSION_TARGETS:
                    targets.add(str(obj))
        return targets

    @cached_property
    def class_links(self) -> list[tuple[str, str]]:
        """Pairs of named classes the ontology connects other than by hierarchy.

        An object property links its domain to its range, an equivalence links
        its two sides, and an anonymous class expression (a restriction, an
        intersection, a union, nested to any depth) links the class it is
        stated on to every class it names. gist states most of its hierarchy
        that way, as ``owl:equivalentClass`` intersections.
        """
        links: list[tuple[str, str]] = []
        for prop in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            if isinstance(prop, URIRef):
                links += [(d, r) for d in self.domains(prop) for r in self.ranges(prop)]
        for a, b in self.graph.subject_objects(OWL.equivalentClass):
            if isinstance(a, URIRef) and isinstance(b, URIRef):
                links.append((str(a), str(b)))
        for pred in _EXPRESSION_LINKS:
            for cls, expression in self.graph.subject_objects(pred):
                if isinstance(cls, URIRef) and isinstance(expression, BNode):
                    links += [
                        (str(cls), target)
                        for target in self._expression_targets(expression)
                    ]
        return links

"""SHACL shapes derived from the ontology's own axioms (issue #498).

Most useful shapes follow from what the model already says: a cardinality
restriction is a minimum and maximum count, an existential restriction a
qualified count of one, a universal restriction a class every value must have.
Deriving them each time a check runs leaves nothing to keep in sync: the model
is the single statement, and the shapes are its closed-world reading.

Every constraint carries a message naming the axiom it comes from, so a
violation says which part of the model the data does not meet.

What is derived:

| In the ontology                         | Generated constraint                         |
|-----------------------------------------|----------------------------------------------|
| min / max / exact cardinality           | ``sh:minCount`` / ``sh:maxCount``            |
| the same, qualified (onClass / onDataRange) | qualified value shape with qualified counts |
| ``someValuesFrom``                      | qualified value shape, ``qualifiedMinCount 1`` |
| ``allValuesFrom``                       | ``sh:class`` or ``sh:datatype``              |
| ``hasValue``                            | ``sh:hasValue``                              |
| functional property                     | ``sh:maxCount 1`` on every subject using it  |
| property range                          | ``sh:class`` or ``sh:datatype``              |

Restrictions count however they are made necessary: ``A ⊑ E``, ``A ≡ E`` in
either orientation, or ``A`` defined as an intersection itself, with
intersections walked to any depth (``A ≡ B ⊓ ∃p.C`` makes ``∃p.C`` necessary
for ``A`` as surely as ``A ⊑ ∃p.C`` does). A datatype admits its whole value
space: ``xsd:integer`` accepts an ``xsd:int`` literal, ``owl:real`` any decimal
type. Anything the generator cannot express faithfully (a union filler, a
user-defined datatype, a property chain) is left out rather than approximated.
"""

from __future__ import annotations

from collections.abc import Iterator

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.term import Node

from .shacl import SH, _list_items

_BUILTIN_DATA_RANGES = {
    RDFS.Literal,
    RDF.langString,
    RDF.PlainLiteral,
    RDF.XMLLiteral,
    RDF.HTML,
    OWL.real,
    OWL.rational,
}

#: The built-in XSD datatypes derived from another, by restriction (XSD 1.1
#: Part 2, section 3). A value of a derived type is a value of its base, so a
#: check for the base must accept it: ``"3"^^xsd:int`` is an ``xsd:integer``.
_XSD_DERIVED: dict[URIRef, tuple[URIRef, ...]] = {
    XSD.decimal: (XSD.integer,),
    XSD.integer: (XSD.nonPositiveInteger, XSD.long, XSD.nonNegativeInteger),
    XSD.nonPositiveInteger: (XSD.negativeInteger,),
    XSD.long: (XSD.int,),
    XSD.int: (XSD.short,),
    XSD.short: (XSD.byte,),
    XSD.nonNegativeInteger: (XSD.unsignedLong, XSD.positiveInteger),
    XSD.unsignedLong: (XSD.unsignedInt,),
    XSD.unsignedInt: (XSD.unsignedShort,),
    XSD.unsignedShort: (XSD.unsignedByte,),
    XSD.string: (XSD.normalizedString,),
    XSD.normalizedString: (XSD.token,),
    XSD.token: (XSD.language, XSD.Name, XSD.NMTOKEN),
    XSD.Name: (XSD.NCName,),
    XSD.NCName: (XSD.ID, XSD.IDREF, XSD.ENTITY),
    XSD.dateTime: (XSD.dateTimeStamp,),
    XSD.duration: (XSD.dayTimeDuration, XSD.yearMonthDuration),
}

#: A datatype whose value space is "every literal": checked by node kind.
ANY_LITERAL = "any literal"


def _with_derived(datatype: URIRef) -> set[URIRef]:
    found = {datatype}
    frontier = [datatype]
    while frontier:
        for child in _XSD_DERIVED.get(frontier.pop(), ()):
            if child not in found:
                found.add(child)
                frontier.append(child)
    return found


def accepted_datatypes(graph: Graph, datatype: URIRef) -> set[URIRef] | str | None:
    """The datatype IRIs whose literals lie in ``datatype``'s value space.

    ``ANY_LITERAL`` for ``rdfs:Literal``; ``None`` for a datatype this cannot
    map faithfully (a user-defined one, whose definition it does not read), so
    the caller leaves the constraint out rather than misreading it. OWL 2's
    numeric types nest: ``owl:real`` holds ``owl:rational`` holds every
    ``xsd:decimal`` type (but not ``xsd:double`` or ``xsd:float``, whose value
    spaces OWL 2 keeps apart).
    """
    if datatype == RDFS.Literal:
        return ANY_LITERAL
    if datatype == OWL.real:
        return {OWL.real, OWL.rational} | _with_derived(XSD.decimal)
    if datatype == OWL.rational:
        return {OWL.rational} | _with_derived(XSD.decimal)
    if datatype == RDF.PlainLiteral:
        return {RDF.PlainLiteral, RDF.langString} | _with_derived(XSD.string)
    if str(datatype).startswith(str(XSD)) or datatype in _BUILTIN_DATA_RANGES:
        return _with_derived(datatype)
    return None


_CARDINALITIES = {
    OWL.minCardinality: ("min", None),
    OWL.maxCardinality: ("max", None),
    OWL.cardinality: ("exact", None),
    OWL.minQualifiedCardinality: ("min", "qualified"),
    OWL.maxQualifiedCardinality: ("max", "qualified"),
    OWL.qualifiedCardinality: ("exact", "qualified"),
}


def _short(graph: Graph, node: Node) -> str:
    if isinstance(node, URIRef):
        try:
            short = graph.namespace_manager.normalizeUri(node)
        except Exception:  # noqa: BLE001 - a display name must not fail
            short = f"<{node}>"
        if not short.startswith("<"):
            return short
        return str(node).rstrip("#/").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return "an anonymous class"


def _is_data_range(graph: Graph, node: Node) -> bool:
    """A datatype: built in, or declared ``rdfs:Datatype``. Not a class."""
    return isinstance(node, URIRef) and (
        str(node).startswith(str(XSD))
        or node in _BUILTIN_DATA_RANGES
        or (node, RDF.type, RDFS.Datatype) in graph
    )


def _count(value: Node) -> int | None:
    try:
        number = int(str(value))
    except ValueError:
        return None
    return number if number >= 0 else None


class _Generator:
    def __init__(self, model: Graph):
        self.model = model
        self.out = Graph()
        for prefix, namespace in model.namespaces():
            self.out.bind(prefix, namespace, override=True)
        self.out.bind("sh", SH)
        self.node_shapes: dict[Node, BNode] = {}
        self.count = 0

    # -- helpers -------------------------------------------------------------

    def name(self, node: Node) -> str:
        return _short(self.model, node)

    def node_shape(self, cls: Node) -> BNode:
        """The node shape targeting ``cls``, created on first use."""
        shape = self.node_shapes.get(cls)
        if shape is None:
            shape = BNode()
            self.out.add((shape, RDF.type, SH.NodeShape))
            self.out.add((shape, SH.targetClass, cls))
            self.out.add(
                (shape, RDFS.label, Literal(f"Generated from {self.name(cls)}"))
            )
            self.node_shapes[cls] = shape
        return shape

    def path(self, prop: Node) -> Node | None:
        """A SHACL path for a property expression: a property, or its inverse."""
        if isinstance(prop, URIRef):
            return prop
        inverse = self.model.value(prop, OWL.inverseOf)
        if isinstance(inverse, URIRef):
            path = BNode()
            self.out.add((path, SH.inversePath, inverse))
            return path
        return None

    def prop_name(self, prop: Node) -> str:
        if isinstance(prop, URIRef):
            return self.name(prop)
        inverse = self.model.value(prop, OWL.inverseOf)
        return f"inverse {self.name(inverse)}" if inverse is not None else "a property"

    def supported(self, filler: Node) -> bool:
        """Whether a value constraint for ``filler`` can be stated faithfully."""
        if not isinstance(filler, URIRef) or filler == OWL.Thing:
            return False
        if _is_data_range(self.model, filler):
            return accepted_datatypes(self.model, filler) is not None
        return True

    def constrain(self, node: Node, filler: Node) -> None:
        """Make every value of ``node`` (a property or value shape) be of
        ``filler``: its class, or its datatype's whole value space. Only for a
        ``filler`` :meth:`supported` accepts."""
        if not isinstance(filler, URIRef):
            return
        if not _is_data_range(self.model, filler):
            self.out.add((node, SH["class"], filler))
            return
        accepted = accepted_datatypes(self.model, filler)
        if accepted == ANY_LITERAL:
            self.out.add((node, SH.nodeKind, SH.Literal))
        elif isinstance(accepted, set) and len(accepted) == 1:
            self.out.add((node, SH.datatype, next(iter(accepted))))
        elif isinstance(accepted, set):
            alternatives: list[Node] = []
            for datatype in sorted(accepted, key=str):
                alternative = BNode()
                self.out.add((alternative, SH.datatype, datatype))
                alternatives.append(alternative)
            head = BNode()
            Collection(self.out, head, alternatives)
            self.out.add((node, SH["or"], head))

    def value_shape(self, filler: Node) -> BNode | None:
        """A shape a value has to meet to be of ``filler``, or None."""
        if not self.supported(filler):
            return None
        shape = BNode()
        self.constrain(shape, filler)
        return shape

    def property_shape(
        self, owner: BNode, path: Node, message: str, description: str
    ) -> BNode:
        prop = BNode()
        self.out.add((owner, SH.property, prop))
        self.out.add((prop, SH.path, path))
        self.out.add((prop, SH.message, Literal(message)))
        self.out.add((prop, SH.description, Literal(description)))
        self.count += 1
        return prop

    # -- what the model says ---------------------------------------------------

    def restrictions(self) -> Iterator[tuple[Node, Node]]:
        """``(class, restriction)`` for every restriction a named class must meet.

        Necessary conditions come from ``C ⊑ E``, from ``C ≡ E`` stated either
        way round, and from a class defined as an intersection itself (OWL 1
        style); an intersection makes each of its members necessary, nested
        to any depth.
        """
        necessary: list[tuple[Node, Node]] = []
        for cls, expr in self.model.subject_objects(RDFS.subClassOf):
            if isinstance(cls, URIRef) and isinstance(expr, BNode):
                necessary.append((cls, expr))
        for a, b in self.model.subject_objects(OWL.equivalentClass):
            if isinstance(a, URIRef) and isinstance(b, BNode):
                necessary.append((a, b))
            elif isinstance(b, URIRef) and isinstance(a, BNode):
                necessary.append((b, a))
        for cls, members in self.model.subject_objects(OWL.intersectionOf):
            if isinstance(cls, URIRef):
                for member in _list_items(self.model, members):
                    if isinstance(member, BNode):
                        necessary.append((cls, member))
        seen: set[tuple[Node, Node]] = set()
        for cls, expr in necessary:
            yield from self._flatten(cls, expr, seen)

    def _flatten(
        self, cls: Node, expr: Node, seen: set[tuple[Node, Node]]
    ) -> Iterator[tuple[Node, Node]]:
        if (cls, expr) in seen:
            return
        seen.add((cls, expr))
        if (expr, OWL.onProperty, None) in self.model:
            yield cls, expr
            return
        for members in self.model.objects(expr, OWL.intersectionOf):
            for member in _list_items(self.model, members):
                if isinstance(member, BNode):
                    yield from self._flatten(cls, member, seen)

    def restriction(self, cls: Node, restriction: Node) -> None:
        prop = self.model.value(restriction, OWL.onProperty)
        if prop is None:
            return
        path = self.path(prop)
        if path is None:
            return
        who, what = self.name(cls), self.prop_name(prop)
        owner = self.node_shape(cls)

        some = self.model.value(restriction, OWL.someValuesFrom)
        if some is not None:
            value = self.value_shape(some)
            if value is not None:
                p = self.property_shape(
                    owner,
                    path,
                    f"'{who}' needs at least one {what} that is {self.name(some)}.",
                    f"From {who} ⊑ {what} some {self.name(some)}.",
                )
                self.out.add((p, SH.qualifiedValueShape, value))
                self.out.add((p, SH.qualifiedMinCount, Literal(1)))
            return

        every = self.model.value(restriction, OWL.allValuesFrom)
        if every is not None:
            if not self.supported(every):
                return
            p = self.property_shape(
                owner,
                path,
                f"Every {what} of '{who}' must be {self.name(every)}.",
                f"From {who} ⊑ {what} only {self.name(every)}.",
            )
            self.constrain(p, every)
            return

        required = self.model.value(restriction, OWL.hasValue)
        if required is not None:
            shown = self.name(required) if isinstance(required, URIRef) else required
            p = self.property_shape(
                owner,
                path,
                f"'{who}' must have {what} {shown}.",
                f"From {who} ⊑ {what} value {shown}.",
            )
            self.out.add((p, SH.hasValue, required))
            return

        for pred, (kind, qualified) in _CARDINALITIES.items():
            raw = self.model.value(restriction, pred)
            if raw is None:
                continue
            n = _count(raw)
            if n is None:
                return
            filler: Node | None = None
            qualifier: BNode | None = None
            if qualified:
                filler = self.model.value(restriction, OWL.onClass) or self.model.value(
                    restriction, OWL.onDataRange
                )
                qualifier = self.value_shape(filler) if filler is not None else None
                if qualifier is None:
                    return
            of = f" {self.name(filler)}" if filler is not None else ""
            phrase = {"min": "at least", "max": "at most", "exact": "exactly"}[kind]
            p = self.property_shape(
                owner,
                path,
                f"'{who}' needs {phrase} {n} {what}{of}.",
                f"From {who} ⊑ {what} {kind} {n}{of}.",
            )
            if qualifier is not None:
                self.out.add((p, SH.qualifiedValueShape, qualifier))
                if kind in ("min", "exact"):
                    self.out.add((p, SH.qualifiedMinCount, Literal(n)))
                if kind in ("max", "exact"):
                    self.out.add((p, SH.qualifiedMaxCount, Literal(n)))
            else:
                if kind in ("min", "exact"):
                    self.out.add((p, SH.minCount, Literal(n)))
                if kind in ("max", "exact"):
                    self.out.add((p, SH.maxCount, Literal(n)))
            return

    def property_axioms(self) -> None:
        """Functional properties and ranges, checked on whoever uses the property."""
        # Every subject of rdfs:range, typed or not: a range applies to a
        # property whatever it is declared as (FOAF types several only as
        # rdf:Property).
        props = {
            p
            for p in self.model.subjects(RDF.type, OWL.FunctionalProperty)
            if isinstance(p, URIRef)
        } | {p for p in self.model.subjects(RDFS.range, None) if isinstance(p, URIRef)}
        for prop in sorted(props, key=str):
            functional = (prop, RDF.type, OWL.FunctionalProperty) in self.model
            ranges = [
                r for r in self.model.objects(prop, RDFS.range) if self.supported(r)
            ]
            if not functional and not ranges:
                continue
            name = self.name(prop)
            shape = BNode()
            self.out.add((shape, RDF.type, SH.NodeShape))
            self.out.add((shape, SH.targetSubjectsOf, prop))
            self.out.add((shape, RDFS.label, Literal(f"Generated from {name}")))
            if functional:
                p = self.property_shape(
                    shape,
                    prop,
                    f"{name} is functional: at most one value.",
                    f"From {name} being a functional property.",
                )
                self.out.add((p, SH.maxCount, Literal(1)))
            for rng in ranges:
                p = self.property_shape(
                    shape,
                    prop,
                    f"Every value of {name} must be {self.name(rng)}.",
                    f"From the range of {name}: {self.name(rng)}.",
                )
                self.constrain(p, rng)


def generate_shapes(model: Graph) -> Graph:
    """The closed-world shapes the ontology's axioms imply (see the module)."""
    generator = _Generator(model)
    for cls, restriction in sorted(
        generator.restrictions(), key=lambda p: (str(p[0]), str(p[1]))
    ):
        generator.restriction(cls, restriction)
    generator.property_axioms()
    return generator.out

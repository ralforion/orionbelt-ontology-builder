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

Restrictions count whether stated through ``rdfs:subClassOf`` or as a member of
an ``owl:equivalentClass`` intersection (gist's style): ``A ≡ B ⊓ ∃p.C`` makes
``∃p.C`` necessary for ``A`` as surely as ``A ⊑ ∃p.C`` does. Anything the
generator cannot express faithfully (a union filler, a datatype restriction
with facets, a property chain) is left out rather than approximated.
"""

from __future__ import annotations

from collections.abc import Iterator

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from rdflib.term import Node

from .shacl import SH, _list_items

_BUILTIN_DATA_RANGES = {
    RDFS.Literal,
    RDF.langString,
    RDF.PlainLiteral,
    RDF.XMLLiteral,
    RDF.HTML,
}

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

    def value_shape(self, filler: Node) -> BNode | None:
        """A shape a value has to meet to be of ``filler``, or None."""
        if not isinstance(filler, URIRef) or filler == OWL.Thing:
            return None
        shape = BNode()
        if _is_data_range(self.model, filler):
            self.out.add((shape, SH.datatype, filler))
        else:
            self.out.add((shape, SH["class"], filler))
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
        """``(class, restriction)`` for every restriction a named class must meet."""
        for cls, expr in self.model.subject_objects(RDFS.subClassOf):
            if (
                isinstance(cls, URIRef)
                and (expr, RDF.type, OWL.Restriction) in self.model
            ):
                yield cls, expr
        for cls, expr in self.model.subject_objects(OWL.equivalentClass):
            if not isinstance(cls, URIRef) or not isinstance(expr, BNode):
                continue
            if (expr, RDF.type, OWL.Restriction) in self.model:
                yield cls, expr
            for members in self.model.objects(expr, OWL.intersectionOf):
                for member in _list_items(self.model, members):
                    if (member, RDF.type, OWL.Restriction) in self.model:
                        yield cls, member

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
            if not isinstance(every, URIRef) or every == OWL.Thing:
                return
            p = self.property_shape(
                owner,
                path,
                f"Every {what} of '{who}' must be {self.name(every)}.",
                f"From {who} ⊑ {what} only {self.name(every)}.",
            )
            if _is_data_range(self.model, every):
                self.out.add((p, SH.datatype, every))
            else:
                self.out.add((p, SH["class"], every))
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
        props = {
            p
            for t in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.FunctionalProperty)
            for p in self.model.subjects(RDF.type, t)
            if isinstance(p, URIRef)
        }
        for prop in sorted(props, key=str):
            functional = (prop, RDF.type, OWL.FunctionalProperty) in self.model
            ranges = [
                r
                for r in self.model.objects(prop, RDFS.range)
                if isinstance(r, URIRef) and r != OWL.Thing
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
                if _is_data_range(self.model, rng):
                    self.out.add((p, SH.datatype, rng))
                else:
                    self.out.add((p, SH["class"], rng))


def generate_shapes(model: Graph) -> Graph:
    """The closed-world shapes the ontology's axioms imply (see the module)."""
    generator = _Generator(model)
    for cls, restriction in sorted(
        generator.restrictions(), key=lambda p: (str(p[0]), str(p[1]))
    ):
        generator.restriction(cls, restriction)
    generator.property_axioms()
    return generator.out

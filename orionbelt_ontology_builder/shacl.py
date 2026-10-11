"""SHACL: shapes kept in the ontology, shapes added to it, and checks against them.

SHACL is closed-world validation of *data*: a missing value is a violation,
where the quality rules and the reasoner treat it as merely unknown. So it runs
only when asked, and its findings are labelled as what they are.

Shapes are ordinary RDF, so the ones a user adds are stored in the ontology
itself, where save, load, undo, autosave and export already handle them. A
check splits the graph in two first: the shapes, and the data they check. The
shapes are never validated as data.

Runs are bounded: a deadline on every triple lookup (the SPARQL console's store
proxy), no ``owl:imports`` resolution, and no SHACL-SPARQL constraint that
reaches the network through ``SERVICE``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib.term import Node

from .quality.models import QualityFinding, Severity
from .sparql import QueryTimeout, _DeadlineStore

SH = Namespace("http://www.w3.org/ns/shacl#")

#: The quality rule ID SHACL findings carry.
SHACL_RULE_ID = "Q015"

DEFAULT_DEADLINE_SECONDS = 10.0

_SEVERITY: dict[Node, Severity] = {
    SH.Violation: "error",
    SH.Warning: "warning",
    SH.Info: "info",
}

#: Predicates that make an untyped node a shape (SHACL 2.1: a node with a
#: target, or a constraint parameter, is a shape).
_TARGETS = (SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf)

#: Where SHACL-SPARQL keeps query text.
_QUERY_TEXT = (SH.select, SH.ask, SH.construct, SH.update)

#: ``SERVICE <iri>`` or ``SERVICE ?var``, with or without ``SILENT``.
_SERVICE = re.compile(r"\bSERVICE\s+(?:SILENT\s+)?[<?$]", re.IGNORECASE)


class ShapesError(ValueError):
    """Shapes that cannot be added or run: unparsable, invalid, or unsafe."""


# -- finding shapes ----------------------------------------------------------


def shape_nodes(graph: Graph) -> set[Node]:
    """Every shape in ``graph``: typed ones, and untyped ones with a target."""
    nodes: set[Node] = set(graph.subjects(RDF.type, SH.NodeShape))
    nodes |= set(graph.subjects(RDF.type, SH.PropertyShape))
    for pred in _TARGETS:
        nodes |= set(graph.subjects(pred, None))
    return nodes


def _closure(graph: Graph, node: Node) -> set[tuple[Node, Node, Node]]:
    """The triples that make up one shape.

    For a named shape, only its SHACL statements and its ``rdf:type``s: a
    class that doubles as a shape (an implicit class target) keeps its
    ``rdfs:label`` and its OWL axioms as data. Everything reached through blank
    nodes from there (property shapes, ``sh:path`` sequences, ``sh:in`` lists)
    belongs to the shape.
    """
    triples: set[tuple[Node, Node, Node]] = set()
    if isinstance(node, BNode):
        frontier: list[Node] = [node]
    else:
        frontier = []
        for pred, obj in graph.predicate_objects(node):
            if str(pred).startswith(str(SH)) or pred == RDF.type:
                triples.add((node, pred, obj))
                if isinstance(obj, BNode):
                    frontier.append(obj)
    seen: set[Node] = set()
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        for pred, obj in graph.predicate_objects(current):
            triples.add((current, pred, obj))
            if isinstance(obj, BNode):
                frontier.append(obj)
    return triples


def split_shapes(graph: Graph) -> tuple[Graph, Graph]:
    """``(data, shapes)``: the shapes' triples apart from everything else.

    A named shape's ``rdf:type`` triples go to both, because a class that is
    also a node shape is validated by being a class (an implicit target) and
    is data by being a class.
    """
    shape_triples: set[tuple[Node, Node, Node]] = set()
    for node in shape_nodes(graph):
        shape_triples |= _closure(graph, node)
    data, shapes = Graph(), Graph()
    for prefix, namespace in graph.namespaces():
        data.bind(prefix, namespace, override=True)
        shapes.bind(prefix, namespace, override=True)
    for triple in graph:
        if triple in shape_triples:
            shapes.add(triple)
            if (
                triple[1] == RDF.type
                and not isinstance(triple[0], BNode)
                and triple[2] not in (SH.NodeShape, SH.PropertyShape)
            ):
                data.add(triple)
        else:
            data.add(triple)
    return data, shapes


@dataclass(frozen=True)
class ShapeInfo:
    """One top-level shape, as the shapes list shows it."""

    node: Node
    name: str
    kind: str
    targets: tuple[str, ...]
    constraints: int
    triples: int


def _short(graph: Graph, node: Node) -> str:
    if isinstance(node, URIRef):
        try:
            return graph.namespace_manager.normalizeUri(node)
        except Exception:  # noqa: BLE001 - a display name must not fail
            return str(node)
    return f"_:{node}"


def list_shapes(graph: Graph) -> list[ShapeInfo]:
    """The top-level shapes: those no other shape nests through sh:property."""
    nodes = shape_nodes(graph)
    nested = {o for o in graph.objects(None, SH.property)}
    result = []
    for node in nodes - nested:
        label = graph.value(node, RDFS.label)
        targets = tuple(
            f"{graph.namespace_manager.normalizeUri(pred).split(':')[-1]} "
            f"{_short(graph, obj)}"
            for pred in _TARGETS
            for obj in graph.objects(node, pred)
        )
        closure = _closure(graph, node)
        constraints = sum(
            1
            for _, pred, _ in closure
            if str(pred).startswith(str(SH))
            and pred not in (*_TARGETS, SH.property, SH.path, SH.name)
        )
        kind = (
            "Property shape"
            if (node, RDF.type, SH.PropertyShape) in graph
            or (node, SH.path, None) in graph
            else "Node shape"
        )
        result.append(
            ShapeInfo(
                node=node,
                name=str(label) if label else _short(graph, node),
                kind=kind,
                targets=targets,
                constraints=constraints,
                triples=len(closure),
            )
        )
    return sorted(result, key=lambda s: s.name.lower())


def shape_turtle(graph: Graph, node: Node) -> str:
    """One shape as Turtle, for reading."""
    out = Graph()
    for prefix, namespace in graph.namespaces():
        out.bind(prefix, namespace, override=True)
    for triple in _closure(graph, node):
        out.add(triple)
    return out.serialize(format="turtle")


# -- adding and removing ---------------------------------------------------------


def _refuse_network(shapes: Graph) -> None:
    for pred in _QUERY_TEXT:
        for text in shapes.objects(None, pred):
            if isinstance(text, Literal) and _SERVICE.search(str(text)):
                raise ShapesError(
                    "These shapes contain a SPARQL query using SERVICE, which would "
                    "reach out to another server. Federated queries are not "
                    "supported here."
                )


def parse_shapes(text: str, format: str = "turtle") -> Graph:
    """Parse and vet shapes before they are added or run.

    Refuses text that does not parse, holds no shape, does not conform to the
    SHACL meta-shapes (SHACL for SHACL), or would query another server.
    """
    shapes = Graph()
    try:
        shapes.parse(data=text, format=format)
    except Exception as exc:
        raise ShapesError(f"The shapes do not parse as {format}: {exc}") from exc
    if not shape_nodes(shapes):
        raise ShapesError(
            "No shapes found: expected sh:NodeShape or sh:PropertyShape resources, "
            "or nodes with a target such as sh:targetClass."
        )
    _refuse_network(shapes)
    from pyshacl import validate
    from pyshacl.errors import ReportableRuntimeError

    # A copy: the meta-shapes check mixes RDFS triples into the shapes graph it
    # is given (owl:Class rdfs:subClassOf rdfs:Class and the like), and those
    # must not ride along into the ontology.
    scratch = Graph()
    for triple in shapes:
        scratch.add(triple)
    try:
        validate(
            Graph(),
            shacl_graph=scratch,
            meta_shacl=True,
            inference="none",
            do_owl_imports=False,
            advanced=False,
            js=False,
        )
    except ReportableRuntimeError as exc:
        # pySHACL raises, rather than returning conforms=False, when the
        # shapes themselves fail SHACL-for-SHACL; its message is the report.
        report = str(exc).split("Validation Report", 1)[-1].strip()
        raise ShapesError(f"The shapes are not valid SHACL.\n\n{report}") from exc
    return shapes


def add_shapes(graph: Graph, shapes: Graph) -> int:
    """Copy ``shapes`` into ``graph``; returns how many triples were new."""
    before = len(graph)
    graph.bind("sh", SH)
    # Only prefixes for namespaces the ontology has no prefix for yet: a
    # second prefix for one namespace makes the same IRI print two ways.
    bound_prefixes = {p for p, _ in graph.namespaces()}
    bound_namespaces = {str(n) for _, n in graph.namespaces()}
    for prefix, namespace in shapes.namespaces():
        if (
            prefix
            and prefix not in bound_prefixes
            and str(namespace) not in bound_namespaces
        ):
            graph.bind(prefix, namespace)
    for triple in shapes:
        graph.add(triple)
    return len(graph) - before


def remove_shape(graph: Graph, node: Node) -> int:
    """Remove one shape, leaving anything another shape still uses.

    Its blank-node structure can be shared (one ``sh:in`` list, one nested
    property shape); triples another shape still reaches stay.
    """
    mine = _closure(graph, node)
    others: set[tuple[Node, Node, Node]] = set()
    for other in shape_nodes(graph) - {node}:
        others |= _closure(graph, other)
    removed = 0
    for triple in mine - others:
        # A class that is also a shape stays a class: only the shape typing goes.
        if triple[1] == RDF.type and triple[2] not in (SH.NodeShape, SH.PropertyShape):
            continue
        graph.remove(triple)
        removed += 1
    return removed


# -- running ---------------------------------------------------------------------


@dataclass
class ShaclRun:
    conforms: bool | None
    findings: list[QualityFinding] = field(default_factory=list)
    report: Graph | None = None
    duration_ms: float = 0.0
    #: Why the run did not complete: a timeout, or shapes pySHACL rejected.
    error: str | None = None
    shapes_checked: int = 0


def run_shacl(
    data: Graph,
    shapes: Graph,
    *,
    origin: str,
    deadline_s: float = DEFAULT_DEADLINE_SECONDS,
    kind: Callable[[str], str | None] | None = None,
    name: Callable[[str], str] | None = None,
) -> ShaclRun:
    """Validate ``data`` against ``shapes`` and map the report to findings.

    ``kind`` and ``name`` resolve a focus node for navigation and display;
    the caller has the ontology context to do that.
    """
    run = ShaclRun(conforms=None, shapes_checked=len(shape_nodes(shapes)))
    if not run.shapes_checked:
        run.conforms = True
        return run
    try:
        _refuse_network(shapes)
    except ShapesError as exc:
        run.error = str(exc)
        return run
    from pyshacl import validate

    began = time.monotonic()
    # Same identifier as the data graph: the memory store answers a lookup only
    # for the graph it is asked about, so a fresh identifier would see nothing.
    bounded = Graph(
        store=_DeadlineStore(data.store, began + deadline_s),
        identifier=data.identifier,
    )
    try:
        conforms, report, _ = validate(
            bounded,
            shacl_graph=shapes,
            inference="none",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            do_owl_imports=False,
            advanced=False,
            js=False,
        )
    except QueryTimeout:
        run.error = (
            f"The check did not finish within {deadline_s:g} seconds and was "
            "stopped. Narrow the shapes' targets, or check fewer shapes at once."
        )
        return run
    except Exception as exc:  # noqa: BLE001 - pySHACL failures are reported, not raised
        run.error = f"pySHACL could not run these shapes: {exc}"
        return run
    finally:
        run.duration_ms = (time.monotonic() - began) * 1000
    run.conforms = bool(conforms)
    run.report = report
    run.findings = _findings(report, shapes, origin, kind, name)
    return run


def _findings(
    report: Graph,
    shapes: Graph,
    origin: str,
    kind: Callable[[str], str | None] | None,
    name: Callable[[str], str] | None,
) -> list[QualityFinding]:
    findings: dict[tuple[str, str, str], QualityFinding] = {}
    for result in report.subjects(RDF.type, SH.ValidationResult):
        focus = report.value(result, SH.focusNode)
        if focus is None:
            continue
        severity_iri = report.value(result, SH.resultSeverity)
        severity = _SEVERITY.get(severity_iri, "error") if severity_iri else "error"
        path = report.value(result, SH.resultPath)
        value = report.value(result, SH.value)
        shape = report.value(result, SH.sourceShape)
        component = report.value(result, SH.sourceConstraintComponent)
        messages = [str(m) for m in report.objects(result, SH.resultMessage)]
        focus_str = str(focus) if isinstance(focus, URIRef) else f"_:{focus}"
        shown = name(focus_str) if name and isinstance(focus, URIRef) else focus_str
        detail = messages[0] if messages else _component_text(component)
        on_path = f" ({_short(shapes, path)})" if path is not None else ""
        finding = QualityFinding(
            rule_id=SHACL_RULE_ID,
            severity=severity,
            resource=focus_str,
            resource_kind=kind(focus_str)
            if kind and isinstance(focus, URIRef)
            else None,
            message=f"'{shown}'{on_path}: {detail}",
            evidence={
                "severity": str(severity_iri) if severity_iri else None,
                "path": _short(shapes, path) if path is not None else None,
                "value": str(value) if value is not None else None,
                "component": str(component) if component is not None else None,
                "shape": shape_label(shapes, shape) if shape is not None else None,
            },
            suggestion=_shape_description(shapes, shape),
            source_shape=shape_label(shapes, shape) if shape is not None else None,
            origin=origin,  # type: ignore[arg-type]
        )
        findings.setdefault(finding.key, finding)
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        findings.values(),
        key=lambda f: (order[f.severity], f.source_shape or "", f.resource, f.message),
    )


def _component_text(component: Node | None) -> str:
    if component is None:
        return "does not conform to the shape."
    local = str(component).rsplit("#", 1)[-1].removesuffix("ConstraintComponent")
    return f"violates {local}."


def _shape_description(shapes: Graph, shape: Node | None) -> str | None:
    """A shape's sh:description, as the suggestion. Its sh:message is already
    the finding's message, through pySHACL's sh:resultMessage."""
    if shape is None:
        return None
    text = shapes.value(shape, SH.description)
    return str(text) if text is not None else None


def shape_label(shapes: Graph, shape: Node) -> str:
    """A name for a shape a reader can find: a blank-node property shape is
    named by the shape that holds it and its path, not by its node ID."""
    if isinstance(shape, BNode):
        parent = shapes.value(None, SH.property, shape)
        path = shapes.value(shape, SH.path)
        if parent is not None:
            where = _short(shapes, path) if path is not None else "property"
            return f"{shape_label(shapes, parent)} › {where}"
    label = shapes.value(shape, RDFS.label)
    return str(label) if label else _short(shapes, shape)


def shapes_from(graphs: Iterable[Graph]) -> Graph:
    """Several shapes graphs as one."""
    merged = Graph()
    for g in graphs:
        for prefix, namespace in g.namespaces():
            merged.bind(prefix, namespace, override=False)
        for triple in g:
            merged.add(triple)
    return merged

"""SHACL: shapes kept in the ontology, shapes added to it, and checks against them.

SHACL is closed-world validation of *data*: a missing value is a violation,
where the quality rules and the reasoner treat it as merely unknown. So it runs
only when asked, and its findings are labelled as what they are.

Shapes are ordinary RDF, so the ones a user adds are stored in the ontology
itself, where save, load, undo, autosave and export already handle them. A
check splits the graph in two first: the shapes, and the data they check. The
shapes are never validated as data.

What belongs to a shape is its *structure*: its SHACL statements, the blank
nodes they build (property shapes, paths, lists), and the shapes it refers to.
The values a shape merely mentions (``sh:targetNode``, ``sh:hasValue``, the
members of ``sh:in``) are data the shape talks about, and stay data.

Runs are bounded. pySHACL runs in a worker process that is killed when the
time limit passes, because a constraint can spend its time inside a regular
expression, where no check of the clock can interrupt it. ``owl:imports`` is
not resolved, and no SHACL-SPARQL constraint may reach another server through
``SERVICE``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS
from rdflib.term import Node

from .quality.models import QualityFinding, Severity

SH = Namespace("http://www.w3.org/ns/shacl#")

#: The quality rule ID SHACL findings carry.
SHACL_RULE_ID = "Q015"

DEFAULT_DEADLINE_SECONDS = 10.0

_SHAPE_TYPES = (SH.NodeShape, SH.PropertyShape)

_SEVERITY: dict[str, Severity] = {
    str(SH.Violation): "error",
    str(SH.Warning): "warning",
    str(SH.Info): "info",
}

#: Predicates that make an untyped node a shape (SHACL 2.1: a node with a
#: target is a shape).
_TARGETS = (SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf)

#: Predicates whose object is a shape.
_SHAPE_REFS = (SH.property, SH.node, SH.qualifiedValueShape, SH["not"])
#: Predicates whose object is a list of shapes.
_SHAPE_LIST_REFS = (SH["and"], SH["or"], SH.xone)
#: Predicates whose object is a value the shape talks about, not structure.
_VALUE_REFS = (SH.targetNode, SH.hasValue)
#: Predicates whose object is a list of such values.
_VALUE_LIST_REFS = (SH["in"],)
#: Predicates whose object may be a *named* node that is still part of the
#: shape: a SPARQL constraint, its prefix declarations. Of such a node only
#: its SHACL statements are the shape's (``sh:prefixes`` usually points at
#: the ontology itself, whose other statements are data).
_NAMED_STRUCTURE_REFS = (SH.sparql, SH.prefixes, SH.declare)

#: Where SHACL-SPARQL keeps query text.
_QUERY_TEXT = (SH.select, SH.ask, SH.construct, SH.update)

#: ``SERVICE <iri>`` or ``SERVICE ?var``, with or without ``SILENT``.
_SERVICE = re.compile(r"\bSERVICE\s+(?:SILENT\s+)?[<?$]", re.IGNORECASE)

Triple = tuple[Node, Node, Node]


class ShapesError(ValueError):
    """Shapes that cannot be added or run: unparsable, invalid, or unsafe."""


# -- shape structure -----------------------------------------------------------


def _list_items(graph: Graph, head: Node) -> list[Node]:
    try:
        return list(Collection(graph, head))
    except Exception:  # noqa: BLE001 - a malformed list contributes nothing
        return []


def _referenced(graph: Graph, node: Node) -> set[Node]:
    """The shapes ``node`` refers to directly."""
    found: set[Node] = set()
    for pred in _SHAPE_REFS:
        found.update(graph.objects(node, pred))
    for pred in _SHAPE_LIST_REFS:
        for head in graph.objects(node, pred):
            found.update(_list_items(graph, head))
    return {n for n in found if not isinstance(n, Literal)}


def shape_nodes(graph: Graph) -> set[Node]:
    """Every shape in ``graph``: typed ones, ones with a target, and every
    shape another one refers to (an untyped named helper behind ``sh:node``
    is as much a shape as a typed one)."""
    nodes: set[Node] = set()
    for shape_type in _SHAPE_TYPES:
        nodes.update(graph.subjects(RDF.type, shape_type))
    for pred in _TARGETS:
        nodes.update(graph.subjects(pred, None))
    frontier = list(nodes)
    while frontier:
        for ref in _referenced(graph, frontier.pop()):
            if ref not in nodes:
                nodes.add(ref)
                frontier.append(ref)
    return nodes


def _is_pure_shape(graph: Graph, node: Node) -> bool:
    """A shape and nothing else: any annotation on it is the shape's.

    A class that is also a node shape (an implicit class target) is not: its
    label and OWL axioms are the class's, and stay data.
    """
    if isinstance(node, BNode):
        return True
    return all(t in _SHAPE_TYPES for t in graph.objects(node, RDF.type))


def _own_triples(graph: Graph, node: Node, shapes: set[Node]) -> set[Triple]:
    """The triples that make up one shape, not counting the shapes it refers to.

    Blank nodes are followed as structure (property shapes, paths, lists),
    except where they are values: the object of ``sh:targetNode`` or
    ``sh:hasValue``, a member of an ``sh:in`` list, and any other shape,
    which has triples of its own.
    """
    triples: set[Triple] = set()
    # (node, inside a value list, a named node of which only SHACL counts)
    frontier: list[tuple[Node, bool, bool]] = []

    def is_shacl(pred: Node, obj: Node) -> bool:
        return str(pred).startswith(str(SH)) or (
            pred == RDF.type and str(obj).startswith(str(SH))
        )

    def take(subject: Node, pred: Node, obj: Node, in_values: bool) -> None:
        triples.add((subject, pred, obj))
        if obj in shapes:
            return
        if isinstance(obj, URIRef):
            if pred in _NAMED_STRUCTURE_REFS:
                frontier.append((obj, False, True))
            return
        if not isinstance(obj, BNode):
            return
        if pred in _VALUE_REFS or (in_values and pred == RDF.first):
            return
        frontier.append((obj, in_values or pred in _VALUE_LIST_REFS, False))

    pure = _is_pure_shape(graph, node)
    for pred, obj in graph.predicate_objects(node):
        if pure or is_shacl(pred, obj):
            take(node, pred, obj, False)
    seen: set[Node] = set()
    while frontier:
        current, in_values, shacl_only = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        for pred, obj in graph.predicate_objects(current):
            if not shacl_only or is_shacl(pred, obj):
                take(current, pred, obj, in_values)
    return triples


def _reachable(graph: Graph, start: Node) -> set[Node]:
    """``start`` and every shape it refers to, however indirectly."""
    found = {start}
    frontier = [start]
    while frontier:
        for ref in _referenced(graph, frontier.pop()):
            if ref not in found:
                found.add(ref)
                frontier.append(ref)
    return found


#: Types that make a shape an implicit class target (SHACL 2.1.3.1).
_CLASS_TYPES = (RDFS.Class, URIRef("http://www.w3.org/2002/07/owl#Class"))


def _has_target(graph: Graph, node: Node) -> bool:
    return any((node, pred, None) in graph for pred in _TARGETS) or any(
        (node, RDF.type, t) in graph for t in _CLASS_TYPES
    )


def _top_level(graph: Graph, shapes: set[Node]) -> set[Node]:
    """The shapes that stand on their own: every shape with a target of its
    own (explicit, or implicit as a class), and every shape no other refers
    to. A targeted shape is checked for itself even when another shape also
    uses it, and a shape that refers to itself is still a root."""
    referenced: set[Node] = set()
    for node in shapes:
        referenced |= _referenced(graph, node)
    return {n for n in shapes if n not in referenced or _has_target(graph, n)}


def split_shapes(graph: Graph) -> tuple[Graph, Graph]:
    """``(data, shapes)``: the shapes' triples apart from everything else.

    A class that is also a shape keeps its non-SHACL types in both graphs:
    it is validated by being a class (an implicit target) and is data by
    being a class.
    """
    shapes_set = shape_nodes(graph)
    shape_triples: set[Triple] = set()
    for node in shapes_set:
        shape_triples |= _own_triples(graph, node, shapes_set)
    data, shapes = Graph(), Graph()
    for prefix, namespace in graph.namespaces():
        data.bind(prefix, namespace, override=True)
        shapes.bind(prefix, namespace, override=True)
    for triple in graph:
        if triple in shape_triples:
            shapes.add(triple)
        else:
            data.add(triple)
            if (
                triple[1] == RDF.type
                and triple[0] in shapes_set
                and triple[2] not in _SHAPE_TYPES
            ):
                shapes.add(triple)
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


def _shape_closure(graph: Graph, node: Node, shapes: set[Node]) -> set[Triple]:
    """A shape with every shape it refers to, as one readable whole."""
    triples: set[Triple] = set()
    for shape in _reachable(graph, node):
        triples |= _own_triples(graph, shape, shapes)
    return triples


def list_shapes(graph: Graph) -> list[ShapeInfo]:
    """The top-level shapes: those no other shape refers to."""
    shapes = shape_nodes(graph)
    result = []
    for node in _top_level(graph, shapes):
        label = graph.value(node, RDFS.label)
        targets = tuple(
            f"{str(pred).rsplit('#', 1)[-1]} {_short(graph, obj)}"
            for pred in _TARGETS
            for obj in graph.objects(node, pred)
        )
        closure = _shape_closure(graph, node, shapes)
        constraints = sum(
            1
            for _, pred, _ in closure
            if str(pred).startswith(str(SH))
            and pred not in (*_TARGETS, *_SHAPE_REFS, SH.path, SH.name)
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
    """One shape, with the shapes it refers to, as Turtle for reading."""
    out = Graph()
    for prefix, namespace in graph.namespaces():
        out.bind(prefix, namespace, override=True)
    for triple in _shape_closure(graph, node, shape_nodes(graph)):
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


def parse_shapes(
    text: str, format: str = "turtle", deadline_s: float = DEFAULT_DEADLINE_SECONDS
) -> Graph:
    """Parse and vet shapes before they are added or run.

    Refuses text that does not parse, holds no shape, would query another
    server, or does not conform to the SHACL meta-shapes (SHACL for SHACL).
    The meta-shapes check runs in the worker, under the same time limit as a
    check.
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
    outcome = _in_worker(Graph(), shapes, meta=True, deadline_s=deadline_s)
    if "timeout" in outcome:
        raise ShapesError(
            f"Checking the shapes did not finish within {deadline_s:g} seconds."
        )
    if "invalid" in outcome:
        report = outcome["invalid"].split("Validation Report", 1)[-1].strip()
        raise ShapesError(f"The shapes are not valid SHACL.\n\n{report}")
    if "failure" in outcome:
        raise ShapesError(f"pySHACL could not check these shapes: {outcome['failure']}")
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
    """Remove one top-level shape and what only it uses.

    Raises :class:`ShapesError` for a class that is also a shape another
    shape still uses: there is no way to stop it being checked that keeps
    both the class and that shape intact.

    The shapes it refers to go with it unless another top-level shape still
    reaches them, and structure another shape shares (one ``sh:in`` list)
    stays. A class that is also a shape stays a class: only what makes it a
    shape is removed. Data the shape mentions is never touched.
    """
    shapes = shape_nodes(graph)
    kept_reach: set[Node] = set()
    for other in _top_level(graph, shapes) - {node}:
        kept_reach |= _reachable(graph, other)
    if node in kept_reach:
        # Named by the top-level shapes that reach it, not by the blank
        # property shape that may hold the reference.
        users = sorted(
            _short(graph, root)
            for root in _top_level(graph, shapes) - {node}
            if node in _reachable(graph, root)
        )
        if any((node, RDF.type, t) in graph for t in _CLASS_TYPES):
            # Its target is implicit: being a class is what makes it check
            # the class's instances. Dropping that would delete the class,
            # and dropping its constraints would break the shapes using it,
            # so it is refused, and said so, rather than quietly kept.
            raise ShapesError(
                f"{_short(graph, node)} is also a class, so it checks that "
                "class's instances for as long as it is a shape, and "
                f"{', '.join(users)} still use{'s' if len(users) == 1 else ''} it. "
                "Remove those shapes first, or remove its constraints on the "
                "Source page."
            )
        # Another shape still uses this one: it stops being checked on its
        # own (its targets go) and stays as that shape's part.
        targets: set[Triple] = {
            (node, pred, obj) for pred in _TARGETS for obj in graph.objects(node, pred)
        }
        for target in targets:
            graph.remove(target)
        return len(targets)
    owned = _reachable(graph, node) - kept_reach
    doomed: set[Triple] = set()
    for shape in owned:
        doomed |= _own_triples(graph, shape, shapes)
    for shape in kept_reach:
        doomed -= _own_triples(graph, shape, shapes)
    for triple in doomed:
        graph.remove(triple)
    return len(doomed)


# -- the worker --------------------------------------------------------------------


def _in_worker(
    data: Graph, shapes: Graph, *, meta: bool, deadline_s: float
) -> dict[str, Any]:
    """Run pySHACL in a fresh worker process, killed if the deadline passes.

    A subprocess per check (see :mod:`.shacl_worker`): it starts in a fraction
    of a second, and killing it is the whole of the cleanup.
    """
    request = json.dumps(
        {
            "data_nt": data.serialize(format="nt"),
            "shapes_nt": shapes.serialize(format="nt"),
            "prefixes": [(p, str(n)) for p, n in shapes.namespaces()],
            "meta": meta,
        }
    )
    # The package's own location first, so the worker imports this copy of it
    # whether or not it is installed (a checkout run with streamlit run).
    env = dict(os.environ)
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root, *filter(None, [env.get("PYTHONPATH")])]
    )
    worker = subprocess.Popen(
        [sys.executable, "-m", "orionbelt_ontology_builder.shacl_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        out, err = worker.communicate(request, timeout=deadline_s)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.communicate()
        return {"timeout": True}
    if worker.returncode != 0:
        tail = (err or "").strip().splitlines()[-1:] or ["no output"]
        return {"failure": f"the SHACL worker stopped ({tail[0]})"}
    try:
        result: dict[str, Any] = json.loads(out)
    except json.JSONDecodeError:
        return {"failure": "the SHACL worker returned no readable result"}
    return result


def _validate_in_worker(
    data_nt: str, shapes_nt: str, prefixes: list[tuple[str, str]], meta: bool
) -> dict[str, Any]:
    """The worker's side: validate, and hand back plain data.

    Results are turned into dictionaries here, where the shapes graph is, so
    shape labels and identities are worked out against the same blank nodes
    the report names.
    """
    from pyshacl import validate
    from pyshacl.errors import ReportableRuntimeError

    # One blank-node map for both: a node the shapes name as a target or a
    # value is the same node in the data, and parsing the two separately
    # would make it two.
    bnodes: dict[str, Node] = {}
    data = Graph().parse(data=data_nt, format="nt", bnode_context=bnodes)
    shapes = Graph().parse(data=shapes_nt, format="nt", bnode_context=bnodes)
    for prefix, namespace in prefixes:
        shapes.bind(prefix, namespace, override=True)
    try:
        conforms, report, text = validate(
            data,
            shacl_graph=shapes,
            meta_shacl=meta,
            inference="none",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            do_owl_imports=False,
            advanced=False,
            js=False,
        )
    except ReportableRuntimeError as exc:
        return {"invalid": str(exc)} if meta else {"failure": str(exc)}
    except Exception as exc:  # noqa: BLE001 - reported to the user, not raised
        return {"failure": f"{type(exc).__name__}: {exc}"}
    if not isinstance(report, Graph):
        # pySHACL hands back a ValidationFailure rather than raising when a
        # constraint cannot be evaluated.
        return {"failure": str(report) or str(text)}
    for prefix, namespace in prefixes:
        report.bind(prefix, namespace, override=True)
    return {
        "conforms": bool(conforms),
        "results": _result_rows(report, shapes),
        "report_ttl": report.serialize(format="turtle"),
    }


def _result_rows(report: Graph, shapes: Graph) -> list[dict[str, Any]]:
    rows = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        focus = report.value(result, SH.focusNode)
        if focus is None:
            continue
        shape = report.value(result, SH.sourceShape)
        path = report.value(result, SH.resultPath)
        value = report.value(result, SH.value)
        component = report.value(result, SH.sourceConstraintComponent)
        severity = report.value(result, SH.resultSeverity)
        description = shapes.value(shape, SH.description) if shape is not None else None
        rows.append(
            {
                "focus": str(focus),
                "focus_is_uri": isinstance(focus, URIRef),
                "severity": str(severity) if severity is not None else None,
                "path": _short(shapes, path) if path is not None else None,
                "value": str(value) if value is not None else None,
                # The whole term: "x"@en and "x"@de print alike and are not.
                "value_term": value.n3() if value is not None else None,
                "component": str(component) if component is not None else None,
                "shape": shape_label(shapes, shape) if shape is not None else None,
                # The shape itself, not its label: two property shapes on one
                # path read the same and are still two shapes.
                "shape_id": str(shape) if shape is not None else None,
                "messages": sorted(
                    str(m) for m in report.objects(result, SH.resultMessage)
                ),
                "description": str(description) if description is not None else None,
            }
        )
    return rows


# -- running ---------------------------------------------------------------------


@dataclass
class ShaclRun:
    conforms: bool | None
    findings: list[QualityFinding] = field(default_factory=list)
    #: The full validation report, as Turtle, for download.
    report_ttl: str | None = None
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
    all_shapes = shape_nodes(shapes)
    run = ShaclRun(conforms=None, shapes_checked=len(_top_level(shapes, all_shapes)))
    if not all_shapes:
        run.conforms = True
        return run
    try:
        _refuse_network(shapes)
    except ShapesError as exc:
        run.error = str(exc)
        return run
    began = time.monotonic()
    outcome = _in_worker(data, shapes, meta=False, deadline_s=deadline_s)
    run.duration_ms = (time.monotonic() - began) * 1000
    if "timeout" in outcome:
        run.error = (
            f"The check did not finish within {deadline_s:g} seconds and was "
            "stopped. Narrow the shapes' targets, or check fewer shapes at once."
        )
        return run
    if "failure" in outcome or "invalid" in outcome:
        run.error = (
            "pySHACL could not run these shapes: "
            f"{outcome.get('failure') or outcome.get('invalid')}"
        )
        return run
    run.conforms = outcome["conforms"]
    run.report_ttl = outcome["report_ttl"]
    run.findings = _findings(outcome["results"], origin, kind, name)
    return run


def _findings(
    rows: list[dict[str, Any]],
    origin: str,
    kind: Callable[[str], str | None] | None,
    name: Callable[[str], str] | None,
) -> list[QualityFinding]:
    findings: dict[tuple[str, str, str], QualityFinding] = {}
    for row in rows:
        focus = row["focus"] if row["focus_is_uri"] else f"_:{row['focus']}"
        shown = name(focus) if name and row["focus_is_uri"] else focus
        detail = (
            row["messages"][0] if row["messages"] else _component_text(row["component"])
        )
        on_path = f" ({row['path']})" if row["path"] else ""
        finding = QualityFinding(
            rule_id=SHACL_RULE_ID,
            severity=_SEVERITY.get(row["severity"] or "", "error"),
            resource=focus,
            resource_kind=kind(focus) if kind and row["focus_is_uri"] else None,
            message=f"'{shown}'{on_path}: {detail}",
            evidence={
                "severity": row["severity"],
                "path": row["path"],
                "value": row["value"],
                "value_term": row["value_term"],
                "component": row["component"],
                "shape": row["shape"],
                "shape_id": row["shape_id"],
            },
            suggestion=row["description"],
            source_shape=row["shape"],
            origin=origin,  # type: ignore[arg-type]
        )
        findings.setdefault(finding.key, finding)
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        findings.values(),
        key=lambda f: (order[f.severity], f.source_shape or "", f.resource, f.message),
    )


def _component_text(component: str | None) -> str:
    if not component:
        return "does not conform to the shape."
    local = component.rsplit("#", 1)[-1].removesuffix("ConstraintComponent")
    return f"violates {local}."


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

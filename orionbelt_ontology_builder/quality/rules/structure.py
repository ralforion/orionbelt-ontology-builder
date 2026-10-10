"""Rules about the shape of the model: hierarchy, connectivity, property pairs."""

from __future__ import annotations

from collections import deque

import networkx as nx
from rdflib import URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ..context import QualityContext
from ..models import Severity
from ..registry import OWL_PROFILE, SKOS_PROFILE, Rule, RuleResult, register

_OWL = frozenset({OWL_PROFILE})
_OWL_SKOS = frozenset({OWL_PROFILE, SKOS_PROFILE})


def _cycles(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Adapter over ``validate()``'s ``class_cycle`` and ``validate_skos()``'s
    ``broader_cycle``: their messages, our scope.

    A one-member cycle (``A ⊑ A``) is Q009's, so it is left out here.
    """
    result = RuleResult(checked=len(ctx.classes) + len(ctx.concepts))
    # Both come from the same walk over the same parent map, in the same order.
    cycles = ctx.ont._cycles_in(ctx.ont._class_parent_map())
    for issue, cycle in zip(ctx.ont._class_cycle_issues(), cycles, strict=True):
        own = [uri for uri in cycle if uri in ctx.classes]
        if not own or len(cycle) < 2:
            continue
        result.findings.append(
            ctx.finding(
                "Q006",
                severity,
                issue["subject_uri"],
                issue["message"],
                evidence={"cycle": list(cycle)},
                suggestion="Remove one subClassOf edge in the cycle, or replace the "
                "cycle with owl:equivalentClass if the classes are meant to be "
                "the same.",
                related=cycle[1:],
            )
        )
        result.affected.update(own)
    for issue in ctx.skos_issues:
        uri = issue.get("subject_uri", "")
        if issue["type"] != "broader_cycle" or uri not in ctx.concepts:
            continue
        if (URIRef(uri), SKOS.broader, URIRef(uri)) in ctx.graph:
            continue  # a self-loop: Q009
        result.findings.append(
            ctx.finding(
                "Q006",
                severity,
                uri,
                issue["message"],
                suggestion="Remove one skos:broader (or skos:narrower) link in the "
                "cycle.",
            )
        )
        result.affected.add(uri)
    return result


def _self_edges(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.classes) + len(ctx.concepts))
    for uri in sorted(ctx.classes):
        if (URIRef(uri), RDFS.subClassOf, URIRef(uri)) in ctx.graph:
            result.findings.append(
                ctx.finding(
                    "Q009",
                    severity,
                    uri,
                    f"'{ctx.name(uri)}' is stated to be a subclass of itself.",
                    suggestion="Remove the subClassOf edge: every class is a "
                    "subclass of itself anyway, so it says nothing.",
                )
            )
            result.affected.add(uri)
    for uri in sorted(ctx.concepts):
        ref = URIRef(uri)
        for pred in (SKOS.broader, SKOS.narrower):
            if (ref, pred, ref) in ctx.graph:
                result.findings.append(
                    ctx.finding(
                        "Q009",
                        severity,
                        uri,
                        f"Concept '{ctx.name(uri)}' is its own "
                        f"{ctx.ont._local_name(pred)}.",
                        evidence={"predicate": str(pred)},
                        suggestion=f"Remove the skos:{ctx.ont._local_name(pred)} "
                        "link to itself.",
                    )
                )
                result.affected.add(uri)
    return result


def _unconnected(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Adapter over ``validate()``'s ``orphan_class``."""
    result = RuleResult(checked=len(ctx.classes))
    for issue in ctx.validation_issues:
        if issue["type"] != "orphan_class" or issue["subject_uri"] not in ctx.classes:
            continue
        result.findings.append(
            ctx.finding(
                "Q007",
                severity,
                issue["subject_uri"],
                issue["message"],
                suggestion="Place it in the hierarchy, use it in a domain, range or "
                "restriction, or remove it if it is left over.",
            )
        )
        result.affected.add(issue["subject_uri"])
    return result


def _missing_domain_range(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Adapter over ``validate()``'s ``missing_domain`` and ``missing_range``."""
    result = RuleResult(checked=len(ctx.properties))
    for issue in ctx.validation_issues:
        if issue["type"] not in ("missing_domain", "missing_range"):
            continue
        if issue["subject_uri"] not in ctx.properties:
            continue
        result.findings.append(
            ctx.finding(
                "Q008",
                severity,
                issue["subject_uri"],
                issue["message"],
                evidence={"missing": issue["type"].removeprefix("missing_")},
                suggestion="Add one only if every use of the property should imply "
                "it: in OWL a domain or range is an inference rule, not a check.",
            )
        )
        result.affected.add(issue["subject_uri"])
    return result


def _path_to(ctx: QualityContext, start: str, goal: str) -> list[str] | None:
    """The parent chain from ``start`` up to ``goal``, both included."""
    came_from: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            path: list[str] = []
            step: str | None = node
            while step is not None:
                path.append(step)
                step = came_from[step]
            return path[::-1]
        for parent in ctx.parents.get(node, []):
            if parent not in came_from:
                came_from[parent] = node
                queue.append(parent)
    return None


def _redundant_subclass(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.classes))
    for child in sorted(ctx.classes):
        # A class in a cycle reaches all of its parents through every other
        # one, so each edge would read as redundant. Q006 says why.
        if child in ctx.cycle_members:
            continue
        parents = ctx.parents.get(child, [])
        if len(parents) < 2:
            continue
        for parent in parents:
            for other in parents:
                if other == parent:
                    continue
                path = _path_to(ctx, other, parent)
                if not path:
                    continue
                chain = " ⊑ ".join(ctx.name(uri) for uri in [child, *path])
                result.findings.append(
                    ctx.finding(
                        "Q019",
                        severity,
                        child,
                        f"'{ctx.name(child)}' ⊑ '{ctx.name(parent)}' is already "
                        f"implied by {chain}.",
                        evidence={"redundant_parent": parent, "path": [child, *path]},
                        suggestion=f"Remove the direct subClassOf from "
                        f"'{ctx.name(child)}' to '{ctx.name(parent)}'.",
                        related=path,
                    )
                )
                result.affected.add(child)
                break
    return result


def _islands(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.classes))
    graph: nx.Graph = nx.Graph()
    graph.add_nodes_from(ctx.classes)
    graph.add_edges_from(
        (child, parent) for child, ps in ctx.parents.items() for parent in ps
    )
    graph.add_edges_from(ctx.class_links)
    graph.remove_edges_from(nx.selfloop_edges(graph))
    # Ranked by how much of *this* ontology a component holds, so a large
    # imported vocabulary does not become "the model" and leave the
    # ontology's own classes looking cut off from it.
    components = sorted(
        (c for c in nx.connected_components(graph) if len(c) > 1),
        key=lambda c: (-len(c & ctx.classes), -len(c), min(c)),
    )
    # The first component is the model; everything else is cut off from it.
    # A lone class is Q007's to report, not an island.
    for component in components[1:]:
        own = sorted(component & ctx.classes)
        if not own:
            continue
        members = sorted(component, key=ctx.name)
        shown = [ctx.name(uri) for uri in members[:10]]
        more = f" and {len(members) - 10} more" if len(members) > 10 else ""
        result.findings.append(
            ctx.finding(
                "Q020",
                severity,
                own[0],
                f"{len(members)} classes are connected to each other but not to "
                f"the rest of the model: {', '.join(shown)}{more}.",
                evidence={"members": members},
                suggestion="Connect the group to the main model through a "
                "superclass, a property or a restriction, or split it into its "
                "own ontology.",
                related=[uri for uri in members if uri != own[0]],
            )
        )
        result.affected.update(own)
    return result


def _missing_inverse(ctx: QualityContext, severity: Severity) -> RuleResult:
    object_props = {
        str(p)
        for p in ctx.graph.subjects(RDF.type, OWL.ObjectProperty)
        if isinstance(p, URIRef) and str(p) in ctx.properties
    }
    result = RuleResult(checked=len(object_props))
    # (domain, range) -> properties going that way, for properties with no
    # inverse yet. A property that already has one is paired already.
    by_direction: dict[tuple[str, str], set[str]] = {}
    for prop in sorted(object_props):
        ref = URIRef(prop)
        if (ref, OWL.inverseOf, None) in ctx.graph or (
            None,
            OWL.inverseOf,
            ref,
        ) in ctx.graph:
            continue
        for d in ctx.domains(ref):
            for r in ctx.ranges(ref):
                # A property from a class to itself goes both ways on its own;
                # pairing it with every other such property says nothing.
                if d != r:
                    by_direction.setdefault((d, r), set()).add(prop)
    pairs: set[tuple[str, str]] = set()
    for (d, r), props in by_direction.items():
        for back in by_direction.get((r, d), set()):
            for there in props:
                if there != back:
                    pairs.add((min(there, back), max(there, back)))
    for p, q in sorted(pairs):
        result.findings.append(
            ctx.finding(
                "Q021",
                severity,
                p,
                f"'{ctx.name(p)}' and '{ctx.name(q)}' connect the same classes in "
                "opposite directions without owl:inverseOf between them.",
                evidence={"pair": [p, q]},
                suggestion=f"If '{ctx.name(q)}' is '{ctx.name(p)}' read backwards, "
                "declare them owl:inverseOf; otherwise consider dropping one.",
                related=[q],
            )
        )
        result.affected.update((p, q))
    return result


def _multi_parent(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.classes))
    for uri in sorted(ctx.classes):
        parents = ctx.parents.get(uri, [])
        if len(parents) < 2:
            continue
        result.findings.append(
            ctx.finding(
                "Q022",
                severity,
                uri,
                f"'{ctx.name(uri)}' has {len(parents)} parents: "
                + ", ".join(ctx.name(p) for p in parents)
                + ".",
                evidence={"parents": parents},
                suggestion="Legal OWL. Keep it if each parent is a real "
                "classification; otherwise pick one.",
                related=parents,
            )
        )
        result.affected.add(uri)
    return result


def _outside_hierarchy(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.classes))
    for uri in sorted(ctx.classes):
        if uri not in ctx.used_classes or uri in ctx.in_hierarchy:
            continue
        result.findings.append(
            ctx.finding(
                "Q023",
                severity,
                uri,
                f"'{ctx.name(uri)}' is used by properties or restrictions but has "
                "neither a parent nor a subclass.",
                suggestion="Give it a superclass if the model is meant to be a "
                "taxonomy; a flat model can leave it as it is.",
            )
        )
        result.affected.add(uri)
    return result


for _rule in (
    Rule(
        "Q006",
        "Hierarchy cycles",
        "Classes that are their own ancestor through rdfs:subClassOf, and "
        "concepts that are their own ancestor through skos:broader.",
        "structure",
        _OWL_SKOS,
        "warning",
        True,
        _cycles,
    ),
    Rule(
        "Q007",
        "Unconnected classes",
        "Classes not used in any hierarchy, domain or range, restriction, or "
        "instance typing.",
        "structure",
        _OWL,
        "info",
        True,
        _unconnected,
    ),
    Rule(
        "Q008",
        "Missing property domain or range",
        "Properties with no rdfs:domain or rdfs:range (or domainIncludes / "
        "rangeIncludes). A policy, off by default: OWL does not require them.",
        "structure",
        _OWL,
        "info",
        False,
        _missing_domain_range,
    ),
    Rule(
        "Q009",
        "Self-referential hierarchy edge",
        "A class stated as a subclass of itself, or a concept as its own "
        "broader or narrower.",
        "structure",
        _OWL_SKOS,
        "warning",
        True,
        _self_edges,
    ),
    Rule(
        "Q019",
        "Redundant subclass edges",
        "A ⊑ C stated directly while another path A ⊑ B ⊑ … ⊑ C already implies it.",
        "structure",
        _OWL,
        "warning",
        True,
        _redundant_subclass,
    ),
    Rule(
        "Q020",
        "Disconnected class islands",
        "Groups of two or more classes connected to each other but not to the "
        "rest of the model.",
        "structure",
        _OWL,
        "info",
        True,
        _islands,
    ),
    Rule(
        "Q021",
        "Opposite properties without inverse",
        "Object properties connecting the same two classes in opposite "
        "directions, without owl:inverseOf between them.",
        "structure",
        _OWL,
        "info",
        True,
        _missing_inverse,
    ),
    Rule(
        "Q022",
        "Multiple parents",
        "Classes with more than one named superclass. Legal OWL, so off by default.",
        "structure",
        _OWL,
        "info",
        False,
        _multi_parent,
    ),
    Rule(
        "Q023",
        "Classes outside the hierarchy",
        "Classes used by properties or restrictions that have neither a parent "
        "nor a subclass. A valid style, so off by default.",
        "structure",
        _OWL,
        "info",
        False,
        _outside_hierarchy,
    ),
):
    register(_rule)

"""Model quality checks and the quality score.

``OntologyManager.validate()`` answers "is something broken?". These checks
answer "is this a well-made ontology?": the shape of the hierarchy, how classes
connect, whether properties pair up. Most findings are advice, not errors, so
the severities stop at ``warning``.

Every check is scored as a share of the entities it looks at, not as a count
of findings, so a large ontology is not marked down for being large. A check
that only finds problems in somebody else's ontology finds none at all: only
entities in the ontology's own namespace are in scope, unless the caller asks
for everything.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

import networkx as nx
from rdflib import BNode, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from rdflib.term import Node

from .ontology_manager import _DOMAIN_INCLUDES, _RANGE_INCLUDES

if TYPE_CHECKING:
    from .ontology_manager import OntologyManager

#: A finding: ``severity``, ``type``, ``subject``, ``subject_uri``,
#: ``subject_kind`` and ``message``, all strings, like ``validate()`` issues.
QualityIssue = dict[str, str]

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

#: How much one check counts toward the score, by severity.
_WEIGHTS = {"warning": 3, "info": 1}


@dataclass(frozen=True)
class QualityCheck:
    """One check: what it is called, how it is shown, and how it runs."""

    key: str
    title: str
    description: str
    category: str
    severity: str
    default_on: bool
    #: What the score divides by: ``"classes"`` or ``"properties"``.
    population: str
    #: Returns the findings and the URIs of the entities they affect. The two
    #: differ for a finding that names several entities (an island, a pair of
    #: properties), and the score counts entities, not findings.
    run: Callable[[QualityContext], tuple[list[QualityIssue], set[str]]]


@dataclass
class CheckResult:
    """One check's contribution to the score."""

    affected: int
    population: int

    @property
    def score(self) -> float | None:
        """Share of the population the check found nothing wrong with."""
        if not self.population:
            return None
        return 1 - min(self.affected, self.population) / self.population


@dataclass
class QualityReport:
    """What :func:`assess_quality` found, check by check."""

    #: Findings keyed by check, in catalogue order. A check that ran and found
    #: nothing is present with an empty list.
    findings: dict[str, list[QualityIssue]] = field(default_factory=dict)
    per_check: dict[str, CheckResult] = field(default_factory=dict)
    #: 0-100, or None when no enabled check had anything to look at.
    score: int | None = None

    @property
    def issues(self) -> list[QualityIssue]:
        return [issue for group in self.findings.values() for issue in group]


class QualityContext:
    """What several checks share, worked out once per run."""

    def __init__(self, ont: OntologyManager, include_external: bool = False):
        self.ont = ont
        self.graph = ont.graph
        self.include_external = include_external

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
        if self.include_external or not self._has_own_entities:
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

    def population(self, name: str) -> int:
        return len(self.classes if name == "classes" else self.properties)

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

    def issue(self, check: QualityCheck, uri: str, message: str) -> QualityIssue:
        return {
            "severity": check.severity,
            "type": check.key,
            "subject": self.name(uri),
            "subject_uri": uri,
            "subject_kind": self.kind(uri),
            "message": message,
        }

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


# -- checks ----------------------------------------------------------------


def _reused(*issue_types: str) -> Callable[[QualityContext], tuple]:
    """A check that is ``validate()``'s own, limited to what is in scope."""

    def run(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
        issues = [
            {**issue, "subject_kind": ctx.kind(issue["subject_uri"])}
            for issue in ctx.validation_issues
            if issue["type"] in issue_types and ctx.in_scope(issue["subject_uri"])
        ]
        return issues, {issue["subject_uri"] for issue in issues}

    return run


def _class_cycles(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
    issues = [
        {**issue, "subject_kind": "Class"}
        for issue in ctx.ont._class_cycle_issues()
        if ctx.in_scope(issue["subject_uri"])
    ]
    return issues, {uri for uri in ctx.cycle_members if uri in ctx.classes}


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


def _redundant_subclass(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
    check = CHECKS_BY_KEY["redundant_subclass"]
    issues: list[QualityIssue] = []
    affected: set[str] = set()
    for child in sorted(ctx.classes):
        # A class in a cycle reaches all of its parents through every other
        # one, so each edge would read as redundant. class_cycle says why.
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
                if path:
                    chain = " ⊑ ".join(ctx.name(uri) for uri in [child, *path])
                    issues.append(
                        ctx.issue(
                            check,
                            child,
                            f"'{ctx.name(child)}' ⊑ '{ctx.name(parent)}' is already "
                            f"implied by {chain}; the direct subClassOf can go.",
                        )
                    )
                    affected.add(child)
                    break
    return issues, affected


def _disconnected_islands(
    ctx: QualityContext,
) -> tuple[list[QualityIssue], set[str]]:
    check = CHECKS_BY_KEY["disconnected_island"]
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
    issues: list[QualityIssue] = []
    affected: set[str] = set()
    # The first component is the model; everything else is cut off from it.
    # A lone class is orphan_class's to report, not an island.
    for component in components[1:]:
        own = sorted(component & ctx.classes)
        if not own:
            continue
        members = sorted(component, key=ctx.name)
        shown = [ctx.name(uri) for uri in members[:10]]
        more = f" and {len(members) - 10} more" if len(members) > 10 else ""
        issues.append(
            ctx.issue(
                check,
                own[0],
                f"{len(members)} classes are connected to each other but not to "
                f"the rest of the model: {', '.join(shown)}{more}.",
            )
        )
        affected.update(own)
    return issues, affected


def _multi_parent(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
    check = CHECKS_BY_KEY["multi_parent"]
    issues = [
        ctx.issue(
            check,
            uri,
            f"'{ctx.name(uri)}' has {len(ctx.parents[uri])} parents: "
            + ", ".join(ctx.name(p) for p in ctx.parents[uri])
            + ". Legal OWL; worth a look if it was not meant.",
        )
        for uri in sorted(ctx.classes)
        if len(ctx.parents.get(uri, [])) > 1
    ]
    return issues, {issue["subject_uri"] for issue in issues}


def _missing_inverse(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
    check = CHECKS_BY_KEY["missing_inverse"]
    # (domain, range) -> properties going that way, for properties with no
    # inverse yet. A property that already has one is paired already.
    by_direction: dict[tuple[str, str], set[str]] = {}
    for prop in ctx.graph.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(prop, URIRef) or not ctx.in_scope(str(prop)):
            continue
        if (prop, OWL.inverseOf, None) in ctx.graph or (
            None,
            OWL.inverseOf,
            prop,
        ) in ctx.graph:
            continue
        for d in ctx.domains(prop):
            for r in ctx.ranges(prop):
                # A property from a class to itself goes both ways on its own;
                # pairing it with every other such property says nothing.
                if d != r:
                    by_direction.setdefault((d, r), set()).add(str(prop))
    pairs: set[tuple[str, str]] = set()
    for (d, r), props in by_direction.items():
        for back in by_direction.get((r, d), set()):
            for there in props:
                if there != back:
                    pairs.add((min(there, back), max(there, back)))
    issues: list[QualityIssue] = []
    affected: set[str] = set()
    for p, q in sorted(pairs):
        issues.append(
            ctx.issue(
                check,
                p,
                f"'{ctx.name(p)}' and '{ctx.name(q)}' connect the same classes in "
                "opposite directions. If one is the other read backwards, declare "
                "them owl:inverseOf; otherwise consider dropping one.",
            )
        )
        affected.update((p, q))
    return issues, affected


def _flat_class(ctx: QualityContext) -> tuple[list[QualityIssue], set[str]]:
    check = CHECKS_BY_KEY["flat_class"]
    linked = {uri for link in ctx.class_links for uri in link}
    issues = [
        ctx.issue(
            check,
            uri,
            f"'{ctx.name(uri)}' is used by properties or restrictions but has "
            "neither a parent nor a subclass.",
        )
        for uri in sorted(ctx.classes)
        if uri in linked and uri not in ctx.in_hierarchy
    ]
    return issues, {issue["subject_uri"] for issue in issues}


QUALITY_CHECKS: tuple[QualityCheck, ...] = (
    QualityCheck(
        "class_cycle",
        "Circular hierarchy",
        "Classes that are their own ancestor through rdfs:subClassOf.",
        "structure",
        "warning",
        True,
        "classes",
        _class_cycles,
    ),
    QualityCheck(
        "redundant_subclass",
        "Redundant subclass edges",
        "A ⊑ C stated directly while another path A ⊑ B ⊑ … ⊑ C already implies it.",
        "structure",
        "warning",
        True,
        "classes",
        _redundant_subclass,
    ),
    QualityCheck(
        "disconnected_island",
        "Disconnected islands",
        "Groups of two or more classes connected to each other but not to the "
        "rest of the model.",
        "structure",
        "info",
        True,
        "classes",
        _disconnected_islands,
    ),
    QualityCheck(
        "orphan_class",
        "Unconnected classes",
        "Classes not used in any hierarchy, domain or range, restriction, or "
        "instance typing.",
        "structure",
        "info",
        True,
        "classes",
        _reused("orphan_class"),
    ),
    QualityCheck(
        "missing_inverse",
        "Bidirectional properties without inverse",
        "Object properties connecting the same two classes in opposite "
        "directions, without owl:inverseOf between them.",
        "structure",
        "info",
        True,
        "properties",
        _missing_inverse,
    ),
    QualityCheck(
        "missing_domain",
        "Properties without domain or range",
        "Properties with no rdfs:domain or rdfs:range (or domainIncludes / "
        "rangeIncludes).",
        "structure",
        "info",
        True,
        "properties",
        _reused("missing_domain", "missing_range"),
    ),
    QualityCheck(
        "multi_parent",
        "Multiple parents",
        "Classes with more than one named superclass. Legal OWL, so off by default.",
        "structure",
        "info",
        False,
        "classes",
        _multi_parent,
    ),
    QualityCheck(
        "flat_class",
        "Classes outside the hierarchy",
        "Classes used by properties or restrictions that have neither a parent "
        "nor a subclass. A valid style, so off by default.",
        "structure",
        "info",
        False,
        "classes",
        _flat_class,
    ),
    QualityCheck(
        "missing_label",
        "Classes without label",
        "Classes with no rdfs:label or skos:prefLabel.",
        "naming",
        "warning",
        True,
        "classes",
        _reused("missing_label"),
    ),
)

CHECKS_BY_KEY = {check.key: check for check in QUALITY_CHECKS}


def assess_quality(
    ont: OntologyManager,
    enabled: Collection[str] | None = None,
    include_external: bool = False,
) -> QualityReport:
    """Run the ``enabled`` checks (every default-on one when None) and score them.

    Each check scores ``1 - affected / population`` over its own population;
    the overall score is their average weighted by severity, as 0-100. Checks
    with nothing to look at do not count.
    """
    if enabled is None:
        enabled = {check.key for check in QUALITY_CHECKS if check.default_on}
    ctx = QualityContext(ont, include_external=include_external)
    report = QualityReport()
    weighted = total = 0.0
    for check in QUALITY_CHECKS:
        if check.key not in enabled:
            continue
        issues, affected = check.run(ctx)
        result = CheckResult(len(affected), ctx.population(check.population))
        report.findings[check.key] = issues
        report.per_check[check.key] = result
        if (score := result.score) is not None:
            weight = _WEIGHTS[check.severity]
            weighted += weight * score
            total += weight
    if total:
        report.score = round(100 * weighted / total)
    return report

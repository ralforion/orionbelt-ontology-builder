"""What the dashboard shows about the loaded ontology.

Counts, how well the ontology's own entities are documented, the shape of its
class hierarchy, and how its individuals and labels spread. The coverage
figures read the predicates rules Q001 (label) and Q002 (definition) read, and
over the same entities, so the dashboard and the Quality section never
disagree about what counts as documented.

No Streamlit import: it runs the same from the page, a test or a script.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import DC, DCTERMS, OWL, RDFS, SKOS, URIRef

from .quality.context import QualityContext
from .quality.registry import OWL_PROFILE, SKOS_PROFILE

if TYPE_CHECKING:
    from .ontology_manager import OntologyManager

#: Where an ontology's name is looked for, first match wins.
TITLE_PREDICATES = (RDFS.label, DCTERMS.title, DC.title, SKOS.prefLabel)
#: The language of a label without a language tag, as the dashboard lists it.
NO_LANGUAGE = "no tag"


@dataclass(frozen=True)
class Coverage:
    """How many of ``total`` entities have something, e.g. a label."""

    label: str
    have: int
    total: int

    @property
    def share(self) -> float:
        return self.have / self.total if self.total else 0.0


@dataclass(frozen=True)
class Hierarchy:
    """The shape of the ``rdfs:subClassOf`` tree over the ontology's classes."""

    classes: int
    #: Classes without a named superclass among them.
    roots: int
    #: Classes without a subclass among them.
    leaves: int
    #: Classes with more than one named superclass among them.
    multi_parent: int
    #: Classes per depth, a root at depth 0. A class sits at its deepest
    #: position, the longest path up to a root.
    per_depth: tuple[int, ...]
    #: Classes on or below a ``subClassOf`` cycle, which have no depth.
    in_cycles: int

    @property
    def max_depth(self) -> int:
        return len(self.per_depth) - 1 if self.per_depth else 0


@dataclass(frozen=True)
class Overview:
    """Everything the dashboard's Overview draws, worked out in one pass."""

    title: str
    ontology_iri: str
    version: str
    comment: str
    #: Content triples, the number the sidebar reports: the ontology header's
    #: own triples left out (issue #263).
    triples: int
    imports: int
    uses_owl: bool
    uses_skos: bool
    #: Tile label -> value, in display order.
    counts: dict[str, int]
    #: Whether coverage and hierarchy count only the ontology's own entities
    #: (its namespace, or ``rdfs:isDefinedBy`` it) because the graph holds
    #: others too, such as a merged upper ontology.
    own_scope_only: bool
    coverage: tuple[Coverage, ...]
    hierarchy: Hierarchy
    #: (class name, individuals), most first.
    instances_per_class: tuple[tuple[str, int], ...]
    #: (language tag, or NO_LANGUAGE, preferred labels), most first.
    label_languages: tuple[tuple[str, int], ...]

    @property
    def is_empty(self) -> bool:
        return not any(self.counts.values())


def _coverage(ctx: QualityContext, uris: set[str], kind: str) -> Iterable[Coverage]:
    if not uris:
        return
    yield Coverage(f"{kind} labels", sum(1 for u in uris if ctx.labels(u)), len(uris))
    yield Coverage(
        f"{kind} definitions", sum(1 for u in uris if ctx.definitions(u)), len(uris)
    )


def _hierarchy(ctx: QualityContext) -> Hierarchy:
    classes = ctx.classes
    parents = {
        c: [p for p in ctx.parents.get(c, []) if p in classes and p != c]
        for c in classes
    }
    children: dict[str, list[str]] = {c: [] for c in classes}
    for child, ps in parents.items():
        for p in ps:
            children[p].append(child)

    # Longest path from a root, by Kahn's order: a class is placed once every
    # superclass is. What a cycle holds (and what hangs below it) never is.
    waiting = {c: len(ps) for c, ps in parents.items()}
    depth = {c: 0 for c, n in waiting.items() if n == 0}
    ready = list(depth)
    while ready:
        current = ready.pop()
        for child in children[current]:
            depth[child] = max(depth.get(child, 0), depth[current] + 1)
            waiting[child] -= 1
            if waiting[child] == 0:
                ready.append(child)

    per_depth = Counter(depth.values())
    return Hierarchy(
        classes=len(classes),
        roots=sum(1 for ps in parents.values() if not ps),
        leaves=sum(1 for cs in children.values() if not cs),
        multi_parent=sum(1 for ps in parents.values() if len(ps) > 1),
        per_depth=tuple(per_depth[d] for d in range(max(per_depth, default=-1) + 1)),
        in_cycles=len(classes) - len(depth),
    )


def _ranked(counts: Counter[str], top: int) -> tuple[tuple[str, int], ...]:
    """The ``top`` largest, then the rest folded into one "Other" row."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    head, tail = ranked[:top], ranked[top:]
    if tail:
        head.append((f"Other ({len(tail)})", sum(n for _, n in tail)))
    return tuple(head)


def ontology_overview(ont: OntologyManager, *, top: int = 8) -> Overview:
    """Work out what the dashboard shows about ``ont``."""
    ctx = QualityContext(ont)
    stats = ont.get_statistics()
    metadata = ont.get_ontology_metadata()
    vocabularies = ctx.vocabularies
    uses_skos = SKOS_PROFILE in vocabularies
    # An empty graph uses neither; it gets the OWL tiles, at zero.
    uses_owl = OWL_PROFILE in vocabularies or not uses_skos

    counts: dict[str, int] = {}
    if uses_owl:
        # Named classes, as the Classes page lists them: get_statistics()
        # also counts the anonymous ones a union or a complement declares.
        counts["Classes"] = len(ont.get_classes())
        counts["Object properties"] = stats["object_properties"]
        counts["Data properties"] = stats["data_properties"]
        counts["Individuals"] = stats["individuals"]
        counts["Restrictions"] = stats["restrictions"]
    if uses_skos:
        counts["Concept schemes"] = stats["concept_schemes"]
        counts["Concepts"] = stats["concepts"]

    coverage = [
        *_coverage(ctx, ctx.classes, "Class"),
        *_coverage(ctx, ctx.properties, "Property"),
    ]
    if ctx.properties:
        props = [URIRef(p) for p in ctx.properties]
        coverage.append(
            Coverage(
                "Property domains",
                sum(1 for p in props if ctx.domains(p)),
                len(props),
            )
        )
        coverage.append(
            Coverage(
                "Property ranges", sum(1 for p in props if ctx.ranges(p)), len(props)
            )
        )
    coverage.extend(_coverage(ctx, ctx.concepts, "Concept"))

    instances: Counter[str] = Counter()
    for individual in ont.get_individuals():
        for class_uri in individual["class_uris"]:
            if class_uri != str(OWL.Thing):
                instances[ctx.name(class_uri)] += 1

    languages: Counter[str] = Counter(
        label.language or NO_LANGUAGE
        for uri in ctx.documentable
        for label in ctx.labels(uri)
    )

    # The quality context counts only the ontology's own entities when it has
    # any; say so when that left something out.
    in_scope = len(ctx.classes) + len(ctx.properties) + len(ctx.concepts)
    named = (
        len(ont.get_classes())
        + len(ont.get_object_properties())
        + len(ont.get_data_properties())
        + stats["concepts"]
    )

    iri = str(ont.ontology_uri)
    version_info = ont.graph.value(ont.ontology_uri, OWL.versionInfo)
    # FOAF and PROV-O name themselves with a Dublin Core title, not a label.
    title = next(
        (
            str(value)
            for pred in TITLE_PREDICATES
            if (value := ont.graph.value(ont.ontology_uri, pred)) is not None
        ),
        "",
    )
    return Overview(
        title=title or ont._local_name(ont.ontology_uri) or iri,
        ontology_iri=iri,
        version=str(version_info or metadata.get("version_iri", "")),
        comment=metadata.get("comment", ""),
        triples=stats["content_triples"],
        imports=len(ont.get_imports()),
        uses_owl=uses_owl,
        uses_skos=uses_skos,
        counts=counts,
        own_scope_only=in_scope < named,
        coverage=tuple(coverage),
        hierarchy=_hierarchy(ctx),
        instances_per_class=_ranked(instances, top),
        label_languages=_ranked(languages, top),
    )

"""What the rules share, worked out once per run.

Most of all, *which resources are this ontology's own*. An ontology that merged
gist in is not the place to report gist's modelling, so by default a rule only
looks at the ontology's own classes and properties (``include_imports`` turns
that off). And *how classes connect*: real ontologies state much of their
structure through anonymous class expressions, which a reading of plain
``rdfs:subClassOf`` edges misses.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from collections.abc import Iterable, Iterator
from functools import cached_property
from typing import TYPE_CHECKING, Any

from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.namespace import DC, DCTERMS, OWL, RDF, RDFS, SKOS, XSD
from rdflib.term import Node

from ..ontology_manager import _DOMAIN_INCLUDES, _RANGE_INCLUDES, SKOSXL
from .models import QualityFinding, Severity
from .registry import OWL_PROFILE, SKOS_PROFILE

if TYPE_CHECKING:
    from ..ontology_manager import OntologyManager

_KIND_BY_TYPE = {
    OWL.Class: "Class",
    OWL.ObjectProperty: "Object Property",
    OWL.DatatypeProperty: "Data Property",
    SKOS.Concept: "SKOS Concept",
}

_OBO = Namespace("http://purl.obolibrary.org/obo/")

#: Vocabularies whose types describe a resource's role, not its class.
_META_NAMESPACES = (str(RDF), str(RDFS), str(OWL), str(SKOS))

#: Where a preferred label lives.
LABEL_PREDICATES = (RDFS.label, SKOS.prefLabel)

#: Where a definition or description lives. IAO_0000115 is the OBO
#: "definition" annotation.
DEFINITION_PREDICATES = (
    SKOS.definition,
    RDFS.comment,
    DCTERMS.description,
    DC.description,
    _OBO.IAO_0000115,
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def words(text: str) -> list[str]:
    """``"PersonName"``, ``"person_name"`` and ``"person name"`` as words."""
    spaced = _CAMEL_BOUNDARY.sub(" ", text)
    return [w for w in re.split(r"[\s_\-.]+", spaced) if w]


def normalise(text: str) -> str:
    """For comparing labels: Unicode NFC, case-folded, whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


#: Where an anonymous class expression names a class: a restriction's filler,
#: a complement, or a member of an intersection or union list.
_EXPRESSION_TARGETS = (
    OWL.someValuesFrom,
    OWL.allValuesFrom,
    OWL.onClass,
    OWL.complementOf,
    RDF.first,
)

#: Data ranges that are not in the XSD namespace. A restriction on a data
#: property names one of these, or an XSD type, where an object restriction
#: names a class.
_BUILTIN_DATA_RANGES = frozenset(
    {RDFS.Literal, RDF.langString, RDF.PlainLiteral, RDF.XMLLiteral, RDF.HTML}
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
            for rdf_type in (
                OWL.Class,
                OWL.ObjectProperty,
                OWL.DatatypeProperty,
                RDFS.Class,
            )
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
    def concepts(self) -> set[str]:
        """Named, in-scope ``skos:Concept`` resources."""
        return self._declared(SKOS.Concept)

    @cached_property
    def documentable(self) -> list[str]:
        """Classes, properties and concepts: what labels and definitions are for."""
        return sorted(self.classes | self.properties | self.concepts)

    def literals(
        self, uri: str, predicates: Iterable[URIRef]
    ) -> list[tuple[URIRef, Literal]]:
        ref = URIRef(uri)
        return [
            (pred, obj)
            for pred in predicates
            for obj in self.graph.objects(ref, pred)
            if isinstance(obj, Literal)
        ]

    def labels(self, uri: str) -> list[Literal]:
        """Preferred labels, SKOS-XL ones included.

        A ``skosxl:prefLabel`` whose label resource has a ``literalForm`` is a
        preferred label (SKOS Reference B.3.4.2), read through the same
        helper the SKOS validator uses. Deduplicated by value and language,
        since a plain and an XL label with the same literal are one statement
        (Codex review of PR #505).
        """
        found: dict[tuple[str, str], Literal] = {}
        for _, lit in self.literals(uri, LABEL_PREDICATES):
            found.setdefault((str(lit), lit.language or ""), lit)
        for item in self.ont._xl_literals(URIRef(uri), SKOSXL.prefLabel):
            key = (item["value"], item["lang"])
            found.setdefault(key, Literal(item["value"], lang=item["lang"] or None))
        return list(found.values())

    @cached_property
    def skos_concepts(self) -> list[dict[str, Any]]:
        """``get_concepts()``, for the rules that reuse the SKOS validator's
        helpers on it."""
        if SKOS_PROFILE not in self.vocabularies:
            return []
        return self.ont.get_concepts()

    def definitions(self, uri: str) -> list[tuple[URIRef, Literal]]:
        return self.literals(uri, DEFINITION_PREDICATES)

    @cached_property
    def uses_other_languages(self) -> bool:
        """Whether any label is tagged with a language other than English."""
        return any(
            isinstance(lit, Literal)
            and lit.language
            and not lit.language.lower().startswith("en")
            for pred in LABEL_PREDICATES
            for lit in self.graph.objects(None, pred)
        )

    def english_name(self, uri: str) -> str | None:
        """The English name to run English-only heuristics on, or None.

        An ``@en`` label first, then an untagged one, then the local name, but
        the last two only when nothing in the ontology is labelled in another
        language: there an untagged or local name may well not be English.
        """
        labels = self.labels(uri)
        for lit in labels:
            if lit.language and lit.language.lower().startswith("en"):
                return str(lit)
        if self.uses_other_languages:
            return None
        for lit in labels:
            if not lit.language:
                return str(lit)
        return self.ont._local_name(URIRef(uri))

    @cached_property
    def deprecated(self) -> set[str]:
        """Resources marked ``owl:deprecated true``."""
        return {
            str(s)
            for s, value in self.graph.subject_objects(OWL.deprecated)
            if isinstance(s, URIRef)
            and isinstance(value, Literal)
            and str(value).strip().lower() in ("true", "1")
        }

    def named_owners(self, node) -> set[str]:
        """The named resources a node is, or hangs off.

        All of them: one restriction can be shared by several classes, and
        reporting only the first one found would make the result depend on
        triple order (Codex review of PR #505).
        """
        owners: set[str] = set()
        seen = set()
        frontier = [node]
        while frontier:
            current = frontier.pop()
            if isinstance(current, URIRef):
                owners.add(str(current))
                continue
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(self.graph.subjects(None, current))
        return owners

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

    def kind(self, uri: str) -> str | None:
        """What the resource is, as the navigation names it, or None.

        An individual is anything typed ``owl:NamedIndividual`` or with a type
        outside the RDF, RDFS, OWL and SKOS vocabularies; telling it apart is
        what sends its Open button to Individuals rather than Classes (Codex
        review of PR #505).
        """
        ref = URIRef(uri)
        for rdf_type, kind in _KIND_BY_TYPE.items():
            if (ref, RDF.type, rdf_type) in self.graph:
                return kind
        for type_node in self.graph.objects(ref, RDF.type):
            if type_node == OWL.NamedIndividual or not str(type_node).startswith(
                _META_NAMESPACES
            ):
                return "Individual"
        if (ref, RDFS.subClassOf, None) in self.graph or (
            None,
            RDFS.subClassOf,
            ref,
        ) in self.graph:
            return "Class"
        return None

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
                    if not self.is_data_range(str(obj)):
                        targets.add(str(obj))
                elif isinstance(obj, BNode):
                    targets |= self._expression_targets(obj)
        return targets

    def domains(self, prop: URIRef) -> set[str]:
        return self._class_targets(prop, (RDFS.domain, *_DOMAIN_INCLUDES))

    def ranges(self, prop: URIRef) -> set[str]:
        return self._class_targets(prop, (RDFS.range, *_RANGE_INCLUDES))

    def is_data_range(self, uri: str) -> bool:
        """An XSD or RDF datatype, or anything declared ``rdfs:Datatype``.

        Not a class, so not something two classes can be connected through:
        two hierarchies that each restrict a data property to ``xsd:string``
        are still two hierarchies (Codex review of PR #504).
        """
        return (
            uri.startswith(str(XSD))
            or URIRef(uri) in _BUILTIN_DATA_RANGES
            or (URIRef(uri), RDF.type, RDFS.Datatype) in self.graph
        )

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
                elif (
                    isinstance(obj, URIRef)
                    and pred in _EXPRESSION_TARGETS
                    and not self.is_data_range(str(obj))
                ):
                    targets.add(str(obj))
        return targets

    @cached_property
    def used_classes(self) -> set[str]:
        """Classes a property or a restriction uses.

        Wider than the endpoints of :attr:`class_links`, which needs a class
        at each end: a data property's domain, or an object property with a
        domain and no range, uses its class all the same (Codex review of
        PR #504).
        """
        used = {uri for link in self.class_links for uri in link}
        for rdf_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
            for prop in self.graph.subjects(RDF.type, rdf_type):
                if isinstance(prop, URIRef):
                    used |= self.domains(prop)
                    if rdf_type == OWL.ObjectProperty:
                        used |= self.ranges(prop)
        for pred in (RDFS.subClassOf, OWL.equivalentClass):
            for cls, expression in self.graph.subject_objects(pred):
                if (
                    isinstance(cls, URIRef)
                    and isinstance(expression, BNode)
                    and (expression, RDF.type, OWL.Restriction) in self.graph
                ):
                    used.add(str(cls))
        return used

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

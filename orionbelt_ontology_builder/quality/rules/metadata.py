"""Rules about labels, definitions and other annotations."""

from __future__ import annotations

import re

from rdflib import URIRef
from rdflib.namespace import DCTERMS, OWL, RDFS, SKOS, XSD

from ..context import (
    _OBO,
    DEFINITION_PREDICATES,
    LABEL_PREDICATES,
    SKOSXL,
    QualityContext,
    words,
)
from ..models import Severity
from ..registry import OWL_PROFILE, SKOS_PROFILE, Rule, RuleResult, register

_ANY = frozenset({OWL_PROFILE, SKOS_PROFILE})


def _missing_label(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        if any(str(label).strip() for label in ctx.labels(uri)):
            continue
        kind = ctx.kind(uri)
        result.findings.append(
            ctx.finding(
                "Q001",
                severity,
                uri,
                f"{kind} '{ctx.name(uri)}' has no preferred label "
                "(rdfs:label or skos:prefLabel).",
                suggestion="Add an rdfs:label (skos:prefLabel for a concept) with "
                "a language tag.",
            )
        )
        result.affected.add(uri)
    return result


def _missing_definition(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        if any(str(text).strip() for _, text in ctx.definitions(uri)):
            continue
        result.findings.append(
            ctx.finding(
                "Q002",
                severity,
                uri,
                f"{ctx.kind(uri)} '{ctx.name(uri)}' has no definition or description.",
                suggestion="Add a skos:definition (or rdfs:comment) saying what it "
                "is and how it differs from its siblings.",
            )
        )
        result.affected.add(uri)
    return result


#: A whole value that says nothing: empty, dashes, dots, "n/a", "?", or only
#: a to-do marker in any case.
_EMPTY_VALUE = re.compile(
    r"^\s*(?:-+|\.{2,}|…|n/?a|none|\?+|todo|tbd|fixme)?\s*[.:!]?\s*$",
    re.IGNORECASE,
)
#: Markers inside a text that it was left to be written later. Capitals only
#: for the to-do words, so "a todo-list item" is prose, not a marker.
_PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|(?i:\blorem ipsum\b)")


def _placeholders(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        for pred, text in ctx.definitions(uri):
            value = str(text)
            match = _PLACEHOLDER.search(value)
            if match:
                found = match.group(0)
            elif _EMPTY_VALUE.match(value):
                found = value.strip() or "(empty)"
            else:
                continue
            result.findings.append(
                ctx.finding(
                    "Q004",
                    severity,
                    uri,
                    f"The {ctx.ont._local_name(pred)} of '{ctx.name(uri)}' is a "
                    f"placeholder: {found!r}.",
                    evidence={"predicate": str(pred), "value": value, "matched": found},
                    suggestion="Write the description, or remove the placeholder so "
                    "the gap shows as a missing definition.",
                )
            )
            result.affected.add(uri)
    return result


#: Links to a deprecated resource that are not a use of it:
#: - annotations *about* the deprecation ("replaced by", "see also");
#: - a direct equivalence, which is how an old name is kept resolving to its
#:   successor (GoodRelations: ``Individual ≡ ActualProductOrServiceInstance``);
#: - disjointness, which only rules something out and keeps holding after the
#:   deprecation (gist keeps deprecated classes in its disjointness axioms).
#: A deprecated class inside a class expression is still reported: there the
#: predicate is the restriction's, not one of these.
_NOT_A_USE = {
    DCTERMS.isReplacedBy,
    RDFS.seeAlso,
    _OBO.IAO_0100001,  # term replaced by
    OWL.deprecated,
    OWL.equivalentClass,
    OWL.equivalentProperty,
    OWL.sameAs,
    OWL.disjointWith,
    OWL.propertyDisjointWith,
}


def _replacement(ctx: QualityContext, uri: str) -> str | None:
    for pred in (DCTERMS.isReplacedBy, _OBO.IAO_0100001):
        for obj in ctx.graph.objects(URIRef(uri), pred):
            if isinstance(obj, URIRef):
                return str(obj)
    return None


def _deprecated_use(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    if not ctx.deprecated:
        return result
    for subject, pred, obj in ctx.graph:
        if pred in _NOT_A_USE:
            continue
        # A literal that happens to spell a deprecated URI is text, not a
        # reference (Codex review of PR #505). Typing an individual with a
        # deprecated class is a use, so rdf:type is not skipped.
        used = [
            str(term)
            for term in (pred, obj)
            if isinstance(term, URIRef) and str(term) in ctx.deprecated
        ]
        if not used:
            continue
        for owner in sorted(ctx.named_owners(subject)):
            # A deprecated resource describing itself, or another deprecated
            # one, is not a use anyone needs to fix.
            if owner in ctx.deprecated or not ctx.in_scope(owner):
                continue
            for target in used:
                replacement = _replacement(ctx, target)
                hint = (
                    f"Use '{ctx.name(replacement)}' instead."
                    if replacement
                    else "Replace it with a current resource, or drop the reference."
                )
                result.findings.append(
                    ctx.finding(
                        "Q016",
                        severity,
                        owner,
                        f"'{ctx.name(owner)}' uses '{ctx.name(target)}', which is "
                        "deprecated.",
                        evidence={
                            "deprecated": target,
                            "predicate": str(pred),
                            "replacement": replacement,
                        },
                        suggestion=hint,
                        related=[target] + ([replacement] if replacement else []),
                    )
                )
                result.affected.add(owner)
    return result


for _rule in (
    Rule(
        "Q001",
        "Missing preferred label",
        "Classes, properties and concepts with no rdfs:label or skos:prefLabel.",
        "metadata",
        _ANY,
        "warning",
        True,
        _missing_label,
    ),
    Rule(
        "Q002",
        "Missing definition",
        "Classes, properties and concepts with no skos:definition, rdfs:comment, "
        "dcterms:description or IAO definition.",
        "metadata",
        _ANY,
        "info",
        True,
        _missing_definition,
    ),
    Rule(
        "Q004",
        "Placeholder descriptions",
        "Definitions or descriptions that are empty, a dash, or say TODO, TBD, "
        "FIXME or lorem ipsum.",
        "metadata",
        _ANY,
        "warning",
        True,
        _placeholders,
    ),
    Rule(
        "Q016",
        "Use of deprecated resources",
        "References to anything marked owl:deprecated true, other than "
        "'replaced by' and 'see also' annotations, aliases (equivalence) and "
        "disjointness.",
        "metadata",
        _ANY,
        "warning",
        True,
        _deprecated_use,
    ),
):
    register(_rule)


# -- vague or circular definitions (Q013) -------------------------------------------

#: Words a definition needs anyway; they say nothing about the thing defined.
_STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "and",
    "or",
    "is",
    "are",
    "be",
    "by",
    "with",
    "that",
    "this",
    "which",
    "it",
    "its",
    "as",
    "at",
    "any",
    "some",
    "thing",
    "something",
    "kind",
    "type",
    "sort",
}
_NEGATIVE_START = re.compile(
    r"^\s*(not\b|no\b|(anything|something|everything)\s+(that\s+)?(is|which is)\s+not\b)",
    re.IGNORECASE,
)
#: Fewer words than this cannot say what something is and how it differs.
_MIN_WORDS = 5


def _content_words(text: str) -> set[str]:
    return {
        w.casefold().rstrip("s")
        for w in re.findall(r"[A-Za-z][A-Za-z-]+", text)
        if w.casefold() not in _STOPWORDS
    }


def _english_definitions(ctx: QualityContext, uri: str) -> list[str]:
    """The definitions English heuristics may judge: ``@en``, or untagged
    when nothing in the ontology is labelled in another language."""
    texts = []
    for _, text in ctx.definitions(uri):
        lang = (text.language or "").lower()
        if lang.startswith("en") or (not lang and not ctx.uses_other_languages):
            texts.append(str(text))
    return texts


def _vague_definitions(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        texts = [t for t in _english_definitions(ctx, uri) if t.strip()]
        if not texts:
            continue
        label_words = set()
        for label in ctx.labels(uri):
            label_words |= _content_words(str(label))
        label_words |= _content_words(" ".join(words(ctx.ont._local_name(URIRef(uri)))))
        parent_words: set[str] = set()
        for parent in ctx.parents.get(uri, []):
            for label in ctx.labels(parent):
                parent_words |= _content_words(str(label))
            parent_words |= _content_words(
                " ".join(words(ctx.ont._local_name(URIRef(parent))))
            )
        for text in texts:
            if _PLACEHOLDER.search(text) or _EMPTY_VALUE.match(text):
                continue  # Q004's
            reasons = []
            content = _content_words(text)
            if len(text.split()) < _MIN_WORDS:
                reasons.append("too short")
            if content and content <= label_words:
                reasons.append("only repeats the name")
            if _NEGATIVE_START.match(text):
                reasons.append("says only what it is not")
            if parent_words and not (content & parent_words):
                reasons.append("does not name its superclass")
            if not reasons:
                continue
            result.findings.append(
                ctx.finding(
                    "Q013",
                    severity,
                    uri,
                    f"The definition of '{ctx.name(uri)}' {', and '.join(reasons)}: "
                    f"'{text[:80]}{'…' if len(text) > 80 else ''}'",
                    evidence={"reasons": reasons, "definition": text},
                    suggestion="Say what kind of thing it is (its superclass) and "
                    "what sets it apart: 'A Customer is a Person who has bought …'.",
                )
            )
            result.affected.add(uri)
    return result


# -- missing language tags (Q017) ----------------------------------------------------

#: Literals a localised ontology tags with a language: every label and
#: definition form the other rules read, plus alternative and hidden labels.
_TEXT_PREDICATES = (
    *LABEL_PREDICATES,
    SKOS.altLabel,
    SKOS.hiddenLabel,
    *DEFINITION_PREDICATES,
)
_XL_LABELS = (SKOSXL.prefLabel, SKOSXL.altLabel, SKOSXL.hiddenLabel)


def _untagged(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        found = {
            ctx.ont._local_name(pred)
            for pred, text in ctx.literals(uri, _TEXT_PREDICATES)
            if not text.language
            and (text.datatype is None or text.datatype == XSD.string)
            and str(text).strip()
        }
        # SKOS-XL labels, read through their literal form as Q001 reads them.
        found |= {
            f"skosxl:{ctx.ont._local_name(pred)}"
            for pred in _XL_LABELS
            for item in ctx.ont._xl_literals(URIRef(uri), pred)
            if not item["lang"] and item["value"].strip()
        }
        untagged = sorted(found)
        if not untagged:
            continue
        result.findings.append(
            ctx.finding(
                "Q017",
                severity,
                uri,
                f"'{ctx.name(uri)}' has text without a language tag: "
                f"{', '.join(untagged)}.",
                evidence={"predicates": untagged},
                suggestion="Tag labels and definitions with their language "
                '("Customer"@en), so translations can sit beside them.',
            )
        )
        result.affected.add(uri)
    return result


for _rule in (
    Rule(
        "Q013",
        "Vague or circular definitions",
        "English definitions that are too short, only repeat the name, say only "
        "what something is not, or do not name the superclass.",
        "metadata",
        _ANY,
        "info",
        False,
        _vague_definitions,
    ),
    Rule(
        "Q017",
        "Missing language tags",
        "Labels and definitions without a language tag. For localised "
        "ontologies, so off by default.",
        "metadata",
        _ANY,
        "info",
        False,
        _untagged,
    ),
):
    register(_rule)

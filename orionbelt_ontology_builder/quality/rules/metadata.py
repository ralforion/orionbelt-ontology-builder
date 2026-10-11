"""Rules about labels, definitions and other annotations."""

from __future__ import annotations

import re

from rdflib import URIRef
from rdflib.namespace import DCTERMS, OWL, RDFS

from ..context import _OBO, QualityContext
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

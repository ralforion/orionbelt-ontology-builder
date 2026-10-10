"""Rules about names: duplicate labels and naming conventions."""

from __future__ import annotations

import re

from rdflib import URIRef

from ..context import QualityContext, normalise, words
from ..models import Severity
from ..registry import OWL_PROFILE, SKOS_PROFILE, Rule, RuleResult, register


def _duplicate_labels(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Two resources of one kind sharing a preferred label in one language.

    Compared within a kind (classes with classes, properties with properties,
    concepts with concepts), because a class ``Person`` and a property
    ``person`` sharing a word is ordinary.
    """
    result = RuleResult(checked=len(ctx.documentable))
    groups: dict[tuple[str, str, str], set[str]] = {}
    shown: dict[tuple[str, str, str], str] = {}
    for uri in ctx.documentable:
        family = "property" if uri in ctx.properties else ctx.kind(uri)
        for label in ctx.labels(uri):
            text = normalise(str(label))
            if not text:
                continue
            key = (family, (label.language or "").lower(), text)
            groups.setdefault(key, set()).add(uri)
            shown.setdefault(key, str(label))
    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        family, lang, _ = key
        ordered = sorted(members)
        tag = f"@{lang}" if lang else ""
        result.findings.append(
            ctx.finding(
                "Q003",
                severity,
                ordered[0],
                f"{len(ordered)} resources share the label '{shown[key]}'{tag}: "
                + ", ".join(ctx.name(uri) for uri in ordered)
                + ".",
                evidence={"label": shown[key], "lang": lang, "resources": ordered},
                suggestion="If they mean the same thing, merge them; otherwise make "
                "the labels say how they differ.",
                related=ordered[1:],
            )
        )
        result.affected.update(ordered)
    return result


#: Local names that are identifiers, not words (OBO ``GO_0008150``, numeric
#: IDs). Naming conventions do not apply to them.
_OPAQUE = re.compile(r"^(?:[A-Za-z]+_)?\d+$|^[A-Z]+_\d+$")
_UPPER_CAMEL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_LOWER_CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*$")

#: Words ending in "s" that are singular.
_SINGULAR_S = {
    "address",
    "alias",
    "analysis",
    "apparatus",
    "atlas",
    "axis",
    "basis",
    "bias",
    "bonus",
    "bus",
    "campus",
    "canvas",
    "census",
    "chassis",
    "corpus",
    "crisis",
    "diagnosis",
    "focus",
    "gas",
    "genus",
    "hypothesis",
    "iris",
    "lens",
    "means",
    "news",
    "plus",
    "radius",
    "series",
    "species",
    "status",
    "synopsis",
    "thesis",
    "virus",
}
_SINGULAR_ENDINGS = ("ss", "us", "is", "ous", "ics", "sis")

#: Last words that name an attribute of something rather than a thing.
_ATTRIBUTE_WORDS = {
    "amount",
    "code",
    "count",
    "date",
    "flag",
    "id",
    "identifier",
    "number",
    "time",
    "timestamp",
}


def _looks_plural(word: str) -> bool:
    w = word.lower()
    return (
        len(w) > 3
        and w.endswith("s")
        and w not in _SINGULAR_S
        and not w.endswith(_SINGULAR_ENDINGS)
    )


def _naming(ctx: QualityContext, severity: Severity) -> RuleResult:
    checked = sorted(ctx.classes | ctx.properties)
    result = RuleResult(checked=len(checked))

    def report(uri: str, convention: str, message: str, suggestion: str) -> None:
        result.findings.append(
            ctx.finding(
                "Q005",
                severity,
                uri,
                message,
                evidence={"convention": convention},
                suggestion=suggestion,
            )
        )
        result.affected.add(uri)

    for uri in checked:
        local = ctx.ont._local_name(URIRef(uri))
        if not local or _OPAQUE.match(local):
            continue
        is_class = uri in ctx.classes
        name = ctx.name(uri)
        if is_class and not _UPPER_CAMEL.match(local):
            report(
                uri,
                "class_upper_camel",
                f"Class '{name}' is not written in UpperCamelCase.",
                "Name classes like 'PurchaseOrder'.",
            )
        elif not is_class and not _LOWER_CAMEL.match(local):
            report(
                uri,
                "property_lower_camel",
                f"Property '{name}' is not written in lowerCamelCase.",
                "Name properties like 'hasPart' or 'birthDate'.",
            )
        if not is_class:
            continue
        english = ctx.english_name(uri)
        if english is None:
            continue
        last = (words(english) or [""])[-1]
        if _looks_plural(last):
            report(
                uri,
                "class_plural",
                f"Class '{name}' looks plural ('{last}').",
                "Name a class for one member: 'Customer', not 'Customers'.",
            )
        if last.lower() in _ATTRIBUTE_WORDS:
            report(
                uri,
                "class_attribute_like",
                f"Class '{name}' is named like an attribute ('{last}').",
                "If it only holds a value, make it a data property instead.",
            )
    return result


for _rule in (
    Rule(
        "Q003",
        "Duplicate preferred labels",
        "Resources of the same kind sharing a preferred label in the same "
        "language (case and spacing ignored).",
        "naming",
        frozenset({OWL_PROFILE, SKOS_PROFILE}),
        "warning",
        True,
        _duplicate_labels,
    ),
    Rule(
        "Q005",
        "Naming conventions",
        "UpperCamelCase classes, lowerCamelCase properties, and (for English "
        "names) classes that look plural or are named like an attribute.",
        "naming",
        frozenset({OWL_PROFILE}),
        "info",
        True,
        _naming,
    ),
):
    register(_rule)

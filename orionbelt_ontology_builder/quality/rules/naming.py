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
        family = "property" if uri in ctx.properties else ctx.kind(uri) or "other"
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


# -- similar labels (Q014) --------------------------------------------------------


def _loose(text: str) -> str:
    """A label reduced for "probably the same thing": case, separators and a
    plural last word gone (``Customer Orders`` → ``customerorder``)."""
    parts = [w.casefold() for w in words(normalise(text))]
    if parts and _looks_plural(parts[-1]):
        parts[-1] = parts[-1][:-1]
    return "".join(ch for ch in "".join(parts) if ch.isalnum())


def _one_typo_apart(a: str, b: str) -> bool:
    """One inserted, deleted or substituted character, or two swapped
    neighbours, away from each other, and not at either end.

    Both ends are left out on purpose: ``influenced``/``influencer``,
    ``VegetarianPizza``/``VegetarianPizza1`` and ``height``/``weight`` differ
    there by design, while a slip of the keyboard is as likely in between.
    The characters that differ must be letters: ``Class 1 of …`` and
    ``Class 2 of …`` are numbered, not misspelt. So is a whole word: a ratio
    threshold took ``Qualitative``/``Quantitative`` and ``min``/``max`` for
    duplicates, which they are not.
    """
    if a == b or min(len(a), len(b)) < 8 or abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if i == 0 or i >= min(len(a), len(b)) - 2:
        return False  # at the start or the end: other words, not a slip
    if len(a) == len(b):
        if a[i + 1 :] == b[i + 1 :]:
            return a[i].isalpha() and b[i].isalpha()  # one substitution
        return (
            a[i] == b[i + 1]
            and a[i + 1] == b[i]
            and a[i + 2 :] == b[i + 2 :]
            and a[i].isalpha()
            and b[i].isalpha()
        )
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer[i + 1 :] == shorter[i:] and longer[i].isalpha()


def _similar_labels(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Near-duplicates Q003's exact comparison misses: case, separators,
    plurals, and small spelling differences, within one kind and language."""
    result = RuleResult(checked=len(ctx.documentable))
    # Per kind and language, the resources under each label as Q003
    # normalises it: identical labels are one candidate, compared once,
    # however many resources carry them (2,000 identical labels were millions
    # of comparisons, Codex review of #510).
    groups: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for uri in ctx.documentable:
        family = "property" if uri in ctx.properties else ctx.kind(uri) or "other"
        for label in ctx.labels(uri):
            text = str(label)
            if not text.strip():
                continue
            lang = (label.language or "").lower()
            same = groups.setdefault((family, lang), {}).setdefault(normalise(text), {})
            same.setdefault(uri, text)
    pairs: dict[tuple[str, str], dict[str, str]] = {}
    for by_text in groups.values():
        # Candidates by deletion variants: two forms one insertion, deletion,
        # substitution or swap apart always share a variant with one
        # character dropped (or are equal). Comparing only within a variant
        # keeps a large vocabulary from costing every pair.
        loose = {norm: _loose(norm) for norm in by_text}
        buckets: dict[str, list[str]] = {}
        for norm, form in loose.items():
            for variant in {form} | {
                form[:i] + form[i + 1 :] for i in range(len(form))
            }:
                buckets.setdefault(variant, []).append(norm)
        compared: set[tuple[str, str]] = set()
        for bucket in buckets.values():
            for i, norm_a in enumerate(bucket):
                for norm_b in bucket[i + 1 :]:
                    candidate = (min(norm_a, norm_b), max(norm_a, norm_b))
                    if candidate in compared:
                        continue
                    compared.add(candidate)
                    form_a, form_b = loose[norm_a], loose[norm_b]
                    if form_a != form_b and not _one_typo_apart(form_a, form_b):
                        continue
                    for uri_a, text_a in by_text[norm_a].items():
                        for uri_b, text_b in by_text[norm_b].items():
                            if uri_a == uri_b:
                                continue  # one resource's own two labels
                            key = (min(uri_a, uri_b), max(uri_a, uri_b))
                            pairs.setdefault(key, {uri_a: text_a, uri_b: text_b})
    for (a, b), texts in sorted(pairs.items()):
        result.findings.append(
            ctx.finding(
                "Q014",
                severity,
                a,
                f"'{texts[a]}' ({ctx.name(a)}) and '{texts[b]}' ({ctx.name(b)}) are "
                "labelled almost alike.",
                evidence={"labels": [texts[a], texts[b]]},
                suggestion="If they are the same thing, merge them; otherwise make "
                "the labels say how they differ.",
                related=[b],
            )
        )
        result.affected.update((a, b))
    return result


# -- unexpanded acronyms (Q012) ----------------------------------------------------

_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}s?\b")
#: All-capital tokens that are not acronyms to expand.
_NOT_ACRONYMS = {"I", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "OK"}


def _acronyms(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Acronyms in labels of resources with no definition to expand them."""
    result = RuleResult(checked=len(ctx.documentable))
    for uri in ctx.documentable:
        if any(str(text).strip() for _, text in ctx.definitions(uri)):
            continue
        found = sorted(
            {
                token
                for label in ctx.labels(uri)
                for token in _ACRONYM.findall(str(label))
                if token.rstrip("s") not in _NOT_ACRONYMS
            }
        )
        if not found:
            continue
        result.findings.append(
            ctx.finding(
                "Q012",
                severity,
                uri,
                f"'{ctx.name(uri)}' uses {', '.join(found)} in its label, with no "
                "definition saying what it stands for.",
                evidence={"acronyms": found},
                suggestion="Spell the acronym out in a definition (or an altLabel).",
            )
        )
        result.affected.add(uri)
    return result


for _rule in (
    Rule(
        "Q012",
        "Unexpanded acronyms",
        "Labels with acronyms on resources that have no definition to say what "
        "they stand for.",
        "naming",
        frozenset({OWL_PROFILE, SKOS_PROFILE}),
        "info",
        False,
        _acronyms,
    ),
    Rule(
        "Q014",
        "Similar labels",
        "Labels of the same kind and language that differ only by case, "
        "separators, a plural, or one typo-like character. Suggestions, not "
        "certain duplicates.",
        "naming",
        frozenset({OWL_PROFILE, SKOS_PROFILE}),
        "info",
        True,
        _similar_labels,
    ),
):
    register(_rule)

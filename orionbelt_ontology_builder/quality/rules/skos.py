"""SKOS rules, built on the SKOS validator's own helpers.

The SKOS page owns these checks and their autofixes; the quality view reports
them with a stable ID and the same scope as every other rule.
"""

from __future__ import annotations

from ..context import QualityContext
from ..models import Severity
from ..registry import SKOS_PROFILE, Rule, RuleResult, register


def _prefLabel_per_language(ctx: QualityContext, severity: Severity) -> RuleResult:
    """One finding per concept *and language*: two English and two German
    labels are two problems, not one (Codex review of PR #505). Counted over
    the validator's effective labels, so SKOS-XL labels take part."""
    result = RuleResult(checked=len(ctx.concepts))
    for concept in ctx.skos_concepts:
        uri = concept["uri"]
        if uri not in ctx.concepts:
            continue
        by_lang: dict[str, int] = {}
        for item in ctx.ont._effective_labels(concept)["prefLabel"]:
            by_lang[item["lang"]] = by_lang.get(item["lang"], 0) + 1
        for lang, count in sorted(by_lang.items()):
            if count < 2:
                continue
            tag = f"@{lang}" if lang else " (untagged)"
            result.findings.append(
                ctx.finding(
                    "Q010",
                    severity,
                    uri,
                    f"Concept '{ctx.name(uri)}' has {count} prefLabels{tag}; SKOS "
                    "allows at most one per language tag (SKOS Reference S14).",
                    evidence={"lang": lang, "count": count},
                    suggestion="Keep one prefLabel per language and move the "
                    "others to skos:altLabel. The SKOS page can fix this for you.",
                )
            )
            result.affected.add(uri)
    return result


register(
    Rule(
        "Q010",
        "More than one prefLabel per language",
        "Concepts with two or more skos:prefLabel values in the same language "
        "(SKOS Reference S14).",
        "skos",
        frozenset({SKOS_PROFILE}),
        "error",
        True,
        _prefLabel_per_language,
    )
)

"""SKOS rules: adapters over ``OntologyManager.validate_skos()``.

The SKOS page owns these checks and their autofixes; the quality view reports
them with a stable ID and the same scope as every other rule.
"""

from __future__ import annotations

from ..context import QualityContext
from ..models import Severity
from ..registry import SKOS_PROFILE, Rule, RuleResult, register


def _prefLabel_per_language(ctx: QualityContext, severity: Severity) -> RuleResult:
    result = RuleResult(checked=len(ctx.concepts))
    for issue in ctx.skos_issues:
        uri = issue.get("subject_uri", "")
        if issue["type"] != "multi_prefLabel_per_lang" or uri not in ctx.concepts:
            continue
        result.findings.append(
            ctx.finding(
                "Q010",
                severity,
                uri,
                issue["message"],
                suggestion="Keep one prefLabel per language and move the others to "
                "skos:altLabel. The SKOS page can fix this for you.",
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

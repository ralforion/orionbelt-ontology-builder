"""Rules about labels, definitions and other annotations."""

from __future__ import annotations

from ..context import QualityContext
from ..models import Severity
from ..registry import OWL_PROFILE, Rule, RuleResult, register


def _missing_label(ctx: QualityContext, severity: Severity) -> RuleResult:
    """Adapter over ``validate()``'s ``missing_label`` (classes).

    M2 replaces it with a rule of its own that covers properties and SKOS
    concepts too and reads the configured label predicates.
    """
    result = RuleResult(checked=len(ctx.classes))
    for issue in ctx.validation_issues:
        if issue["type"] != "missing_label" or issue["subject_uri"] not in ctx.classes:
            continue
        result.findings.append(
            ctx.finding(
                "Q001",
                severity,
                issue["subject_uri"],
                issue["message"],
                suggestion="Add an rdfs:label (or skos:prefLabel) with a language tag.",
            )
        )
        result.affected.add(issue["subject_uri"])
    return result


register(
    Rule(
        "Q001",
        "Missing preferred label",
        "Classes with no rdfs:label or skos:prefLabel.",
        "metadata",
        frozenset({OWL_PROFILE}),
        "warning",
        True,
        _missing_label,
    )
)

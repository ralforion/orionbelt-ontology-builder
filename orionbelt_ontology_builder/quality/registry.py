"""The rule catalogue: what each rule is, where it applies, how it runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import QualityFinding, Severity

if TYPE_CHECKING:
    from .context import QualityContext

#: The vocabularies a graph can use, for a rule's applicability.
OWL_PROFILE = "owl"
SKOS_PROFILE = "skos"


@dataclass
class RuleResult:
    """What a rule returns: its findings and what they cover."""

    findings: list[QualityFinding] = field(default_factory=list)
    #: Resources the rule looked at.
    checked: int = 0
    #: Distinct resources it found something on. Differs from the number of
    #: findings when one finding names several (an island, a pair).
    affected: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Rule:
    """One rule in the catalogue."""

    id: str
    title: str
    description: str
    category: str
    #: Vocabularies the rule is about; it is skipped on a graph using none.
    applies_to: frozenset[str]
    default_severity: Severity
    default_enabled: bool
    #: Gets the context and the severity to report at. Never mutates the graph.
    evaluate: Callable[[QualityContext, Severity], RuleResult]


#: Every rule, in the order the UI lists them. Filled by the rules modules.
RULES: dict[str, Rule] = {}

CATEGORIES = {"structure": "Structure", "metadata": "Metadata"}


def register(rule: Rule) -> Rule:
    if rule.id in RULES:
        raise ValueError(f"Rule {rule.id} is registered twice")
    if rule.category not in CATEGORIES:
        raise ValueError(f"Rule {rule.id} has unknown category {rule.category!r}")
    RULES[rule.id] = rule
    return rule

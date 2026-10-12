"""What a quality run produces: findings, per-rule status, and the run itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
SEVERITIES: tuple[Severity, ...] = ("error", "warning", "info")

#: Where a finding came from: a Python rule, or a SHACL shapes source (M3).
Origin = Literal[
    "rule", "shacl:ontology", "shacl:bundled", "shacl:generated", "shacl:user"
]


@dataclass(frozen=True)
class QualityFinding:
    """One thing a rule found, about one resource."""

    rule_id: str
    severity: Severity
    #: The resource's URI. A blank node would be "_:" plus a stable label.
    resource: str
    #: "Class", "Object Property", "Data Property", … for navigation; None
    #: when the resource has no page of its own.
    resource_kind: str | None
    message: str
    #: Machine-readable support for the message, e.g. {"path": [...]}.
    evidence: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None
    related_resources: tuple[str, ...] = ()
    #: The SHACL shape that produced it (M3); None for Python rules.
    source_shape: str | None = None
    origin: Origin = "rule"

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity for de-duplication: rule, resource, and what was found."""
        return (self.rule_id, self.resource, repr(sorted(self.evidence.items())))


def finding_order(finding: QualityFinding) -> tuple[int, str, str, str]:
    """Severity first, then rule, resource and message."""
    return (
        SEVERITIES.index(finding.severity),
        finding.rule_id,
        finding.resource,
        finding.message,
    )


@dataclass(frozen=True)
class Suppression:
    """A finding someone looked at and decided is fine, and why.

    Matched by rule and resource, so it holds across runs and edits for as
    long as that rule finds something on that resource.
    """

    rule_id: str
    resource: str
    justification: str
    author: str = ""
    #: ISO 8601 date it was made.
    date: str = ""

    def matches(self, finding: QualityFinding) -> bool:
        return finding.rule_id == self.rule_id and finding.resource == self.resource


@dataclass(frozen=True)
class RuleStatus:
    """How one rule's run went, and what it covered."""

    rule_id: str
    state: Literal["ran", "skipped", "failed"]
    #: Why it was skipped, or the error it failed with.
    reason: str | None
    #: Resources the rule looked at, and how many of them it found something on.
    checked: int
    affected: int
    duration_ms: float


@dataclass(frozen=True)
class QualityRun:
    """One run of the analyzer over one graph with one configuration."""

    #: Sorted by severity, then rule ID, then resource.
    findings: tuple[QualityFinding, ...]
    #: In registry order, one per rule the configuration enables.
    rules: tuple[RuleStatus, ...]
    graph_fingerprint: str
    config_fingerprint: str
    #: ISO 8601, UTC.
    started_at: str
    analyzer_version: str
    #: Findings the configuration's suppressions set aside, with the
    #: suppression each matched. Not in ``findings`` or the counts.
    suppressed: tuple[tuple[QualityFinding, Suppression], ...] = ()

    def all_findings(self) -> tuple[QualityFinding, ...]:
        """Shown and suppressed together, in the run's order."""
        return tuple(
            sorted(
                (*self.findings, *(f for f, _ in self.suppressed)), key=finding_order
            )
        )

    def counts(self) -> dict[Severity, int]:
        """Findings per severity, every severity present."""
        result = dict.fromkeys(SEVERITIES, 0)
        for finding in self.findings:
            result[finding.severity] += 1
        return result

    def by_rule(self, rule_id: str) -> list[QualityFinding]:
        return [f for f in self.findings if f.rule_id == rule_id]

    def status(self, rule_id: str) -> RuleStatus | None:
        return next((s for s in self.rules if s.rule_id == rule_id), None)

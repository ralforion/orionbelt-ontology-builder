"""Semantic Quality Analyzer: advisory rules over the loaded ontology.

``OntologyManager.validate()`` answers "is something broken?". These rules
answer "is this a well-made ontology?". Most findings are advice, and some
modelling choices they flag are deliberate, so no rule here reports an error
for something OWL allows.

The analyzer never imports Streamlit and never mutates the graph, so it runs
the same from the page, a test, or a command line.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from importlib import metadata
from typing import TYPE_CHECKING

from . import rules as _rules  # noqa: F401 - registers the rule catalogue
from .config import PROFILES, QualityConfig, QualityConfigError, RuleSettings
from .context import QualityContext
from .models import (
    SEVERITIES,
    QualityFinding,
    QualityRun,
    RuleStatus,
    Severity,
    Suppression,
    finding_order,
)
from .registry import CATEGORIES, RULES, Rule, RuleResult

if TYPE_CHECKING:
    from ..ontology_manager import OntologyManager

__all__ = [
    "CATEGORIES",
    "PROFILES",
    "RULES",
    "SEVERITIES",
    "QualityConfig",
    "QualityConfigError",
    "QualityFinding",
    "QualityRun",
    "Rule",
    "RuleResult",
    "RuleSettings",
    "RuleStatus",
    "Severity",
    "Suppression",
    "analyze",
    "partition",
]


def _version() -> str:
    try:
        return metadata.version("orionbelt-ontology-builder")
    except metadata.PackageNotFoundError:
        return "unknown"


def analyze(
    ont: OntologyManager,
    config: QualityConfig | None = None,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> QualityRun:
    """Run every rule ``config`` enables over ``ont`` and collect the findings.

    A rule that does not apply to the graph's vocabularies is skipped, with the
    reason. A rule that raises is reported as failed, with the error, and the
    run goes on: a crash must never read as "nothing found".

    ``progress`` is called before each rule with how many have run, how many
    there are, and the rule's ID, so a caller can show where the run is.
    """
    config = config or QualityConfig()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    graph_fingerprint = ont.revision_token()
    ctx = QualityContext(ont, include_imports=config.include_imports)

    findings: dict[tuple[str, str, str], QualityFinding] = {}
    statuses: list[RuleStatus] = []
    enabled = config.enabled_rules()
    for done, rule_id in enumerate(enabled):
        if progress is not None:
            progress(done, len(enabled), rule_id)
        rule = RULES[rule_id]
        if not rule.applies_to & ctx.vocabularies:
            statuses.append(
                RuleStatus(
                    rule_id,
                    "skipped",
                    f"the graph uses no {'/'.join(sorted(rule.applies_to)).upper()}",
                    0,
                    0,
                    0.0,
                )
            )
            continue
        began = time.perf_counter()
        try:
            result = rule.evaluate(ctx, config.severity(rule_id))
        except Exception as exc:  # noqa: BLE001 - one rule must not end the run
            statuses.append(
                RuleStatus(
                    rule_id,
                    "failed",
                    f"{type(exc).__name__}: {exc}",
                    0,
                    0,
                    (time.perf_counter() - began) * 1000,
                )
            )
            continue
        for finding in result.findings:
            findings.setdefault(finding.key, finding)
        statuses.append(
            RuleStatus(
                rule_id,
                "ran",
                None,
                result.checked,
                len(result.affected),
                (time.perf_counter() - began) * 1000,
            )
        )

    shown, suppressed = partition(sorted(findings.values(), key=finding_order), config)
    return QualityRun(
        findings=shown,
        suppressed=suppressed,
        rules=tuple(statuses),
        graph_fingerprint=graph_fingerprint,
        config_fingerprint=config.fingerprint,
        started_at=started_at,
        analyzer_version=_version(),
    )


def partition(
    findings: Iterable[QualityFinding], config: QualityConfig
) -> tuple[tuple[QualityFinding, ...], tuple[tuple[QualityFinding, Suppression], ...]]:
    """Split findings into those to show and those ``config`` suppresses.

    The page applies it again to a stored run, so marking a finding as fine,
    or taking that back, shows at once without a new run.
    """
    shown: list[QualityFinding] = []
    suppressed: list[tuple[QualityFinding, Suppression]] = []
    for finding in findings:
        suppression = config.suppression_for(finding)
        if suppression is None:
            shown.append(finding)
        else:
            suppressed.append((finding, suppression))
    return tuple(shown), tuple(suppressed)

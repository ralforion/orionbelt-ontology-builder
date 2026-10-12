"""Findings as files: JSON for tools, CSV for spreadsheets.

Both carry every finding with its evidence. JSON adds what produced them (the
run's fingerprints, version and rule status), so a report can be traced back
to the ontology revision and the rule settings it describes. Suppressed
findings are listed too, with the reason they were suppressed: a report that
quietly left them out would read as if they had never been found.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from .models import QualityFinding, QualityRun, Suppression
from .registry import RULES

#: CSV columns, in order. Evidence goes in last, as JSON, because its keys
#: differ from rule to rule.
CSV_COLUMNS = (
    "severity",
    "rule_id",
    "rule",
    "resource",
    "resource_kind",
    "message",
    "suggestion",
    "source_shape",
    "origin",
    "related_resources",
    "evidence",
    "suppressed",
)


def _rule_title(rule_id: str) -> str:
    rule = RULES.get(rule_id)
    return rule.title if rule else rule_id


def finding_record(finding: QualityFinding) -> dict[str, Any]:
    """One finding as plain data, with its rule's title added."""
    record = asdict(finding)
    record["related_resources"] = list(finding.related_resources)
    record["rule"] = _rule_title(finding.rule_id)
    return record


def findings_json(
    findings: Iterable[QualityFinding],
    *,
    run: QualityRun | None = None,
    source: str = "quality",
    suppressed: Iterable[tuple[QualityFinding, Suppression]] = (),
) -> str:
    """Findings as a JSON document, with the run's metadata when there is one."""
    document: dict[str, Any] = {"source": source}
    if run is not None:
        document["run"] = {
            "started_at": run.started_at,
            "analyzer_version": run.analyzer_version,
            "graph_fingerprint": run.graph_fingerprint,
            "config_fingerprint": run.config_fingerprint,
            "rules": [asdict(status) for status in run.rules],
        }
    document["findings"] = [finding_record(f) for f in findings]
    set_aside = [{**finding_record(f), "suppression": asdict(s)} for f, s in suppressed]
    if set_aside:
        document["suppressed"] = set_aside
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False)


def findings_csv(
    findings: Iterable[QualityFinding],
    suppressed: Iterable[tuple[QualityFinding, Suppression]] = (),
) -> str:
    """Findings as CSV, one row each; suppressed ones last, with the reason
    in the ``suppressed`` column."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    rows = [(f, None) for f in findings] + [(f, s) for f, s in suppressed]
    for finding, suppression in rows:
        record = finding_record(finding)
        writer.writerow(
            {
                **{column: record.get(column) for column in CSV_COLUMNS},
                "related_resources": " ".join(finding.related_resources),
                "evidence": json.dumps(
                    finding.evidence, ensure_ascii=False, sort_keys=True
                ),
                "suppressed": suppression.justification if suppression else "",
            }
        )
    return buffer.getvalue()

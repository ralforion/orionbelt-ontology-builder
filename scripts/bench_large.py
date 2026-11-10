"""Time what decides whether a large ontology is usable in the builder.

    uv run python scripts/bench_large.py [--sizes 10000 50000] [--no-samples]
        [--quality] [--reasoning-deadline 300]

Each ontology is measured in a process of its own, so the memory figure is
that ontology's alone: the generated trees of ``--sizes`` classes (see
``bench_quality.synthetic``) and the gist core and wine samples. Times are
for loading and exporting (Turtle, N-Triples, the recovery snapshot), the
listings cold, warm and after one edit, statistics, and optionally every
quality rule and RDFS reasoning in the worker, stopped at a deadline.

Prints a Markdown table; the numbers after each work package are recorded in
section 2 of design/PLAN_large_ontologies.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rdflib import Literal, URIRef
from rdflib.namespace import RDFS

SCRIPTS = Path(__file__).resolve().parent
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS.parent)]

from bench_quality import ALL, SAMPLES, synthetic

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import analyze
from orionbelt_ontology_builder.reasoning import ReasoningTimeout

SAMPLE_CASES = {
    "gist core": ("gist/gistCore14.1.0.ttl", "turtle"),
    "wine": ("wine.owl", "xml"),
}

LISTINGS = (
    "get_classes",
    "get_object_properties",
    "get_individuals",
    "get_class_hierarchy",
)


def _rss_mb() -> float:
    """This process's resident memory now, from ``ps`` (macOS and Linux)."""
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(os.getpid())],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip()) / 1024


def _timed(fn: Callable[[], Any]) -> float:
    began = time.perf_counter()
    fn()
    return time.perf_counter() - began


def _build(case: str) -> OntologyManager:
    if case.startswith("synthetic "):
        return synthetic(int(case.split()[1]))
    path, fmt = SAMPLE_CASES[case]
    om = OntologyManager()
    om.load_from_file(str(SAMPLES / path), format=fmt)
    return om


def _edit(om: OntologyManager) -> None:
    """One ordinary edit: a comment on the first class."""
    first = URIRef(om.get_classes()[0]["uri"])
    om.graph.add((first, RDFS.comment, Literal("edited by the benchmark")))


def measure(case: str, quality: bool, reasoning_deadline: float) -> dict[str, Any]:
    row: dict[str, Any] = {}
    began = time.perf_counter()
    om = _build(case)
    row["build or load the source"] = time.perf_counter() - began
    row["triples"] = len(om.graph)
    row["RSS after build (MB)"] = round(_rss_mb())

    began = time.perf_counter()
    ttl = om.export_to_string("turtle")
    row["export Turtle"] = time.perf_counter() - began
    row["serialize N-Triples"] = _timed(lambda: om.graph.serialize(format="nt"))
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "recovery.nt"
        row["save snapshot"] = _timed(lambda: om.save_snapshot(snapshot))
        restored = OntologyManager()
        row["load snapshot"] = _timed(lambda: restored.load_snapshot(snapshot))
    loaded = OntologyManager()
    row["load Turtle"] = _timed(lambda: loaded.load_from_string(ttl, "turtle"))

    for name in LISTINGS:
        row[f"{name} cold"] = _timed(getattr(loaded, name))
    row["get_classes warm"] = _timed(loaded.get_classes)
    _edit(loaded)
    for name in LISTINGS:
        row[f"{name} after edit"] = _timed(getattr(loaded, name))
    row["get_statistics"] = _timed(loaded.get_statistics)

    if quality:
        row["quality, all rules"] = _timed(lambda: analyze(loaded, ALL))
    if reasoning_deadline:
        try:
            row["RDFS reasoning (worker)"] = _timed(
                lambda: loaded.apply_reasoning_in_worker(
                    "rdfs", deadline_s=reasoning_deadline
                )
            )
            row["triples after RDFS"] = len(loaded.graph)
        except ReasoningTimeout:
            row["RDFS reasoning (worker)"] = f"> {reasoning_deadline:g} s"
    return row


def _cell(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return f"{value:,}"
    if value >= 1:
        return f"{value:.2f} s" if value < 100 else f"{value:.0f} s"
    return f"{value * 1000:.0f} ms"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="*", default=[10000, 50000])
    parser.add_argument("--no-samples", action="store_true")
    parser.add_argument("--quality", action="store_true", help="run every rule")
    parser.add_argument(
        "--reasoning-deadline",
        type=float,
        default=0,
        help="run RDFS reasoning in the worker, stopped after this many seconds",
    )
    parser.add_argument("--case", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.case:  # one ontology, in the child process
        row = measure(args.case, args.quality, args.reasoning_deadline)
        print(json.dumps({"case": args.case, "row": row}))
        return

    cases = [f"synthetic {size}" for size in args.sizes]
    if not args.no_samples:
        cases += list(SAMPLE_CASES)
    rows: dict[str, dict[str, Any]] = {}
    for case in cases:
        child = [sys.executable, __file__, "--case", case]
        child += ["--reasoning-deadline", str(args.reasoning_deadline)]
        child += ["--quality"] if args.quality else []
        out = subprocess.run(child, capture_output=True, text=True, check=True)
        rows[case] = json.loads(out.stdout.strip().splitlines()[-1])["row"]
        print(f"measured {case}", file=sys.stderr)

    ops = list(dict.fromkeys(op for row in rows.values() for op in row))
    print("| Operation | " + " | ".join(cases) + " |")
    print("|---|" + "---:|" * len(cases))
    for op in ops:
        cells = [_cell(rows[c][op]) if op in rows[c] else "" for c in cases]
        print(f"| {op} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

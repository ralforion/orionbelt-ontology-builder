"""Time the quality rules: every rule on, on the bundled samples and on
generated ontologies of growing size.

    uv run python scripts/bench_quality.py [--sizes 1000 5000 10000]

Prints one line per ontology with the total and the three slowest rules.
Numbers from a run are recorded in design/PLAN_model_quality_checks.md.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rdflib import Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import (
    RULES,
    QualityConfig,
    RuleSettings,
    analyze,
)

ALL = QualityConfig(rules={rule_id: RuleSettings(enabled=True) for rule_id in RULES})
SAMPLES = (
    Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "samples"
)
SAMPLE_FILES = {
    "foaf.rdf": "xml",
    "pizza.owl": "xml",
    "wine.owl": "xml",
    "prov-o.ttl": "turtle",
    "gist/gistCore14.1.0.ttl": "turtle",
    "geography-thesaurus.ttl": "turtle",
}


def synthetic(size: int) -> OntologyManager:
    """``size`` classes in a tree of fan-out 5, labelled and defined, with a
    property per 10 classes and a few deliberate problems."""
    ns = Namespace("http://bench.example/o#")
    om = OntologyManager(base_uri=str(ns))
    g = om.graph
    for i in range(size):
        c = ns[f"C{i}"]
        g.add((c, RDF.type, OWL.Class))
        g.add((c, RDFS.label, Literal(f"Class {i} of the benchmark", lang="en")))
        if i % 7:
            g.add(
                (
                    c,
                    SKOS.definition,
                    Literal(
                        f"A class {i // 5} that is number {i} of the benchmark tree.",
                        lang="en",
                    ),
                )
            )
        if i:
            g.add((c, RDFS.subClassOf, ns[f"C{(i - 1) // 5}"]))
        if i % 10 == 0:
            p = ns[f"p{i}"]
            g.add((p, RDF.type, OWL.ObjectProperty))
            g.add((p, RDFS.label, Literal(f"relates {i}", lang="en")))
            g.add((p, RDFS.domain, c))
            g.add((p, RDFS.range, ns[f"C{i // 2}"]))
    return om


def bench(name: str, om: OntologyManager) -> None:
    began = time.perf_counter()
    run = analyze(om, ALL)
    total = (time.perf_counter() - began) * 1000
    slowest = sorted(run.rules, key=lambda s: -s.duration_ms)[:3]
    print(
        f"{name:28} {len(om.graph):>8} triples {total:>8.0f} ms "
        f"{len(run.findings):>6} findings  slowest: "
        + ", ".join(f"{s.rule_id} {s.duration_ms:.0f}" for s in slowest)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="*", default=[1000, 5000, 10000])
    args = parser.parse_args()
    for path, fmt in SAMPLE_FILES.items():
        om = OntologyManager()
        om.load_from_file(str(SAMPLES / path), format=fmt)
        bench(path, om)
    for size in args.sizes:
        bench(f"synthetic {size} classes", synthetic(size))


if __name__ == "__main__":
    main()

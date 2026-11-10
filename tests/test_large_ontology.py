"""Loose time budgets on a 50k-class ontology (213k triples).

Marked ``slow`` and deselected by default: building the ontology alone takes
seconds. Run with ``pytest -m slow``. The budgets sit at three to four times
what ``scripts/bench_large.py`` measures, so they catch a regression of the
order that matters (the recovery file written as Turtle again, a listing
several times slower), not noise.
"""

import time

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDFS

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from scripts.bench_quality import synthetic

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def large() -> OntologyManager:
    return synthetic(50_000)


def _seconds(fn) -> float:
    began = time.perf_counter()
    fn()
    return time.perf_counter() - began


def test_the_recovery_snapshot_round_trips_within_budget(large, tmp_path):
    snapshot = tmp_path / "recovery.nt"
    assert _seconds(lambda: large.save_snapshot(snapshot)) < 1.5  # Turtle: 2.5
    restored = OntologyManager()
    assert _seconds(lambda: restored.load_snapshot(snapshot)) < 15
    assert len(restored.graph) == len(large.graph)


def test_listings_after_one_edit_stay_within_budget(large):
    large.get_classes()
    large.graph.add(
        (URIRef(large.get_classes()[0]["uri"]), RDFS.comment, Literal("edited"))
    )
    assert _seconds(large.get_classes) < 2
    assert _seconds(large.get_class_hierarchy) < 0.6
    assert _seconds(large.get_statistics) < 0.2

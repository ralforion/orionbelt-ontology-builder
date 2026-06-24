"""Tests for browser-localStorage autosave helpers.

The localStorage I/O itself is a frontend component and can't run headless, but
the pure logic around it (emptiness check, change detection, serialize/restore
round-trip) is testable directly.
"""

from ontology_manager import OntologyManager
from orionbelt_ontology_builder.app import (
    AUTOSAVE_MAX_BYTES,
    _content_hash,
    _ontology_is_empty,
)


def test_content_hash_is_stable_and_sensitive():
    assert _content_hash("abc") == _content_hash("abc")
    assert _content_hash("abc") != _content_hash("abd")


def test_empty_ontology_detected(om):
    assert _ontology_is_empty(om) is True


def test_populated_ontology_not_empty(populated_om):
    assert _ontology_is_empty(populated_om) is False


def test_skos_only_ontology_not_empty(skos_om):
    """A vocabulary with only SKOS concepts still counts as having content."""
    assert _ontology_is_empty(skos_om) is False


def test_autosave_round_trip_restores_content(populated_om):
    """export_to_string -> load_from_string reproduces the full graph, which is
    exactly what persist/restore rely on."""
    payload = populated_om.export_to_string(format="turtle")

    restored = OntologyManager()
    assert _ontology_is_empty(restored)
    restored.load_from_string(payload, format="turtle")

    assert not _ontology_is_empty(restored)
    before = {c["name"] for c in populated_om.get_classes()}
    after = {c["name"] for c in restored.get_classes()}
    assert before == after
    assert restored.export_to_string(format="turtle")


def test_autosave_payload_within_size_budget(populated_om):
    payload = populated_om.export_to_string(format="turtle")
    assert len(payload.encode("utf-8")) < AUTOSAVE_MAX_BYTES

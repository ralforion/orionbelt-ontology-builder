"""Tests for merge strategies and conflict detection."""

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS
from ontology_manager import (
    OntologyManager,
    IMPORT_REPLACE,
    IMPORT_MERGE,
    IMPORT_MERGE_OVERWRITE,
)


SECOND_ONT_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://test.org/ont#> .

<http://test.org/ont> a owl:Ontology .

:Vehicle a owl:Class ; rdfs:label "Vehicle" .
:Car a owl:Class ; rdfs:subClassOf :Vehicle ; rdfs:label "Car" .
"""

CONFLICTING_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://test.org/ont#> .

<http://test.org/ont> a owl:Ontology .

:Person a owl:Class ; rdfs:label "Human Being" .
:Employee a owl:Class ; rdfs:subClassOf :Person ; rdfs:label "Worker" .
"""


@pytest.fixture
def base_om():
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_class("Person", label="Person")
    m.add_class("Employee", parent="Person", label="Employee")
    return m


class TestReplaceStrategy:
    def test_replace_replaces_entire_graph(self, base_om):
        result = base_om.merge_from_string(
            SECOND_ONT_TTL, format="turtle", strategy=IMPORT_REPLACE
        )
        classes = base_om.get_classes()
        class_names = [c["name"] for c in classes]
        assert "Vehicle" in class_names
        assert "Car" in class_names
        # Original classes should be gone
        assert "Person" not in class_names
        assert result["triples_added"] >= 0


class TestMergeStrategy:
    def test_merge_adds_without_losing_existing(self, base_om):
        result = base_om.merge_from_string(
            SECOND_ONT_TTL, format="turtle", strategy=IMPORT_MERGE
        )
        classes = base_om.get_classes()
        class_names = [c["name"] for c in classes]
        # Both original and new classes present
        assert "Person" in class_names
        assert "Employee" in class_names
        assert "Vehicle" in class_names
        assert "Car" in class_names
        assert result["triples_added"] > 0

    def test_merge_deduplicates_identical_triples(self, base_om):
        # Merge the same ontology content that already exists
        existing_ttl = base_om.export_to_string(format="turtle")
        before = len(base_om.graph)
        base_om.merge_from_string(existing_ttl, format="turtle", strategy=IMPORT_MERGE)
        after = len(base_om.graph)
        assert after == before  # no duplicates added

    def test_merge_empty_graph_is_noop(self, base_om):
        before = len(base_om.graph)
        # An empty string may cause parse errors; use minimal valid TTL
        base_om.merge_from_string(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n",
            format="turtle",
            strategy=IMPORT_MERGE,
        )
        # Should not lose any triples
        after = len(base_om.graph)
        assert after >= before


class TestMergeOverwriteStrategy:
    def test_merge_overwrite_resolves_label_conflicts(self, base_om):
        result = base_om.merge_from_string(
            CONFLICTING_TTL, format="turtle", strategy=IMPORT_MERGE_OVERWRITE
        )
        # The label should be overwritten to the incoming value
        person_uri = URIRef("http://test.org/ont#Person")
        labels = list(base_om.graph.objects(person_uri, RDFS.label))
        label_strs = [str(label) for label in labels]
        assert "Human Being" in label_strs
        assert result["conflicts_resolved"] > 0

    def test_merge_overwrite_keeps_non_conflicting(self, base_om):
        base_om.merge_from_string(
            CONFLICTING_TTL, format="turtle", strategy=IMPORT_MERGE_OVERWRITE
        )
        # Employee should still exist
        classes = base_om.get_classes()
        class_names = [c["name"] for c in classes]
        assert "Employee" in class_names


class TestConflictDetection:
    def test_detects_label_conflict(self, base_om):
        temp = Graph()
        temp.parse(data=CONFLICTING_TTL, format="turtle")
        conflicts = base_om.detect_conflicts(temp)
        assert len(conflicts) > 0
        person_conflicts = [c for c in conflicts if c["subject"] == "Person"]
        assert len(person_conflicts) > 0
        assert person_conflicts[0]["predicate"] == "label"

    def test_no_conflicts_with_disjoint_content(self, base_om):
        temp = Graph()
        temp.parse(data=SECOND_ONT_TTL, format="turtle")
        conflicts = base_om.detect_conflicts(temp)
        assert len(conflicts) == 0


class TestPreviewImport:
    def test_preview_does_not_modify_graph(self, base_om):
        before = len(base_om.graph)
        preview = base_om.preview_import(SECOND_ONT_TTL, format="turtle")
        after = len(base_om.graph)
        assert after == before
        assert "diff" in preview
        assert "incoming_stats" in preview
        assert "conflicts" in preview
        assert "prefix_conflicts" in preview

    def test_preview_shows_incoming_stats(self, base_om):
        preview = base_om.preview_import(SECOND_ONT_TTL, format="turtle")
        stats = preview["incoming_stats"]
        assert stats["classes"] >= 2  # Vehicle, Car


class TestPrefixConflicts:
    def test_detects_prefix_namespace_mismatch(self):
        om1 = OntologyManager(base_uri="http://a.org/ont#")
        om2_graph = Graph()
        om2_graph.bind("ex", "http://other.org/ex#")
        om1.graph.bind("ex", "http://original.org/ex#")
        conflicts = om1._detect_prefix_conflicts(om2_graph)
        assert len(conflicts) > 0
        assert conflicts[0]["prefix"] == "ex"


class TestUndoAfterMerge:
    def test_undo_restores_pre_merge_state(self, base_om):
        snapshot = base_om.take_snapshot()
        base_om.merge_from_string(
            SECOND_ONT_TTL, format="turtle", strategy=IMPORT_MERGE
        )
        # Verify merge happened
        classes = base_om.get_classes()
        assert any(c["name"] == "Vehicle" for c in classes)
        # Restore
        base_om.restore_snapshot(snapshot)
        classes = base_om.get_classes()
        assert not any(c["name"] == "Vehicle" for c in classes)
        assert any(c["name"] == "Person" for c in classes)

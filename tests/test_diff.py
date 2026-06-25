"""Tests for the diff engine (compare_graphs, summaries, reports)."""

import pytest
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL
from ontology_manager import OntologyManager


@pytest.fixture
def base_om():
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_class("Animal", label="Animal")
    m.add_class("Dog", parent="Animal", label="Dog")
    return m


class TestCompareGraphs:
    def test_identical_graphs_produce_empty_diff(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        diff = base_om.compare_graphs(other)
        assert diff["stats"]["added"] == 0
        assert diff["stats"]["removed"] == 0
        assert diff["stats"]["resources_modified"] == 0

    def test_added_triples_detected(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        # Add a new class to the "other" graph
        cat_uri = URIRef("http://test.org/ont#Cat")
        other.add((cat_uri, RDF.type, OWL.Class))
        other.add((cat_uri, RDFS.label, Literal("Cat")))

        diff = base_om.compare_graphs(other)
        assert diff["stats"]["added"] >= 2
        assert diff["stats"]["resources_added"] >= 1
        # Cat should appear in added resources
        added_names = [
            r["name"] for r in diff["modified_resources"] if r["change_type"] == "added"
        ]
        assert "Cat" in added_names

    def test_removed_triples_detected(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        # Remove Dog from other
        dog_uri = URIRef("http://test.org/ont#Dog")
        for p, o in list(other.predicate_objects(dog_uri)):
            other.remove((dog_uri, p, o))
        for s, p in list(other.subject_predicates(dog_uri)):
            other.remove((s, p, dog_uri))

        diff = base_om.compare_graphs(other)
        assert diff["stats"]["removed"] > 0
        removed_names = [
            r["name"]
            for r in diff["modified_resources"]
            if r["change_type"] == "removed"
        ]
        assert "Dog" in removed_names

    def test_modified_resource_detected(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        # Change Dog's label in other
        dog_uri = URIRef("http://test.org/ont#Dog")
        other.remove((dog_uri, RDFS.label, Literal("Dog")))
        other.add((dog_uri, RDFS.label, Literal("Puppy")))

        diff = base_om.compare_graphs(other)
        modified = [
            r for r in diff["modified_resources"] if r["change_type"] == "modified"
        ]
        assert any(r["name"] == "Dog" for r in modified)

    def test_bnode_triples_counted_but_not_surfaced(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Person")

        other = Graph()
        for t in om.graph:
            other.add(t)

        # Add a restriction (BNode) to other
        bn = BNode()
        other.add((bn, RDF.type, OWL.Restriction))
        other.add((bn, OWL.onProperty, URIRef("http://test.org/ont#hasFriend")))

        diff = om.compare_graphs(other)
        assert diff["stats"]["bnode_added"] >= 2
        # BNode subjects should not appear in modified_resources
        for r in diff["modified_resources"]:
            assert not r["name"].startswith("N")  # BNodes start with N or are UUIDs


class TestCompareToString:
    def test_compare_to_turtle_string(self, base_om):
        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix : <http://test.org/ont#> .

        :Animal a owl:Class ; rdfs:label "Animal" .
        :Cat a owl:Class ; rdfs:label "Cat" .
        """
        diff = base_om.compare_to_string(ttl, format="turtle")
        assert diff["stats"]["added"] > 0


class TestSummarizeChanges:
    def test_summary_contains_added_class(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        cat_uri = URIRef("http://test.org/ont#Cat")
        other.add((cat_uri, RDF.type, OWL.Class))
        other.add((cat_uri, RDFS.label, Literal("Cat")))

        diff = base_om.compare_graphs(other)
        assert any("Added" in s and "Cat" in s for s in diff["summary"])

    def test_summary_contains_removed_class(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        dog_uri = URIRef("http://test.org/ont#Dog")
        for p, o in list(other.predicate_objects(dog_uri)):
            other.remove((dog_uri, p, o))
        for s, p in list(other.subject_predicates(dog_uri)):
            other.remove((s, p, dog_uri))

        diff = base_om.compare_graphs(other)
        assert any("Removed" in s and "Dog" in s for s in diff["summary"])


class TestFormatDiffReport:
    def test_markdown_report_has_headings(self, base_om):
        other = Graph()
        for t in base_om.graph:
            other.add(t)
        cat_uri = URIRef("http://test.org/ont#Cat")
        other.add((cat_uri, RDF.type, OWL.Class))

        diff = base_om.compare_graphs(other)
        report = base_om.format_diff_report(diff, report_format="markdown")
        assert "# Ontology Change Report" in report
        assert "## Summary" in report

    def test_text_report_format(self, base_om):
        diff = base_om.compare_graphs(base_om.graph)
        report = base_om.format_diff_report(diff, report_format="text")
        assert "Ontology Change Report" in report

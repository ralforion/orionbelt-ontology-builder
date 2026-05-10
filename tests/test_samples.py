"""Integration tests against real-world sample ontologies.

Tests import, parsing, validation, search, diff, and export round-trip
using ontologies from samples/ directory.
"""

import os
import subprocess
import pytest
from ontology_manager import OntologyManager

SAMPLES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "orionbelt_ontology_builder", "samples"
)

SAMPLE_FILES = {
    "pizza": ("pizza.owl", "xml", "https://protege.stanford.edu/ontologies/pizza/pizza.owl"),
    "foaf": ("foaf.rdf", "xml", "http://xmlns.com/foaf/spec/index.rdf"),
    "wine": ("wine.owl", "xml", "https://www.w3.org/TR/owl-guide/wine.rdf"),
    "prov-o": ("prov-o.ttl", "turtle", "https://www.w3.org/ns/prov-o"),
    "goodrelations": ("goodrelations.owl", "xml", "http://purl.org/goodrelations/v1.owl"),
    "geography": ("geography-thesaurus.ttl", "turtle", None),
}


def _download(filename, url):
    """Download a sample file if not present."""
    path = os.path.join(SAMPLES_DIR, filename)
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    try:
        subprocess.run(
            ["curl", "-sL", "-o", path, url],
            timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip(f"Could not download {filename}")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        pytest.skip(f"Download produced empty file for {filename}")


def _load(name):
    filename, fmt, url = SAMPLE_FILES[name]
    path = os.path.join(SAMPLES_DIR, filename)
    if not os.path.exists(path):
        if url is None:
            pytest.skip(f"Local sample {filename} not found")
        _download(filename, url)
    om = OntologyManager()
    om.load_from_file(path, fmt)
    return om


# ---------- Import & basic stats ----------

class TestSampleImport:
    """Verify all samples load without errors and contain expected content."""

    @pytest.mark.parametrize("name", list(SAMPLE_FILES.keys()))
    def test_loads_without_error(self, name):
        om = _load(name)
        assert len(om.graph) > 0

    def test_pizza_has_classes(self):
        om = _load("pizza")
        classes = om.get_classes()
        names = [c["name"] for c in classes]
        assert len(classes) >= 50
        # Pizza ontology should have these
        assert "Pizza" in names or "pizza" in [n.lower() for n in names]

    def test_pizza_has_properties(self):
        om = _load("pizza")
        obj_props = om.get_object_properties()
        data_props = om.get_data_properties()
        assert len(obj_props) + len(data_props) >= 5

    def test_wine_has_classes_and_properties(self):
        om = _load("wine")
        classes = om.get_classes()
        obj_props = om.get_object_properties()
        assert len(classes) >= 10
        assert len(obj_props) >= 5

    def test_foaf_has_properties(self):
        om = _load("foaf")
        obj_props = om.get_object_properties()
        data_props = om.get_data_properties()
        assert len(obj_props) + len(data_props) >= 10

    def test_geography_has_skos_concepts(self):
        om = _load("geography")
        concepts = om.get_concepts()
        assert len(concepts) > 50


# ---------- Validation ----------

class TestSampleValidation:
    """Run validation on real ontologies and check it doesn't crash."""

    @pytest.mark.parametrize("name", ["pizza", "wine", "foaf", "prov-o", "goodrelations"])
    def test_validation_runs(self, name):
        om = _load(name)
        issues = om.validate()
        assert isinstance(issues, list)
        # Every issue should have required keys
        for issue in issues:
            assert "severity" in issue
            assert "type" in issue
            assert "message" in issue

    def test_geography_skos_validation(self):
        om = _load("geography")
        issues = om.validate_skos()
        assert isinstance(issues, list)


# ---------- Search ----------

class TestSampleSearch:
    """Test search on real ontologies."""

    def test_pizza_search(self):
        om = _load("pizza")
        results = om.search("pizza")
        assert len(results) > 0

    def test_wine_search(self):
        om = _load("wine")
        results = om.search("wine")
        assert len(results) > 0

    def test_foaf_search(self):
        om = _load("foaf")
        results = om.search("person")
        assert len(results) > 0


# ---------- Export round-trip ----------

class TestSampleRoundTrip:
    """Export and re-import to check round-trip stability."""

    @pytest.mark.parametrize("name", ["pizza", "wine", "prov-o"])
    def test_turtle_roundtrip(self, name):
        om = _load(name)
        original_count = len(om.graph)
        exported = om.export_to_string("turtle")
        assert len(exported) > 0

        om2 = OntologyManager()
        om2.load_from_string(exported, "turtle")
        # Allow small variance from BNode handling
        assert abs(len(om2.graph) - original_count) < original_count * 0.1

    @pytest.mark.parametrize("name", ["pizza", "foaf", "goodrelations"])
    def test_xml_roundtrip(self, name):
        om = _load(name)
        original_count = len(om.graph)
        exported = om.export_to_string("xml")
        assert len(exported) > 0

        om2 = OntologyManager()
        om2.load_from_string(exported, "xml")
        assert abs(len(om2.graph) - original_count) < original_count * 0.1


# ---------- Diff ----------

class TestSampleDiff:
    """Test diff engine against real ontologies."""

    def test_diff_identical(self):
        om = _load("pizza")
        diff = om.compare_graphs(om.graph)
        assert diff["stats"]["added"] == 0
        assert diff["stats"]["removed"] == 0

    def test_diff_after_adding_class(self):
        om = _load("foaf")
        from rdflib import Graph
        original = Graph()
        for t in om.graph:
            original.add(t)

        om.add_class("TestNewClass", label="Test")
        # compare_graphs: added = in other but not self
        # Here self has MORE triples, so the new triples show as "removed" (in self but not other)
        diff = om.compare_graphs(original)
        assert diff["stats"]["removed"] > 0


# ---------- Hierarchy ----------

class TestSampleHierarchy:
    """Test hierarchy extraction on real ontologies."""

    def test_pizza_hierarchy(self):
        om = _load("pizza")
        hierarchy = om.get_class_hierarchy()
        assert len(hierarchy) > 10

    def test_geography_concept_hierarchy(self):
        om = _load("geography")
        hierarchy = om.get_concept_hierarchy()
        assert len(hierarchy) > 20


# ---------- Statistics ----------

class TestSampleStatistics:
    """Test statistics on real ontologies."""

    @pytest.mark.parametrize("name", ["pizza", "wine", "goodrelations"])
    def test_get_statistics(self, name):
        om = _load(name)
        stats = om.get_statistics()
        assert stats["total_triples"] > 0
        assert stats["classes"] >= 0
        assert stats["object_properties"] >= 0

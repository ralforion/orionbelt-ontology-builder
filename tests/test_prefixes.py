"""Tests for prefix management."""

import pytest
from ontology_manager import OntologyManager


@pytest.fixture
def om():
    return OntologyManager(base_uri="http://test.org/ont#")


class TestAddPrefix:
    def test_add_custom_prefix(self, om):
        om.add_prefix("foaf", "http://xmlns.com/foaf/0.1/")
        prefixes = om.get_all_prefixes()
        foaf = [p for p in prefixes if p["prefix"] == "foaf"]
        assert len(foaf) == 1
        assert foaf[0]["namespace"] == "http://xmlns.com/foaf/0.1/"
        assert foaf[0]["source"] == "custom"

    def test_added_prefix_appears_in_get_prefixes(self, om):
        om.add_prefix("schema", "http://schema.org/")
        prefixes = om.get_prefixes()
        assert any(p["prefix"] == "schema" for p in prefixes)


class TestRemovePrefix:
    def test_remove_custom_prefix(self, om):
        # Use a prefix that is NOT in rdflib's built-in defaults
        om.add_prefix("myapp", "http://myapp.example.org/")
        om.remove_prefix("myapp")
        prefixes = om.get_all_prefixes()
        assert not any(p["prefix"] == "myapp" for p in prefixes)

    def test_cannot_remove_standard_prefix(self, om):
        with pytest.raises(ValueError, match="Cannot remove standard prefix"):
            om.remove_prefix("owl")

    def test_cannot_remove_rdf_prefix(self, om):
        with pytest.raises(ValueError, match="Cannot remove standard prefix"):
            om.remove_prefix("rdf")


class TestGetAllPrefixes:
    def test_includes_standard_prefixes(self, om):
        prefixes = om.get_all_prefixes()
        prefix_names = [p["prefix"] for p in prefixes]
        assert "owl" in prefix_names
        assert "rdf" in prefix_names
        assert "rdfs" in prefix_names

    def test_source_classification(self, om):
        om.add_prefix("ex", "http://example.org/")
        prefixes = om.get_all_prefixes()
        for p in prefixes:
            if p["prefix"] in ("owl", "rdf", "rdfs", "xsd", "skos", "dc", "dcterms"):
                assert p["source"] == "standard"
            elif p["prefix"] == "ex":
                assert p["source"] == "custom"

    def test_prefixes_sorted(self, om):
        om.add_prefix("zzz", "http://zzz.org/")
        om.add_prefix("aaa", "http://aaa.org/")
        prefixes = om.get_all_prefixes()
        names = [p["prefix"] for p in prefixes]
        # (default) should come first, then alphabetical
        default_idx = names.index("(default)") if "(default)" in names else -1
        if default_idx >= 0:
            assert default_idx == 0


class TestPrefixNamespaceNormalization:
    """A custom prefix namespace is normalized to end with '#' or '/', so
    entities created in it get a separator (issue #115)."""

    def test_namespace_without_separator_gets_hash(self, om):
        bound = om.add_prefix("boat", "http://example.org/ontology")
        assert bound == "http://example.org/ontology#"
        ns = {p["prefix"]: p["namespace"] for p in om.get_all_prefixes()}
        assert ns["boat"] == "http://example.org/ontology#"

    def test_namespace_with_hash_is_unchanged(self, om):
        assert om.add_prefix("ex", "http://example.org/ns#") == "http://example.org/ns#"

    def test_namespace_with_slash_is_unchanged(self, om):
        assert om.add_prefix("s", "http://schema.org/") == "http://schema.org/"

    def test_class_in_normalized_namespace_is_not_mangled(self, om):
        # The issue #115 repro: without normalization the class URI would be
        # http://example.org/ontologyDog and its name "ontologyDog".
        bound = om.add_prefix("boat", "http://example.org/ontology")
        uri = om.add_class("Dog", namespace=bound)
        assert str(uri) == "http://example.org/ontology#Dog"
        cls = {c["uri"]: c for c in om.get_classes()}
        assert cls["http://example.org/ontology#Dog"]["name"] == "Dog"
        assert "http://example.org/ontologyDog" not in cls

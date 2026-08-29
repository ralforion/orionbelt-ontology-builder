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

    def test_urn_namespace_is_not_normalized(self, om):
        # A URN already ends in its own separator (':'); appending '#' would
        # mangle it into urn:example:#Dog (review on #117).
        assert om.add_prefix("ex", "urn:example:") == "urn:example:"
        uri = om.add_class("Dog", namespace="urn:example:")
        assert str(uri) == "urn:example:Dog"

    def test_non_http_scheme_left_as_is(self, om):
        # Only http(s) namespaces are normalized; other schemes are untouched.
        assert om.add_prefix("ex", "urn:example") == "urn:example"

    def test_http_query_namespace_not_normalized(self, om):
        # A trailing '=', '?' or '&' is an intentional separator.
        assert (
            om.add_prefix("q", "http://example.org/ns?term=")
            == "http://example.org/ns?term="
        )


class TestDefaultPrefix:
    """``:`` must name this ontology's namespace, never a foreign one.

    ``Graph.bind`` defaults to ``replace=False``, so re-binding ``:`` over an
    existing binding silently parks the new namespace under ``default1:`` and
    leaves ``:`` where it was. Nothing raises; the damage only shows up when
    something reads ``:`` back, which is why each case below reads it back.
    """

    def _empty_prefix(self, om):
        return str(om.graph.store.namespace(""))

    def test_loaded_file_does_not_keep_the_empty_prefix(self):
        om = OntologyManager()
        om.load_from_string(
            """
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix : <http://other.example/vocab#> .
            <http://example.org/ontology> a owl:Ontology .
            <http://example.org/ontology#Event> a owl:Class .
            """,
            "turtle",
        )
        assert self._empty_prefix(om) == om.base_uri

    def test_displaced_namespace_stays_bound(self):
        om = OntologyManager()
        om.load_from_string(
            """
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix : <http://other.example/vocab#> .
            <http://example.org/ontology> a owl:Ontology .
            <http://example.org/ontology#Event> a owl:Class .
            """,
            "turtle",
        )
        bound = {str(ns) for _, ns in om.graph.namespaces()}
        assert "http://other.example/vocab#" in bound

    def test_set_base_uri_moves_the_empty_prefix(self, om):
        om.add_class("Event")
        om.set_base_uri("http://acme.example/onto#")
        assert self._empty_prefix(om) == "http://acme.example/onto#"

    def test_renamed_namespace_serializes_under_the_empty_prefix(self, om):
        om.add_class("Event")
        om.set_base_uri("http://acme.example/onto#")
        turtle = om.graph.serialize(format="turtle")
        assert "@prefix : <http://acme.example/onto#>" in turtle
        assert ":Event" in turtle

    def test_old_base_uri_is_not_kept_as_a_prefix(self, om):
        # set_base_uri rewrites every resource into the new namespace, so the
        # old one is abandoned, not displaced: keeping a prefix for it would
        # offer the old base URI as a place to create entities.
        om.add_class("Event")
        om.set_base_uri("http://acme.example/onto#")
        bound = {str(ns) for _, ns in om.graph.namespaces()}
        assert "http://test.org/ont#" not in bound
        assert "http://test.org/ont#" not in om.get_creatable_namespaces()

    def test_sparql_resolves_the_empty_prefix_to_this_ontology(self, om):
        # The user-visible symptom: `:Event` matched nothing because `:` named
        # a namespace the ontology no longer used.
        from orionbelt_ontology_builder import sparql

        om.add_class("Event")
        om.set_base_uri("http://acme.example/onto#")
        result = sparql.run_query(om.graph, "SELECT ?p WHERE { :Event ?p ?o }")
        assert result.rows

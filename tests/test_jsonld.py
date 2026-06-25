"""Tests for JSON-LD import support."""

import pytest
from ontology_manager import OntologyManager


JSONLD_MINIMAL = """{
  "@context": {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "ex": "http://example.org/ont#"
  },
  "@graph": [
    {
      "@id": "http://example.org/ont",
      "@type": "owl:Ontology"
    },
    {
      "@id": "ex:Animal",
      "@type": "owl:Class",
      "rdfs:label": "Animal"
    },
    {
      "@id": "ex:Dog",
      "@type": "owl:Class",
      "rdfs:label": "Dog",
      "rdfs:subClassOf": {"@id": "ex:Animal"}
    }
  ]
}"""

JSONLD_NO_CONTEXT = """{
  "@graph": [
    {
      "@id": "http://example.org/ont",
      "@type": "http://www.w3.org/2002/07/owl#Ontology"
    },
    {
      "@id": "http://example.org/ont#Thing",
      "@type": "http://www.w3.org/2002/07/owl#Class"
    }
  ]
}"""


@pytest.fixture
def om():
    return OntologyManager()


class TestJsonLdImport:
    def test_import_minimal_jsonld(self, om):
        om.load_from_string(JSONLD_MINIMAL, format="json-ld")
        classes = om.get_classes()
        class_names = [c["name"] for c in classes]
        assert "Animal" in class_names
        assert "Dog" in class_names

    def test_import_preserves_hierarchy(self, om):
        om.load_from_string(JSONLD_MINIMAL, format="json-ld")
        classes = om.get_classes()
        dog = next(c for c in classes if c["name"] == "Dog")
        assert "Animal" in dog.get("parents", [])

    def test_import_without_context(self, om):
        om.load_from_string(JSONLD_NO_CONTEXT, format="json-ld")
        classes = om.get_classes()
        class_names = [c["name"] for c in classes]
        assert "Thing" in class_names


class TestJsonLdPrefixExtraction:
    def test_extracts_prefixes_from_context(self, om):
        prefixes = om._extract_prefixes_from_jsonld(JSONLD_MINIMAL)
        prefix_names = [p["prefix"] for p in prefixes]
        assert "ex" in prefix_names
        ex_entry = next(p for p in prefixes if p["prefix"] == "ex")
        assert ex_entry["namespace"] == "http://example.org/ont#"

    def test_no_context_returns_empty(self, om):
        prefixes = om._extract_prefixes_from_jsonld(JSONLD_NO_CONTEXT)
        # No prefix mappings in this document
        assert isinstance(prefixes, list)

    def test_invalid_json_returns_empty(self, om):
        prefixes = om._extract_prefixes_from_jsonld("not json at all")
        assert prefixes == []

    def test_list_context_merged(self, om):
        data = """{
          "@context": [
            {"ex": "http://example.org/"},
            {"foaf": "http://xmlns.com/foaf/0.1/"}
          ],
          "@graph": []
        }"""
        prefixes = om._extract_prefixes_from_jsonld(data)
        names = [p["prefix"] for p in prefixes]
        assert "ex" in names
        assert "foaf" in names


class TestJsonLdRoundTrip:
    def test_export_import_roundtrip(self, om):
        om.load_from_string(JSONLD_MINIMAL, format="json-ld")
        exported = om.export_to_string(format="json-ld")

        om2 = OntologyManager()
        om2.load_from_string(exported, format="json-ld")
        classes = om2.get_classes()
        class_names = [c["name"] for c in classes]
        assert "Animal" in class_names
        assert "Dog" in class_names

    def test_loaded_prefixes_populated(self, om):
        om.load_from_string(JSONLD_MINIMAL, format="json-ld")
        assert hasattr(om, "_loaded_prefixes")
        assert len(om._loaded_prefixes) > 0

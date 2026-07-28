"""Tests for import namespace detection."""

from ontology_manager import OntologyManager

TURTLE_WITH_ONTOLOGY = """\
@prefix : <http://imported.org/ont#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://imported.org/ont> a owl:Ontology .
:Dog a owl:Class ;
     rdfs:label "Dog" .
"""

TURTLE_WITHOUT_ONTOLOGY = """\
@prefix : <http://noont.org/schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Cat a owl:Class ;
     rdfs:label "Cat" .
:hasColor a owl:DatatypeProperty .
"""

TURTLE_SLASH_NAMESPACE = """\
@prefix : <http://example.com/vocab/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<http://example.com/vocab> a owl:Ontology .
:Fruit a owl:Class .
"""


def test_import_with_ontology_updates_namespace():
    m = OntologyManager(base_uri="http://old.org/ns#")
    m.load_from_string(TURTLE_WITH_ONTOLOGY)
    assert m.base_uri == "http://imported.org/ont#"
    assert "imported.org" in str(m.ontology_uri)


def test_import_without_ontology_infers_namespace():
    """Regression: imports without owl:Ontology must not keep the old namespace."""
    m = OntologyManager(base_uri="http://old.org/ns#")
    m.load_from_string(TURTLE_WITHOUT_ONTOLOGY)
    assert "noont.org" in m.base_uri
    # New resources should use the imported namespace
    uri = m._uri("Dog")
    assert "noont.org" in str(uri)


def test_import_slash_namespace():
    m = OntologyManager()
    m.load_from_string(TURTLE_SLASH_NAMESPACE)
    assert m.base_uri == "http://example.com/vocab/"


def test_import_preserves_classes():
    m = OntologyManager()
    m.load_from_string(TURTLE_WITH_ONTOLOGY)
    names = [c["name"] for c in m.get_classes()]
    assert "Dog" in names

import pytest

from ontology_manager import OntologyManager


@pytest.fixture
def om():
    """Fresh OntologyManager with default namespace."""
    return OntologyManager()


@pytest.fixture
def populated_om():
    """OntologyManager with a small class/property/individual graph."""
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_class("Person", label="Person")
    m.add_class("Organization", label="Organization")
    m.add_class("Employee", parent="Person", label="Employee")
    m.add_object_property("worksFor", domain="Person", range_="Organization")
    m.add_data_property("hasName", domain="Person", range_="string")
    m.add_individual("alice", "Employee", label="Alice")
    m.add_individual("acme", "Organization", label="ACME Corp")
    return m


@pytest.fixture
def skos_om():
    """OntologyManager with a SKOS ConceptScheme and sample concepts."""
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_concept_scheme("MyScheme", label="My Scheme")
    m.add_concept("Animal", scheme="MyScheme", pref_label="Animal")
    m.add_concept("Dog", scheme="MyScheme", pref_label="Dog", broader="Animal")
    m.add_concept("Cat", scheme="MyScheme", pref_label="Cat", broader="Animal")
    return m

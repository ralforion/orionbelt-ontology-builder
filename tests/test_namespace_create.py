"""Tests for creating entities in a chosen namespace (issue #87, part A)."""

from ontology_manager import OntologyManager

OTHER = "http://other.example/ns#"


def test_add_class_default_namespace():
    om = OntologyManager(base_uri="http://test.org/ont#")
    uri = om.add_class("Dog")
    assert str(uri) == "http://test.org/ont#Dog"


def test_add_class_custom_namespace():
    om = OntologyManager(base_uri="http://test.org/ont#")
    uri = om.add_class("Dog", namespace=OTHER)
    assert str(uri) == OTHER + "Dog"
    cls = {c["uri"]: c for c in om.get_classes()}
    assert OTHER + "Dog" in cls
    assert cls[OTHER + "Dog"]["name"] == "Dog"


def test_same_local_name_two_namespaces_coexist():
    # The core of issue #87: reuse a name across namespaces without prefixing.
    om = OntologyManager(base_uri="http://test.org/ont#")
    om.add_class("Order", label="Sales order")
    om.add_class("Order", namespace=OTHER, label="Military order")
    uris = {c["uri"] for c in om.get_classes()}
    assert "http://test.org/ont#Order" in uris
    assert OTHER + "Order" in uris
    assert len([c for c in om.get_classes() if c["name"] == "Order"]) == 2


def test_add_object_property_custom_namespace():
    om = OntologyManager(base_uri="http://test.org/ont#")
    uri = om.add_object_property("knows", namespace=OTHER)
    assert str(uri) == OTHER + "knows"
    assert OTHER + "knows" in {p["uri"] for p in om.get_object_properties()}


def test_add_data_property_custom_namespace():
    om = OntologyManager(base_uri="http://test.org/ont#")
    uri = om.add_data_property("age", range_="integer", namespace=OTHER)
    assert str(uri) == OTHER + "age"
    assert OTHER + "age" in {p["uri"] for p in om.get_data_properties()}


def test_add_individual_custom_namespace_keeps_base_class():
    # The individual lands in OTHER, but its class reference resolves in base.
    om = OntologyManager(base_uri="http://test.org/ont#")
    om.add_class("Person")
    uri = om.add_individual("alice", "Person", namespace=OTHER)
    assert str(uri) == OTHER + "alice"
    alice = next(i for i in om.get_individuals() if i["uri"] == OTHER + "alice")
    assert "Person" in alice.get("classes", [])
    assert "http://test.org/ont#Person" in alice.get("class_uris", [])


def test_full_uri_overrides_namespace_argument():
    # A full URI passed as the name is used verbatim, ignoring the namespace.
    om = OntologyManager(base_uri="http://test.org/ont#")
    uri = om.add_class("http://verbatim.example/Thing", namespace=OTHER)
    assert str(uri) == "http://verbatim.example/Thing"


class TestCreatableNamespaces:
    def test_base_namespace_is_first(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        nss = om.get_creatable_namespaces()
        assert nss[0] == "http://test.org/ont#"

    def test_excludes_rdflib_default_bindings(self):
        # rdflib auto-binds ~30 prefixes (foaf, schema, brick, ...); none of
        # them should appear as creation targets.
        om = OntologyManager(base_uri="http://test.org/ont#")
        nss = om.get_creatable_namespaces()
        assert nss == ["http://test.org/ont#"]

    def test_user_added_prefix_is_offered(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_prefix("ex", OTHER)
        assert OTHER in om.get_creatable_namespaces()

    def test_removed_prefix_no_longer_offered(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_prefix("ex", OTHER)
        om.remove_prefix("ex")
        assert OTHER not in om.get_creatable_namespaces()

    def test_namespace_in_use_by_entity_is_offered(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Dog", namespace=OTHER)
        assert OTHER in om.get_creatable_namespaces()

    def test_syntax_namespaces_excluded(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_prefix("ex", OTHER)
        nss = om.get_creatable_namespaces()
        assert "http://www.w3.org/2002/07/owl#" not in nss
        assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#" not in nss

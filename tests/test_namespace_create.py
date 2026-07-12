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


class TestRenamePreservesNamespace:
    def test_rename_class_keeps_namespace(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Thing", namespace=OTHER, label="a thing")
        assert om.rename_class(OTHER + "Thing", "Thing2") is True
        uris = {c["uri"]: c for c in om.get_classes()}
        assert OTHER + "Thing2" in uris
        assert OTHER + "Thing" not in uris
        # Base namespace must not have swallowed it.
        assert "http://test.org/ont#Thing2" not in uris
        # The label survives the rename (post-rename update targets the new URI).
        assert uris[OTHER + "Thing2"]["label"] == "a thing"

    def test_rename_property_keeps_namespace(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_object_property("knows", namespace=OTHER)
        assert om.rename_property(OTHER + "knows", "knowsWell") is True
        uris = {p["uri"] for p in om.get_object_properties()}
        assert OTHER + "knowsWell" in uris
        assert "http://test.org/ont#knowsWell" not in uris

    def test_rename_individual_keeps_namespace(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Person")
        om.add_individual("alice", "Person", namespace=OTHER)
        assert om.rename_individual(OTHER + "alice", "alice2") is True
        uris = {i["uri"] for i in om.get_individuals()}
        assert OTHER + "alice2" in uris
        assert "http://test.org/ont#alice2" not in uris

    def test_rename_to_full_uri_still_overrides(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Thing", namespace=OTHER)
        assert om.rename_class(OTHER + "Thing", "http://third.example/X") is True
        uris = {c["uri"] for c in om.get_classes()}
        assert "http://third.example/X" in uris

    def test_base_namespace_rename_unchanged(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Dog")
        assert om.rename_class("Dog", "Hound") is True
        uris = {c["uri"] for c in om.get_classes()}
        assert "http://test.org/ont#Hound" in uris

    def test_move_class_between_namespaces_keeps_references(self):
        # Moving a class = renaming it to a full URI in another namespace; every
        # reference (subclass links, instance typing) must follow.
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Animal")
        om.add_class("Dog", parent="Animal", namespace=OTHER)
        om.add_individual("rex", OTHER + "Dog")
        # Move OTHER#Dog to the base namespace.
        assert om.rename_class(OTHER + "Dog", "http://test.org/ont#Dog") is True

        classes = {c["uri"]: c for c in om.get_classes()}
        assert "http://test.org/ont#Dog" in classes
        assert OTHER + "Dog" not in classes
        # Subclass link preserved (by local name and by URI).
        assert "Animal" in classes["http://test.org/ont#Dog"]["parents"]
        # Instance typing preserved.
        rex = next(i for i in om.get_individuals() if i["name"] == "rex")
        assert "http://test.org/ont#Dog" in rex.get("class_uris", [])


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

    def test_reflects_graph_after_load(self):
        # Derived from the live graph, so a prefix bound before a load must not
        # linger once the loaded ontology no longer declares it (issue #87
        # review, finding 2).
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_prefix("ex", OTHER)
        assert OTHER in om.get_creatable_namespaces()

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix ex2: <http://second.example/ns#> .\n"
            "ex2:Foo a owl:Class .\n"
            "<http://loaded.example/ont> a owl:Ontology .\n"
        )
        om.load_from_string(ttl)
        nss = om.get_creatable_namespaces()
        assert OTHER not in nss
        assert "http://second.example/ns#" in nss

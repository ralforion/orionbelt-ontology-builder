"""Tests for class CRUD operations."""


def test_add_class(om):
    om.add_class("Animal", label="Animal")
    classes = om.get_classes()
    names = [c["name"] for c in classes]
    assert "Animal" in names


def test_add_class_with_parent(om):
    om.add_class("Animal")
    om.add_class("Dog", parent="Animal")
    classes = {c["name"]: c for c in om.get_classes()}
    assert "Animal" in classes["Dog"]["parents"]


def test_rename_class(populated_om):
    result = populated_om.rename_class("Person", "Human")
    assert result is True
    names = [c["name"] for c in populated_om.get_classes()]
    assert "Human" in names
    assert "Person" not in names


def test_delete_class_removes_class(populated_om):
    populated_om.delete_class("Organization")
    names = [c["name"] for c in populated_om.get_classes()]
    assert "Organization" not in names


def test_delete_class_removes_individual_typing(populated_om):
    """Regression: deleting a class strips rdf:type from its instances."""
    populated_om.delete_class("Employee")
    # alice should still exist as NamedIndividual but lose Employee type
    individuals = populated_om.get_individuals()
    alice = next((i for i in individuals if i["name"] == "alice"), None)
    assert alice is not None
    # The Employee type is gone; alice may have no class type left
    assert "Employee" not in alice.get("types", [])


def test_get_class_hierarchy(populated_om):
    hierarchy = populated_om.get_class_hierarchy()
    assert "Person" in hierarchy
    assert "Employee" in hierarchy["Person"]


def test_get_classes_includes_parent_uris(populated_om):
    """Regression: graph viewer needs URI-keyed parent links to disambiguate
    cross-namespace duplicates without local-name lookup."""
    classes = {c["name"]: c for c in populated_om.get_classes()}
    employee = classes["Employee"]
    assert employee["parents"] == ["Person"]
    assert len(employee["parent_uris"]) == 1
    assert employee["parent_uris"][0].endswith("Person")


class TestCrossNamespaceDuplicates:
    """Regression tests for the v1.3.0 'duplicate local name' fix.

    When two ontologies are merged that both define a class with the same
    local name (e.g. gist:Organization and foaf:Organization), the URI-based
    operations must address them independently.
    """

    def _make_two_orgs(self):
        from rdflib import Graph, RDF, OWL, RDFS, Literal, URIRef
        from ontology_manager import OntologyManager

        om = OntologyManager(base_uri="http://example.org/myont#")

        # Inject FOAF-style and gist-style 'Organization' classes directly,
        # since add_class would put both in the base namespace and collapse them.
        foaf_org = URIRef("http://xmlns.com/foaf/0.1/Organization")
        gist_org = URIRef("https://w3id.org/semanticarts/ns/ontology/gist/Organization")
        om.graph.add((foaf_org, RDF.type, OWL.Class))
        om.graph.add((foaf_org, RDFS.label, Literal("FOAF Organization")))
        om.graph.add((gist_org, RDF.type, OWL.Class))
        om.graph.add((gist_org, RDFS.label, Literal("gist Organization")))
        om.graph.bind("foaf", "http://xmlns.com/foaf/0.1/")
        om.graph.bind("gist", "https://w3id.org/semanticarts/ns/ontology/gist/")
        return om, str(foaf_org), str(gist_org)

    def test_get_classes_returns_both_with_distinct_uris(self):
        om, foaf_uri, gist_uri = self._make_two_orgs()
        classes = om.get_classes()
        orgs = [c for c in classes if c["name"] == "Organization"]
        assert len(orgs) == 2
        uris = {c["uri"] for c in orgs}
        assert uris == {foaf_uri, gist_uri}

    def test_delete_by_uri_only_affects_one(self):
        om, foaf_uri, gist_uri = self._make_two_orgs()
        om.delete_class(foaf_uri)
        remaining = [c for c in om.get_classes() if c["name"] == "Organization"]
        assert len(remaining) == 1
        assert remaining[0]["uri"] == gist_uri

    def test_rename_by_uri_only_affects_one(self):
        om, foaf_uri, gist_uri = self._make_two_orgs()
        result = om.rename_class(foaf_uri, "SocialOrganization")
        assert result is True
        names = sorted(c["name"] for c in om.get_classes())
        # gist's Organization untouched, foaf's renamed (now in base namespace)
        assert "Organization" in names  # still has gist's
        assert "SocialOrganization" in names

    def test_class_relations_expose_uris(self):
        """Regression for Relations tab key collisions."""
        from rdflib import URIRef, RDF, OWL
        om, foaf_uri, gist_uri = self._make_two_orgs()
        om.graph.add((URIRef(foaf_uri), OWL.equivalentClass, URIRef(gist_uri)))
        rels = om.get_class_relations()
        equiv = [r for r in rels if r["relation"] == "equivalentClass"]
        assert len(equiv) == 1
        assert "subject_uri" in equiv[0]
        assert "object_uri" in equiv[0]
        assert {equiv[0]["subject_uri"], equiv[0]["object_uri"]} == {foaf_uri, gist_uri}

"""Tests for SKOS vocabulary operations."""

import pytest
from rdflib.namespace import SKOS

from ontology_manager import OntologyManager


@pytest.fixture
def om():
    return OntologyManager(base_uri="http://test.org/ont#")


class TestConceptScheme:
    def test_add_scheme(self, om):
        om.add_concept_scheme("Animals", label="Animal Taxonomy")
        schemes = om.get_concept_schemes()
        assert len(schemes) == 1
        assert schemes[0]["name"] == "Animals"
        assert schemes[0]["label"] == "Animal Taxonomy"

    def test_delete_scheme(self, om):
        om.add_concept_scheme("ToDelete")
        om.add_concept("C1", scheme="ToDelete", pref_label="C1")
        om.delete_concept_scheme("ToDelete")
        assert om.get_concept_schemes() == []

    def test_concept_count(self, skos_om):
        schemes = skos_om.get_concept_schemes()
        assert schemes[0]["concept_count"] == 3


class TestConcept:
    def test_add_concept_basic(self, om):
        om.add_concept("Thing", pref_label="A Thing")
        concepts = om.get_concepts()
        assert len(concepts) == 1
        assert concepts[0]["name"] == "Thing"
        assert concepts[0]["prefLabel"] == "A Thing"

    def test_add_concept_with_scheme_and_broader(self, skos_om):
        concepts = skos_om.get_concepts()
        dog = next(c for c in concepts if c["name"] == "Dog")
        assert "Animal" in dog["broader"]
        assert "MyScheme" in dog["schemes"]

    def test_inverse_narrower_auto_added(self, skos_om):
        concepts = skos_om.get_concepts()
        animal = next(c for c in concepts if c["name"] == "Animal")
        assert "Dog" in animal["narrower"]
        assert "Cat" in animal["narrower"]

    def test_concept_with_language(self, om):
        om.add_concept("Hund", pref_label="Hund", lang="de")
        concepts = om.get_concepts()
        assert concepts[0]["prefLabel"] == "Hund"

    def test_filter_by_scheme(self, skos_om):
        skos_om.add_concept_scheme("OtherScheme")
        skos_om.add_concept("Fish", scheme="OtherScheme", pref_label="Fish")
        my_concepts = skos_om.get_concepts(scheme="MyScheme")
        names = [c["name"] for c in my_concepts]
        assert "Fish" not in names
        assert "Dog" in names

    def test_delete_concept(self, skos_om):
        skos_om.delete_concept("Dog")
        concepts = skos_om.get_concepts()
        names = [c["name"] for c in concepts]
        assert "Dog" not in names
        # Animal should no longer list Dog as narrower
        animal = next(c for c in concepts if c["name"] == "Animal")
        assert "Dog" not in animal["narrower"]


class TestConceptRelation:
    def test_add_related(self, skos_om):
        skos_om.add_concept_relation("Dog", "related", "Cat")
        concepts = skos_om.get_concepts()
        dog = next(c for c in concepts if c["name"] == "Dog")
        cat = next(c for c in concepts if c["name"] == "Cat")
        assert "Cat" in dog["related"]
        assert "Dog" in cat["related"]  # symmetric

    def test_add_broader(self, om):
        om.add_concept("A")
        om.add_concept("B")
        om.add_concept_relation("B", "broader", "A")
        concepts = om.get_concepts()
        b = next(c for c in concepts if c["name"] == "B")
        a = next(c for c in concepts if c["name"] == "A")
        assert "A" in b["broader"]
        assert "B" in a["narrower"]  # inverse

    def test_unknown_relation_raises(self, om):
        om.add_concept("X")
        om.add_concept("Y")
        with pytest.raises(ValueError, match="Unknown SKOS relation"):
            om.add_concept_relation("X", "invalidRel", "Y")


class TestConceptHierarchy:
    def test_hierarchy_structure(self, skos_om):
        h = skos_om.get_concept_hierarchy()
        assert "Dog" in h["Animal"]
        assert "Cat" in h["Animal"]
        assert h["Dog"] == []

    def test_hierarchy_filtered_by_scheme(self, skos_om):
        skos_om.add_concept_scheme("Other")
        skos_om.add_concept("Fish", scheme="Other", pref_label="Fish")
        h = skos_om.get_concept_hierarchy(scheme="MyScheme")
        assert "Fish" not in h


class TestValidateSKOS:
    def test_missing_prefLabel(self, om):
        om.add_concept("NoLabel")
        issues = om.validate_skos()
        assert any(i["type"] == "missing_prefLabel" for i in issues)

    def test_no_scheme(self, om):
        om.add_concept_scheme("S")
        om.add_concept("Orphan", pref_label="Orphan")
        issues = om.validate_skos()
        assert any(i["type"] == "no_scheme" for i in issues)

    def test_duplicate_prefLabel_in_scheme(self, om):
        om.add_concept_scheme("S")
        om.add_concept("A", scheme="S", pref_label="Same")
        om.add_concept("B", scheme="S", pref_label="Same")
        issues = om.validate_skos()
        assert any(i["type"] == "duplicate_prefLabel" for i in issues)

    def test_broader_cycle(self, om):
        om.add_concept("X", pref_label="X")
        om.add_concept("Y", pref_label="Y", broader="X")
        # Write the closing edge straight into the graph rather than through
        # ``add_concept_relation``, which now refuses it. A cycle can still
        # reach the validator by import, which is what this covers.
        om.graph.add((om._uri("X"), SKOS.broader, om._uri("Y")))
        issues = om.validate_skos()
        assert any(i["type"] == "broader_cycle" for i in issues)

    def test_broader_cycle_refused_at_write_time(self, om):
        om.add_concept("X", pref_label="X")
        om.add_concept("Y", pref_label="Y", broader="X")
        with pytest.raises(ValueError, match="cycle"):
            om.add_concept_relation("X", "broader", "Y")

    def test_valid_skos_no_issues(self, skos_om):
        issues = skos_om.validate_skos()
        assert len(issues) == 0

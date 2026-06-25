"""Tests for bulk operations."""

import pytest
from ontology_manager import OntologyManager


@pytest.fixture
def om():
    return OntologyManager(base_uri="http://test.org/ont#")


@pytest.fixture
def om_with_classes(om):
    om.add_class("Person", label="Person")
    om.add_class("Animal")
    return om


class TestParseBulkText:
    def test_simple_one_per_line(self):
        text = "Dog\nCat\nBird"
        result = OntologyManager.parse_bulk_text(text)
        assert result == [{"name": "Dog"}, {"name": "Cat"}, {"name": "Bird"}]

    def test_skips_empty_lines(self):
        text = "Dog\n\n  \nCat\n"
        result = OntologyManager.parse_bulk_text(text)
        assert result == [{"name": "Dog"}, {"name": "Cat"}]

    def test_csv_with_header(self):
        text = "Name, Label, Parent\nDog, A Dog, Animal\nCat, A Cat, Animal"
        result = OntologyManager.parse_bulk_text(text)
        assert len(result) == 2
        assert result[0] == {"name": "Dog", "label": "A Dog", "parent": "Animal"}
        assert result[1] == {"name": "Cat", "label": "A Cat", "parent": "Animal"}

    def test_csv_with_explicit_columns(self):
        text = "Dog, Mammal\nCat, Mammal"
        result = OntologyManager.parse_bulk_text(text, columns=["name", "parent"])
        assert len(result) == 2
        assert result[0] == {"name": "Dog", "parent": "Mammal"}

    def test_csv_missing_columns_filled_empty(self):
        text = "Name, Label, Parent\nDog"
        result = OntologyManager.parse_bulk_text(text)
        assert result[0]["name"] == "Dog"
        assert result[0]["label"] == ""
        assert result[0]["parent"] == ""

    def test_empty_text(self):
        assert OntologyManager.parse_bulk_text("") == []
        assert OntologyManager.parse_bulk_text("  \n  ") == []


class TestBulkAddClasses:
    def test_add_multiple(self, om):
        entries = [{"name": "Dog"}, {"name": "Cat"}, {"name": "Bird"}]
        result = om.bulk_add_classes(entries)
        assert result["created"] == ["Dog", "Cat", "Bird"]
        assert result["errors"] == []
        assert result["skipped"] == []
        classes = [c["name"] for c in om.get_classes()]
        assert "Dog" in classes and "Cat" in classes and "Bird" in classes

    def test_skip_existing(self, om_with_classes):
        entries = [{"name": "Person"}, {"name": "NewClass"}]
        result = om_with_classes.bulk_add_classes(entries)
        assert result["created"] == ["NewClass"]
        assert result["skipped"] == ["Person"]

    def test_with_labels_and_parents(self, om_with_classes):
        entries = [{"name": "Student", "label": "A Student", "parent": "Person"}]
        result = om_with_classes.bulk_add_classes(entries)
        assert result["created"] == ["Student"]
        classes = {c["name"]: c for c in om_with_classes.get_classes()}
        assert classes["Student"]["label"] == "A Student"
        assert "Person" in classes["Student"]["parents"]

    def test_empty_name_error(self, om):
        entries = [{"name": ""}, {"name": "Valid"}]
        result = om.bulk_add_classes(entries)
        assert len(result["errors"]) == 1
        assert result["created"] == ["Valid"]


class TestBulkAddProperties:
    def test_add_object_properties(self, om_with_classes):
        entries = [
            {"name": "likes", "domain": "Person", "range": "Person"},
            {"name": "owns", "domain": "Person", "range": "Animal"},
        ]
        result = om_with_classes.bulk_add_properties(entries, property_type="object")
        assert result["created"] == ["likes", "owns"]
        props = [p["name"] for p in om_with_classes.get_object_properties()]
        assert "likes" in props

    def test_add_data_properties(self, om_with_classes):
        entries = [{"name": "age", "domain": "Person", "range": "integer"}]
        result = om_with_classes.bulk_add_properties(entries, property_type="data")
        assert result["created"] == ["age"]

    def test_skip_existing_property(self, om_with_classes):
        om_with_classes.add_object_property("hasFriend")
        entries = [{"name": "hasFriend"}, {"name": "hasEnemy"}]
        result = om_with_classes.bulk_add_properties(entries, property_type="object")
        assert result["skipped"] == ["hasFriend"]
        assert result["created"] == ["hasEnemy"]


class TestBulkAddIndividuals:
    def test_add_multiple(self, om_with_classes):
        entries = [
            {"name": "fido", "class": "Animal", "label": "Fido"},
            {"name": "rex", "class": "Animal"},
        ]
        result = om_with_classes.bulk_add_individuals(entries)
        assert result["created"] == ["fido", "rex"]

    def test_missing_class_error(self, om_with_classes):
        entries = [{"name": "bob"}]
        result = om_with_classes.bulk_add_individuals(entries)
        assert len(result["errors"]) == 1
        assert result["errors"][0]["error"] == "Missing class"


class TestBulkUpdateAnnotations:
    def test_add_annotations(self, om_with_classes):
        updates = [
            {"resource": "Person", "predicate": "comment", "value": "A person"},
            {"resource": "Animal", "predicate": "label", "value": "An Animal"},
        ]
        result = om_with_classes.bulk_update_annotations(updates)
        assert result["applied"] == 2
        assert result["errors"] == []

    def test_delete_annotation(self, om_with_classes):
        # Person already has label "Person"
        updates = [
            {
                "resource": "Person",
                "predicate": "label",
                "value": "Person",
                "action": "delete",
            },
        ]
        result = om_with_classes.bulk_update_annotations(updates)
        assert result["applied"] == 1
        annots = om_with_classes.get_annotations("Person")
        labels = [a for a in annots if a["predicate_label"] == "label"]
        assert len(labels) == 0

    def test_missing_value_for_add(self, om_with_classes):
        updates = [{"resource": "Person", "predicate": "label", "value": ""}]
        result = om_with_classes.bulk_update_annotations(updates)
        assert len(result["errors"]) == 1


class TestBulkDeleteClasses:
    def test_delete_multiple(self, om_with_classes):
        result = om_with_classes.bulk_delete_classes(["Person", "Animal"])
        assert result["deleted"] == ["Person", "Animal"]
        classes = [c["name"] for c in om_with_classes.get_classes()]
        assert "Person" not in classes
        assert "Animal" not in classes

    def test_delete_empty_list(self, om_with_classes):
        result = om_with_classes.bulk_delete_classes([])
        assert result["deleted"] == []


class TestBulkDeleteProperties:
    def test_delete_property(self, om_with_classes):
        om_with_classes.add_object_property("likes")
        result = om_with_classes.bulk_delete_properties(["likes"])
        assert result["deleted"] == ["likes"]


class TestBulkDeleteIndividuals:
    def test_delete_multiple(self, om_with_classes):
        om_with_classes.add_individual("fido", "Animal")
        om_with_classes.add_individual("rex", "Animal")
        result = om_with_classes.bulk_delete_individuals(["fido", "rex"])
        assert result["deleted"] == ["fido", "rex"]
        inds = [i["name"] for i in om_with_classes.get_individuals()]
        assert "fido" not in inds

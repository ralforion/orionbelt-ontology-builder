"""Tests for bulk operations."""

import pytest
from ontology_manager import OntologyManager
from rdflib.namespace import RDFS


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

    def test_header_optional_comma(self):
        # Issue #91: a data line with commas but no header row should still
        # be parsed positionally when default_columns are supplied.
        text = "Dog, A Dog, Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [{"name": "Dog", "label": "A Dog", "parent": "Animal"}]

    def test_header_optional_semicolon(self):
        text = "Dog; A Dog; Animal\nCat; A Cat; Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [
            {"name": "Dog", "label": "A Dog", "parent": "Animal"},
            {"name": "Cat", "label": "A Cat", "parent": "Animal"},
        ]

    def test_semicolon_preserves_comma_in_label(self):
        # Semicolon delimiter lets a label legitimately contain a comma.
        text = "Dog; A Dog, the domestic one; Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [
            {"name": "Dog", "label": "A Dog, the domestic one", "parent": "Animal"}
        ]

    def test_semicolon_header(self):
        text = "Name; Label; Parent\nDog; A Dog; Animal"
        result = OntologyManager.parse_bulk_text(text)
        assert result == [{"name": "Dog", "label": "A Dog", "parent": "Animal"}]

    def test_simple_mode_without_default_columns(self):
        # Without default_columns and no header, a comma line stays a single name
        # (preserves the documented simple-mode behavior).
        text = "Dog, A Dog, Animal"
        result = OntologyManager.parse_bulk_text(text)
        assert result == [{"name": "Dog, A Dog, Animal"}]

    def test_header_takes_precedence_over_default_columns(self):
        text = "Name, Parent\nDog, Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [{"name": "Dog", "parent": "Animal"}]

    def test_semicolon_in_label_does_not_flip_comma_csv(self):
        # A comma CSV (header uses commas) must stay comma-delimited even when a
        # later row's label contains a semicolon.
        text = "Name, Label, Parent\nDog, A dog; domestic, Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [
            {"name": "Dog", "label": "A dog; domestic", "parent": "Animal"}
        ]

    def test_semicolon_in_label_header_less_comma_csv(self):
        # Same protection without a header row: commas outnumber the lone ';',
        # so the line stays comma-delimited.
        text = "Dog, A dog; domestic, Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [
            {"name": "Dog", "label": "A dog; domestic", "parent": "Animal"}
        ]

    def test_semicolon_delimiter_with_multiple_commas_in_label(self):
        # Review finding 4: a semicolon row whose label has several commas must
        # still be read as semicolon-delimited (both split to 3 fields, so the
        # column-count heuristic favours the semicolon escape hatch).
        text = "Dog; A, friendly, domestic dog; Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [
            {"name": "Dog", "label": "A, friendly, domestic dog", "parent": "Animal"}
        ]

    def test_column_count_disambiguates_comma_csv(self):
        # Comma split matches the expected 3 columns; semicolon in the label does
        # not, so comma stays the delimiter.
        text = "Dog, A; B; C, Animal"
        result = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert result == [{"name": "Dog", "label": "A; B; C", "parent": "Animal"}]


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

    def test_missing_parent_declared_as_class(self, om):
        # Issue #106: a referenced parent that isn't a class should be declared
        # as one, so subClassOf points at a real class node.
        result = om.bulk_add_classes([{"name": "Dog", "parent": "Animal"}])
        assert "Dog" in result["created"]
        assert "Animal" in result["created"]
        classes = {c["name"]: c for c in om.get_classes()}
        assert "Animal" in classes  # now a real owl:Class
        assert "Animal" in classes["Dog"]["parents"]
        # The whole graph still serializes.
        assert om.graph.serialize(format="turtle")

    def test_existing_parent_not_redeclared(self, om_with_classes):
        # Person already exists; it must not be re-created or duplicated.
        result = om_with_classes.bulk_add_classes(
            [{"name": "Student", "parent": "Person"}]
        )
        assert result["created"] == ["Student"]  # Person not re-created
        student = next(
            c for c in om_with_classes.get_classes() if c["name"] == "Student"
        )
        assert "Person" in student["parents"]

    def test_explicit_parent_row_keeps_its_label(self, om):
        # When the parent is also an explicit row (even later), that row creates
        # it with its label; it is not auto-declared as a bare class first.
        result = om.bulk_add_classes(
            [
                {"name": "Dog", "parent": "Animal"},
                {"name": "Animal", "label": "An Animal"},
            ]
        )
        assert result["created"] == ["Dog", "Animal"]  # Animal once, from its row
        classes = {c["name"]: c for c in om.get_classes()}
        assert classes["Animal"]["label"] == "An Animal"
        assert "Animal" in classes["Dog"]["parents"]

    def test_explicit_row_in_other_namespace_does_not_suppress_parent(self, om):
        # Review P1: a same-named explicit row in a DIFFERENT namespace must not
        # suppress declaring the base-namespace parent the child references.
        om.bulk_add_classes(
            [
                {"name": "Dog", "parent": "Animal"},
                {"name": "Animal", "namespace": "http://other.example/ns#"},
            ]
        )
        base_animal = str(om._uri("Animal"))  # base namespace
        other_animal = "http://other.example/ns#Animal"
        uris = {c["uri"] for c in om.get_classes()}
        # The parent the child actually points at is a real class...
        assert base_animal in uris
        assert base_animal in {
            str(o) for o in om.graph.objects(om._uri("Dog"), RDFS.subClassOf)
        }
        # ...and so is the unrelated other-namespace class.
        assert other_animal in uris
        assert om.graph.serialize(format="turtle")

    def test_failed_explicit_parent_row_still_backfills(self, om):
        # Review P2: an explicit parent row that errors must not suppress
        # declaring the parent the child actually references.
        result = om.bulk_add_classes(
            [
                {"name": "Dog", "parent": "Animal"},
                {"name": "Animal", "parent": "Bad Parent"},  # invalid -> errors
            ]
        )
        assert any(e["name"] == "Animal" for e in result["errors"])
        base_animal = str(om._uri("Animal"))
        uris = {c["uri"] for c in om.get_classes()}
        # Backfilled despite the failed explicit row, so no dangling parent.
        assert base_animal in uris
        assert base_animal in {
            str(o) for o in om.graph.objects(om._uri("Dog"), RDFS.subClassOf)
        }
        assert om.graph.serialize(format="turtle")

    def test_same_local_name_other_namespace_not_skipped(self):
        # Review finding 3: a base-namespace entry must not be skipped just
        # because the local name exists in another namespace.
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Dog", namespace="http://other.example/ns#")
        result = om.bulk_add_classes([{"name": "Dog"}])
        assert result["created"] == ["Dog"]
        assert result["skipped"] == []
        assert "http://test.org/ont#Dog" in {c["uri"] for c in om.get_classes()}

    def test_namespace_column_creates_in_namespace(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        entries = [{"name": "Dog", "namespace": "http://other.example/ns#"}]
        result = om.bulk_add_classes(entries)
        assert result["created"] == ["Dog"]
        assert "http://other.example/ns#Dog" in {c["uri"] for c in om.get_classes()}

    def test_duplicate_full_uri_still_skipped(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Dog")
        result = om.bulk_add_classes([{"name": "Dog"}])
        assert result["skipped"] == ["Dog"]
        assert result["created"] == []

    def test_second_row_adds_extra_parent(self, om):
        # Issue #157: two rows for the same class naming different parents give
        # the class both parents instead of dropping the second row.
        result = om.bulk_add_classes(
            [
                {"name": "TVCurrent", "parent": "Current"},
                {"name": "TVCurrent", "parent": "TVQuantity"},
            ]
        )
        # TVCurrent is created once (row 1) and updated once (row 2's parent);
        # both referenced parents are backfilled as classes (issue #106).
        assert result["created"].count("TVCurrent") == 1
        assert result["updated"] == ["TVCurrent"]
        assert {"Current", "TVQuantity"} <= set(result["created"])
        parents = next(c for c in om.get_classes() if c["name"] == "TVCurrent")[
            "parents"
        ]
        assert "Current" in parents
        assert "TVQuantity" in parents

    def test_existing_class_gains_new_parent(self, om_with_classes):
        # Person already exists; a row giving it a parent adds the link and is
        # reported as updated (not created, not silently skipped).
        result = om_with_classes.bulk_add_classes(
            [{"name": "Person", "parent": "Animal"}]
        )
        assert result["created"] == []
        assert result["updated"] == ["Person"]
        assert result["skipped"] == []
        person = next(c for c in om_with_classes.get_classes() if c["name"] == "Person")
        assert "Animal" in person["parents"]

    def test_existing_parent_link_is_skipped_not_duplicated(self, om_with_classes):
        om_with_classes.update_class("Person", new_parent="Animal")
        result = om_with_classes.bulk_add_classes(
            [{"name": "Person", "parent": "Animal"}]
        )
        assert result["updated"] == []
        assert result["skipped"] == ["Person"]
        person = next(c for c in om_with_classes.get_classes() if c["name"] == "Person")
        assert person["parents"].count("Animal") == 1

    def test_existing_class_without_parent_still_skipped(self, om_with_classes):
        result = om_with_classes.bulk_add_classes([{"name": "Person"}])
        assert result["created"] == []
        assert result["updated"] == []
        assert result["skipped"] == ["Person"]

    def test_added_parent_to_existing_class_is_backfilled(self, om_with_classes):
        # The new parent isn't a class yet, so it's declared as a bare owl:Class
        # just like on the create path (issue #106).
        result = om_with_classes.bulk_add_classes(
            [{"name": "Person", "parent": "Organism"}]
        )
        assert result["updated"] == ["Person"]
        assert "Organism" in result["created"]
        assert "Organism" in {c["name"] for c in om_with_classes.get_classes()}
        assert om_with_classes.graph.serialize(format="turtle")

    def test_invalid_parent_on_existing_class_is_an_error(self, om_with_classes):
        result = om_with_classes.bulk_add_classes(
            [{"name": "Person", "parent": "Bad Parent"}]
        )
        assert result["updated"] == []
        assert result["skipped"] == []
        assert [e["name"] for e in result["errors"]] == ["Person"]


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


class TestBulkErrorDetail:
    """Bulk add reports failed entries with a reason instead of failing
    silently (issue #114)."""

    def test_invalid_name_recorded_with_reason(self, om):
        result = om.bulk_add_classes([{"name": "Dog, 1"}])
        assert result["created"] == []
        assert len(result["errors"]) == 1
        err = result["errors"][0]
        assert err["name"] == "Dog, 1"
        assert err["error"]  # a non-empty human-readable reason

    def test_issue_114_repro_parses_to_one_invalid_entry(self, om):
        # The exact input from issue #114: the parser picks ';' (it splits to the
        # expected 3 fields, comma splits to 4), yielding a single entry whose
        # name contains a comma/space and is rejected -- now surfaced, not silent.
        text = "Dog, 1; A very, special Dog; Animal, and friends"
        entries = OntologyManager.parse_bulk_text(
            text, default_columns=["name", "label", "parent"]
        )
        assert entries == [
            {
                "name": "Dog, 1",
                "label": "A very, special Dog",
                "parent": "Animal, and friends",
            }
        ]
        result = om.bulk_add_classes(entries)
        assert result["created"] == []
        assert [e["name"] for e in result["errors"]] == ["Dog, 1"]
        assert not om.get_classes()

    def test_partial_success_records_only_the_bad_rows(self, om):
        result = om.bulk_add_classes(
            [{"name": "Dog"}, {"name": "bad name"}, {"name": "Cat"}]
        )
        assert set(result["created"]) == {"Dog", "Cat"}
        assert [e["name"] for e in result["errors"]] == ["bad name"]


class TestBulkResultMessage:
    """The flash-message builder names failed entries and their reason."""

    def test_message_lists_failures_with_reason(self):
        from orionbelt_ontology_builder import app

        result = {
            "created": [],
            "skipped": [],
            "errors": [{"name": "Dog, 1", "error": "Names cannot contain spaces."}],
        }
        msg, mtype = app._bulk_result_message(result, "class(es)")
        assert "Dog, 1" in msg
        assert "Names cannot contain spaces." in msg
        assert mtype == "error"  # nothing created, only errors

    def test_message_partial_is_warning(self):
        from orionbelt_ontology_builder import app

        result = {
            "created": ["Dog"],
            "skipped": [],
            "errors": [{"name": "bad name", "error": "invalid"}],
        }
        msg, mtype = app._bulk_result_message(result, "class(es)")
        assert "Created 1 class(es)" in msg
        assert "bad name" in msg
        assert mtype == "warning"

    def test_message_all_created_is_success(self):
        from orionbelt_ontology_builder import app

        result = {"created": ["Dog", "Cat"], "skipped": [], "errors": []}
        msg, mtype = app._bulk_result_message(result, "class(es)")
        assert mtype == "success"
        assert "could not be created" not in msg

    def test_message_truncates_long_error_lists(self):
        from orionbelt_ontology_builder import app

        result = {
            "created": [],
            "skipped": [],
            "errors": [{"name": f"n{i}", "error": "bad"} for i in range(15)],
        }
        msg, _ = app._bulk_result_message(result, "class(es)")
        assert "...and 5 more" in msg

    def test_message_counts_updated(self):
        from orionbelt_ontology_builder import app

        result = {"created": ["Dog"], "updated": ["Cat"], "skipped": [], "errors": []}
        msg, mtype = app._bulk_result_message(result, "class(es)")
        assert "Created 1 class(es)" in msg
        assert "Updated 1 existing" in msg
        assert mtype == "success"

    def test_message_only_updated_is_success(self):
        # A run that only added parents to existing classes still succeeded.
        from orionbelt_ontology_builder import app

        result = {"created": [], "updated": ["Cat"], "skipped": [], "errors": []}
        msg, mtype = app._bulk_result_message(result, "class(es)")
        assert "Updated 1 existing" in msg
        assert "Nothing to create" not in msg
        assert mtype == "success"

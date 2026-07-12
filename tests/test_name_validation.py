"""Tests for entity name validation (issue #93)."""

import pytest
from ontology_manager import OntologyManager


VALID = [
    "OutputTable",
    "output-table",
    "my-class.v2",
    "3DModel",  # relaxed NCName allows a leading digit
    "_private",
    "Straße",  # Unicode letters are allowed
    "日本語",
    "http://other.example/ns#Thing",  # explicit full IRI
]

INVALID = [
    "state/output-table",  # the reported case
    "Output Table",  # space
    "has space",
    "a:b",  # colon (prefix separator)
    "has#frag",
    "-leading",
    ".leading",
    "",
    "   ",
    "http://ex.org/A B",  # full IRI with a space
]


class TestInvalidNameReason:
    @pytest.mark.parametrize("name", VALID)
    def test_valid(self, name):
        assert OntologyManager.invalid_name_reason(name) is None

    @pytest.mark.parametrize("name", INVALID)
    def test_invalid(self, name):
        assert OntologyManager.invalid_name_reason(name) is not None


class TestAddRejectsInvalid:
    def test_add_class_rejects_slash(self, om):
        with pytest.raises(ValueError):
            om.add_class("state/output-table")
        assert om.get_classes() == []

    def test_add_class_rejects_space(self, om):
        with pytest.raises(ValueError):
            om.add_class("Output Table")

    def test_add_class_accepts_valid(self, om):
        om.add_class("OutputTable")
        assert "OutputTable" in [c["name"] for c in om.get_classes()]

    def test_add_object_property_rejects_invalid(self, om):
        with pytest.raises(ValueError):
            om.add_object_property("has/friend")

    def test_add_data_property_rejects_invalid(self, om):
        with pytest.raises(ValueError):
            om.add_data_property("has age")

    def test_add_individual_rejects_invalid(self, om):
        om.add_class("Person")
        with pytest.raises(ValueError):
            om.add_individual("alice/bob", "Person")

    def test_add_concept_rejects_invalid(self, om):
        with pytest.raises(ValueError):
            om.add_concept("bad/concept")

    def test_add_concept_scheme_rejects_invalid(self, om):
        with pytest.raises(ValueError):
            om.add_concept_scheme("bad scheme")


class TestRenameRejectsInvalid:
    def test_rename_class_rejects_invalid(self, om):
        om.add_class("Dog")
        with pytest.raises(ValueError):
            om.rename_class("Dog", "state/output-table")
        # The original class is untouched.
        assert "Dog" in [c["name"] for c in om.get_classes()]

    def test_rename_individual_rejects_space(self, om):
        om.add_class("Person")
        om.add_individual("alice", "Person")
        with pytest.raises(ValueError):
            om.rename_individual("alice", "alice bob")


class TestSerializableAfterValidation:
    def test_valid_ontology_serializes(self, om):
        # The whole point: a validated ontology must still serialize (a space in
        # a name would previously break Turtle export entirely).
        om.add_class("OutputTable", label="Output Table")
        ttl = om.graph.serialize(format="turtle")
        assert "OutputTable" in ttl


class TestBulkAddReportsInvalid:
    def test_bulk_add_records_invalid_name(self, om):
        result = om.bulk_add_classes([{"name": "Good"}, {"name": "bad/name"}])
        assert "Good" in result["created"]
        assert any(e["name"] == "bad/name" for e in result["errors"])
        assert "bad/name" not in [c["name"] for c in om.get_classes()]

    def test_bulk_add_records_invalid_parent(self, om):
        # Review P3: an invalid reference must not leave an unserializable URI.
        result = om.bulk_add_classes([{"name": "Good", "parent": "Bad Parent"}])
        assert any(e["name"] == "Good" for e in result["errors"])
        assert "Good" not in [c["name"] for c in om.get_classes()]
        # The graph is still serializable (no half-written broken triple).
        assert om.graph.serialize(format="turtle")


class TestSurroundingWhitespace:
    @pytest.mark.parametrize("name", ["Foo ", " Foo", "Foo\tBar", "Foo\nBar"])
    def test_surrounding_or_inner_whitespace_rejected(self, name):
        # Review P1: the validator no longer strips, so whitespace that would
        # otherwise reach _uri() verbatim is rejected.
        assert OntologyManager.invalid_name_reason(name) is not None

    def test_add_class_trailing_space_no_partial_write(self, om):
        with pytest.raises(ValueError):
            om.add_class("Foo ")
        assert om.get_classes() == []
        assert om.graph.serialize(format="turtle")


class TestFullUriValidation:
    @pytest.mark.parametrize(
        "uri",
        [
            "http://ex.org/A<B",
            "http://ex.org/A>B",
            'http://ex.org/A"B',
            "http://ex.org/A|B",
            "http://ex.org/A^B",
        ],
    )
    def test_full_uri_with_breaking_chars_rejected(self, uri):
        # Review P2: characters rdflib refuses to serialize must be rejected.
        assert OntologyManager.invalid_name_reason(uri) is not None

    def test_add_class_bad_uri_no_partial_write(self, om):
        with pytest.raises(ValueError):
            om.add_class("http://ex.org/A<B")
        assert om.get_classes() == []


class TestReferenceValidation:
    def test_add_class_rejects_invalid_parent(self, om):
        with pytest.raises(ValueError):
            om.add_class("Good", parent="Bad Parent")
        assert om.get_classes() == []
        assert om.graph.serialize(format="turtle")

    def test_add_object_property_rejects_invalid_range(self, om):
        with pytest.raises(ValueError):
            om.add_object_property("likes", domain="Person", range_="Bad Range")

    def test_add_individual_rejects_invalid_class(self, om):
        with pytest.raises(ValueError):
            om.add_individual("alice", "Bad Class")
        assert om.get_individuals() == []

"""Tests for annotation operations, including language-tagged and typed literals."""

import pytest


def test_add_annotation(populated_om):
    populated_om.add_annotation("Person", "label", "Persona", lang="es")
    anns = populated_om.get_annotations("Person")
    values = [a["value"] for a in anns]
    assert "Persona" in values


def test_delete_plain_annotation(populated_om):
    populated_om.add_annotation("Person", "comment", "A human being")
    populated_om.delete_annotation("Person", "comment", "A human being")
    anns = populated_om.get_annotations("Person")
    comments = [a for a in anns if a["predicate"] == "comment"]
    assert not any(a["value"] == "A human being" for a in comments)


def test_delete_language_tagged_annotation(populated_om):
    """Regression: delete must match language-tagged literals."""
    populated_om.add_annotation("Person", "label", "Persona", lang="es")
    populated_om.delete_annotation("Person", "label", "Persona", lang="es")
    anns = populated_om.get_annotations("Person")
    assert not any(a["value"] == "Persona" and a.get("language") == "es" for a in anns)


def test_delete_annotation_without_lang_removes_all_matching_values(populated_om):
    """When no lang/datatype is provided, remove all literals with that string value."""
    populated_om.add_annotation("Person", "label", "Persona", lang="es")
    populated_om.add_annotation("Person", "label", "Persona", lang="fr")
    populated_om.delete_annotation("Person", "label", "Persona")
    anns = populated_om.get_annotations("Person")
    assert not any(a["value"] == "Persona" for a in anns)


def test_delete_annotation_by_predicate_only(populated_om):
    """Passing value=None removes all annotations for that predicate."""
    populated_om.add_annotation("Person", "comment", "Note 1")
    populated_om.add_annotation("Person", "comment", "Note 2")
    populated_om.delete_annotation("Person", "comment")
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate"] == "comment" for a in anns)


SKOS_EXAMPLE = "http://www.w3.org/2004/02/skos/core#example"


def test_delete_skos_example_by_local_name(populated_om):
    """Regression (#47): skos:example was undeletable because delete's
    predicate map omitted it and fell back to the base namespace."""
    populated_om.add_annotation("Person", "example", "An example")
    populated_om.delete_annotation("Person", "example", "An example")
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate_uri"] == SKOS_EXAMPLE for a in anns)


def test_delete_skos_example_by_full_uri(populated_om):
    """The View Annotations bin button now passes the full predicate URI."""
    populated_om.add_annotation("Person", "example", "An example")
    populated_om.delete_annotation("Person", SKOS_EXAMPLE, "An example")
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate_uri"] == SKOS_EXAMPLE for a in anns)


def test_delete_annotation_by_curie(populated_om):
    """A bound prefix:local CURIE resolves to the right URI."""
    populated_om.add_annotation("Person", "example", "An example")
    populated_om.delete_annotation("Person", "skos:example", "An example")
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate_uri"] == SKOS_EXAMPLE for a in anns)


def test_bulk_delete_skos_example(populated_om):
    """Regression (#47): bulk 'delete' action must remove skos:example."""
    populated_om.add_annotation("Person", "example", "An example")
    result = populated_om.bulk_update_annotations(
        [
            {
                "resource": "Person",
                "predicate": "skos:example",
                "value": "An example",
                "action": "delete",
            }
        ]
    )
    assert result["applied"] == 1
    assert not result["errors"]
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate_uri"] == SKOS_EXAMPLE for a in anns)


def test_add_delete_roundtrip_all_common_predicates(populated_om):
    """Every predicate add_annotation knows must also be deletable by name."""
    for local in ("seeAlso", "definition", "note", "title", "example"):
        populated_om.add_annotation("Person", local, f"v-{local}")
        populated_om.delete_annotation("Person", local, f"v-{local}")
    anns = populated_om.get_annotations("Person")
    assert not any(a["value"].startswith("v-") for a in anns)


def test_a_refused_annotation_leaves_nothing_behind(populated_om):
    """A rejected write must not declare the annotation type it was for.

    The type was declared before the object was built, so a language tag rdflib
    refuses left a new, zero-use annotation property in the ontology while the
    caller was told the annotation had failed. Bulk Edit reaches this and
    carries on to the next row, so nothing undid it (review of PR #291).
    """
    before = populated_om.get_custom_annotation_properties()
    with pytest.raises(ValueError, match="not a valid language tag"):
        populated_om.add_annotation("Person", "badLangNote", "value", lang="xx1")

    assert populated_om.get_custom_annotation_properties() == before
    assert not any(
        a["value"] == "value" for a in populated_om.get_annotations("Person")
    )


def test_a_refused_iri_annotation_leaves_nothing_behind(populated_om):
    """The same, for the other refusal on that path: a value that is no IRI."""
    before = populated_om.get_custom_annotation_properties()
    with pytest.raises(ValueError):
        populated_om.add_annotation(
            "Person", "badIriNote", "not an iri", value_is_uri=True
        )

    assert populated_om.get_custom_annotation_properties() == before


def test_a_bad_language_tag_is_reported_per_row_in_a_bulk_edit(populated_om):
    """One bad row is refused with advice and changes nothing."""
    result = populated_om.bulk_update_annotations(
        [
            {
                "resource": "Person",
                "predicate": "badLangNote",
                "value": "value",
                "lang": "xx1",
                "action": "add",
            }
        ]
    )
    assert result["applied"] == 0
    assert "x-mycode" in result["errors"][0]["error"]
    assert populated_om.get_custom_annotation_properties() == []

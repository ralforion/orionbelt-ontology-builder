"""Names are unique across entity kinds, not just within one (issue #279).

A class, a property, an individual and a SKOS concept of the same name are one
URI carrying several rdf:types. The app then lists that single resource as both
a class and an individual, and deleting either one removes the whole thing, so
the create flows refuse the collision instead of quietly making it.
"""

import pytest
from rdflib import OWL, RDF
from streamlit.testing.v1 import AppTest

NS = "http://test.org/ont#"


# --- what the engine reports ------------------------------------------------


def test_a_free_name_has_no_kinds(populated_om):
    assert populated_om.entity_kinds("Nothing") == []
    assert populated_om.name_conflict_reason("Nothing", "class") is None


@pytest.mark.parametrize(
    ("name", "kinds"),
    [
        ("Person", ["class"]),
        ("worksFor", ["object property"]),
        ("hasName", ["data property"]),
        ("alice", ["individual"]),
    ],
)
def test_entity_kinds_names_what_is_there(populated_om, name, kinds):
    assert populated_om.entity_kinds(name) == kinds


def test_a_class_named_after_an_individual_is_refused(populated_om):
    reason = populated_om.name_conflict_reason("alice", "class")
    assert reason and "already an individual" in reason


def test_an_individual_named_after_a_class_is_refused(populated_om):
    reason = populated_om.name_conflict_reason("Person", "individual")
    assert reason and "already a class" in reason


def test_the_same_kind_keeps_the_plain_message(populated_om):
    assert (
        populated_om.name_conflict_reason("Person", "class")
        == "Class 'Person' already exists!"
    )
    # Both flavours of property share one name space, so either one clashes.
    assert (
        populated_om.name_conflict_reason("hasName", "property")
        == "Property 'hasName' already exists!"
    )


def test_skos_names_are_in_the_same_space(skos_om):
    assert skos_om.name_conflict_reason("Dog", "class").startswith(
        "'Dog' is already a SKOS concept"
    )
    assert skos_om.name_conflict_reason("MyScheme", "individual").startswith(
        "'MyScheme' is already a SKOS concept scheme"
    )
    assert (
        skos_om.name_conflict_reason("Dog", "concept")
        == "Concept 'Dog' already exists!"
    )


def test_another_namespace_is_another_name(populated_om):
    """The clash is over the URI, so the same local name elsewhere is free."""
    assert (
        populated_om.name_conflict_reason(
            "alice", "class", namespace="http://other.example/vocab#"
        )
        is None
    )


# --- bulk add ---------------------------------------------------------------


def test_bulk_classes_reject_an_individuals_name(populated_om):
    result = populated_om.bulk_add_classes([{"name": "alice"}, {"name": "Product"}])
    assert result["created"] == ["Product"]
    assert [e["name"] for e in result["errors"]] == ["alice"]
    assert populated_om.entity_kinds("alice") == ["individual"]


def test_bulk_individuals_reject_a_class_name(populated_om):
    result = populated_om.bulk_add_individuals([{"name": "Person", "class": "Person"}])
    assert result["created"] == []
    assert [e["name"] for e in result["errors"]] == ["Person"]
    assert populated_om.entity_kinds("Person") == ["class"]


def test_bulk_properties_reject_the_other_flavours_name(populated_om):
    """hasName is a data property; the same name as an object property would be
    one resource typed as both."""
    result = populated_om.bulk_add_properties([{"name": "hasName"}], "object")
    assert result["created"] == []
    assert [e["name"] for e in result["errors"]] == ["hasName"]
    assert populated_om.entity_kinds("hasName") == ["data property"]


def test_a_backfilled_parent_never_pins_a_type_on_an_individual(populated_om):
    """A parent nobody declared is normally backfilled as a bare owl:Class; one
    whose name is an individual's must not be."""
    result = populated_om.bulk_add_classes([{"name": "Robot", "parent": "alice"}])
    assert result["created"] == ["Robot"]
    assert populated_om.entity_kinds("alice") == ["individual"]
    assert any(e["name"].endswith("alice") for e in result["errors"])


# --- deleting a name that is already punned ---------------------------------


def _pun_alice_as_a_class(om):
    """The state an imported ontology can arrive in: one URI, two types."""
    om.graph.add((om._uri("alice"), RDF.type, OWL.Class))


def test_delete_impact_warns_that_the_name_is_also_something_else(populated_om):
    _pun_alice_as_a_class(populated_om)
    impact = populated_om.get_delete_impact("alice", "class")
    assert impact["also_typed_as"] == ["individual"]
    text = populated_om.format_delete_impact(impact)
    assert "also an individual" in text


def test_an_ordinary_delete_says_nothing_about_other_kinds(populated_om):
    impact = populated_om.get_delete_impact("Person", "class")
    assert impact["also_typed_as"] == []
    assert "also" not in populated_om.format_delete_impact(impact)


def test_validation_reports_a_name_that_is_two_things(populated_om):
    """A loaded ontology can already hold one; nothing else in the app says so."""
    assert not [i for i in populated_om.validate() if i["type"] == "punned_name"]
    _pun_alice_as_a_class(populated_om)
    punned = [i for i in populated_om.validate() if i["type"] == "punned_name"]
    assert len(punned) == 1
    assert punned[0]["subject"] == "alice"
    assert "a class and an individual" in punned[0]["message"]


# --- the add form in front of it --------------------------------------------


def _add_class_script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Person")
        om.add_individual("alice", "Person")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_add_class_form(ont, ont.get_classes(), "add_cls_test")


def test_the_add_class_form_refuses_an_individuals_name():
    at = AppTest.from_function(_add_class_script)
    at.run(timeout=120)
    assert not at.exception, at.exception

    at.text_input[0].set_value("alice")
    at.button[0].click().run(timeout=120)
    assert not at.exception, at.exception

    om = at.session_state["ontology"]
    assert om.entity_kinds("alice") == ["individual"]
    assert [c["name"] for c in om.get_classes()] == ["Person"]
    assert any("already an individual" in e.value for e in at.error)

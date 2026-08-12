"""Names are unique across entity kinds, not just within one (issue #279).

A class, a property, an individual and a SKOS concept of the same name are one
URI carrying several rdf:types. The app then lists that single resource as both
a class and an individual, and deleting either one removes the whole thing, so
the create flows refuse the collision instead of quietly making it.
"""

import pytest
from rdflib import OWL, RDF, RDFS
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


# --- the engine refuses it too, not only the forms --------------------------


@pytest.mark.parametrize(
    ("call", "args"),
    [
        ("add_class", ("alice",)),
        ("add_object_property", ("alice",)),
        ("add_data_property", ("alice",)),
        ("add_concept", ("alice",)),
        ("add_concept_scheme", ("alice",)),
        ("add_individual", ("Person", "Person")),
    ],
)
def test_add_refuses_a_name_another_kind_owns(populated_om, call, args):
    with pytest.raises(ValueError, match="already a"):
        getattr(populated_om, call)(*args)
    assert populated_om.entity_kinds("alice") == ["individual"]
    assert populated_om.entity_kinds("Person") == ["class"]


def test_the_two_property_flavours_are_one_name_space(populated_om):
    """worksFor is an object property; the same name as a data property would be
    one resource on both property lists."""
    with pytest.raises(ValueError, match="already an object property"):
        populated_om.add_data_property("worksFor")
    assert populated_om.entity_kinds("worksFor") == ["object property"]


def test_a_parent_of_another_kind_is_refused_and_nothing_is_written(populated_om):
    with pytest.raises(ValueError, match="already an individual"):
        populated_om.add_class("Robot", parent="alice")
    assert populated_om.entity_kinds("Robot") == []
    assert populated_om.entity_kinds("alice") == ["individual"]


def test_adding_the_same_kind_again_still_works(populated_om):
    """Not a conflict: re-adding is how templates and bulk rows top up an
    existing entity, and the guard must not break that."""
    populated_om.add_class("Person", comment="Again")
    assert populated_om.entity_kinds("Person") == ["class"]


def _loaded_with_a_punned_name():
    """PROV-O declares prov:EmptyCollection as both a class and an individual."""
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    om = OntologyManager(base_uri=NS)
    om.load_from_string(
        """
        @prefix : <http://test.org/ont#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        :Both a owl:Class, owl:NamedIndividual .
        """,
        format="turtle",
    )
    return om


def test_loading_an_ontology_that_puns_is_left_alone():
    """Reading a file is not creating an entity, so it must not be rejected."""
    assert _loaded_with_a_punned_name().entity_kinds("Both") == ["class", "individual"]


def test_a_name_that_arrived_punned_stays_usable_as_what_it_is():
    """The guard stops a *new* type going onto a name. Subclassing the punned
    class, or editing it, adds none, so it must keep working."""
    om = _loaded_with_a_punned_name()
    om.add_class("Sub", parent="Both")
    om.add_class("Both", comment="topped up")
    assert om.entity_kinds("Both") == ["class", "individual"]
    sub = next(c for c in om.get_classes() if c["name"] == "Sub")
    assert sub["parents"] == ["Both"]
    # A third type is still refused.
    with pytest.raises(ValueError, match="already a class"):
        om.add_object_property("Both")


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


def test_a_row_whose_parent_is_an_individual_writes_nothing(populated_om):
    """An undeclared parent is normally backfilled as a bare owl:Class, so a
    parent naming an individual would pun it. The row fails before any of it is
    written: no class, and above all no subClassOf pointing at the individual,
    which would list it as a parent on the Classes page."""
    result = populated_om.bulk_add_classes([{"name": "Robot", "parent": "alice"}])
    assert result["created"] == []
    assert [e["name"] for e in result["errors"]] == ["Robot"]
    assert populated_om.entity_kinds("alice") == ["individual"]
    assert populated_om.entity_kinds("Robot") == []
    assert (populated_om._uri("Robot"), RDFS.subClassOf, None) not in populated_om.graph


def test_an_existing_class_is_not_linked_to_a_parent_of_another_kind(populated_om):
    """The same guard on the other half of bulk_add_classes: the row that adds a
    parent to a class that is already there (issue #157)."""
    result = populated_om.bulk_add_classes([{"name": "Employee", "parent": "acme"}])
    assert result["updated"] == []
    assert [e["name"] for e in result["errors"]] == ["Employee"]
    assert "acme" not in populated_om.get_classes()[0]["parents"]
    assert (
        populated_om._uri("Employee"),
        RDFS.subClassOf,
        populated_om._uri("acme"),
    ) not in populated_om.graph


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

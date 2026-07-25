"""The add forms must validate what the editors validate (issue #152 follow-up).

Written after diffing the two paths: the editors were fixed first, which left the
Add Restriction form picking entities by local name (so a restriction meant for an
imported class landed on a base-namespace twin) and the relation forms carrying
hand-written type lists that had drifted from the engine.
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ontology_manager import OntologyManager


def _restrictions_script():
    # Imports and data live in here: AppTest runs the script in its own
    # namespace, so module-level names are not visible to it.
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    imported_ttl = """
    @prefix : <http://test.org/ont#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix other: <http://other.example/vocab#> .
    :Local a owl:Class .
    other:Foo a owl:Class . other:Bar a owl:Class .
    other:relatedTo a owl:ObjectProperty .
    """

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.load_from_string(imported_ttl, format="turtle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_add_restriction(ont, ont.get_classes(), ont.get_object_properties())


def test_add_restriction_keeps_an_imported_class_and_property():
    """Picking Foo / relatedTo / Bar used to create the restriction on :Foo."""
    at = AppTest.from_function(_restrictions_script)
    at.run(timeout=120)
    assert not at.exception, at.exception

    # The pickers offer the imported entities; select them and submit.
    at.selectbox[0].set_value("Foo")  # Apply to Class
    at.selectbox[1].set_value("relatedTo")  # On Property
    at.selectbox[2].set_value("someValuesFrom")
    at.selectbox[3].set_value("Bar")  # Value (Class)
    at.button[0].click().run(timeout=120)

    assert not at.exception, at.exception
    rows = at.session_state["ontology"].get_restrictions()
    assert len(rows) == 1, rows
    assert rows[0]["applied_to_uris"] == ["http://other.example/vocab#Foo"]
    assert rows[0]["property_uri"] == "http://other.example/vocab#relatedTo"
    assert rows[0]["value_uri"] == "http://other.example/vocab#Bar"


def _relations_script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_object_property("worksFor")
        om.add_object_property("employs")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["rel_active_tab"] = "Property Relations"

    from orionbelt_ontology_builder import app

    app.render_relations()


def test_property_relation_form_offers_every_type_the_engine_has():
    """The hand-written list had drifted: propertyDisjointWith was missing, so a
    relation of that type could be viewed and edited but never created."""
    at = AppTest.from_function(_relations_script)
    at.run(timeout=120)
    assert not at.exception, at.exception

    type_picker = next(s for s in at.selectbox if s.label == "Relation Type")
    assert set(type_picker.options) == set(OntologyManager.PROPERTY_RELATIONS)

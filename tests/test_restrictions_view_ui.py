"""Restrictions View renders duplicate restrictions without a key clash (#148 review).

Two identical restrictions produce two equal dicts from get_restrictions(), so
keying delete buttons by list.index() collided (both del_rest_0). The view keys
by rendered-row position instead; this guards that it renders cleanly.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Car")
        om.add_class("Wheel")
        om.add_object_property("hasPart", domain="Car", range_="Wheel")
        # Two identical restrictions -> two equal dicts from get_restrictions().
        om.add_restriction("Car", "hasPart", "someValuesFrom", "Wheel")
        om.add_restriction("Car", "hasPart", "someValuesFrom", "Wheel")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["rest_active_tab"] = "View Restrictions"

    from orionbelt_ontology_builder import app

    app.render_restrictions()


def test_duplicate_restrictions_render_without_key_clash():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    del_buttons = [b for b in at.button if b.key and b.key.startswith("del_rest_")]
    assert {b.key for b in del_buttons} == {"del_rest_0", "del_rest_1"}

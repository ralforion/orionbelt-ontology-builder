"""Focus mode with nothing focusable still renders (PR #261 review P1).

Focus mode is a persisted setting and the entity-type toggles are another, so
the two can disagree: a session can come back with focus on and Classes,
Individuals and SKOS all off. There is then no node to focus on, the branch that
draws the focus picker does not run, and anything reading its variables below
takes the page down with an UnboundLocalError rather than showing a graph.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle")
        om.add_class("Wheel")
        om.add_object_property("hasPart")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        # What the report described: focus on, nothing it could focus on.
        st.session_state["_viz_cfg_focus_mode"] = True
        for _key in ("show_classes", "show_individuals", "show_skos"):
            st.session_state[f"_viz_cfg_{_key}"] = False

    from orionbelt_ontology_builder import app

    app.render_visualization()


def test_the_page_survives_focus_with_no_focusable_types():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception


def test_it_says_why_there_is_nothing_to_focus_on():
    """Not merely "does not crash": an empty graph with no explanation reads as
    the focus itself being broken."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert any(
        "Enable Classes, Individuals or SKOS" in info.value for info in at.info
    ), [info.value for info in at.info]

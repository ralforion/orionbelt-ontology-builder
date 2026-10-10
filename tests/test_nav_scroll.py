"""A card opened from another page is scrolled into view, once.

Search, a graph click and a quality finding's Open button all open a card
through ``_nav_open_entity``. On a long list that card can open far below the
fold, so the navigation asks for one scroll: the list draws a keyed marker in
that card on the next rerun, and the page shim scrolls to it. Python cannot
see the scroll; these tests hold the parts it can.
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui


def _anchor_script():
    import streamlit as st

    from orionbelt_ontology_builder.ui import scroll_anchor

    for key in ("a", "b"):
        with st.expander(key, expanded=True):
            scroll_anchor("class", key)


def test_the_marker_is_drawn_once_and_only_for_the_requested_card():
    at = AppTest.from_function(_anchor_script)
    at.session_state["_scroll_to_card"] = ("class", "b")
    at.run()
    assert not at.exception
    # Consumed by the card it named...
    assert "_scroll_to_card" not in at.session_state
    # ...so the next rerun draws nothing and leaves the reader where they are.
    at.run()
    assert "_scroll_to_card" not in at.session_state


def test_a_request_for_another_card_is_left_alone():
    at = AppTest.from_function(_anchor_script)
    at.session_state["_scroll_to_card"] = ("class", "elsewhere")
    at.run()
    assert at.session_state["_scroll_to_card"] == ("class", "elsewhere")


def _classes_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.ui import _nav_open_entity, _uid

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        for i in range(60):
            om.add_class(f"C{i:02d}", label=f"C{i:02d}")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        _nav_open_entity("Class", _uid("http://test.org/q#C55"))
    app.render_classes()


def test_navigating_to_a_class_consumes_the_scroll_request_on_its_page():
    at = AppTest.from_function(_classes_page)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert "_scroll_to_card" not in at.session_state
    assert at.session_state["active_class"][0] == ui._uid("http://test.org/q#C55")


def test_the_shim_scrolls_to_the_same_key_python_draws():
    assert f".st-key-{ui.SCROLL_TARGET_KEY}" in ui._HELP_WIRING_JS
    assert "scrollIntoView" in ui._HELP_WIRING_JS

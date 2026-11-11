"""Past a size, Bulk Edit builds its table only for what a filter names (WP3)."""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.views import annotations

    annotations.BULK_EDIT_MAX_RESOURCES = 2
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/b#")
        om.add_class("Bicycle", label="Bicycle")
        om.add_class("Wheel", label="Wheel")
        om.add_class("Saddle", label="Saddle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
    st.session_state["ann_active_tab"] = "Bulk Edit"
    app.render_annotations()


def _rows(at):
    return at.dataframe[0].value


def test_no_rows_until_a_filter_names_some():
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    assert len(_rows(at)) == 0
    assert any("Type part of a name" in info.value for info in at.info)

    at.text_input(key="bulk_annotations_filter").set_value("whe").run(timeout=60)
    rows = _rows(at)
    assert set(rows["Resource"]) == {"Wheel"}

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


def test_a_short_grid_fits_its_rows():
    from orionbelt_ontology_builder.views.annotations import (
        BULK_EDIT_FIT_ROWS,
        _bulk_edit_height,
    )

    assert (
        _bulk_edit_height(0)
        < _bulk_edit_height(3)
        < _bulk_edit_height(BULK_EDIT_FIT_ROWS)
    )


def _long_grid_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.views import annotations

    annotations.BULK_EDIT_FIT_ROWS = 2
    # Set here too: the module outlives each AppTest, and the filter test
    # above lowers it.
    annotations.BULK_EDIT_MAX_RESOURCES = 2_000
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/b#")
        for name in ("Bicycle", "Wheel", "Saddle"):
            om.add_class(name, label=name)
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
    st.session_state["ann_active_tab"] = "Bulk Edit"
    app.render_annotations()


def test_a_long_grid_goes_in_the_box_the_window_sizes():
    """Past BULK_EDIT_FIT_ROWS the grid stretches inside a keyed box, which
    the app's CSS sizes to the window so Apply Changes stays in view."""
    from orionbelt_ontology_builder.ui import _CUSTOM_CSS

    at = AppTest.from_function(_long_grid_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    ids = [block.proto.id for block in at.get("flex_container")]
    assert any(i.endswith("-bulk_edit_grid") for i in ids), ids
    assert ".st-key-bulk_edit_grid" in _CUSTOM_CSS
    assert "100vh" in _CUSTOM_CSS

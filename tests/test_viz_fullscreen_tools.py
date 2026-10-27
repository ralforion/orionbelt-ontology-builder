"""The sidebar's tools on the graph in fullscreen (issue #452).

Fullscreen hides the sidebar, and with it Undo, Redo, the search and the
language pack. The graph draws them in the gap before Render, shown only in
fullscreen; a search result is found on the graph rather than opened on its
page, which would leave fullscreen.
"""

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.views import visualization as viz

NS = "http://example.org/t#"


class _State(dict):
    """Stand-in for ``st.session_state``, which is read and written both ways."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _Undo:
    def __init__(self):
        self.undone = self.redone = 0

    def can_undo(self):
        return True

    def can_redo(self):
        return True

    def undo(self):
        self.undone += 1
        return "Add class"

    def redo(self):
        self.redone += 1
        return "Add class"


def test_the_tools_show_only_in_fullscreen():
    assert (
        ".st-key-viz_fs_tools {\n    display: none !important;" in viz.BAND_SWITCH_CSS
    )
    css = viz.graph_fullscreen_css(False)
    assert f"body.{viz.GRAPH_FS_CLASS} .st-key-viz_fs_tools" in css
    assert "display: flex !important" in css


def test_undo_from_the_graph_says_so_in_a_toast(monkeypatch):
    """The banner is drawn above the switch row, which fullscreen hides."""
    um = _Undo()
    state = _State(undo_manager=um)
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.undo_last_change(toast=True)
    assert um.undone == 1
    assert state["flash_message"] == {
        "message": "Undid: Add class",
        "type": "info",
        "toast": True,
    }
    assert state["_ont_mutation_count"] == 1
    ui.redo_last_change(toast=True)
    assert um.redone == 1
    assert state["flash_message"]["message"] == "Redid: Add class"


def test_a_result_the_graph_draws_is_found_on_it(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.viz_search_picked("Class", NS + "A", "Class: A", False)
    assert state["viz_find_entity"] == "Class: A"
    assert state["_viz_find_seq"] == 1
    assert "search_navigate_to" not in state


def test_a_property_drawn_as_edges_has_them_shown(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.viz_search_picked("Object Property", NS + "p", None, True)
    assert state[ui.VIZ_SHOW_PROPERTY] == NS + "p"
    assert state[ui.VIZ_PROPERTY_SHOW_SEQ] == 1
    assert "search_navigate_to" not in state


def test_a_result_the_graph_cannot_show_opens_its_page(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.viz_search_picked("Individual", NS + "i", None, False)
    assert state["search_navigate_to"] == "Individuals"
    assert state["active_ind"][0] == ui._uid(NS + "i")


def test_the_search_finds_by_the_label_find_uses():
    """A result is matched to Find's option by URI and kind, so a class and
    a concept on the same IRI each go to their own node."""
    assert viz._FIND_KIND_BY_SEARCH_TYPE == {
        "Class": "Class",
        "Individual": "Individual",
        "Data Property": "Data Property",
        "SKOS Concept": "Concept",
    }


def test_opening_the_search_puts_the_cursor_in_its_box():
    """A popover has no autofocus: the script focuses the box once the button
    of this popover opens it, and leaves clicks inside the popover alone."""
    js = viz._SEARCH_FOCUS_JS
    assert ".st-key-viz_fs_tools [data-testid='stPopoverButton']" in js
    assert ".st-key-viz_fs_search input" in js
    assert "window.__orionbeltSearchFocus" in js


def _two_ages_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://example.org/one#")
        om.add_class("Person")
        om.add_data_property("age", domain="Person", range_="integer")
        om.add_data_property(
            "age", range_="integer", namespace="http://example.org/two#"
        )
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_show_data_props"] = True
    app.render_visualization()


def test_two_data_properties_sharing_a_name_are_found_apart():
    """Find keyed a data property by its bare name, so the second ``age``
    took the first one's option: picking either, in Find or from the
    graph's search, went to the same node."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_two_ages_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    at.text_input(key="viz_fs_search").set_value("age").run(timeout=120)
    one, two = "http://example.org/one#age", "http://example.org/two#age"
    picked = {}
    for uri in (one, two):
        at.button(key=f"viz_fs_search_Data Property_{ui._uid(uri)}").click()
        at.run(timeout=120)
        assert not at.exception, at.exception
        picked[uri] = at.session_state["viz_find_entity"]
    assert picked[one] != picked[two], picked
    assert all(label.startswith("Data Property: age") for label in picked.values())

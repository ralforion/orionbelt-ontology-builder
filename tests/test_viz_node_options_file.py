"""Saving and loading the Node options panel as a file (issue #485).

Driven through session state directly, as the panel's own callbacks are: the
file is written from the ``_viz_cfg_`` keys and loaded back into them, and the
page copies those into its widgets on the next render.
"""

import json

import pytest
import streamlit as st

from orionbelt_ontology_builder import ui

A, B, C = (f"http://example.org/ont#{n}" for n in "ABC")
FILTERS = {
    "class": {"uris": [A, B, C], "selected_uris": [A, B]},
    "ind": {"uris": [], "selected_uris": []},
}
TARGETS = {"Class: A": "cls_a", "Class: B": "cls_b", "Class: C": "cls_c"}


class _Upload:
    """What st.file_uploader leaves in session state, as far as it is read."""

    def __init__(self, text, name="node-options.json"):
        self._data = text.encode("utf-8")
        self.name = name

    def getvalue(self):
        return self._data


@pytest.fixture
def session(monkeypatch):
    st.session_state.clear()
    toasts = []
    monkeypatch.setattr(ui.st, "toast", lambda text, **_: toasts.append(text))
    st.session_state["_viz_cfg_selected_class_uris"] = [A, B]
    # What the page records on every render: the entities the filter has an
    # opinion about, which is what an undo restores.
    st.session_state["_viz_cfg_known_class_uris"] = [A, B, C]
    st.session_state["_viz_cfg_focus_mode"] = True
    st.session_state["_viz_cfg_focus_depth"] = 2
    ui.viz_set_focus_seeds(["Class: C"])
    yield toasts
    st.session_state.clear()


def _load(text, ontology_uri="http://example.org/ont"):
    st.session_state[ui.node_options_file_key()] = _Upload(text)
    ui.viz_load_node_options(FILTERS, TARGETS, ontology_uri)


def _saved():
    return ui.node_options_file(FILTERS, TARGETS, "http://example.org/ont")


def test_the_file_holds_both_halves_of_the_panel(session):
    data = json.loads(_saved())
    assert data["format"] == ui.NODE_OPTIONS_FORMAT
    assert data["shown"] == {"class": [A, B], "ind": []}
    assert data["focus"] == {"on": True, "depth": 2, "node_ids": ["cls_c"]}


def test_loading_it_back_restores_what_was_saved(session):
    saved = _saved()
    st.session_state["_viz_cfg_selected_class_uris"] = [C]
    st.session_state["_viz_cfg_focus_mode"] = False
    st.session_state["_viz_cfg_focus_depth"] = 1
    ui.viz_set_focus_seeds([])

    _load(saved)

    assert st.session_state["_viz_cfg_selected_class_uris"] == [A, B]
    assert st.session_state["_viz_cfg_focus_seeds"] == ["Class: C"]
    assert st.session_state["_viz_cfg_focus_mode"] is True
    assert st.session_state["_viz_cfg_focus_depth"] == 2
    assert session == ["Loaded node-options.json."]


def test_a_load_is_one_undo_step(session):
    saved = _saved()
    st.session_state["_viz_cfg_selected_class_uris"] = [C]
    _load(saved)
    ui.viz_node_undo()
    assert st.session_state["_viz_cfg_selected_class_uris"] == [C]


def test_what_this_ontology_lacks_is_left_out_and_counted(session):
    data = json.loads(_saved())
    data["shown"]["class"].append("http://example.org/ont#Gone")
    data["focus"]["node_ids"].append("cls_gone")
    _load(json.dumps(data), ontology_uri="http://example.org/other")
    assert st.session_state["_viz_cfg_selected_class_uris"] == [A, B]
    assert st.session_state["_viz_cfg_focus_seeds"] == ["Class: C"]
    assert "2 saved entities are not in this ontology" in session[-1]
    assert "saved for http://example.org/ont" in session[-1]


def test_focus_stays_off_when_none_of_its_nodes_are_here(session):
    """Focus mode with no seeds backfills an arbitrary node."""
    data = json.loads(_saved())
    data["focus"]["node_ids"] = ["cls_gone"]
    _load(json.dumps(data))
    assert st.session_state["_viz_cfg_focus_mode"] is False


@pytest.mark.parametrize("text", ['{"some": "other file"}', "not json", "[1, 2]"])
def test_another_file_is_refused_and_changes_nothing(session, text):
    _load(text)
    assert st.session_state["_viz_cfg_selected_class_uris"] == [A, B]
    assert st.session_state["_viz_cfg_focus_seeds"] == ["Class: C"]
    assert session[-1].startswith("Could not load node-options.json")


def test_the_uploader_is_emptied_after_a_load(session):
    """A new key, so the same file can be loaded again later."""
    before = ui.node_options_file_key()
    _load(_saved())
    assert ui.node_options_file_key() != before

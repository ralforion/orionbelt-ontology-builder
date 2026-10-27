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


# --- Codex review of PR #534 --------------------------------------------------


def test_undo_puts_the_focus_depth_back(session):
    data = json.loads(_saved())
    data["focus"]["depth"] = 5
    _load(json.dumps(data))
    assert st.session_state["_viz_cfg_focus_depth"] == 5
    ui.viz_node_undo()
    assert st.session_state["_viz_cfg_focus_depth"] == 2


def test_a_load_that_only_changes_the_depth_is_still_an_undo_step(session):
    data = json.loads(_saved())
    data["focus"]["depth"] = 4
    _load(json.dumps(data))
    assert ui.viz_node_undo_available()
    ui.viz_node_undo()
    assert st.session_state["_viz_cfg_focus_depth"] == 2


def test_moving_the_depth_slider_is_an_undo_step_of_its_own(session):
    """With the depth in the snapshot, a move the history did not know about
    would be reverted by the next Undo along with what that Undo is for."""
    st.session_state["viz_focus_depth"] = 3
    ui.viz_focus_depth_changed()
    assert st.session_state["_viz_cfg_focus_depth"] == 3
    ui.viz_node_undo()
    assert st.session_state["_viz_cfg_focus_depth"] == 2


@pytest.mark.parametrize(
    "damage",
    [
        {"shown": {"class": [C], "ind": 42}},
        {"shown": {"class": [C, 7]}},
        {"shown": [C]},
        {"focus": {"node_ids": "cls_a"}},
        {"focus": {"depth": "3"}},
        {"focus": {"depth": True}},
        {"focus": {"on": "yes"}},
        {"focus": 1},
    ],
)
def test_a_damaged_file_is_refused_whole(session, damage):
    """Checked through before anything is applied: a file that set the class
    filter and then broke on the individuals left the panel half loaded."""
    data = json.loads(_saved())
    data.update(damage)
    _load(json.dumps(data))
    assert st.session_state["_viz_cfg_selected_class_uris"] == [A, B]
    assert st.session_state["_viz_cfg_focus_seeds"] == ["Class: C"]
    assert st.session_state["_viz_cfg_focus_depth"] == 2
    assert not ui.viz_node_undo_available()
    assert session[-1].startswith("Could not load node-options.json")


# --- the file's name -----------------------------------------------------------


def _ont(label=None, base="http://example.org/demo#"):
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    ont = OntologyManager(base_uri=base)
    if label is not None:
        ont.set_ontology_metadata(label=label)
    return ont


def test_the_file_is_named_after_the_ontology():
    """Files saved from several ontologies must not all be node-options.json:
    they pile up as copies in Downloads, or overwrite each other on the
    desktop, which saves to a path."""
    assert ui.node_options_file_name(_ont()) == "demo-node-options.json"


def test_the_ontology_s_label_comes_first_and_is_made_safe_for_a_file_name():
    name = ui.node_options_file_name(_ont(label="Wine / Food: v2"))
    assert name == "Wine-Food-v2-node-options.json"


def test_a_nameless_ontology_falls_back_to_the_plain_name():
    assert ui.node_options_file_name(_ont(label="???")) == "node-options.json"


def test_the_tab_title_still_uses_the_same_name(session):
    st.session_state["ontology"] = _ont(label="Wine")
    from orionbelt_ontology_builder import app

    assert app._page_title() == "Wine · OrionBelt"

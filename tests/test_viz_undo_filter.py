"""Undo and redo keep the graph's node filters (issue #401).

The Visualization tells an edit apart from a whole-ontology swap by comparing
two counters: a mutation bump with no matching edit bump means load / import /
new, and the node filters reset to "everything shown" rather than being diffed
against an ontology that may reuse URIs for unrelated entities (issue #180).

The Undo and Redo buttons moved only the mutation counter, so they read as a
swap: undoing a single edit put every hidden class back on the canvas. An undo
restores an earlier snapshot of the *same* ontology, and the undo history is
rebuilt from scratch wherever the ontology is genuinely replaced, so it is an
edit for this purpose and the filter is diffed like any other.
"""

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager, UndoManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Shown")
        om.add_class("Hidden")
        st.session_state.ontology = om
        st.session_state.undo_manager = UndoManager(om)
        st.session_state["_autosave_restored"] = True
        # The cross-session restore mounts the localStorage component, which
        # blocks forever without a browser to answer it.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["nav_radio"] = "Visualization"
        # A filter narrowed on purpose: `known` carries both classes, so the
        # deselected one reads as hidden rather than as never seen.
        uris = [c["uri"] for c in om.get_classes()]
        st.session_state["_viz_cfg_selected_class_uris"] = [
            u for u in uris if u.endswith("Shown")
        ]
        st.session_state["_viz_cfg_known_class_uris"] = set(uris)
    if st.session_state.pop("_test_add_class", False):
        st.session_state.ontology.add_class("Bicycle")
        app.save_checkpoint("Added Bicycle")
    app.main()


def _rerun(at):
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _edited():
    """The page with one undoable edit behind it, filter still narrowed."""
    at = _rerun(AppTest.from_function(_script))
    at.session_state["_test_add_class"] = True
    return _rerun(at)


def _click(at, key):
    at.button(key=key).click()
    return _rerun(at)


def _selected(at):
    return sorted(
        u.rsplit("#", 1)[-1] for u in at.session_state["_viz_cfg_selected_class_uris"]
    )


def _classes(at):
    return sorted(c["name"] for c in at.session_state["ontology"].get_classes())


def test_the_narrowed_filter_survives_an_undo():
    at = _click(_edited(), "btn_undo")
    assert _selected(at) == ["Shown"]


def test_the_undo_still_undoes():
    """The filter is kept by reading the undo as an edit, not by skipping it."""
    at = _click(_edited(), "btn_undo")
    assert _classes(at) == ["Hidden", "Shown"]


def test_the_narrowed_filter_survives_a_redo():
    at = _click(_click(_edited(), "btn_undo"), "btn_redo")
    assert _classes(at) == ["Bicycle", "Hidden", "Shown"]
    # Bicycle was created while the filter was narrowed, so it stays out of it
    # (issue #194) — being redone doesn't let it in either.
    assert _selected(at) == ["Shown"]


@pytest.fixture
def session(monkeypatch):
    """A session_state stand-in: dict access plus the attribute access ui uses."""

    class _State(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:  # pragma: no cover - mirrors Streamlit
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_the_bump_reads_as_an_edit_rather_than_a_swap(session):
    ui.viz_mark_ontology_seen()
    ui.note_undo_redo()
    assert session["_ont_mutation_count"] == 1
    assert not ui.viz_ontology_was_replaced()


def test_a_bare_mutation_bump_still_reads_as_a_swap(session):
    """The other half of the pair: a load / import / new must still reset."""
    ui.viz_mark_ontology_seen()
    session["_ont_mutation_count"] = 1
    assert ui.viz_ontology_was_replaced()

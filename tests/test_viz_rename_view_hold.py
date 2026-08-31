"""A rename must not zoom the graph out (issue #329).

Renaming an entity mints a new URI, and its graph node is keyed by a hash of
that URI — so to the layout cache the entity you renamed went away and a
stranger arrived. The cache then failed its "nothing went away" test (issue
#314) and vis re-framed the whole graph, zooming out of the very class you were
renaming.

The render hands the component where each renamed node went, so the cached
position is carried across to the new id and the camera stays put. The Python
half is tested here; the component half is pinned at the source level, the way
test_viz_camera_hold.py pins the invariant it builds on.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app

NS = "http://test.org/ont#"

_VIEWER = (
    Path(__file__).resolve().parent.parent
    / "orionbelt_ontology_builder"
    / "lib"
    / "graph_viewer"
    / "index.html"
)


@pytest.fixture
def session(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    return state


def _id(name):
    return app.viz_node_id("class", NS + name)


# --- the map the component is given -----------------------------------------


def test_no_renames_is_an_empty_map(session):
    """Every render but the one right after a rename."""
    assert app.viz_rename_map(None) == {}
    assert app.viz_rename_map({}) == {}


def test_a_rename_maps_the_old_node_id_to_the_new_one(session):
    app.viz_note_rename("class", NS + "Person", NS + "Human")

    assert app.viz_rename_map(session["_viz_pending_renames"]) == {
        _id("Person"): _id("Human")
    }


def test_a_chain_of_renames_collapses_to_one_hop(session):
    """The notes are left one rename at a time, but the component applies a
    single hop per id — an intermediate name is not where the node ended up."""
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    app.viz_note_rename("class", NS + "Human", NS + "Being")

    assert app.viz_rename_map(session["_viz_pending_renames"]) == {
        _id("Person"): _id("Being"),
        _id("Human"): _id("Being"),
    }


def test_a_rename_back_to_the_old_name_carries_nothing(session):
    """Renamed and renamed back before the next render: the node is under the
    id it already had, so there is nothing to move. An id mapped to itself would
    tell the component the node set changed when it did not."""
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    app.viz_note_rename("class", NS + "Human", NS + "Person")

    assert app.viz_rename_map(session["_viz_pending_renames"]) == {}


def test_the_map_is_in_node_ids_not_uris(session):
    """Individuals and properties carry a prefix; the component matches against
    the ids the graph actually uses."""
    app.viz_note_rename("individual", NS + "alice", NS + "alicia")

    assert app.viz_rename_map(session["_viz_pending_renames"]) == {
        app.viz_node_id("individual", NS + "alice"): app.viz_node_id(
            "individual", NS + "alicia"
        )
    }


# --- the render actually hands it over ---------------------------------------


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app as _app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Person")
        om.add_class("Organization")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
    if st.session_state.pop("_test_rename", False):
        om = st.session_state.ontology
        old_uri = next(c["uri"] for c in om.get_classes() if c["name"] == "Person")
        om.rename_class(old_uri, "Human")
        new_uri = next(c["uri"] for c in om.get_classes() if c["name"] == "Human")
        _app.viz_note_rename("class", old_uri, new_uri)
        st.session_state["_test_renamed"] = (old_uri, new_uri)
    _app.render_visualization()


@pytest.fixture
def graph_args(monkeypatch):
    """Capture the kwargs the page hands the graph component."""
    seen: list[dict] = []

    def _declare(name, path=None, **kwargs):
        def _component(**call_kwargs):
            seen.append(call_kwargs)

        return _component

    monkeypatch.setattr("streamlit.components.v1.declare_component", _declare)
    return seen


def _run(at):
    """Run the page again."""
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def test_an_ordinary_render_carries_no_renames(graph_args):
    at = AppTest.from_function(_script, default_timeout=300).run(timeout=300)
    assert not at.exception, at.exception

    assert graph_args, "the graph component was never rendered"
    assert graph_args[-1]["renames"] == "{}"


def test_the_render_after_a_rename_carries_where_the_node_went(graph_args):
    import json

    at = AppTest.from_function(_script, default_timeout=300).run(timeout=300)
    assert not at.exception, at.exception
    at.session_state["_test_rename"] = True
    _run(at)

    old_uri, new_uri = at.session_state["_test_renamed"]
    assert json.loads(graph_args[-1]["renames"]) == {
        app.viz_node_id("class", old_uri): app.viz_node_id("class", new_uri)
    }


# --- the component half ------------------------------------------------------


def _viewer() -> str:
    return _VIEWER.read_text(encoding="utf-8")


def test_the_viewer_carries_a_renamed_node_position_to_its_new_id():
    """Without the carry the renamed node is placed afresh by physics, and the
    cached layout is one node short of the graph it is restoring."""
    src = _viewer()
    start = src.index("var _renames = {};")
    block = src[start : src.index("var usedSaved = false;", start)]
    assert "JSON.parse(args.renames" in block, "the viewer ignores the rename map"
    assert "_raw.pos[newId] = _raw.pos[oldId]" in block, (
        "the cached position is not moved to the id the node now has"
    )
    assert "delete _raw.pos[oldId]" in block, (
        "the old id is left behind, so the cache no longer matches the graph"
    )
    assert "sessionStorage.setItem('viz_pos'" in block, (
        "the rewritten cache is not persisted, so a re-mount reads the old ids"
    )


def test_a_rename_render_holds_the_camera():
    """Anything else keyed off the old URI — the entity's annotation nodes —
    also comes back under a new id, so the "nothing went away" test fails even
    with the position carried. A rename is still the same graph, so hold."""
    src = _viewer()
    start = src.index("// Same render generation but a changed node set")
    branch = src[start : src.index("var nodes = new vis.DataSet", start)]
    assert "_hold = !!savedView && (_keptAll || _carried)" in branch, (
        "a rename render still lets vis re-frame the whole graph"
    )

"""The graph's node cap, and what it does to focus mode (issue #216).

The cap keeps vis-network from being handed more nodes than it can draw. It used
to be applied while *assembling* the graph, which broke focus mode: focus builds
everything and prunes to the seeds' neighbourhood afterwards, so a class past the
cap never got a node, the seed was not found, and the graph came out empty — with
nothing said about why. Classes are built in alphabetical order, so which ones
this hit was a matter of their name.

These run the real ``render_visualization`` through ``AppTest`` and inspect the
graph payload it caches, seeded through the environment because
``AppTest.from_function`` executes the script source in a fresh namespace without
the test's closures.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        if os.environ["SHAPE"] == "chain":
            # A subclass chain: every class has exactly one link either way, so
            # a focus at depth 1 keeps a known handful.
            for i in range(int(os.environ["N_CLASSES"])):
                om.add_class(f"C{i:04d}", parent=f"C{i - 1:04d}" if i else None)
        else:
            # A star: one hub every other class is a subclass of, so a depth-1
            # focus on the hub asks for more than the graph can draw.
            om.add_class("Hub")
            for i in range(int(os.environ["N_CLASSES"])):
                om.add_class(f"C{i:04d}", parent="Hub")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_focus_mode"] = os.environ["SEED"] != ""
        if os.environ["SEED"] == "*":
            # What the multiselect defaults to: every selected class a seed.
            st.session_state["_viz_cfg_focus_seeds"] = [
                f"Class: {c['name']}" for c in om.get_classes()
            ]
        elif os.environ["SEED"]:
            st.session_state["_viz_cfg_focus_seeds"] = [os.environ["SEED"]]
        st.session_state["_viz_cfg_focus_depth"] = int(os.environ["DEPTH"])
        if os.environ.get("FIND"):
            # What picking an entity in "Find and centre" leaves behind.
            st.session_state["viz_find_entity"] = os.environ["FIND"]

    app.render_visualization()


def _graph(n_classes, seed="", shape="chain", depth=1, find=""):
    """Render once and return ``(nodes, edges, notice)``. An empty seed means
    focus mode off; ``find`` is an entity picked in "Find and centre"."""
    os.environ["N_CLASSES"] = str(n_classes)
    os.environ["SEED"] = seed
    os.environ["SHAPE"] = shape
    os.environ["DEPTH"] = str(depth)
    os.environ["FIND"] = find
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    assert data, "the visualization built no graph"
    return (
        json.loads(data["nodes"]),
        json.loads(data["edges"]),
        data.get("notice") or "",
    )


# --- the bug ----------------------------------------------------------------


def test_a_class_past_the_render_cap_can_still_be_focused_on():
    """The regression: C0519 is the 520th class, so the cap cut it out of the
    build and focusing on it drew nothing at all."""
    over = app.GRAPH_MAX_NODES + 20
    nodes, edges, notice = _graph(over, seed=f"Class: C{over - 1:04d}")

    labels = {n.get("label") for n in nodes}
    assert f"C{over - 1:04d}" in labels, "the seed itself is missing"
    # Depth 1 over a subclass chain: the seed and its one parent.
    assert labels == {f"C{over - 1:04d}", f"C{over - 2:04d}"}
    assert len(edges) == 1
    assert notice == ""


def test_focusing_still_works_for_a_class_below_the_cap():
    nodes, _, notice = _graph(app.GRAPH_MAX_NODES + 20, seed="Class: C0002")
    assert {n.get("label") for n in nodes} == {"C0001", "C0002", "C0003"}
    assert notice == ""


# --- the cap still holds where it protects the browser ----------------------


def test_without_focus_the_graph_stops_at_the_render_cap():
    nodes, _, notice = _graph(app.GRAPH_MAX_NODES + 20)
    assert len(nodes) == app.GRAPH_MAX_NODES
    # Silence here is what made the missing classes a mystery to debug.
    assert f"20 of {app.GRAPH_MAX_NODES + 20} classes are not drawn" in notice


def test_a_neighbourhood_larger_than_the_cap_is_cut_and_said_so(monkeypatch):
    """Focus assembles more than it draws, so the prune has to hold the line."""
    monkeypatch.setattr(app, "GRAPH_MAX_NODES", 10)
    nodes, edges, notice = _graph(40, seed="Class: Hub", shape="star")

    assert len(nodes) == 10
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)
    assert "more than the 10 nodes the graph can draw" in notice


def test_more_seeds_than_the_cap_are_cut_before_any_hop(monkeypatch):
    """The seeds alone can overflow the cap — they default to every selected
    class — so the budget has to bind before the first ring, not after it."""
    monkeypatch.setattr(app, "GRAPH_MAX_NODES", 10)
    nodes, edges, notice = _graph(40, seed="*")

    assert len(nodes) == 10
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)
    assert "more than the 10 nodes the graph can draw" in notice


def test_a_seed_past_the_assembly_cap_says_why_the_graph_is_empty(monkeypatch):
    """The assembly cap is far above the render one, but it is still a cap; when
    a seed falls past it the empty graph has to explain itself."""
    monkeypatch.setattr(app, "FOCUS_BUILD_MAX_NODES", 5)
    nodes, edges, notice = _graph(20, seed="Class: C0019")

    assert nodes == [] and edges == []
    assert "Nothing to focus on" in notice
    assert "Filter Nodes" in notice


def test_the_assembly_cap_is_only_raised_for_focus():
    """A plain render must keep handing vis-network at most GRAPH_MAX_NODES."""
    assert app.FOCUS_BUILD_MAX_NODES > app.GRAPH_MAX_NODES
    nodes, _, _ = _graph(app.GRAPH_MAX_NODES + 200)
    assert len(nodes) == app.GRAPH_MAX_NODES


def test_the_assembly_allowance_needs_the_prune_not_just_the_mode():
    """Clearing the focus multiselect leaves the mode on with no seed, so nothing
    prunes on that render. Raising the cap for the mode alone handed the browser
    every node in the ontology — caught in the running app, since driving the
    multiselect takes a second AppTest run and this page's segmented control
    cannot be re-serialized."""
    assert app.graph_node_cap(True) == app.FOCUS_BUILD_MAX_NODES
    assert app.graph_node_cap(False) == app.GRAPH_MAX_NODES


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_focus_depth_grows_the_neighbourhood_from_a_far_class(depth):
    over = app.GRAPH_MAX_NODES + 20
    nodes, _, _ = _graph(over, seed=f"Class: C{over - 1:04d}", depth=depth)
    # The chain ends at the seed, so each hop adds exactly one class.
    assert len(nodes) == depth + 1


# --- Find and centre past the cap (issue #234) ------------------------------


def test_a_class_past_the_cap_is_drawn_when_it_is_the_find_target():
    """The reported bug. The dropdown lists every class regardless of what was
    drawn, so picking one past the cap left the viewer nothing to centre on: it
    dropped the camera pin, which re-enables the post-layout auto-fit, so the
    graph visibly reframed while the picked class was absent."""
    over = app.GRAPH_MAX_NODES + 20
    target = f"C{over - 1:04d}"
    nodes, _, _ = _graph(over, find=f"Class: {target}")
    assert target in {n.get("label") for n in nodes}


def test_the_cap_still_holds_with_a_find_target():
    """The picked class is not an extra node on top of the budget, it simply is
    not the one dropped."""
    over = app.GRAPH_MAX_NODES + 20
    nodes, _, _ = _graph(over, find=f"Class: C{over - 1:04d}")
    assert len(nodes) <= app.GRAPH_MAX_NODES


def test_a_class_below_the_cap_is_unaffected_by_being_the_find_target():
    over = app.GRAPH_MAX_NODES + 20
    nodes, _, _ = _graph(over, find="Class: C0002")
    assert "C0002" in {n.get("label") for n in nodes}


def test_without_a_find_target_the_class_past_the_cap_is_still_dropped():
    """The cap is unchanged; only the entity the user named is protected."""
    over = app.GRAPH_MAX_NODES + 20
    nodes, _, _ = _graph(over)
    assert f"C{over - 1:04d}" not in {n.get("label") for n in nodes}

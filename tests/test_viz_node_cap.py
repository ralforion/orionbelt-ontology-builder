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
import sources
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
        # One entity of another kind, to check that a Find target which is not
        # a class is reachable too. Those loops run after classes, so the budget
        # is already spent by the time they start (issue #234 review).
        # One entity of another kind, to check that a Find target which is not
        # a class is reachable too. Those loops run after classes, so the budget
        # is already spent by the time they start (issue #234 review).
        #
        # Data properties and individuals are off by default, and Find only lists
        # the types that are shown, so the toggle has to be on for the entity to
        # be findable at all.
        extra = os.environ.get("EXTRA", "")
        if extra == "dprop":
            om.add_data_property("findMe")
            st.session_state["_viz_cfg_show_data_props"] = True
        elif extra == "dprop_capped_domain":
            # Its domain is a class the cap drops, so the "domain isn't
            # displayed" guard skips the property even when it is the target.
            om.add_data_property(
                "findMe", domain=f"C{int(os.environ['N_CLASSES']) - 1:04d}"
            )
            st.session_state["_viz_cfg_show_data_props"] = True
        elif extra == "ind":
            om.add_individual("findMe", "C0000")
            st.session_state["_viz_cfg_show_individuals"] = True
        elif extra == "skos":
            om.add_concept("findMe")
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
        if os.environ.get("HIDE"):
            # A narrowed node filter that does *not* include the Find target,
            # and a find-seq already marked as revealed: the state left behind
            # when an entity was visible at the moment it was picked and a later
            # filter change hid it (issue #234).
            keep = set(os.environ["HIDE"].split())
            st.session_state["_viz_cfg_selected_class_uris"] = [
                c["uri"] for c in om.get_classes() if c["name"] in keep
            ]
            st.session_state["_viz_cfg_known_class_uris"] = {
                c["uri"] for c in om.get_classes()
            }
            st.session_state["_viz_find_seq"] = 1
            st.session_state["_viz_find_revealed_seq"] = 1
        if os.environ.get("HIDE_ALL"):
            # The filter emptied completely, with the reveal already marked done.
            st.session_state["_viz_cfg_selected_class_uris"] = []
            st.session_state["_viz_cfg_known_class_uris"] = {
                c["uri"] for c in om.get_classes()
            }
            st.session_state["_viz_find_seq"] = 1
            st.session_state["_viz_find_revealed_seq"] = 1

    app.render_visualization()


def _graph(
    n_classes,
    seed="",
    shape="chain",
    depth=1,
    find="",
    extra="",
    hide="",
    hide_all=False,
):
    """Render once and return ``(nodes, edges, notice)``. An empty seed means
    focus mode off; ``find`` is an entity picked in "Find and centre"."""
    os.environ["N_CLASSES"] = str(n_classes)
    os.environ["SEED"] = seed
    os.environ["SHAPE"] = shape
    os.environ["DEPTH"] = str(depth)
    os.environ["FIND"] = find
    os.environ["EXTRA"] = extra
    os.environ["HIDE"] = hide
    os.environ["HIDE_ALL"] = "1" if hide_all else ""
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


def test_a_neighbourhood_larger_than_the_cap_is_cut_and_said_so(monkeypatch, patch_ui):
    """Focus assembles more than it draws, so the prune has to hold the line."""
    patch_ui("GRAPH_MAX_NODES", 10)
    nodes, edges, notice = _graph(40, seed="Class: Hub", shape="star")

    assert len(nodes) == 10
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)
    assert "more than the 10 nodes the graph can draw" in notice


def test_more_seeds_than_the_cap_are_cut_before_any_hop(monkeypatch, patch_ui):
    """The seeds alone can overflow the cap — they default to every selected
    class — so the budget has to bind before the first ring, not after it."""
    patch_ui("GRAPH_MAX_NODES", 10)
    nodes, edges, notice = _graph(40, seed="*")

    assert len(nodes) == 10
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)
    assert "more than the 10 nodes the graph can draw" in notice


def test_a_seed_past_the_assembly_cap_says_why_the_graph_is_empty(
    monkeypatch, patch_ui
):
    """The assembly cap is far above the render one, but it is still a cap; when
    a seed falls past it the empty graph has to explain itself."""
    patch_ui("FOCUS_BUILD_MAX_NODES", 5)
    nodes, edges, notice = _graph(20, seed="Class: C0019")

    assert nodes == [] and edges == []
    assert "Nothing to focus on" in notice
    assert "Node options" in notice


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


@pytest.mark.parametrize(
    ("extra", "find"),
    [
        ("dprop", "Data Property: findMe"),
        ("ind", "Individual: findMe"),
        ("skos", "Concept: findMe"),
    ],
)
def test_a_non_class_find_target_is_drawn_after_classes_fill_the_budget(extra, find):
    """Classes are built first, so by the time these loops run the budget is
    already spent. Letting their block run is not enough on its own: the loop
    still has to get past its own cap check to add the prioritised entity."""
    nodes, _, _ = _graph(app.GRAPH_MAX_NODES + 20, find=find, extra=extra)
    assert "findMe" in {n.get("label") for n in nodes}


@pytest.mark.parametrize(
    ("extra", "find"),
    [
        ("dprop", "Data Property: findMe"),
        ("ind", "Individual: findMe"),
        ("skos", "Concept: findMe"),
    ],
)
def test_a_non_class_find_target_costs_at_most_one_node_over_the_cap(extra, find):
    """Classes are built first and fill the budget, so a target of a later kind
    cannot be swapped for one of them: it is added past the cap instead. One
    extra node is immaterial to the browser, which is what the cap protects; a
    graph silently missing what you asked for is not."""
    nodes, _, _ = _graph(app.GRAPH_MAX_NODES + 20, find=find, extra=extra)
    assert len(nodes) <= app.GRAPH_MAX_NODES + 1


def test_the_find_target_is_part_of_the_graph_cache_key():
    """Otherwise the fix above never runs on the path a user actually takes.

    The page builds and caches a graph on arrival, with no target. Picking one
    changes which nodes *would* be built, so unless the key sees it there is no
    rebuild and the cached payload still lacks the entity that was asked for.

    Pinned at the source rather than by driving it, because AppTest cannot run
    this page twice: serialising the widget states between runs breaks on the
    filter multiselects, the same limitation that keeps the rest of this file to
    a single render per assertion.
    """
    src = sources.viz_text()
    key_line = next(
        line for line in src.splitlines() if line.strip().startswith("graph_key = f")
    )
    assert "_find_id" in key_line, (
        "the Find target decides which nodes are built, so it must be part of "
        "the cache key or picking one will not trigger a rebuild"
    )


def test_a_data_property_find_target_is_drawn_even_if_its_domain_was_capped_out():
    """A data property is normally skipped when its domain class isn't drawn,
    which is right for the general case and wrong for the one entity the user
    asked to see: its domain is exactly the kind of class the cap drops."""
    over = app.GRAPH_MAX_NODES + 20
    nodes, _, _ = _graph(
        over, find="Data Property: findMe", extra="dprop_capped_domain"
    )
    assert "findMe" in {n.get("label") for n in nodes}


def test_a_find_target_hidden_by_a_later_filter_change_is_still_drawn():
    """The state the reporter was in: the entity was visible when they picked
    it, so nothing needed revealing and the find-seq was marked done; a later
    filter change then hid it. The pick had not changed, so the once-per-pick
    reveal never ran again and the graph never got the node, while the app went
    on telling the viewer to centre on it (issue #234)."""
    keep = "C0001 C0002 C0003"
    nodes, _, _ = _graph(40, find="Class: C0007", hide=keep)
    labels = {n.get("label") for n in nodes}
    assert "C0007" in labels, "the entity asked for is missing from the graph"


def test_the_node_filter_still_hides_everything_else():
    """Only the entity you asked for is exempt; the filter is otherwise honoured."""
    keep = "C0001 C0002 C0003"
    nodes, _, _ = _graph(40, find="Class: C0007", hide=keep)
    labels = {n.get("label") for n in nodes}
    assert labels == {"C0001", "C0002", "C0003", "C0007"}


def test_a_find_target_survives_an_emptied_class_filter():
    """Clearing the filter entirely skips the class loop before the per-node
    bypass can run, so the entity asked for disappeared with everything else."""
    nodes, _, _ = _graph(40, find="Class: C0007", hide_all=True)
    assert {n.get("label") for n in nodes} == {"C0007"}


def test_find_does_not_rewrite_the_users_node_filter():
    """Picking an entity used to un-hide it by editing the filter, which both
    changed a setting the user had chosen and went stale as soon as a later
    filter change hid it again. The graph exempts it at build time instead, so
    the filter is left exactly as it was found."""
    import ast

    src = sources.viz_text()
    tree = ast.parse(src)
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "_viz_find_revealed_seq" in ast.dump(node.test)
    ]
    assert handlers, "the Find reveal handler was not found"
    for handler in handlers:
        for node in ast.walk(handler):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                dumped = ast.dump(target)
                assert not ("_viz_cfg_selected_" in dumped and "_uris" in dumped), (
                    f"line {node.lineno}: Find must not write the node filter; "
                    "the graph exempts the target at build time instead"
                )

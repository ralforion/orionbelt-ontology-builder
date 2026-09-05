"""Annotations in focus mode (issue #272).

An annotation node hangs off the one entity it annotates and leads nowhere else,
but the focus prune counted it as a hop like any other node: a depth-1 focus drew
its neighbours stripped of their annotations while the Annotations toggle was on,
and the only way to bring them back — a deeper focus — pulled in a ring of
unrelated entities as well.

Same harness as ``test_viz_node_cap``: the real ``render_visualization`` through
AppTest, inspecting the graph payload it caches, seeded through the environment
because ``AppTest.from_function`` runs the script source in a fresh namespace.
"""

import json
import os
import re

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        # A subclass chain A -> B -> C, one custom annotation each, so a depth-1
        # focus on A covers A and B (and their annotations) but not C.
        om = OntologyManager()
        om.add_class("A")
        om.add_class("B", parent="A")
        om.add_class("C", parent="B")
        for name in ("A", "B", "C"):
            if os.environ.get("ANNOTATION_KIND") == "label_comment":
                # The two the graph deliberately does not draw.
                om.add_annotation(name, "rdfs:comment", f"about {name}")
            else:
                om.add_annotation(name, "wikidataId", f"Q-{name}")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_show_annotations"] = os.environ["ANNOTATIONS"] == "1"
        st.session_state["_viz_cfg_focus_mode"] = os.environ["SEED"] != ""
        if os.environ["SEED"]:
            st.session_state["_viz_cfg_focus_seeds"] = [os.environ["SEED"]]
        st.session_state["_viz_cfg_focus_depth"] = int(os.environ["DEPTH"])

    app.render_visualization()


def _render(seed="Class: A", depth=1, annotations=True, annotation_kind="custom"):
    """Render once and return the app.

    Every knob is written on every call, none defaulted from what is already in
    the environment: these are process-wide, so a test that set one and a test
    that did not would pass or fail by the order pytest happened to run them in
    (Codex review of PR #407).
    """
    os.environ["SEED"] = seed
    os.environ["DEPTH"] = str(depth)
    os.environ["ANNOTATIONS"] = "1" if annotations else "0"
    os.environ["ANNOTATION_KIND"] = annotation_kind
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _graph(seed="Class: A", depth=1, annotations=True, annotation_kind="custom"):
    """Render once and return ``(nodes, edges)``. An empty seed means focus off."""
    at = _render(seed, depth, annotations, annotation_kind)
    data = at.session_state["last_graph_data"]
    assert data, "the visualization built no graph"
    return json.loads(data["nodes"]), json.loads(data["edges"])


def _notice(at):
    return at.session_state["last_graph_data"].get("notice") or ""


def _annotation_labels(nodes):
    return {n.get("label") for n in nodes if n.get("ntype") == "Annotation"}


def _class_labels(nodes):
    return {n.get("label") for n in nodes if n.get("ntype") != "Annotation"}


# --- the bug ----------------------------------------------------------------


def test_a_neighbour_keeps_its_annotations():
    """The regression: at depth 1 only the seed's own annotation survived, since
    a neighbour's annotation sits one hop further out."""
    nodes, _ = _graph(seed="Class: A", depth=1)
    assert _class_labels(nodes) == {"A", "B"}
    assert _annotation_labels(nodes) == {"Q-A", "Q-B"}


def test_a_riding_annotation_keeps_its_edge():
    """A node whose edge was dropped is an orphan box floating in the graph."""
    nodes, edges = _graph(seed="Class: A", depth=1)
    ann_ids = {n["id"] for n in nodes if n.get("ntype") == "Annotation"}
    assert ann_ids
    linked = {e["to"] for e in edges if e["to"] in ann_ids}
    assert linked == ann_ids


def test_annotations_do_not_widen_the_neighbourhood():
    """They ride along; they do not buy a hop for the entity they hang off."""
    nodes, _ = _graph(seed="Class: A", depth=1)
    assert "C" not in _class_labels(nodes)


def test_a_deeper_focus_still_reaches_further_classes():
    nodes, _ = _graph(seed="Class: A", depth=2)
    assert _class_labels(nodes) == {"A", "B", "C"}
    assert _annotation_labels(nodes) == {"Q-A", "Q-B", "Q-C"}


# --- the toggle still decides ----------------------------------------------


def test_the_annotations_toggle_still_turns_them_off_under_focus():
    nodes, _ = _graph(seed="Class: A", depth=1, annotations=False)
    assert _annotation_labels(nodes) == set()
    assert _class_labels(nodes) == {"A", "B"}


def test_without_focus_annotations_are_unchanged():
    nodes, _ = _graph(seed="", annotations=True)
    assert _class_labels(nodes) == {"A", "B", "C"}
    assert _annotation_labels(nodes) == {"Q-A", "Q-B", "Q-C"}


# --- the render cap still binds ---------------------------------------------


def test_riding_annotations_stay_inside_the_render_cap(patch_ui):
    """They are hung back on after the hops are counted, so they have to respect
    the cap the prune exists to hold."""
    patch_ui("GRAPH_MAX_NODES", 3)
    nodes, edges = _graph(seed="Class: A", depth=2)

    assert len(nodes) <= 3
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)


def test_annotations_are_dropped_before_the_focus_itself(patch_ui):
    """The classes asked for come first; the annotations fill what is left."""
    patch_ui("GRAPH_MAX_NODES", 4)
    nodes, _ = _graph(seed="Class: A", depth=2)

    assert _class_labels(nodes) == {"A", "B", "C"}
    assert len(_annotation_labels(nodes)) == 1


def test_the_app_says_when_annotations_were_cut(patch_ui):
    patch_ui("GRAPH_MAX_NODES", 3)
    notice = _notice(_render(seed="Class: A", depth=2))
    assert "annotations" in notice.lower(), notice


def test_the_app_says_so_when_the_focus_itself_left_no_room(patch_ui):
    """The gap the guard left (issue #405).

    A focus too big to draw in full already sets a notice, and the annotation
    shortfall was only reported when nothing else had spoken — so a focus that
    overflowed on its nodes alone drew not one annotation with Annotations
    ticked, and said only that it was full. Both facts are now in the notice.
    """
    patch_ui("GRAPH_MAX_NODES", 2)
    at = _render(seed="Class: A", depth=2)
    nodes = json.loads(at.session_state["last_graph_data"]["nodes"])

    assert _annotation_labels(nodes) == set(), "no room was left for any of them"
    notice = _notice(at)
    assert "annotation" in notice.lower(), notice
    assert "covers more than" in notice, notice


def test_a_label_or_comment_is_not_drawn_as_a_node():
    """What issue #405 turned out to be.

    An entity whose only annotations are its label and comment draws none of
    them: those two are in the node's tooltip instead. Nothing is wrong with
    that, but it is the whole of "sometimes annotations are not shown", so it is
    pinned here as a rule rather than left as an accident of the loop.
    """
    nodes, _ = _graph(seed="Class: A", depth=1, annotation_kind="label_comment")

    assert _class_labels(nodes) == {"A", "B"}
    assert _annotation_labels(nodes) == set()


def test_annotations_survive_an_assembly_that_ran_out_of_room(patch_ui):
    """The focus build is allowed past the render cap because the prune brings it
    back down, so the annotations cannot be built with the rest of the graph: the
    budget is spent on entities the focus then throws away, and the ones the
    focus keeps are never reached. They are built after the prune instead, from
    what it kept (issue #272 review)."""
    patch_ui("FOCUS_BUILD_MAX_NODES", 4)
    nodes, edges = _graph(seed="Class: C", depth=1)

    # The assembly stops at 4 entity nodes, well before any annotation would
    # have been added under the old order.
    assert "C" in _class_labels(nodes)
    assert "Q-C" in _annotation_labels(nodes)
    kept = {n["id"] for n in nodes}
    assert all(e["from"] in kept and e["to"] in kept for e in edges)


def test_annotations_do_not_eat_the_focus_assembly_budget(patch_ui):
    """The entity the assembly cap can just reach is still reachable with
    Annotations on: they are no longer competing for that budget."""
    patch_ui("FOCUS_BUILD_MAX_NODES", 3)
    with_anns, _ = _graph(seed="Class: C", depth=1, annotations=True)
    without, _ = _graph(seed="Class: C", depth=1, annotations=False)

    assert _class_labels(with_anns) == _class_labels(without)


def test_the_graph_cache_version_moved_with_the_pruning():
    """A session holding a payload built under the old prune would keep serving
    a focus without its annotations until something unrelated evicted it.

    A floor rather than an exact version: anything from 20 up evicts a payload
    built before the pruning changed, which is the whole guarantee. Pinning the
    number instead made every later bump — each of which also evicts it — look
    like a regression.
    """
    source = (app.PKG_DIR / "views" / "visualization.py").read_text("utf-8")
    match = re.search(r"^\s*_graph_ver = (\d+)$", source, re.MULTILINE)
    assert match, "the graph cache version is no longer a plain assignment"
    assert int(match.group(1)) >= 20

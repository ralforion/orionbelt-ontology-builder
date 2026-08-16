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


def _graph(seed="Class: A", depth=1, annotations=True):
    """Render once and return ``(nodes, edges)``. An empty seed means focus off."""
    os.environ["SEED"] = seed
    os.environ["DEPTH"] = str(depth)
    os.environ["ANNOTATIONS"] = "1" if annotations else "0"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    assert data, "the visualization built no graph"
    return json.loads(data["nodes"]), json.loads(data["edges"])


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
    os.environ["SEED"] = "Class: A"
    os.environ["DEPTH"] = "2"
    os.environ["ANNOTATIONS"] = "1"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    notice = at.session_state["last_graph_data"].get("notice") or ""
    assert "annotations" in notice.lower(), notice


def test_the_graph_cache_version_moved_with_the_pruning():
    """A session holding a payload built under the old prune would keep serving
    a focus without its annotations until something unrelated evicted it."""
    source = (app.PKG_DIR / "views" / "visualization.py").read_text("utf-8")
    assert "_graph_ver = 20" in source

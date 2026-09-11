"""Curved or straight edges, and who decides (issue #425).

The curve on an edge that is the only link between its two nodes is decoration,
and it is redrawn on every frame. Measured against a vendored vis-network under
a 6x CPU throttle, holding the graph at 200 nodes and varying the edges, the
curve added 1.0ms per redraw at 100 edges, 1.7ms at 200, 4.7ms at 400 and 7.4ms
at 800; holding the edges at 300 and varying the nodes from 100 to 800, it
stayed between 1.6 and 3.9ms with no trend. The cost is in the edges, so the
threshold counts those. On the ontology in the report, 543 of the 549 edges
drawn were single links paying for it.

So the default is ``auto``: curved while it is nearly free, straight once the
graph is large enough for it not to be. The reporter asked to be able to say
otherwise, and ``curved``/``straight`` are obeyed at any size.

Parallel edges keep their curves throughout. That is what tells them apart
(issue #245), and it is set per edge, which vis honours over the global default.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app, ui

# --- the rule ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "curved"),
    [
        (1, True),
        (ui.CURVED_EDGE_MAX_EDGES - 1, True),
        (ui.CURVED_EDGE_MAX_EDGES, True),
        (ui.CURVED_EDGE_MAX_EDGES + 1, False),
        (5000, False),
    ],
)
def test_auto_follows_the_edge_count(count, curved):
    assert ui.edges_are_curved("auto", count) is curved


def test_the_user_is_obeyed_at_any_size():
    """Both ways round: the setting is the answer, not a hint."""
    assert ui.edges_are_curved("curved", 5000) is True
    assert ui.edges_are_curved("straight", 1) is False


def test_a_value_from_nowhere_reads_as_auto():
    """config.json is a file on disk, and anything could have written it."""
    assert ui.edges_are_curved("", 10) is True
    assert ui.edges_are_curved("Curved", 5000) is False


def test_the_setting_is_persisted_and_validated():
    assert "edge_curves" in app._VIZ_PERSIST_KEYS
    assert ui._VIZ_CHOICES["edge_curves"] == ("auto", "curved", "straight")


# --- and in the graph the page builds ----------------------------------------


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for i in range(int(os.environ["N_CLASSES"])):
            om.add_class(f"C{i:04d}", parent=f"C{i - 1:04d}" if i else None)
        if os.environ.get("PARALLEL"):
            # Two more links between the same pair, so the fan-out has something
            # to fan: a relation each way plus the subClassOf already there.
            om.add_object_property("knows", domain="C0000", range_="C0001")
            om.add_object_property("owns", domain="C0001", range_="C0000")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_edge_curves"] = os.environ["CURVES"]
    app.main() if False else app.render_visualization()


def _graph(n_classes, curves="auto", parallel=False):
    os.environ["N_CLASSES"] = str(n_classes)
    os.environ["CURVES"] = curves
    os.environ["PARALLEL"] = "1" if parallel else ""
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    return json.loads(data["options"]), json.loads(data["edges"])


def test_a_small_graph_keeps_its_curves():
    options, _ = _graph(12)
    assert options["edges"]["smooth"]["type"] == "curvedCW"


def test_a_large_graph_drops_them():
    """A chain of N classes draws N-1 edges, so this clears the threshold."""
    options, edges = _graph(ui.CURVED_EDGE_MAX_EDGES + 40)
    assert len(edges) > ui.CURVED_EDGE_MAX_EDGES
    assert options["edges"]["smooth"] is False


def test_the_setting_overrides_the_size_in_both_directions():
    options, _ = _graph(ui.CURVED_EDGE_MAX_EDGES + 40, curves="curved")
    assert options["edges"]["smooth"]["type"] == "curvedCW"

    options, _ = _graph(12, curves="straight")
    assert options["edges"]["smooth"] is False


def test_parallel_edges_keep_their_own_curves_on_a_straight_graph():
    """The fan-out is per edge, and vis honours that over the global default."""
    options, edges = _graph(12, curves="straight", parallel=True)

    assert options["edges"]["smooth"] is False
    fanned = [e for e in edges if isinstance(e.get("smooth"), dict)]
    assert len(fanned) >= 2, "the parallel pair lost its fan-out"
    assert {e["smooth"]["type"] for e in fanned} <= {"curvedCW", "curvedCCW"}
    assert all(e["smooth"]["enabled"] for e in fanned)


def test_the_viewer_applies_a_curve_change_without_rebuilding():
    """Same nodes, same edges, different options: the one case the viewer's
    same-data guard does not catch on its own.

    That guard exists so a selection click does not reset the viewport, and it
    compares the seq and the node and edge payloads only. An edge-style change
    moves none of those, so the setting was written, persisted and read, the
    graph payload was rebuilt, and the canvas went on drawing the old curves.
    Applied in place rather than by rebuilding, so the viewport survives it.
    """
    viewer = (app.PKG_DIR / "lib" / "graph_viewer" / "index.html").read_text("utf-8")
    guard = viewer.index("args.edges === lastEdges")
    rebuild = viewer.index("lastSeq = args.seq", guard)
    same_data = viewer[guard:rebuild]

    assert "smoothOf(args.options)" in same_data, "the guard never reads the option"
    assert "network.setOptions({edges: {smooth:" in same_data, "not applied in place"
    assert "lastSmooth" in viewer[rebuild : rebuild + 400], (
        "a rebuild must record what it drew, or the next in-place check is blind"
    )


def test_the_choice_is_part_of_the_graph_cache_key():
    """Same ontology, different payload, so a rerun must not serve the old one."""
    src = (app.PKG_DIR / "views" / "visualization.py").read_text("utf-8")
    key_line = next(ln for ln in src.splitlines() if "graph_key = f" in ln)
    assert "{edge_curves}" in key_line

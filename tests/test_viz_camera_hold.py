"""The camera holds still when the graph only gains nodes (issue #314).

Adding a subclass rebuilds the graph with the same layout generation, so the
nodes already placed keep their positions — but vis re-frames the whole graph
once physics settles, and the view zoomed out to the whole ontology every time.
Building one subclass after another, the class you are working on is the one
thing you stop being able to see.

None of it is observable outside a browser, so the invariant is pinned at the
source level the way test_viz_fullscreen.py pins the fullscreen ones. Verified
by hand in the running app: at scale 1.016 on FOAF, adding a subclass used to
leave the graph at 0.484 and now leaves it at 1.016, with the new node in view;
turning a node type off (nodes go away) still re-frames.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _viewer() -> str:
    return _VIEWER.read_text(encoding="utf-8")


def _rebuild_branch(src: str) -> str:
    """The branch that runs when the node set changed under the same seq."""
    start = src.index("// Same render generation but a changed node set")
    return src[start : src.index("var nodes = new vis.DataSet", start)]


def test_a_grown_graph_keeps_the_view_it_had():
    """vis's post-stabilization fit is what moved the camera, so the branch that
    restores a saved viewport has to switch it off."""
    branch = _rebuild_branch(_viewer())
    assert "fit: !_pin && !_hold" in branch, (
        "the rebuild re-frames the graph even when it is holding a saved view"
    )
    assert "_hold = !!savedView" in branch, "the hold is not tied to a saved view"


def test_the_hold_needs_every_node_that_was_placed():
    """A view is only worth keeping while what it framed is still on screen. A
    filter swapped for another set places every node afresh, and the old frame
    would hold nothing at all — so that case still re-frames."""
    branch = _rebuild_branch(_viewer())
    assert "Object.keys(_raw.pos).length === pinnedIds.length" in branch, (
        "the hold no longer checks that nothing was dropped from the graph"
    )


def test_a_fresh_layout_still_frames_the_graph():
    """Nothing to hold on a Render click or a first visit: the fit is what puts
    the graph on screen at all."""
    src = _viewer()
    fresh = src[src.index("// Fresh layout (Render, or nothing cached)") :]
    assert "fit: !_pin" in fresh[: fresh.index("var nodes = new vis.DataSet")]

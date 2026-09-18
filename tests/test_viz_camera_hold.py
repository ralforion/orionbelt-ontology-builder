"""The camera holds still when the graph only gains nodes (issue #314).

Adding a subclass rebuilds the graph with the same layout generation, so the
nodes already placed keep their positions — but vis re-frames the whole graph
once physics settles, and the view zoomed out to the whole ontology every time.
Building one subclass after another, the class you are working on is the one
thing you stop being able to see.

None of it is observable outside a browser, so the invariant is pinned at the
source level the way test_viz_fullscreen.py pins the fullscreen ones. Verified
by hand in the running app: at scale 1.016 on FOAF, adding a subclass used to
leave the graph at 0.484 and now leaves it at 1.016, with the new node in view.

Losing a node used to re-frame whatever the loss was. Deleting an annotation
took the view off the entity it hung from (issue #455), so the question the
rebuild asks is now whether the old frame still holds one of the nodes that
stayed put: a delete keeps the camera, and a filter swapped for a set that
leaves the frame empty re-frames as before.
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


def test_the_hold_needs_a_frame_with_something_left_in_it():
    """A view is only worth keeping while what it framed is still on screen.

    Nothing dropped from the graph is one way to know that, and it is the one
    the grown-graph case above relies on. A node going away is not by itself the
    other way round: a deleted annotation leaves the graph exactly where it was
    (issue #455), while a filter swapped for another set places every node
    afresh and leaves the old frame holding nothing. So the second question is
    asked of the frame itself.
    """
    branch = _rebuild_branch(_viewer())
    assert "Object.keys(_raw.pos).length === pinnedIds.length" in branch, (
        "the hold no longer knows whether anything was dropped from the graph"
    )
    assert "viewHoldsAny(savedView, pinnedIds, _raw.pos, el)" in branch, (
        "a render that lost a node re-frames without asking what is still framed"
    )
    hold = branch[branch.index("var _hold = ") :].split("\n", 1)[0]
    assert "_keptAll" in hold and "_framesKept" in hold, hold


def test_the_frame_test_measures_the_viewport_it_saved():
    """``getViewPosition()`` is the canvas point the view is centred on and
    ``getScale()`` is canvas units to pixels, so the reach either way is half the
    element's size over the scale. A view with no scale, or an element with no
    size yet, answers "no" rather than dividing by zero."""
    src = _viewer()
    fn = src[src.index("function viewHoldsAny(") :].split("\n}", 1)[0]
    assert "el.clientWidth" in fn and "el.clientHeight" in fn, fn
    assert "2 * view.scale" in fn, fn
    assert "view.position.x" in fn and "view.position.y" in fn, fn
    assert "if (!reachX || !reachY) return false;" in fn, fn
    assert "!view.scale" in fn, fn


def test_a_fresh_layout_still_frames_the_graph():
    """Nothing to hold on a Render click or a first visit: the fit is what puts
    the graph on screen at all."""
    src = _viewer()
    fresh = src[src.index("// Fresh layout (Render, or nothing cached)") :]
    assert "fit: !_pin" in fresh[: fresh.index("var nodes = new vis.DataSet")]

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


def _fresh_branch(src: str) -> str:
    """The branch that runs when the layout is computed from scratch."""
    start = src.index("// Fresh layout (Render, or nothing cached)")
    return src[start : src.index("var nodes = new vis.DataSet", start)]


def test_a_first_visit_still_frames_the_graph():
    """With no camera to carry, the fit is what puts the graph on screen at all."""
    fresh = _fresh_branch(_viewer())
    assert "fit: !_pin && !savedView" in fresh, fresh
    assert (
        "savedView = (_raw && _raw.hash === nodeHash && _raw.view) || null;" in fresh
    ), fresh


def test_a_carried_camera_has_to_be_one_of_this_graph():
    """The cache outlives the generation counter, so the carry needs its own
    identity check (PR #464 review P2).

    sessionStorage survives a reload while ``viz_render_seq`` restarts at 0, so
    the first render after one lands in this branch holding the previous
    session's frame — and the rescue below only fires when *nothing* is framed,
    which an overlapping stale view would pass. Matching the node hash is what
    says the saved view was taken of the same nodes.
    """
    fresh = _fresh_branch(_viewer())
    assert "_raw.hash === nodeHash && _raw.view" in fresh, fresh
    # The same key the cache is written under, so the two cannot drift apart.
    src = _viewer()
    assert "hash: nodeHash" in src, "the cache no longer records the node set"


def test_a_re_layout_keeps_the_camera_it_had():
    """Render means "lay this out again", not "and take me back to the whole
    ontology" (issue #460).

    The layout is deterministic, so a Render on the same nodes puts them back
    where they were; ending it on a fit meant zooming in again every time, with
    the selection still highlighted somewhere off in the distance to aim at.
    """
    fresh = _fresh_branch(_viewer())
    assert "heldAcrossLayout = !!savedView" in fresh, fresh
    # ...and the fit that used to be unconditional is now the button's job.
    src = _viewer()
    assert "function fitGraph(" in src
    assert 'id="fit-btn"' in src


def test_a_carried_camera_that_lands_on_nothing_fits_after_all():
    """A fresh layout places every node again, so a wide spacing change can move
    the graph out from under the camera. The check is the one the node-set
    rebuild makes, put to the positions physics actually produced."""
    src = _viewer()
    settle = src[src.index("stabilizationIterationsDone") :]
    settle = settle[: settle.index("// Build dynamic legend")]
    assert "heldAcrossLayout && !tookTheCamera && !viewHoldsAny(" in settle, settle
    assert "network.getPositions()" in settle, settle
    assert "network.fit(" in settle, settle
    # A camera the user moved themselves is not one to second-guess.
    assert "var tookTheCamera = !settling;" in settle, settle

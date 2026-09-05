"""The selected node's links are drawn in front (issue #385).

vis draws the edges in one pass and their arrowheads in a second, both walking
``body.edgeIndices`` in order — so which arrowhead lands on top of which comes
down to the order the builder happened to emit them in, and a restriction's was
always over a relation's because restrictions are assembled last. Nothing about
the ontology says one is above the other, so the fix is not to reorder the
builder but to raise what the user is looking at: selecting a class puts its
links over everything they cross, and dropping the selection puts the order
back.

Canvas behaviour, so none of it is observable from Python; the invariants that
would silently break it are pinned at the source level, the way the neighbour
ring's are in test_viz_neighbour_highlight.py.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _viewer():
    return _VIEWER.read_text(encoding="utf-8")


def _function(src, name):
    return src[src.index(f"function {name}(") :].split("\n}", 1)[0]


def test_selecting_a_node_raises_its_links():
    """It rides along with the neighbour ring, which every path that selects a
    node already goes through (issue #224) — so a new selection path cannot
    forget to raise the links without also forgetting to ring the neighbours,
    which its own test already forbids."""
    fn = _function(_viewer(), "applyNeighbourHighlight")
    assert "raiseEdgesOf(" in fn, fn


def test_dropping_the_selection_puts_the_order_back():
    fn = _function(_viewer(), "clearNeighbourHighlight")
    assert "restoreEdgeOrder()" in fn, fn


def test_the_draw_order_is_mutated_in_place():
    """vis hands the same ``edgeIndices`` array around its renderer, so a fresh
    one would leave those holders pointing at the order before the raise."""
    src = _viewer()
    assert "body.edgeIndices =" not in src, "the array is shared; reorder it in place"
    assert "idx.length = 0" in _function(src, "setEdgeIndices")


def test_the_raise_keeps_the_builder_s_order_within_each_group():
    """A stable partition, not a sort: the order the edges were emitted in is
    what the parallel-edge curves (issue #245) and the legend are built around,
    and the only thing this changes is which side of the line they sit on."""
    fn = _function(_viewer(), "raiseEdgesOf")
    assert "back.concat(front)" in fn, fn
    assert "sort(" not in fn, fn


def test_the_edges_themselves_are_left_alone():
    """The DataSet is not touched: this is a view concern, and an edge update
    would ripple into the selection and the ring restore that read it back."""
    fn = _function(_viewer(), "raiseEdgesOf")
    assert "data.edges" not in fn and ".update(" not in fn, fn


def test_a_rebuild_between_the_raise_and_the_restore_is_survivable():
    """Ids that have gone since the order was taken must not come back, and ids
    that arrived after it must not be dropped."""
    fn = _function(_viewer(), "restoreEdgeOrder")
    assert "present[eid]" in fn, fn
    assert "known[eid]" in fn, fn

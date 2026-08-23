"""Node options gets out of the way when the graph is clicked.

The card floats over the top of the canvas (PR #310), so after a click it covers
the very graph the click was about, while the answer appears in the details panel
beside it. Selecting a node or an edge therefore closes it.

Closed by clicking the expander's own summary rather than by setting anything:
the expander is uncontrolled from Python — Streamlit only re-applies ``expanded``
when the label changes, and moving the label is what closed the panel under the
user in issue #267. None of it is observable outside a browser, so the wiring is
pinned here the way test_viz_fullscreen.py pins the fullscreen invariants.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _viewer() -> str:
    return _VIEWER.read_text(encoding="utf-8")


def _handler(src: str, event: str) -> str:
    """The body of ``network.on('<event>', ...)``."""
    start = src.index(f"network.on('{event}'")
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced braces in the {event} handler")


def test_selecting_a_node_or_an_edge_closes_the_card():
    src = _viewer()
    for event in ("selectNode", "selectEdge"):
        assert "closeNodeOptions()" in _handler(src, event), (
            f"a {event} leaves Node options covering the graph"
        )


def test_clicking_empty_canvas_leaves_it_alone():
    """A deselect is not a reason to close a card the user opened: nothing new
    is being shown beside it."""
    assert "closeNodeOptions()" not in _handler(_viewer(), "deselectNode")


def test_the_card_is_closed_the_way_a_user_closes_it():
    """Through the summary, so Streamlit's own expander state follows and the
    card does not spring back open on the next rerun. Setting ``open`` on the
    <details> would look right and then reopen."""
    src = _viewer()
    body = src[src.index("function closeNodeOptions()") :]
    body = body[: body.index("\n}\n")]
    assert "details[open] > summary" in body
    assert "summary.click()" in body, "the card is closed without clicking its summary"
    assert ".open = false" not in body
    # The parent document is another frame's: unreachable one day, unimportant.
    assert "catch" in body

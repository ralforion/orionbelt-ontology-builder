"""The node tooltip has to be styled here, because vis's stylesheet is not vendored.

The viewer loads `vis-network.min.js` and nothing else. vis puts `.vis-tooltip`
styling in `vis-network.css`, so without a rule of our own the element arrived
with no box at all: black text on a transparent background over a near-black
canvas, and `position: static`, which meant the top/left vis writes inline did
nothing and it sat in the document flow instead of beside the pointer. It was in
the DOM, reporting `visibility: visible`, and invisible on screen. Measured
before and after:

    colour      rgb(0,0,0)     ->  rgb(250,250,250)
    background  rgba(0,0,0,0)  ->  rgb(38,39,48)
    position    static         ->  absolute
    z-index     auto           ->  20

None of it is observable from Python, so it is pinned at the source level like
the viewer's other invariants.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _viewer():
    return _VIEWER.read_text(encoding="utf-8")


def _rule(src, selector):
    start = src.index(selector + " {")
    return src[start : src.index("}", start)]


def test_the_tooltip_is_styled_at_all():
    """vis ships no CSS here, so every property it needs comes from this rule."""
    src = _viewer()
    assert ".vis-tooltip {" in src, "no rule at all is what made it invisible"
    rule = _rule(src, ".vis-tooltip")
    for prop in ("position", "background", "color", "padding", "z-index"):
        assert prop in rule, (prop, rule)


def test_it_is_positioned_where_vis_puts_it():
    """vis writes top/left inline; `position: static` ignores both, which is how
    it ended up in the document flow rather than beside the node."""
    assert "position: absolute" in _rule(_viewer(), ".vis-tooltip")


def test_it_follows_the_theme_rather_than_a_fixed_colour():
    """The canvas is near-black in dark mode and white in light, so a fixed
    colour is invisible in one of them. The variables are set beside the ones
    the toolbar chips use."""
    src = _viewer()
    rule = _rule(src, ".vis-tooltip")
    assert "var(--node-tip-bg" in rule
    assert "var(--node-tip-fg" in rule
    assert "setProperty('--node-tip-bg', theme.panel)" in src
    assert "setProperty('--node-tip-fg', theme.text)" in src


def test_a_long_comment_wraps_instead_of_running_off():
    """A title carries newlines and a comment can be a paragraph."""
    rule = _rule(_viewer(), ".vis-tooltip")
    assert "white-space: pre-wrap" in rule
    assert "max-width" in rule


def test_it_cannot_swallow_a_click_on_the_node_under_it():
    assert "pointer-events: none" in _rule(_viewer(), ".vis-tooltip")

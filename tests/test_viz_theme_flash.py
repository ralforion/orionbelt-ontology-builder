"""Guards for the graph viewer's first-frame background (issue #372).

Streamlit replaces the component's document whenever a panel is toggled, and a
fresh document paints the stylesheet's white until Python's theme arrives. The
viewer paints the colour it last drew instead, from sessionStorage, before the
first frame. Two things make that work, and neither shows up in a unit test of
the Python side, so they are pinned here.
"""

from pathlib import Path

_VIEWER = (
    Path(__file__).resolve().parent.parent
    / "orionbelt_ontology_builder"
    / "lib"
    / "graph_viewer"
    / "index.html"
)


def test_the_remembered_colour_outranks_the_fallback_css():
    """The early script inserts `html, body { background: ... }`, which has the
    same specificity as the stylesheet's white and its dark media query. Same
    specificity means document order decides, so the script has to come after
    the stylesheet or the remembered colour is simply ignored — and the flash
    comes back for anyone whose app theme differs from their OS preference."""
    html = _VIEWER.read_text(encoding="utf-8")
    early = html.index("viz_theme_bg")
    fallback = html.index("@media (prefers-color-scheme: dark)")
    assert fallback < early, (
        "the early-paint script must run after the fallback stylesheet, "
        "otherwise the remembered background loses the cascade"
    )
    assert html.index("</style>", fallback) < early


def test_both_theme_paths_remember_the_colour():
    """A same-data re-render goes through applyTheme; a fresh mount rebuilds the
    network instead. Only the rebuild path runs on the very first render, so if
    it doesn't store the colour there is nothing to paint on the next mount."""
    html = _VIEWER.read_text(encoding="utf-8")
    assert html.count("rememberThemeBg(") == 3  # the definition and both callers
    # Nobody writes the key behind the helper's back.
    assert html.count("sessionStorage.setItem('viz_theme_bg'") == 1

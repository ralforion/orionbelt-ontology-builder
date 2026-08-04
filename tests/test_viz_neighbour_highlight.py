"""Guards for the graph viewer's neighbour highlight (issue #224).

Selecting a node rings the nodes at the other end of its edges, dashed for
incoming and solid for outgoing. All of it is canvas behaviour, so none of it is
observable from Python; the invariants that silently break it are pinned at the
source level instead, the way the fullscreen ones are in test_viz_fullscreen.py.
"""

import re
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _viewer():
    return _VIEWER.read_text(encoding="utf-8")


def test_programmatic_selection_also_rings_the_neighbours():
    """Every ``selectNodes()`` call must ring the neighbourhood itself.

    ``selectNodes()`` does not fire ``selectNode``, so the paths that restore a
    selection without a click — a re-mount rebuild and both Find & centre paths —
    would leave the node selected but its neighbours unringed.
    """
    src = _viewer()
    sites = list(re.finditer(r"network\.selectNodes\(", src))
    assert len(sites) == 3, (
        f"expected 3 programmatic selectNodes() sites, found {len(sites)} — "
        "a new one must ring the neighbourhood too"
    )
    for site in sites:
        following = src[site.end() : site.end() + 200]
        assert "applyNeighbourHighlight(" in following, (
            "every selectNodes() must be followed by applyNeighbourHighlight(), "
            "since selectNodes() does not fire selectNode (issue #224)"
        )


def test_losing_the_node_selection_clears_the_ring():
    """Deselecting a node, or selecting an edge instead, drops the ring.

    An edge-only selection means no node is selected, and vis does not fire
    ``deselectNode`` on the way there — so that handler has to clear it too or
    the ring outlives the selection that raised it.
    """
    src = _viewer()
    for event in ("deselectNode", "selectEdge"):
        handler = src.split(f"network.on('{event}'", 1)[1].split("\n    });", 1)[0]
        assert "clearNeighbourHighlight()" in handler, (
            f"{event} must clear the neighbour ring (issue #224)"
        )


def test_the_ring_colour_is_the_theme_colour():
    """The ring is drawn in the theme's text colour, never a fixed one.

    Node fills encode entity type and stay the same in both themes, so a
    hard-coded ring would have to contrast with white *and* #0e1117. Reusing
    ``theme.text`` is contrast-correct in both by construction.
    """
    src = _viewer()
    body = src.split("function applyNeighbourHighlight(", 1)[1].split("\n}\n", 1)[0]
    assert "currentTheme.text" in body, (
        "the ring must take its colour from the theme, so it reads in light and "
        "dark alike (issue #224)"
    )
    rung = body.split("var ring =", 1)[1].split(";", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{6}", rung.replace("#333333", "")), (
        "no fixed ring colour beyond the light-theme fallback"
    )


def test_a_theme_change_redraws_a_live_ring():
    """applyTheme runs without a rebuild, so it has to recolour a live ring."""
    src = _viewer()
    body = src.split("function applyTheme(", 1)[1].split("\n}\n", 1)[0]
    assert "applyNeighbourHighlight(hlSource)" in body, (
        "a theme change under a live selection must redraw the ring, or it keeps "
        "the previous theme's colour (issue #224)"
    )


def test_the_ring_does_not_impersonate_the_validation_ring():
    """Width 3 means "has validation issues" — the ring must not reuse it.

    A red border at width 3 is what the "Highlight issues" mode marks broken
    entities with, so a neighbour ring at the same weight would read as a
    validation warning.
    """
    app_src = (_PKG / "app.py").read_text(encoding="utf-8")
    issue_widths = set(re.findall(r"border_width = (\d+) if has_issue", app_src))
    assert issue_widths == {"3"}, (
        f"expected the validation ring at width 3, found {issue_widths}"
    )

    src = _viewer()
    width = src.split("var HL_WIDTH =", 1)[1].split(";", 1)[0].strip()
    assert width not in issue_widths, (
        f"the neighbour ring must not use width {width} — that is the "
        "validation-issue ring (issue #224)"
    )


def test_the_restore_writes_every_field_back_explicitly():
    """The undo must not rely on a DataSet update ignoring undefined fields.

    Only classes and individuals carry ``borderWidth``, and nothing carries
    ``shapeProperties``, so writing an undefined value back would leave those
    nodes ringed forever. The fallbacks are vis's own defaults.
    """
    src = _viewer()
    body = src.split("function clearNeighbourHighlight(", 1)[1].split("\n}\n", 1)[0]
    assert "s.borderWidth === undefined ? 1 :" in body
    assert "borderDashes: false" in body

"""Guards for the graph page's CSS hooks into Streamlit's DOM.

None of this is observable outside a browser, and all of it is keyed off markup
Streamlit generates rather than markup this app writes. A hook that stops
matching fails silently — the panel goes back to taking a column out of the
canvas, or an invisible component reappears as a band above it — so the hooks
are pinned here instead.
"""

from pathlib import Path

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.views.visualization import graph_overlay_css

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"


def test_every_overlay_is_taken_out_of_the_row():
    """The three panels that used to cost the canvas space must all float."""
    css = graph_overlay_css(dark=False)
    for hook, what in [
        (".st-key-viz_hide_panel", "the details panel"),
        (".st-key-viz_show_panel", "the reopen toggle"),
        (".st-key-viz_filter_nodes", "the Node options picker"),
    ]:
        assert hook in css, f"{what} no longer floats over the canvas"
    # Their positioning context, and the canvas claiming the freed width.
    assert '[data-testid="stHorizontalBlock"]:has(.st-key-graph_viewer)' in css
    assert "flex: 1 1 100% !important" in css


def test_the_cards_are_opaque():
    """Chips and labels over a busy graph need something solid behind them."""
    light, dark = graph_overlay_css(dark=False), graph_overlay_css(dark=True)
    assert "background: #ffffff" in light
    assert "background: #262730" in dark  # the app's own dark surface, not black
    assert "box-shadow:" in light and "box-shadow:" in dark


def test_the_storage_component_rule_names_the_package_that_is_imported():
    """The invisible browser-storage iframe is hidden by its served URL.

    Streamlit serves a component from ``/component/<module>.<name>/``, so the
    rule keys on the module the app imports. Renaming the dependency without
    updating the rule would put its 26px band back above the canvas.
    """
    assert 'iframe[src*="streamlit_local_storage"]' in ui._CUSTOM_CSS
    assert "from streamlit_local_storage import" in (_PKG / "ui.py").read_text()

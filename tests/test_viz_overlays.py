"""Guards for the graph page's CSS hooks into Streamlit's DOM.

None of this is observable outside a browser, and all of it is keyed off markup
Streamlit generates rather than markup this app writes. A hook that stops
matching fails silently — the panel goes back to taking a column out of the
canvas, or an invisible component reappears as a band above it — so the hooks
are pinned here instead.
"""

import re
from pathlib import Path

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.views.visualization import (
    _TOOLBAR_CLEARANCE,
    graph_overlay_css,
)

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


def test_the_panel_cap_pays_for_its_own_offset():
    """The card starts a toolbar's height down the canvas, so a cap of the full
    row height would let a long editor hang that far past the canvas and over
    the status bar. The cap has to subtract the same offset."""
    css = graph_overlay_css(dark=False)
    assert f"max-height: calc(100% - {_TOOLBAR_CLEARANCE})" in css
    # ...and the padding has to sit inside that cap, not on top of it.
    assert "box-sizing: border-box" in css


def test_the_canvas_does_not_pay_for_the_column_gap():
    """Every row on this page is separated by the column's 16px gap. Above the
    canvas that gap reads as a band, because the canvas already opens with a
    strip of empty graph above its legend."""
    css = graph_overlay_css(dark=False)
    assert "margin-top: -12px" in css


def test_the_picker_cannot_animate_the_canvas_around():
    """Streamlit opens an expander with a JS height animation on the <details>.

    It animates towards the height of a body that is out of the flow here, so
    the graph slid down by the height of a card that was never in the flow and
    snapped back when the animation ended. Only an !important declaration
    outranks a script animation.
    """
    css = graph_overlay_css(dark=False)
    assert ".st-key-viz_filter_nodes details {" in css
    rule = css[css.index(".st-key-viz_filter_nodes details {") :]
    assert "height: auto !important" in rule[: rule.index("}")]


def test_css_only_markdown_is_taken_out_of_the_flow():
    """An st.markdown carrying only a <style> still takes a slot in the page
    column's 16px gap grid. Four of them ride above the graph."""
    assert "> style:only-child" in ui._CUSTOM_CSS


def test_the_page_starts_below_streamlit_s_header():
    """The header is an opaque bar painted over the page, not behind it.

    Hiding the CSS-only elements above the title moved the first line of the
    page up under it, which clipped the breadcrumb. The top padding is what
    keeps them apart, so it may not drop below the header's 60px.
    """
    rule = ui._CUSTOM_CSS[
        ui._CUSTOM_CSS.index(".block-container, .stMainBlockContainer") :
    ]
    rule = rule[: rule.index("}")]
    padding = re.search(r"padding-top:\s*([\d.]+)rem", rule)
    assert padding, "the page no longer sets its own top padding"
    assert float(padding.group(1)) * 16 >= 60


def test_the_storage_component_rule_names_the_package_that_is_imported():
    """The invisible browser-storage iframe is hidden by its served URL.

    Streamlit serves a component from ``/component/<module>.<name>/``, so the
    rule keys on the module the app imports. Renaming the dependency without
    updating the rule would put its 26px band back above the canvas.
    """
    assert 'iframe[src*="streamlit_local_storage"]' in ui._CUSTOM_CSS
    assert "from streamlit_local_storage import" in (_PKG / "ui.py").read_text()


def _toolbar_bottom_px(viewer: str) -> int:
    """How far down the canvas its own toolbar reaches, from the buttons' CSS."""
    bottoms = []
    for button in ("#download-btn", "#fullscreen-btn"):
        rule = viewer[viewer.index(button + " {") :]
        rule = rule[: rule.index("}")]
        top = re.search(r"top:\s*(\d+)px", rule)
        height = re.search(r"height:\s*(\d+)px", rule)
        assert top and height, f"{button} no longer sizes itself in px"
        bottoms.append(int(top.group(1)) + int(height.group(1)))
    return max(bottoms)


def test_the_overlays_clear_the_canvas_toolbar():
    """The canvas keeps download and fullscreen in the corner the cards use.

    The overlays live outside the iframe, so they win every hit test over those
    buttons — covering one is enough to make it unclickable, with nothing on
    screen to say why. They start below the toolbar instead.
    """
    viewer = (_PKG / "lib" / "graph_viewer" / "index.html").read_text()
    css = graph_overlay_css(dark=False)
    offsets = re.findall(r"top:\s*([\d.]+)rem", css)
    assert offsets, "the overlays no longer offset themselves from the top"
    clearance = min(float(o) for o in offsets) * 16  # rem at Streamlit's root size
    assert clearance >= _toolbar_bottom_px(viewer), (
        "an overlay now starts over the canvas's own toolbar buttons"
    )

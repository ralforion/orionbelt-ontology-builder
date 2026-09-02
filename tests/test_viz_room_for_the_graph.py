"""Guards for the room above the canvas (issue #381).

The canvas fits itself to whatever is left below the controls, so every pixel
these give back is a pixel of graph. None of it is observable outside a browser,
so the hooks are pinned here.
"""

from pathlib import Path

import sources

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.views.visualization import graph_space_css

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"


def test_empty_style_blocks_stay_out_of_the_layout():
    """CSS injected through st.markdown leaves an empty element behind that
    still takes a slot in the page column's 16px gap grid — four of them ride
    above the graph.

    The rule that hides them was written as a chain of child combinators and
    stopped matching when Streamlit put another wrapper between the markdown
    element and its container: measured in the browser, 0 elements matched
    while 4 sat in the page. Descendant combinators survive that.
    """
    css = ui._CUSTOM_CSS
    rule = css[css.index('[data-testid="stElementContainer"]:has(') :]
    rule = rule[: rule.index("}") + 1]
    assert "style:only-child" in rule, (
        "only a markdown block with nothing to show may be hidden"
    )
    assert '> [data-testid="stMarkdown"]' not in rule, (
        "the child chain breaks whenever Streamlit adds a wrapper; match on "
        "descendants instead"
    )


def test_the_find_row_gives_its_height_back_when_switched_off():
    """Off, the row must cost the page nothing — not even the slot its own
    wrapper holds in the gap grid, which is a band of empty page where the row
    used to be."""
    on, off = graph_space_css(True), graph_space_css(False)
    assert ".st-key-viz_find_row" not in on
    assert ".st-key-viz_find_row" in off
    assert '[data-testid="stLayoutWrapper"]:has(> .st-key-viz_find_row)' in off


def test_the_find_row_is_hidden_rather_than_skipped():
    """What the row holds — the find target, the node filter, the focus seeds —
    is read by the run that builds the graph further down. A run that never
    rendered it would have to rebuild all of that from the saved config, so the
    row is always rendered and only ever taken out of the flow."""
    src = sources.viz_text()
    assert 'st.container(key="viz_find_row")' in src
    # ...and nothing gates it behind the switch.
    assert "if find_row_open:" not in src


def test_render_is_sized_to_its_label():
    """Stretched across its column, Render was the largest thing above the
    canvas — for a button only reached after changing something else."""
    src = sources.viz_text()
    button = src[src.index("render_graph = st.button(") :].split(")", 1)[0]
    assert "use_container_width" not in button
    assert 'key="viz_render_btn"' in button
    assert ".st-key-viz_render_btn button" in graph_space_css(True)


def test_the_render_label_never_breaks():
    """The button's column is a share of the row, so a narrow window squeezed
    it until "Render" broke into "Rend / er". The label is held on one line and
    the button keeps its own width whatever the column does."""
    css = graph_space_css(True)
    button = css[css.index(".st-key-viz_render_btn button {") :]
    button = button[: button.index("}")]
    assert "white-space: nowrap" in button
    assert "width: max-content" in button
    # The label is its own element inside the button, and it wraps on its own.
    assert ".st-key-viz_render_btn button p" in css


def test_the_page_keeps_its_own_spacing():
    """The title, the section tabs and the gaps between the rows are left
    alone: the room comes from the controls, not from crowding the page."""
    css = graph_space_css(True)
    assert "stHeading" not in css
    assert "gap:" not in css

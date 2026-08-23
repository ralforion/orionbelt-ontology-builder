"""Taking the selected text away with you (issue #312).

Both places the selection is reported cut it to fit: the node draws a label
short enough for the node, and the bar under the graph ellipsises its one line.
An annotation's value is usually the thing worth copying and is exactly what
those cuts eat. There are two buttons, answering two questions: the canvas one
hands over what the selection is called, and the one in the black bar hands over
the whole line the bar reports. The bar also keeps that line in a tooltip, since
the ellipsis is what made its tail unreadable.

The bar half runs the real page through AppTest, as test_viz_details_link does.
The canvas half is browser behaviour, pinned at the source level the way
test_viz_fullscreen.py pins the fullscreen invariants. Verified by hand in the
running app as well.
"""

import json
import os
from pathlib import Path

import sources
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.views.visualization import (
    COPY_ICON_PATH,
    status_bar_copy_html,
)

URL = "https://webeep.polimi.it/course/view.php?id=123456"
CUT = URL[:30] + "..."

_VIEWER = (
    Path(__file__).resolve().parent.parent
    / "orionbelt_ontology_builder"
    / "lib"
    / "graph_viewer"
    / "index.html"
)


def _viewer() -> str:
    return _VIEWER.read_text(encoding="utf-8")


# --- the button on the canvas ------------------------------------------------


def test_the_canvas_copies_the_whole_label_and_only_that():
    """The label the node drew is cut to fit it, so the whole one is copied —
    and only that. The tooltip repeats the name and adds a sentence about it,
    which is worth reading on screen and not worth pasting."""
    src = _viewer()
    body = src[src.index("function selectionText(") :]
    body = body[: body.index("\n}\n")]
    assert "d.flabel || d.label" in body, "the copy hands over the cut label"
    assert "d.title" not in body, "the copy carries the tooltip along with it"


def test_the_button_comes_and_goes_with_the_selection():
    """Nothing selected, nothing to copy: an enabled button that does nothing
    reads as broken."""
    src = _viewer()
    body = src[src.index("function setCopyTarget(") :]
    body = body[: body.index("\n}\n")]
    assert "display = copyText ? 'flex' : 'none'" in body
    for event in ("deselectNode", "deselectEdge"):
        handler = src[src.index(f"network.on('{event}'") :]
        handler = handler[: handler.index("});")]
        assert "setCopyTarget('')" in handler, f"{event} leaves a stale copy target"


def test_the_desktop_webview_can_copy_too():
    """It has no async clipboard API, and a button that silently does nothing
    there is worse than the old selection-based copy."""
    src = _viewer()
    body = src[src.index("function copySelection()") :]
    body = body[: body.index("\n}\n")]
    assert "navigator.clipboard" in body
    assert "legacyCopy(text)" in body, "no fallback when the clipboard API is out"
    assert "execCommand('copy')" in _viewer()


def test_a_modifier_click_reports_the_node_it_hit():
    """Ctrl/Cmd-click and Alt-click ask Python to focus, and that request is the
    value Streamlit keeps. On its own it left the panel and the copy button on
    whatever was picked before the click — and the rebuild that followed
    restored that stale node over the one just clicked."""
    src = _viewer()
    handler = src[src.index("network.on('click'") :]
    handler = handler[: handler.index("focusRequest")]
    assert "setCopyTarget(selectionText(mnd))" in handler
    request = src[src.index("focusRequest: true") - 400 :]
    request = request[: request.index("focusRequest: true") + 200]
    assert "selectionPayload(params.nodes[0], mnd)" in request, (
        "the focus request does not carry the node it was made on"
    )


def test_an_edge_keeps_the_canvas_button_through_a_rebuild():
    """A node comes back after a rebuild by its id and the component reads the
    copy text off it; an edge has no id to come back by, so the button vanished
    on the next re-mount while the edge was still selected. Python hands the
    text over instead."""
    viz = sources.viz_text()
    assert "copy_text=(" in viz, "the component is not told what to offer"
    body = _viewer()
    restore = body[body.index("setCopyTarget(restoreNode") :]
    restore = restore[: restore.index(";") + 1]
    assert "args.copy_text" in restore, (
        "a rebuild clears the copy target for anything it cannot restore by id"
    )


# --- where the button sits ---------------------------------------------------


def test_the_button_and_the_bar_share_a_container():
    """It is laid over the end of the bar, and needs one thing to be positioned
    against in either layout: beside the View button it sits in a column, and
    for a selection without one — an annotation, the case this is all for — the
    bar has the row to itself."""
    viz = sources.viz_text()
    assert 'st.container(key="graph_status_cell")' in viz
    assert ".st-key-graph_status_cell { position: relative; }" in viz
    positioned = viz[viz.index(".st-key-graph_status_cell [data-testid=") :]
    positioned = positioned[: positioned.index("}")]
    assert "position: absolute" in positioned
    assert "stColumn" not in positioned, (
        "the button is positioned only inside a column again — the annotation "
        "path has no column, and there the icon fell out below the bar"
    )


def test_the_container_sticks_with_everything_else():
    """It is another wrapper between the bar and the page, and the bar has to
    stay in view while the graph is worked on."""
    viz = sources.viz_text()
    sticky = viz[
        viz.index('div[data-testid="stLayoutWrapper"]:has(#graph-status-bar)') :
    ]
    sticky = sticky[: sticky.index("}")]
    assert "stVerticalBlockBorderWrapper" in sticky


# --- the bar under the graph -------------------------------------------------


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Course")
        om.add_annotation("Course", "webeep", os.environ["ANN_VALUE"])
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The settings restore mounts a localStorage component that blocks
        # without a browser to answer it; the bar is what this file is about, so
        # the details panel is pinned shut rather than inherited.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_details_panel"] = False
        st.session_state["_viz_cfg_show_annotations"] = True
        ann = next(
            a
            for a in om.get_annotations(om.namespace + "Course")
            if a["predicate"] == "webeep"
        )
        value = ann["value"]
        st.session_state["_viz_last_selection"] = {
            "selected": True,
            "ntype": "Annotation",
            "ename": app.annotation_ename(om.namespace + "Course", ann),
            "label": value[:30] + "..." if len(value) > 30 else value,
            "flabel": value,
            "title": f"webeep: {value}",
        }

    app.render_visualization()


def _run(value=URL):
    os.environ["ANN_VALUE"] = value
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _bar(at):
    bars = [m.value for m in at.markdown if 'id="graph-status-bar"' in m.value]
    assert bars, "the status bar was not drawn"
    return bars[0]


def test_the_bar_carries_the_whole_line_in_its_tooltip():
    """One row, ellipsised: the tail is unreadable without it."""
    bar = _bar(_run())
    assert f'title="{URL} — webeep: {URL}"' in bar
    assert "text-overflow:ellipsis" in bar, "the tooltip stands in for a cut line"


def test_the_bar_shows_the_whole_label_not_the_node_s_cut_one():
    bar = _bar(_run())
    assert f"<b>{URL}</b>" in bar
    assert CUT not in bar


LINE = f"{URL} — webeep: {URL}"


def test_the_bar_button_copies_the_line_the_bar_shows():
    """Where the canvas button copies only what the selection is called. Two
    buttons, two answers, both a single click."""
    out = status_bar_copy_html(LINE)
    assert json.dumps(LINE) in out, "the button does not carry the line"
    assert COPY_ICON_PATH in out, "the bar's icon is not the canvas's"
    assert "execCommand('copy')" in out, "no fallback for the desktop webview"


def test_the_bar_button_is_handed_the_whole_line():
    """The tooltip's text, not the label alone — the page has to pass that."""
    assert "status_bar_copy_html(_bar_title)" in sources.viz_text()


def test_a_value_cannot_end_the_script_it_travels_in():
    """The line is the user's own text and it lands inside a <script>: a value
    carrying "</script>" would close the block and spill into the page."""
    out = status_bar_copy_html("x </script><img src=y onerror=alert(1)> z")
    assert out.count("</script>") == 1, "a value can close the script block"
    assert "<\\/script>" in out


def test_the_bar_escapes_what_it_is_given():
    """It is the user's own text, and it goes straight into HTML."""
    bar = _bar(_run(value="<img src=x onerror=alert(1)>"))
    assert "<img" not in bar
    assert "&lt;img" in bar

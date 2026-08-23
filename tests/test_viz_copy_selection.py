"""Taking the selected text away with you (issue #312).

Both places the selection is reported cut it to fit: the node draws a label
short enough for the node, and the bar under the graph ellipsises its one line.
An annotation's value is usually the thing worth copying and is exactly what
those cuts eat. So the canvas has a copy button that hands over the whole
selection, and the bar carries the whole line in its tooltip with a copy
popover beside it.

The bar half runs the real page through AppTest, as test_viz_details_link does.
The canvas half is browser behaviour, pinned at the source level the way
test_viz_fullscreen.py pins the fullscreen invariants. Verified by hand in the
running app as well.
"""

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

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


def test_the_canvas_offers_the_selection_in_full():
    """The whole label, not the one the node drew, and the tooltip's own lines
    under it — so the value and what it hangs on read as they do on screen."""
    src = _viewer()
    body = src[src.index("function selectionText(") :]
    body = body[: body.index("\n}\n")]
    assert "d.flabel || d.label" in body, "the copy hands over the cut label"
    assert "d.title" in body, "the copy drops everything but the label"


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


def test_the_copy_popover_holds_the_selection_unwrapped():
    """As a code block, which is what carries Streamlit's own copy button."""
    codes = [c.value for c in _run().code]
    assert f"{URL}\nwebeep: {URL}" in codes, codes


def test_the_bar_escapes_what_it_is_given():
    """It is the user's own text, and it goes straight into HTML."""
    bar = _bar(_run(value="<img src=x onerror=alert(1)>"))
    assert "<img" not in bar
    assert "&lt;img" in bar

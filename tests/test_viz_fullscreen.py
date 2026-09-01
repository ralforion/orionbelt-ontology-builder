"""Guards for the graph viewer's fullscreen behaviour (issue #189).

Both invariants here are only observable in a real browser, so they are pinned at
the source level: breaking either one silently drops fullscreen or repaints the
details panel behind it, and no other test would notice.
"""

import ast
from pathlib import Path

import sources

from orionbelt_ontology_builder.views.visualization import (
    GRAPH_FS_CLASS,
    graph_fullscreen_css,
)

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"


def _status_placeholder_assignments(tree):
    """Every ``status = st.empty()`` assignment in the tree, as AST nodes."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "status" not in targets:
            continue
        call = node.value
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "empty"
        ):
            found.append(node)
    return found


def test_graph_status_placeholder_is_unconditional():
    """The build-status placeholder must be created on every render.

    It sits above the graph component, so emitting it only while rebuilding
    shifts the component's slot in Streamlit's element tree from one render to
    the next. Streamlit then re-creates the component's iframe, which reloads the
    viewer and drops graph fullscreen — the first-click and Ctrl-click "falls
    back to normal mode" glitches in issue #189.
    """
    tree = ast.parse(sources.viz_text())
    placeholders = _status_placeholder_assignments(tree)
    assert placeholders, (
        "expected a `status = st.empty()` placeholder in the Visualization source"
    )

    conditional = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "needs_rebuild" not in names:
            continue
        for stmt in node.body:
            conditional.extend(_status_placeholder_assignments(stmt))
    assert not conditional, (
        "`status = st.empty()` must sit outside `if needs_rebuild:` so the graph "
        "component keeps its position in the element tree (issue #189)"
    )


def test_fullscreen_is_taken_on_the_page_not_on_the_canvas():
    """The fullscreen element must be the *parent page's* root element.

    Fullscreening the canvas' own container put the whole of Streamlit's DOM —
    Display options, Find & focus, Path finder, Node options, the details panel
    — behind the fullscreen graph, so every one of them meant leaving fullscreen
    and going back in (issue #381).
    """
    src = _VIEWER.read_text(encoding="utf-8")

    enter = src[src.index("function enterFullscreen(") :].split("\n}", 1)[0]
    assert "parentDoc()" in enter and "documentElement" in enter, (
        "fullscreen must be requested on the parent page's root element"
    )
    assert "getElementById('container')" not in enter, (
        "fullscreening the component's own container leaves every control "
        "outside it behind (issue #381)"
    )


def test_the_fullscreen_state_lives_on_the_page():
    """Streamlit replaces this document whenever it re-mounts the component, so
    a flag in it would be lost while the app was still fullscreen — the button
    would offer to enter what it is already in. The state is a class on the
    parent's body, and both sides have to agree on its name."""
    src = _VIEWER.read_text(encoding="utf-8")
    assert f"var FS_CLASS = '{GRAPH_FS_CLASS}'" in src
    assert GRAPH_FS_CLASS in graph_fullscreen_css(dark=False)
    # And the button reads it back on mount rather than assuming "not fullscreen".
    assert "setFullscreenIcon(on)" in src
    assert "syncFullscreenState()" in src


def test_only_our_own_page_fullscreen_is_followed():
    """Streamlit fullscreens elements of its own (the chart and image
    expanders). Following one of those would hide the app's chrome behind
    somebody else's fullscreen element."""
    src = _VIEWER.read_text(encoding="utf-8")
    fn = src[src.index("function pageFullscreenOn(") :].split("\n}", 1)[0]
    assert "=== d.documentElement" in fn


def test_selections_reach_python_while_fullscreen():
    """The workaround from issue #189 is retired.

    Selections used to be held back until exit: the fullscreen element lived in
    this document, so a rerun that re-mounted the component destroyed it. The
    page survives every rerun, and the details panel the selection repaints is
    now on screen — holding it back would leave a visible panel showing a stale
    node.
    """
    src = _VIEWER.read_text(encoding="utf-8")

    assert "flushPendingSelection" not in src
    assert "pendingSelection" not in src

    # Every selection event still goes through the one helper, so there is a
    # single place where what reaches Python is decided.
    for event in ("selectNode", "selectEdge", "deselectNode", "deselectEdge"):
        handler = src.split(f"network.on('{event}'", 1)[1].split("});", 1)[0]
        assert "sendSelection(" in handler, f"{event} must use sendSelection()"
        assert "setComponentValue" not in handler, (
            f"{event} must not send to Streamlit directly"
        )


def test_the_native_exit_hook_is_reclaimed_by_every_mount():
    """The desktop host calls a hook on the top window when its own window
    leaves fullscreen (Esc, the green button, the Window menu). The hook is a
    function of the document that installed it, and fullscreen now outlives
    that document — so a mount that finds the page still fullscreen has to
    claim the hook back, or the chrome stays hidden with nobody to put it back.
    """
    src = _VIEWER.read_text(encoding="utf-8")
    sync = src[src.index("function syncFullscreenState(") :].split("\n}", 1)[0]
    assert "installNativeFsExitHook()" in sync
    assert "setNativeFsExitHook(null)" in sync
    # ...and that is what a fresh render runs.
    assert "syncFullscreenState();" in src
    assert "setFullscreenIcon(stageOn())" not in src


def test_the_page_listener_is_removed_with_the_document():
    """The listener is registered on the parent, which outlives this document by
    many re-mounts. Without the teardown each mount piles another dead one on."""
    src = _VIEWER.read_text(encoding="utf-8")
    assert "d.addEventListener('fullscreenchange', onPageFullscreenChange)" in src
    assert "d.removeEventListener('fullscreenchange', onPageFullscreenChange)" in src
    assert "window.addEventListener('pagehide'" in src


def test_fullscreen_hides_the_app_chrome_but_not_the_controls():
    """What fullscreen hides is the app around the page: the sidebar, Streamlit's
    header, and everything above the switch row. The controls themselves come
    along — that is the point of taking the page (issue #381)."""
    css = graph_fullscreen_css(dark=False)
    for hook in (
        '[data-testid="stSidebar"]',
        '[data-testid="stHeader"]',
    ):
        assert hook in css, f"{hook} must be hidden in fullscreen"
    # Everything above the switch row, named by position rather than one by one.
    assert "*:has(~ * .st-key-viz_band_switches)" in css
    # A :has() inside a :has() is invalid and takes its whole rule down without
    # a word, which is how the title and the tabs stayed on screen the first
    # time this was written.
    assert ":has(~ *:has(" not in css
    # ...and nothing that hides a control.
    for hook in (
        ".st-key-viz_band_switches",
        ".st-key-viz_find_row",
        ".st-key-graph_viewer",
    ):
        assert f"{hook} {{" not in css


def test_the_canvas_measures_the_page_not_its_own_iframe():
    """A fullscreen page does not resize the component iframe, so the iframe's
    own window.innerHeight says nothing about the box to fill. The height comes
    from the page's viewport in both states — there is no separate fullscreen
    measurement left to drift (issue #177 follow-up)."""
    src = _VIEWER.read_text(encoding="utf-8")
    fn = src[src.index("function viewportHeight(") :].split("\n}", 1)[0]
    assert "documentElement.clientHeight" in fn
    assert "window.parent.innerHeight" in fn
    assert "viewportHeight()" in src.split("function autofitHeight(", 1)[1]
    assert "function fullscreenHeight(" not in src


def test_the_toolbar_says_what_its_buttons_do():
    """The three canvas buttons carried a native `title`, which never appeared:
    the hover target is the <svg> inside the button, and a tooltip is not looked
    up from there. The page draws them instead."""
    src = _VIEWER.read_text(encoding="utf-8")

    for tip in ("Fullscreen", "Download as PNG", "Copy what is selected"):
        assert f'data-tip="{tip}"' in src
        assert f'aria-label="{tip}"' in src
    assert "title=" not in src.split("<body>", 1)[1].split("</button>", 1)[0]
    # The icon must not eat the hover, or there is nothing to show a tip for.
    svg_rule = src[src.index("#fullscreen-btn svg, #download-btn svg") :]
    assert "pointer-events: none" in svg_rule[: svg_rule.index("}")]
    # Every later change of what a button says goes through the one helper.
    assert "btn.title =" not in src
    assert src.count("setButtonTip(") >= 4


def test_a_tooltip_steps_aside_for_whatever_is_under_the_button():
    """The tip drops under its button, where the details panel's card also
    floats — and that card is Streamlit's DOM in the parent, which always paints
    over this iframe, so a tip behind it is not dimmed but absent. The viewer
    asks the page what is at the spot and moves the tip beside the button when
    the answer is not itself."""
    src = _VIEWER.read_text(encoding="utf-8")
    fn = src[src.index("function placeTip(") :].split("\n}", 1)[0]
    assert "elementFromPoint" in fn
    assert "!== fe" in fn, "the test must be 'is the page showing us, or itself'"
    assert "classList.toggle('tip-left'" in fn
    assert ".tip-left::after" in src
    assert "addEventListener('mouseenter'" in src

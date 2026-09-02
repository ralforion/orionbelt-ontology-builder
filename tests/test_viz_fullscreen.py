"""Guards for the graph viewer's fullscreen behaviour (issue #189).

Both invariants here are only observable in a real browser, so they are pinned at
the source level: breaking either one silently drops fullscreen or repaints the
details panel behind it, and no other test would notice.
"""

import ast
import re
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


def test_fullscreen_hides_the_chrome_and_nothing_else():
    """Entering fullscreen is one thing: the class on the *parent page's* body.

    Fullscreening the canvas' own container put the whole of Streamlit's DOM —
    Display options, Find & focus, Path finder, Node options, the details panel
    — behind the fullscreen graph, so every one of them meant leaving fullscreen
    and going back in (issue #381).
    """
    src = _VIEWER.read_text(encoding="utf-8")

    enter = src[src.index("function enterFullscreen(") :].split("\n}", 1)[0]
    assert "setStage(true)" in enter, (
        "fullscreen is the chrome-hiding class on the page's body"
    )
    assert "getElementById('container')" not in enter, (
        "fullscreening the component's own container leaves every control "
        "outside it behind (issue #381)"
    )


def test_the_window_is_left_alone():
    """Fullscreen must not take the screen as well as the page.

    The button used to call requestFullscreen() on the page (and pywebview's
    toggle_fullscreen() on the desktop), which put the whole OS window into
    fullscreen. An ontology is built alongside other windows, and the OS has its
    own shortcut for anyone who does want the screen (issue #390).
    """
    # Comment lines are dropped: they are where the old behaviour is explained,
    # and the point is that no code does it any more.
    code = "\n".join(
        line
        for line in _VIEWER.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )

    for banned in (
        "requestFullscreen",
        "exitFullscreen",
        "fullscreenEnabled",
        "fullscreenElement",
        "orionbelt_toggle_fullscreen",
        "allowFullscreen",
    ):
        assert banned not in code, (
            f"{banned} takes the OS window into fullscreen with the graph (issue #390)"
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
    assert "setFullscreenIcon(stageOn())" in src
    assert "syncFullscreenState()" in src


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


def test_the_state_is_read_back_by_every_mount():
    """A re-mount lands in a document that knows nothing while the page may still
    be fullscreen, so the button would offer to enter what it is already in."""
    src = _VIEWER.read_text(encoding="utf-8")
    sync = src[src.index("function syncFullscreenState(") :].split("\n}", 1)[0]
    assert "stageOn()" in sync
    # ...and that is what a fresh render runs.
    assert "syncFullscreenState();" in src


def test_escape_leaves_fullscreen():
    """The browser used to do this for us, back when the page was the fullscreen
    element. Expanding inside the window means wiring Esc up by hand, in both
    documents: the key lands in the viewer's while the canvas has focus and in
    the page's while any of the controls do (issue #390)."""
    src = _VIEWER.read_text(encoding="utf-8")
    fn = src[src.index("function onEscape(") :].split("\n}", 1)[0]
    assert "'Escape'" in fn and "leaveFullscreen()" in fn
    assert "document.addEventListener('keydown', onEscape)" in src
    assert "d.addEventListener('keydown', onEscape)" in src


def test_the_page_listener_is_removed_with_the_document():
    """The listener is registered on the parent, which outlives this document by
    many re-mounts. Without the teardown each mount piles another dead one on."""
    src = _VIEWER.read_text(encoding="utf-8")
    assert "d.removeEventListener('keydown', onEscape)" in src
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
    """The iframe's own window.innerHeight is the height of the slot Streamlit
    gave it, not of the page, so it says nothing about the box to fill. The
    height comes from the page's viewport in both states — there is no separate
    fullscreen measurement left to drift (issue #177 follow-up)."""
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

    for tip in ("Maximize", "Download as PNG", "Copy what is selected"):
        assert f'data-tip="{tip}"' in src
        assert f'aria-label="{tip}"' in src
    assert "title=" not in src.split("<body>", 1)[1].split("</button>", 1)[0]
    # The icon must not eat the hover, or there is nothing to show a tip for.
    svg_rule = src[src.index("#fullscreen-btn svg, #download-btn svg") :]
    assert "pointer-events: none" in svg_rule[: svg_rule.index("}")]
    # Every later change of what a button says goes through the one helper.
    assert "btn.title =" not in src
    assert src.count("setButtonTip(") >= 4


def test_the_button_says_maximize_not_fullscreen():
    """What the button does is fill the browser window; the screen and the OS
    window are left alone (issue #390). So it is labelled the way a window
    control is — Maximize, and Restore once it is one — and the word fullscreen
    never reaches a user. Everything else here keeps the fullscreen names the
    issues behind it use."""
    src = _VIEWER.read_text(encoding="utf-8")
    fn = src[src.index("function setFullscreenIcon(") :].split("\n}", 1)[0]
    assert "'Restore' : 'Maximize'" in fn

    said = re.findall(r'(?:data-tip|aria-label)="([^"]*)"', src)
    said += re.findall(r"setButtonTip\([^,]+,\s*'([^']*)'", src)
    assert said, "the button labels are read from the page, so they must be found"
    for words in said:
        assert "fullscreen" not in words.lower(), f"{words!r} says fullscreen"


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

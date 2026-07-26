"""Guards for the graph viewer's fullscreen behaviour (issue #189).

Both invariants here are only observable in a real browser, so they are pinned at
the source level: breaking either one silently drops fullscreen or repaints the
details panel behind it, and no other test would notice.
"""

import ast
from pathlib import Path

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
    tree = ast.parse((_PKG / "app.py").read_text(encoding="utf-8"))
    placeholders = _status_placeholder_assignments(tree)
    assert placeholders, "expected a `status = st.empty()` placeholder in app.py"

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


def test_viewer_defers_selection_while_fullscreen():
    """Selections must not round-trip to Streamlit while the graph is fullscreen.

    A round-trip reruns the app and repaints the details panel / status bar
    behind the fullscreen graph; the last selection is flushed on exit instead,
    so the panel returns showing the node the user left selected.
    """
    src = _VIEWER.read_text(encoding="utf-8")

    assert "function sendSelection(" in src
    assert "function flushPendingSelection(" in src

    # Every selection event goes through the deferring helper, never straight to
    # setComponentValue.
    for event in ("selectNode", "selectEdge", "deselectNode", "deselectEdge"):
        handler = src.split(f"network.on('{event}'", 1)[1].split("});", 1)[0]
        assert "sendSelection(" in handler, f"{event} must use sendSelection()"
        assert "setComponentValue" not in handler, (
            f"{event} must not send to Streamlit directly (issue #189)"
        )

    # Both exit paths — the web Fullscreen API and the desktop overlay — flush.
    assert src.count("flushPendingSelection();") == 2

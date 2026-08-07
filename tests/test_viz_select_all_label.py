"""The "Select all" button states how many it would restore you to.

Whether the button is live is decided by ``disabled=not _narrowed``, and its only
other signal is the shown/total on the segmented control above — a different
widget, easy to miss. Without a count in its own label the greyed-out state reads
as an arbitrary disable rather than as "you already have all of them", so the
count is the point of the control and is pinned here.
"""

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "app.py"


def _select_all_button():
    """The ``st.button`` call that restores a node filter, as an AST node."""
    tree = ast.parse(_APP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "button"):
            continue
        for kw in node.keywords:
            if kw.arg == "key" and "viz_select_all" in ast.dump(kw.value):
                return node
    raise AssertionError("no st.button keyed viz_select_all found in app.py")


def test_the_label_carries_a_count():
    """A plain "Select all" cannot explain its own greyed-out state."""
    label = _select_all_button().args[0]
    assert isinstance(label, ast.JoinedStr), (
        "the button label must interpolate a count, not be a fixed string"
    )
    counted = [p for p in label.values if isinstance(p, ast.FormattedValue)]
    assert counted, "the button label must interpolate a count"
    assert any("_entries" in ast.dump(p) for p in counted), (
        "the count must be the kind's total, so the label says what the button "
        "would restore you to"
    )


def test_the_button_still_greys_out_when_nothing_is_hidden():
    """The count is only meaningful next to the enabled/disabled state."""
    disabled = [kw for kw in _select_all_button().keywords if kw.arg == "disabled"]
    assert disabled, "the button must stay gated on whether anything is hidden"
    assert "_narrowed" in ast.dump(disabled[0].value)

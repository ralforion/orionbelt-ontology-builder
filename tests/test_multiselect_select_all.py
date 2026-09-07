"""Which multiselects keep their "Select N matches" row (streamlit/streamlit#16841).

Streamlit 1.63 made Enter commit the first visible row of a multiselect, and
with two or more matches that row is the bulk one. ``_ENTER_INSERTS_JS`` takes
the first real option instead, on every multiselect, so the row itself stays
harmless and is kept wherever selecting everything is a coherent thing to want:
the three bulk delete pages, and the graph's entity filters, whose help text
points at it by name.

``select_all=False`` is passed only where selecting everything is not coherent.
These are source-level checks: the parameter is a rendering detail Streamlit's
test API does not report, and what is worth pinning is the decision per picker.
"""

import re
from pathlib import Path

VIEWS = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "views"


def _call(path: str, label: str) -> str:
    """The ``st.multiselect(...)`` call whose first argument is ``label``."""
    src = (VIEWS / path).read_text(encoding="utf-8")
    start = src.find("st.multiselect(")
    while start != -1:
        depth, i = 0, src.index("(", start)
        for j in range(i, len(src)):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    call = src[start : j + 1]
                    if label in call.split("\n")[1 if "\n" in call else 0]:
                        return call
                    break
        start = src.find("st.multiselect(", start + 1)
    raise AssertionError(f"no multiselect labelled {label!r} in {path}")


def test_a_picker_that_cannot_mean_all_hides_the_row():
    for path, label in (
        ("visualization.py", "Focus node(s)"),
        ("advanced.py", "Chain Properties (in order)"),
        ("advanced.py", "Key Properties"),
        ("skos.py", "Broader Concepts"),
    ):
        assert "select_all=False" in _call(path, label), f"{path}: {label}"


def test_the_bulk_pages_keep_the_row():
    """Selecting every match is the point of a bulk page, so the row stays."""
    for path, label in (
        ("classes.py", "Select classes to delete"),
        ("properties.py", "Select properties to delete"),
        ("individuals.py", "Select individuals to delete"),
    ):
        assert "select_all" not in _call(path, label), f"{path}: {label}"


def test_the_graph_filter_keeps_the_row_its_help_names():
    call = _call("visualization.py", "Select {_plural} to display")
    assert "select_all" not in call
    assert "'Select all'" in call, "the help text points at the row by name"


def test_the_shim_is_what_makes_the_row_safe_to_keep():
    """Every kept row is only harmless while Enter skips it."""
    ui = (VIEWS.parent / "ui.py").read_text(encoding="utf-8")
    assert "SELECT_ALL_NOTE" in ui
    assert re.search(r"var SENTINEL = /\^__\.\*__\$/", ui), "the bulk rows are skipped"

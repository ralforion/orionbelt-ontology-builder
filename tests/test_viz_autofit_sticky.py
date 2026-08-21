"""The autofit measurement and the sticky status bar must not fight (PR #309).

Neither is observable outside a real browser. The status bar pins itself to the
bottom of the window so it stays readable while the page scrolls; autofit sizes
the canvas from the rect of whatever follows it. A pinned element's rect reports
where it is *painted*, which once pinned is above the canvas's own edge — so
measuring it while pinned reserves nothing and the canvas grows until the bar
covers it. The measurement therefore has to un-pin first.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"
_VIZ = _PKG / "views" / "visualization.py"


def _function_body(src: str, name: str) -> str:
    """The text between the braces of ``function <name>(...) { ... }``."""
    start = src.index(f"function {name}(")
    depth = 0
    out: list[str] = []
    for i in range(src.index("{", start), len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(out)
        out.append(ch)
    raise AssertionError(f"unbalanced braces in {name}")


def test_the_status_bar_is_pinned():
    """The premise of the guard below: the bar really is sticky."""
    assert "position: sticky" in _VIZ.read_text()


def test_reserve_measurement_unpins_before_it_measures():
    body = _function_body(_VIEWER.read_text(), "autofitReserve")
    assert "unpinStickies()" in body, "autofitReserve no longer un-pins"
    assert "measureReserve()" in body
    # The measuring itself must stay in measureReserve, i.e. inside the un-pin:
    # a rect read here would be back to reading painted positions.
    assert "getBoundingClientRect" not in body


def test_unpinning_is_reversible():
    body = _function_body(_VIEWER.read_text(), "unpinStickies")
    assert "'static'" in body  # what it forces while measuring
    assert "removeProperty" in body  # and puts back afterwards

"""The graph canvas always fits the window; there is no fixed-height mode (#347).

"Fit to window" used to be a checkbox, with a Graph Height slider behind it. A
fixed height can only ever leave white space or overflow — and with the checkbox
off, collapsing the display options band freed room the canvas would not take,
while the checkbox that explained why was itself inside the collapsed band. So
the option is gone and the canvas is always fitted. The height still handed to
the component is a fallback for the one case the viewer cannot measure: a
browser that walls the parent window off from the component iframe.
"""

from pathlib import Path

from orionbelt_ontology_builder.ui import _VIZ_INT_RANGES, _VIZ_PERSIST_KEYS

_PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
_VIEWER = _PKG / "lib" / "graph_viewer" / "index.html"
_VIZ = _PKG / "views" / "visualization.py"


def test_the_page_offers_no_fixed_height():
    src = _VIZ.read_text()
    assert "Fit to window" not in src
    assert "Graph Height" not in src
    assert "viz_graph_height" not in src
    assert "viz_fit" not in src


def test_the_component_is_always_fitted():
    src = _VIZ.read_text()
    assert "autofit=True," in src
    assert "height=_GRAPH_FALLBACK_HEIGHT," in src


def test_neither_setting_is_persisted_any_more():
    """A browser holding the old pair must not resurrect the fixed height."""
    assert "fit" not in _VIZ_PERSIST_KEYS
    assert "graph_height" not in _VIZ_PERSIST_KEYS
    assert "graph_height" not in _VIZ_INT_RANGES


def test_the_viewer_fits_to_the_window():
    src = _VIEWER.read_text()
    # The fit height is the measurement, floored only at the 300px minimum.
    assert "return Math.max(Math.round(avail), 300);" in src
    # …and the passed height is what it falls back to when it cannot measure.
    assert "var height = args.height || 600;" in src

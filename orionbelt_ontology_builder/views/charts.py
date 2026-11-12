"""Vega-Lite specs for the dashboard's charts.

Pure functions from rows to a spec, so a test can check what is drawn
without a browser. Each chart is one series in the colour the caller passes
(the app's accent, which follows the theme), so none needs a legend, and every
value is printed beside its mark, so no reading depends on a tooltip. Text is
drawn in ``ink``, the theme's text colour, never in the series colour. Marks
are thin, rounded at the data end and square at the baseline.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: Thickness of a meter, and of a ranked bar, in pixels.
_METER = 8
_BAR = 12
#: Width of a column, in pixels.
_COLUMN = 20
#: Height of a meter's row (its line of text and its bar), and of a ranked
#: bar's: the height of the plot, axes and padding come on top.
_METER_ROW = 40
_BAR_ROW = 28
#: Fit the width to the column and leave the height to the spec. Streamlit's
#: default, ``fit``, takes the padding out of the height given, which left a
#: one-row chart about 18 pixels to draw in.
_AUTOSIZE = {"type": "fit-x", "contains": "padding"}
#: Room left past the longest bar for the value printed at its tip.
_HEADROOM = 1.2
#: More for a column, whose value sits above the cap, a line of text tall.
_COLUMN_HEADROOM = 1.35


def percent(have: int, total: int) -> int:
    """``have`` of ``total`` as a whole percentage, 0 for an empty total."""
    return round(100 * have / total) if total else 0


def meter_list(
    rows: Sequence[tuple[str, int, int]], color: str, *, ink: str
) -> dict[str, Any]:
    """One meter per ``(name, have, total)``: its name and figure on a line,
    and under them a bar on a track of the same hue."""
    values = [
        {
            "name": name,
            "share": have / total if total else 0.0,
            "figure": f"{have:,} of {total:,} · {percent(have, total)}%",
            "whole": 1,
        }
        for name, have, total in rows
    ]
    scale = {"domain": [0, 1]}
    # The text sits just above the row's middle and the bar just below it,
    # so the pair is centred in its row.
    above = {"type": "text", "baseline": "bottom", "dy": -2, "color": ink}
    below = {"size": _METER, "yOffset": _METER // 2 + 1}
    return {
        "autosize": _AUTOSIZE,
        "data": {"values": values},
        "height": _METER_ROW * len(values),
        "encoding": {
            "y": {"field": "name", "type": "nominal", "sort": None, "axis": None}
        },
        "layer": [
            {
                "mark": {
                    "type": "bar",
                    **below,
                    "color": color,
                    "opacity": 0.16,
                    "cornerRadiusEnd": _METER / 2,
                },
                "encoding": {
                    "x": {
                        "field": "whole",
                        "type": "quantitative",
                        "scale": scale,
                        "axis": None,
                    }
                },
            },
            {
                "mark": {
                    "type": "bar",
                    **below,
                    "color": color,
                    "cornerRadiusEnd": _METER / 2,
                },
                "encoding": {
                    "x": {
                        "field": "share",
                        "type": "quantitative",
                        "scale": scale,
                        "axis": None,
                    },
                    "tooltip": [
                        {"field": "name", "title": "Coverage"},
                        {"field": "figure", "title": "Have"},
                    ],
                },
            },
            {
                "mark": {**above, "align": "left"},
                "encoding": {"x": {"value": 0}, "text": {"field": "name"}},
            },
            {
                "mark": {**above, "align": "right"},
                "encoding": {"x": {"value": "width"}, "text": {"field": "figure"}},
            },
        ],
    }


def ranked_bars(
    rows: Sequence[tuple[str, int]], color: str, *, what: str, ink: str
) -> dict[str, Any]:
    """Horizontal bars, one per ``(name, count)`` in the order given (largest
    first), with the count at each bar's tip. ``what`` names the counts in
    the tooltip."""
    values = [{"name": name, "count": count} for name, count in rows]
    scale = {"domain": [0, max((c for _, c in rows), default=1) * _HEADROOM]}
    x = {"field": "count", "type": "quantitative", "scale": scale, "axis": None}
    return {
        "autosize": _AUTOSIZE,
        "data": {"values": values},
        "height": _BAR_ROW * len(values),
        "encoding": {
            "y": {
                "field": "name",
                "type": "nominal",
                "sort": None,
                "axis": {
                    "title": None,
                    "labelLimit": 220,
                    # Every name is the reading; Vega would drop one it thinks
                    # crowds its neighbour.
                    "labelOverlap": False,
                    "ticks": False,
                    "domain": False,
                },
            }
        },
        "layer": [
            {
                "mark": {
                    "type": "bar",
                    "size": _BAR,
                    "color": color,
                    "cornerRadiusEnd": 4,
                },
                "encoding": {
                    "x": x,
                    "tooltip": [
                        {"field": "name", "title": "Name"},
                        {"field": "count", "title": what, "format": ","},
                    ],
                },
            },
            {
                "mark": {
                    "type": "text",
                    "align": "left",
                    "baseline": "middle",
                    "dx": 4,
                    "color": ink,
                },
                "encoding": {"x": x, "text": {"field": "count", "format": ","}},
            },
        ],
    }


def column_bars(
    rows: Sequence[tuple[str, int]],
    color: str,
    *,
    x_title: str,
    what: str,
    ink: str,
) -> dict[str, Any]:
    """Columns, one per ``(category, count)`` in the order given, with the
    count on each cap. For ordered categories, such as depth levels."""
    values = [{"name": name, "count": count} for name, count in rows]
    scale = {"domain": [0, max((c for _, c in rows), default=1) * _COLUMN_HEADROOM]}
    y = {"field": "count", "type": "quantitative", "scale": scale, "axis": None}
    return {
        "autosize": _AUTOSIZE,
        "data": {"values": values},
        "height": 150,
        "encoding": {
            "x": {
                "field": "name",
                "type": "ordinal",
                "sort": None,
                "axis": {
                    "title": x_title,
                    "labelAngle": 0,
                    "ticks": False,
                    "domain": False,
                },
            }
        },
        "layer": [
            {
                "mark": {
                    "type": "bar",
                    "size": _COLUMN,
                    "color": color,
                    "cornerRadiusEnd": 4,
                },
                "encoding": {
                    "y": y,
                    "tooltip": [
                        {"field": "name", "title": x_title},
                        {"field": "count", "title": what, "format": ","},
                    ],
                },
            },
            {
                "mark": {
                    "type": "text",
                    "baseline": "bottom",
                    "dy": -3,
                    "color": ink,
                },
                "encoding": {"y": y, "text": {"field": "count", "format": ","}},
            },
        ],
    }


def describe(rows: Sequence[tuple[Any, ...]]) -> str:
    """A text alternative for a chart: its rows, one per clause."""
    return "; ".join(
        " ".join(f"{v:,}" if isinstance(v, int) else str(v) for v in row)
        for row in rows
    )

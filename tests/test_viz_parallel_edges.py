"""Parallel edges between the same two nodes must not overlap (issue #245).

Two entities can be connected several times over — disjointWith and an object
property, say — and vis draws every edge with the same global curve unless each
is told otherwise. The builder gives each one a distinct side and roundness so
they fan out instead of lying on top of each other.
"""

import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder/app.py"


def _curves(n):
    """The (side, roundness) pairs the builder assigns to ``n`` parallel edges.

    A direct port of the loop in ``render_visualization``: the arithmetic sits
    inside a 400-line function that cannot be called in isolation, and it is the
    arithmetic that was wrong.
    """
    return [
        ("curvedCW" if i % 2 == 0 else "curvedCCW", round(0.2 * (i // 2 + 1), 2))
        for i in range(n)
    ]


@pytest.mark.parametrize("count", range(2, 9))
def test_every_parallel_edge_gets_its_own_curve(count):
    """The bug: ``(i + 1) // 2`` was 1 for both i=1 and i=2, so the third edge
    was drawn exactly on top of the first, and every odd one after it repeated
    an earlier curve."""
    curves = _curves(count)
    assert len(set(curves)) == count, f"overlapping curves in {curves}"


def test_a_pair_curves_to_opposite_sides():
    """Two edges is the common case: one each way, equally bowed."""
    assert _curves(2) == [("curvedCW", 0.2), ("curvedCCW", 0.2)]


def test_each_further_pair_bows_wider():
    """So the third and fourth clear the first two rather than crowding them."""
    curves = _curves(6)
    assert [r for _, r in curves] == [0.2, 0.2, 0.4, 0.4, 0.6, 0.6]


def test_the_builder_uses_this_arithmetic():
    """Pin the port against the real loop, so the two cannot drift apart."""
    src = APP.read_text(encoding="utf-8")
    block = src.split("# Spread parallel edges so they don't overlap", 1)[1]
    block = block.split("# Generate and display", 1)[0]
    assert "0.2 * (i // 2 + 1)" in block, (
        "the roundness step changed; update _curves above to match"
    )
    assert '"curvedCW" if i % 2 == 0 else "curvedCCW"' in block

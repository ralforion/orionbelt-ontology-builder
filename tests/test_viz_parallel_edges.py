"""Parallel edges between the same two nodes must not overlap (issue #245).

Two entities can be connected several times over — disjointWith and an object
property, say — and vis draws every edge with the same global curve unless each
is told otherwise. The builder gives each one a distinct side and roundness so
they fan out instead of lying on top of each other.

Three relations between one pair is enough to reproduce it, so these render the
real ``render_visualization`` and read the curves out of the graph payload
rather than re-implementing the arithmetic.
"""

import json
import os
from collections import defaultdict

import pytest
from streamlit.testing.v1 import AppTest


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("A")
        om.add_class("B")
        # As many relations between the same pair as asked for. Three is the
        # count the old arithmetic broke on: the third repeated the first.
        rels = list(om.CLASS_RELATIONS)[: int(os.environ["N_RELS"])]
        for n, rel in enumerate(rels):
            # MIXED points every second relation the other way, which is the
            # case the reporter hit: "A disjointWith B" alongside
            # "B nextItem A" (issue #245).
            if os.environ.get("MIXED") and n % 2:
                om.add_class_relation("B", rel, "A")
            else:
                om.add_class_relation("A", rel, "B")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
    app.render_visualization()


def _curves(n_rels, mixed=False):
    """Render and return each A-B edge's curve as an *absolute* side.

    ``curvedCW`` is clockwise along the edge's own from-to, so the raw label
    says nothing on its own: two edges pointing opposite ways with opposite
    labels sit on the same side of the pair. Normalising to the group's
    canonical order is what the eye actually sees.
    """
    os.environ["N_RELS"] = str(n_rels)
    os.environ["MIXED"] = "1" if mixed else ""
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    edges = json.loads(data["edges"])
    groups = defaultdict(list)
    for edge in edges:
        groups[tuple(sorted((edge["from"], edge["to"])))].append(edge)
    key, biggest = max(groups.items(), key=lambda kv: len(kv[1]))
    out = []
    for edge in biggest:
        smooth = edge.get("smooth") or {}
        side = smooth.get("type")
        if side and edge["from"] != key[0]:
            side = "curvedCCW" if side == "curvedCW" else "curvedCW"
        out.append((side, smooth.get("roundness")))
    return out


@pytest.mark.parametrize("n_rels", [2, 3])
def test_every_parallel_edge_gets_its_own_curve(n_rels):
    """The bug: the third edge was drawn with exactly the first one's curve, so
    two entities related three ways showed only two lines."""
    curves = _curves(n_rels)
    assert len(curves) == n_rels
    assert len(set(curves)) == n_rels, f"overlapping curves in {curves}"


def test_a_pair_curves_to_opposite_sides():
    """The common case: one edge each way, equally bowed."""
    assert set(_curves(2)) == {("curvedCW", 0.2), ("curvedCCW", 0.2)}


def test_the_third_edge_bows_wider_rather_than_repeating_the_first():
    curves = _curves(3)
    assert sorted(r for _, r in curves) == [0.2, 0.2, 0.4]


def test_a_single_edge_is_left_alone():
    """Nothing to spread, so the global curve applies and no per-edge override
    is emitted."""
    os.environ["N_RELS"] = "1"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    edges = json.loads(at.session_state["last_graph_data"]["edges"])
    assert edges, "no edge was drawn"
    assert all("smooth" not in e for e in edges)


@pytest.mark.parametrize("n_rels", [2, 3])
def test_edges_pointing_opposite_ways_still_bow_apart(n_rels):
    """The reported case: `A disjointWith B` next to `B nextItem A`.

    Alternating the label alone puts these on the *same* side, because the
    label is relative to each edge's own direction and the two flips cancel.
    """
    curves = _curves(n_rels, mixed=True)
    assert len(set(curves)) == n_rels, f"overlapping curves in {curves}"


def test_a_reversed_pair_lands_on_opposite_sides():
    sides = [side for side, _ in _curves(2, mixed=True)]
    assert set(sides) == {"curvedCW", "curvedCCW"}

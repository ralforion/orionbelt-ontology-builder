"""Editing a relation or restriction from the Visualization graph (issue #152).

Stage 1 gave Relations and Restrictions their own row editors. This is stage 2:
a class relation or a restriction drawn as a graph edge resolves back to the
axiom it stands for, so the details panel edits that axiom and "Open full
editor" lands on its row.

The edge ids are read out of the real graph payload and fed straight to the
panel, so the two halves are checked against each other rather than against a
hand-written id. Everything is seeded through the environment because
``AppTest.from_function`` executes the script source in a fresh namespace
without the test's closures.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Bicycle", "Wheel", "Engine", "Vehicle"):
            om.add_class(name)
        om.add_class("Tandem", parent="Bicycle")
        om.add_object_property("hasPart")
        om.add_class_relation("Bicycle", "disjointWith", "Engine")
        # Two restrictions on one property differing only in value: the panel
        # has to edit the edge that was clicked, not the first match.
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Engine")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done.
        st.session_state["_viz_settings_restored"] = True
        for key in ("show_classes", "show_obj_props"):
            st.session_state[f"_viz_cfg_{key}"] = True

    mode = os.environ["VIZ_EDIT_MODE"]
    ename = os.environ["VIZ_EDIT_ENAME"]
    if mode == "graph":
        app.render_visualization()
    elif mode == "panel":
        ont = st.session_state.ontology
        app._render_panel_entity_editor(
            ont,
            os.environ["VIZ_EDIT_NTYPE"],
            ename,
            {"title": "tooltip text"},
            ont.get_classes(),
            ont.get_object_properties(),
            ont.get_data_properties(),
            ont.get_individuals(),
        )
    elif mode == "relations":
        # The request "Open full editor" leaves behind, set here rather than
        # through a second AppTest run: these pages' tab picker is a
        # segmented_control, which AppTest cannot re-serialize.
        if ename:
            st.session_state["_rel_open_edge"] = app._edge_id_parts(ename, 3)
        app.render_relations()
    else:
        if ename:
            st.session_state["_rest_open_edge"] = app._edge_id_parts(ename, 4)
        app.render_restrictions()


def _run(mode, ntype="", ename=""):
    os.environ["VIZ_EDIT_MODE"] = mode
    os.environ["VIZ_EDIT_NTYPE"] = ntype
    os.environ["VIZ_EDIT_ENAME"] = ename
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


@pytest.fixture(scope="module")
def graph():
    """The rendered graph's edges, plus the seeded ontology."""
    at = _run("graph")
    return json.loads(at.session_state["last_graph_data"]["edges"]), at.session_state[
        "ontology"
    ]


def _edges(graph, ntype):
    return [e for e in graph[0] if e.get("ntype") == ntype]


def _uris(om):
    return {c["name"]: c["uri"] for c in om.get_classes()}


def _rows(om):
    return sorted((r["property"], r["type"], r["value"]) for r in om.get_restrictions())


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)


# --- what the graph now puts on its edges -----------------------------------


def test_class_relation_edges_carry_their_whole_triple(graph):
    om = graph[1]
    uris = _uris(om)
    decoded = {
        app._edge_id_parts(e["ename"], 3) for e in _edges(graph, "Class Relation")
    }
    # Both the hierarchy edges and the equivalent/disjoint ones are editable
    # rows on the Relations page, so both are tagged.
    assert (uris["Tandem"], "subClassOf", uris["Bicycle"]) in decoded
    assert (uris["Bicycle"], "disjointWith", uris["Engine"]) in decoded


def test_restriction_edges_are_typed_as_restrictions_not_properties(graph):
    om = graph[1]
    rest_edges = _edges(graph, "Restriction")
    assert len(rest_edges) == 2
    # The dashed edge used to be tagged "Object Property", which opened the
    # property definition instead of the axiom that was clicked.
    assert not [e for e in rest_edges if e.get("ntype") == "Object Property"]
    restrictions = om.get_restrictions()
    for edge in rest_edges:
        parts = app._edge_id_parts(edge["ename"], 4)
        assert parts is not None
        matched = [r for r in restrictions if app._restriction_matches_edge(r, parts)]
        assert len(matched) == 1, "an edge must name exactly one restriction"


# --- the details panel ------------------------------------------------------


def _panel_key(ename, prefix):
    return f"{prefix}_panel_{app._uid(ename)}"


def test_panel_opens_the_clicked_relation_with_its_own_values(graph):
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(uris["Bicycle"], "disjointWith", uris["Engine"])
    at = _run("panel", "Class Relation", ename)

    assert at.selectbox(key=_panel_key(ename, "es")).value == "Bicycle"
    assert at.selectbox(key=_panel_key(ename, "et")).value == "disjointWith"
    assert at.selectbox(key=_panel_key(ename, "eo")).value == "Engine"


def test_panel_saves_an_edited_relation(graph):
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(uris["Bicycle"], "disjointWith", uris["Engine"])
    at = _run("panel", "Class Relation", ename)

    at.selectbox(key=_panel_key(ename, "et")).set_value("equivalentClass")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    edited = at.session_state["ontology"]
    triples = {
        (r["subject"], r["relation"], r["object"]) for r in edited.get_class_relations()
    }
    assert ("Bicycle", "equivalentClass", "Engine") in triples
    assert ("Bicycle", "disjointWith", "Engine") not in triples


def test_panel_edits_the_restriction_the_edge_stands_for(graph):
    """The sibling restriction on the same class and property stays untouched."""
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(
        uris["Bicycle"],
        om.get_object_properties()[0]["uri"],
        "someValuesFrom",
        uris["Wheel"],
    )
    at = _run("panel", "Restriction", ename)

    assert at.text_input(key=_panel_key(ename, "er_val")).value == "Wheel"
    at.text_input(key=_panel_key(ename, "er_val")).set_value("Vehicle")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Vehicle"),
    ]


def test_panel_editor_offers_no_cancel(graph):
    """The panel follows the graph selection, so there is nothing to cancel to."""
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(uris["Bicycle"], "disjointWith", uris["Engine"])
    at = _run("panel", "Class Relation", ename)
    assert [b.label for b in at.button] == ["💾 Save"]


def test_panel_reports_an_axiom_that_is_no_longer_there(graph):
    """A selection outlives the graph it was made in — an edge deleted elsewhere,
    or replaced by the panel's own edit — so a stale one has to say so rather
    than edit whatever is at hand."""
    om = graph[1]
    uris = _uris(om)
    gone = app._edge_id(uris["Bicycle"], "equivalentClass", uris["Wheel"])
    at = _run("panel", "Class Relation", gone)
    assert not at.button
    assert "This relation was edited or removed. Click an edge to pick one up." in [
        c.value for c in at.caption
    ]

    gone_rest = app._edge_id(
        uris["Wheel"], uris["Bicycle"], "allValuesFrom", uris["Engine"]
    )
    at = _run("panel", "Restriction", gone_rest)
    assert not at.button
    assert "This restriction was edited or removed. Click an edge to pick one up." in [
        c.value for c in at.caption
    ]


# --- "Open full editor" lands on the row ------------------------------------


def test_open_full_editor_opens_the_relations_row(graph):
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(uris["Bicycle"], "disjointWith", uris["Engine"])
    at = _run("relations", ename=ename)

    row_key = app._uid(f"{uris['Bicycle']}|disjointWith|{uris['Engine']}")
    assert at.session_state["active_crel"] == (row_key, "edit")
    assert at.selectbox(key=f"et_{row_key}").value == "disjointWith"
    # The request is consumed, so a later render doesn't keep reopening it.
    assert "_rel_open_edge" not in at.session_state


def test_open_full_editor_opens_the_restrictions_row(graph):
    om = graph[1]
    uris = _uris(om)
    ename = app._edge_id(
        uris["Bicycle"],
        om.get_object_properties()[0]["uri"],
        "someValuesFrom",
        uris["Wheel"],
    )
    at = _run("restrictions", ename=ename)

    # One editor, on the Wheel restriction rather than its Engine sibling.
    values = [i.value for i in at.text_input if i.key and i.key.startswith("er_val_")]
    assert values == ["Wheel"]
    assert "_rest_open_edge" not in at.session_state


def test_every_selectable_graph_type_has_an_editor_page(graph):
    """The Open button only shows for a mapped type, so a new edge or node
    kind that forgets its page silently loses the jump."""
    types = {e.get("ntype") for e in graph[0] if e.get("ntype")}
    assert types
    assert types <= set(app._PAGE_BY_TYPE)

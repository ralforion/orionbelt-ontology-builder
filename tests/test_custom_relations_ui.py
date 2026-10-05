"""Custom relations on the Relations page and in the graph (issue #484).

Seeded through the environment, like test_viz_relation_restriction_edit.py,
because ``AppTest.from_function`` runs the script without the test's closures.
"""

import json
import os

import pytest
from case_pickers import picker
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app

NS = "http://example.org/ontology#"


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Pnt", "Step1", "Step2", "Step3"):
            om.add_class(name)
        om.add_individual("alice", "Step1")
        om.add_custom_relation("Step1", "nextItem", "Step2")
        om.add_custom_relation("alice", "relatedTo", "Step3")
        om.add_annotation("Step1", "wikidataId", "Q5")
        om.add_restriction("Pnt", "follows", "someValuesFrom", "Step1")
        om.add_restriction("Step2", "follows", "someValuesFrom", "Step3")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["rel_active_tab"] = os.environ.get(
            "CUSREL_TAB", "View Relations"
        )
        for key in ("show_classes", "show_individuals", "show_annotations"):
            st.session_state[f"_viz_cfg_{key}"] = True

    mode = os.environ["CUSREL_MODE"]
    ename = os.environ.get("CUSREL_ENAME", "")
    if mode == "graph":
        app.render_visualization()
    elif mode == "panel":
        ont = st.session_state.ontology
        app._render_panel_entity_editor(
            ont,
            "Custom Relation",
            ename,
            {"title": "tooltip text"},
            ont.get_classes(),
            ont.get_object_properties(),
            ont.get_data_properties(),
            ont.get_individuals(),
        )
    else:
        if ename:
            st.session_state["_rel_open_custom_edge"] = app._edge_id_parts(ename, 3)
        app.render_relations()


def _run(mode, tab="View Relations", ename=""):
    os.environ["CUSREL_MODE"] = mode
    os.environ["CUSREL_TAB"] = tab
    os.environ["CUSREL_ENAME"] = ename
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _rels(at):
    return {
        (r["subject"], r["relation"], r["object"])
        for r in at.session_state["ontology"].get_custom_relations()
    }


def _submit(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)
    assert not at.exception, at.exception


# --- the graph -----------------------------------------------------------------


@pytest.fixture(scope="module")
def graph():
    at = _run("graph")
    data = at.session_state["last_graph_data"]
    return json.loads(data["nodes"]), json.loads(data["edges"])


def test_each_custom_relation_is_a_pink_labelled_edge(graph):
    _nodes, edges = graph
    custom = [e for e in edges if e.get("ntype") == "Custom Relation"]
    assert {(e["label"], e["color"]) for e in custom} == {
        ("nextItem", app.CUSTOM_RELATION_COLOR),
        ("relatedTo", app.CUSTOM_RELATION_COLOR),
    }
    # Solid, so they read apart from the dashed restriction edges.
    assert not any(e.get("dashes") for e in custom)


def test_an_edge_joins_whatever_kinds_its_ends_are_drawn_as(graph):
    _nodes, edges = graph
    (link,) = [e for e in edges if e.get("label") == "relatedTo"]
    assert link["from"] == f"ind_{app._uid(NS + 'alice')}"
    assert link["to"] == app._uid(NS + "Step3")


def test_a_custom_relation_is_not_also_an_annotation_box(graph):
    nodes, _edges = graph
    boxes = {n["label"] for n in nodes if n.get("ntype") == "Annotation"}
    assert "Q5" in boxes  # an ordinary annotation still is one
    assert not any(NS in label for label in boxes)


def test_the_custom_relation_edge_has_an_editor_page(graph):
    assert "Custom Relation" in app._PAGE_BY_TYPE


# --- the details panel ------------------------------------------------------------


def _ename(subject, relation, obj):
    return app._edge_id(NS + subject, NS + relation, NS + obj)


def test_the_panel_edits_the_clicked_relation():
    at = _run("panel", ename=_ename("Step1", "nextItem", "Step2"))
    key = app._uid(_ename("Step1", "nextItem", "Step2"))
    assert at.selectbox(key=f"et_panel_{key}").value == "nextItem"

    picker(at, f"eo_panel_{key}").set_value("Class: Step3")
    _submit(at, "💾 Save")

    assert _rels(at) == {
        ("Step1", "nextItem", "Step3"),
        ("alice", "relatedTo", "Step3"),
    }


def test_the_panel_says_when_the_relation_is_gone():
    at = _run("panel", ename=_ename("Step1", "nextItem", "Step3"))
    assert "This relation was edited or removed. Click an edge to pick one up." in [
        c.value for c in at.caption
    ]


# --- the Relations page ------------------------------------------------------------


def test_the_list_shows_custom_relations():
    at = _run("relations")
    assert len([b for b in at.button if (b.key or "").startswith("del_cusrel_")]) == 2


def test_open_full_editor_opens_the_row():
    ename = _ename("Step1", "nextItem", "Step2")
    at = _run("relations", ename=ename)

    row_key = app._uid(f"{NS}Step1|{NS}nextItem|{NS}Step2")
    assert at.session_state["active_cusrel"] == (row_key, "edit")
    assert "_rel_open_custom_edge" not in at.session_state


def test_adding_a_relation_under_a_new_name():
    at = _run("relations", tab="Custom Relations")
    picker(at, "cusrel_subject").set_value("Class: Step2")
    picker(at, "cusrel_object").set_value("Class: Step3")
    at.text_input(key="cusrel_new").set_value("nextItem")
    _submit(at, "Add Custom Relation")

    assert ("Step2", "nextItem", "Step3") in _rels(at)


def test_a_refused_name_is_reported_and_nothing_is_added():
    at = _run("relations", tab="Custom Relations")
    picker(at, "cusrel_subject").set_value("Class: Step2")
    picker(at, "cusrel_object").set_value("Class: Step3")
    at.text_input(key="cusrel_new").set_value("seeAlso")
    _submit(at, "Add Custom Relation")

    assert any("standard vocabulary" in e.value for e in at.error)
    assert len(_rels(at)) == 2


def test_converting_restrictions_moves_them():
    at = _run("relations", tab="Custom Relations")
    conv = at.selectbox(key="cusrel_conv_prop")
    assert conv.value == NS + "follows"
    assert conv.format_func(conv.value) == "follows (2 links)"
    _submit(at, "Convert")

    om = at.session_state["ontology"]
    assert {("Pnt", "follows", "Step1"), ("Step2", "follows", "Step3")} <= _rels(at)
    assert not [r for r in om.get_restrictions() if r["property"] == "follows"]


def test_keeping_the_restrictions_under_the_same_name_is_refused():
    at = _run("relations", tab="Custom Relations")
    at.radio(key="cusrel_conv_mode").set_value("Keep them (copy)")
    _submit(at, "Convert")

    assert any("OWL 2 DL" in e.value for e in at.error)
    assert len(_rels(at)) == 2


def _same_name_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("A")
        om.add_class("B")
        # Two relations sharing a local name, with no prefix bound for either,
        # linking the same two classes.
        om.add_custom_relation("A", "http://one.example/next", "B")
        om.add_custom_relation("A", "http://two.example/next", "B")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["rel_active_tab"] = "View Relations"
    app.render_relations()


def test_two_relations_sharing_a_name_are_two_rows():
    """Read as one, they collided on the row key and the page crashed."""
    at = AppTest.from_function(_same_name_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert len([b for b in at.button if (b.key or "").startswith("del_cusrel_")]) == 2


def test_deleting_one_of_them_deletes_that_one():
    at = AppTest.from_function(_same_name_script)
    at.run(timeout=120)
    key = app._uid(
        "http://example.org/ontology#A|http://two.example/next|"
        "http://example.org/ontology#B"
    )
    at.button(key=f"del_cusrel_{key}").click().run(timeout=120)
    assert not at.exception, at.exception
    assert [
        r["relation_uri"] for r in at.session_state["ontology"].get_custom_relations()
    ] == ["http://one.example/next"]


def _same_name_conversion_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("A", "B", "C"):
            om.add_class(name)
        om.add_restriction("A", "http://one.example/next", "someValuesFrom", "B")
        om.add_restriction("B", "http://two.example/next", "someValuesFrom", "C")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["rel_active_tab"] = "Custom Relations"
    app.render_relations()


def test_the_conversion_picker_offers_same_named_properties_apart():
    """Keyed by caption, one overwrote the other and could not be picked."""
    at = AppTest.from_function(_same_name_conversion_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    conv = at.selectbox(key="cusrel_conv_prop")
    assert set(conv.options) == {
        "http://one.example/next (1 link)",
        "http://two.example/next (1 link)",
    }

    conv.set_value("http://two.example/next")
    next(b for b in at.button if b.label == "Convert").click().run(timeout=120)
    assert not at.exception, at.exception
    assert [
        r["relation_uri"] for r in at.session_state["ontology"].get_custom_relations()
    ] == ["http://two.example/next"]


# --- and back again (issue #494) -------------------------------------------------------


def test_the_reverse_picker_offers_only_relations_between_classes():
    """relatedTo links an individual, which has no restriction to become."""
    at = _run("relations", tab="Custom Relations")
    back = at.selectbox(key="cusrel_back_rel")
    assert back.options == ["nextItem (1 link)"]


def test_converting_links_back_moves_them_into_restrictions():
    at = _run("relations", tab="Custom Relations")
    _submit(at, "Convert back")

    om = at.session_state["ontology"]
    assert _rels(at) == {("alice", "relatedTo", "Step3")}
    assert [
        (r["applied_to"], r["type"], r["value"])
        for r in om.get_restrictions()
        if r["property"] == "nextItem"
    ] == [(["Step1"], "someValuesFrom", "Step2")]


def test_keeping_the_links_under_the_same_name_is_refused():
    at = _run("relations", tab="Custom Relations")
    at.radio(key="cusrel_back_mode").set_value("Keep them (copy)")
    _submit(at, "Convert back")

    assert any("OWL 2 DL" in e.value for e in at.error)
    assert ("Step1", "nextItem", "Step2") in _rels(at)

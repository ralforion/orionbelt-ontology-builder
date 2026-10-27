"""A colour of the user's own for a property's edges on the graph (issue #160).

Every kind of edge has one colour, so two object properties, or two custom
relations, look alike. A property can be given its own; the colours are a
display setting kept with the other graph settings, keyed by property URI.

The graph is seeded through the environment, like test_custom_relations_ui.py,
because ``AppTest.from_function`` runs the script without the test's closures.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app, ui

NS = "http://example.org/ontology#"
RED, GREEN, BLUE = "#e53935", "#43a047", "#1e88e5"


def _script():
    import json
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("A", "B", "C"):
            om.add_class(name)
        om.add_object_property("hasPart", domain="A", range_="B")
        om.add_object_property("touches", domain="B", range_="C")
        om.add_restriction("C", "hasPart", "someValuesFrom", "A")
        om.add_individual("a1", "A")
        om.add_individual("b1", "B")
        om.add_individual_property("a1", "hasPart", "b1")
        om.add_custom_relation("A", "nextItem", "C")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        for key in ("show_classes", "show_individuals", "show_ind_edges"):
            st.session_state[f"_viz_cfg_{key}"] = True
        st.session_state["_viz_cfg_property_colors"] = json.loads(
            os.environ["PCOLOR_MAP"]
        )
    app.render_visualization()


@pytest.fixture(scope="module")
def edges():
    os.environ["PCOLOR_MAP"] = json.dumps(
        {NS + "hasPart": RED, NS + "nextItem": GREEN, NS + "elsewhere": BLUE}
    )
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return json.loads(at.session_state["last_graph_data"]["edges"])


def _by(edges, ntype=None, label=None):
    return [
        e
        for e in edges
        if (ntype is None or e.get("ntype") == ntype)
        and (label is None or e.get("label") == label)
    ]


def test_every_edge_of_a_coloured_property_takes_its_colour(edges):
    (prop,) = _by(edges, "Object Property", "hasPart")
    (rest,) = _by(edges, "Restriction", "hasPart")
    (assertion,) = [
        e for e in edges if e.get("label") == "hasPart" and not e.get("ntype")
    ]
    for edge in (prop, rest, assertion):
        assert edge["color"] == RED
        assert edge["pcolor"] == "hasPart", "the legend names it by this"
    assert rest["dashes"], "a restriction stays dashed in its new colour"


def test_a_custom_relation_takes_its_colour(edges):
    (rel,) = _by(edges, "Custom Relation", "nextItem")
    assert rel["color"] == GREEN


def test_the_other_edges_keep_the_colour_of_their_kind(edges):
    (other,) = _by(edges, "Object Property", "touches")
    assert other["color"] == "#2196F3"
    assert "pcolor" not in other


def test_a_new_colour_redraws_the_graph_at_once():
    """The graph is cached by a key; a colour has to be part of it, or setting
    one left the graph as it was until something else rebuilt it."""
    os.environ["PCOLOR_MAP"] = json.dumps({})
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    first = json.loads(at.session_state["last_graph_data"]["edges"])
    (prop,) = _by(first, "Object Property", "touches")
    assert prop["color"] == "#2196F3"

    at.session_state["_viz_cfg_property_colors"] = {NS + "touches": RED}
    at.run(timeout=120)
    assert not at.exception, at.exception
    second = json.loads(at.session_state["last_graph_data"]["edges"])
    (prop,) = _by(second, "Object Property", "touches")
    assert prop["color"] == RED


# --- the setting -------------------------------------------------------------


def test_only_well_formed_colours_are_kept():
    stored = {
        NS + "a": "#ABCDEF",
        NS + "b": "red",
        NS + "c": "#12345",
        "": "#123456",
        NS + "d": 7,
        3: "#123456",
    }
    assert ui.clean_property_colors(stored) == {NS + "a": "#abcdef"}
    assert ui.clean_property_colors(["#123456"]) == {}


def test_past_the_cap_the_oldest_go_first():
    many = {f"{NS}p{i}": "#000000" for i in range(ui.PROPERTY_COLOR_MAX + 3)}
    kept = ui.clean_property_colors(many)
    assert len(kept) == ui.PROPERTY_COLOR_MAX
    assert f"{NS}p0" not in kept
    assert f"{NS}p{ui.PROPERTY_COLOR_MAX + 2}" in kept


def test_set_and_reset_through_the_popover_callbacks(monkeypatch):
    state: dict = {
        "_viz_cfg_property_colors": {NS + "old": BLUE, NS + "hasPart": GREEN},
        ui.VIZ_PROPERTY_COLOR_PICK: NS + "hasPart",
        ui.VIZ_PROPERTY_COLOR_VALUE: RED,
    }
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.viz_set_property_color()
    assert state["_viz_cfg_property_colors"] == {NS + "old": BLUE, NS + "hasPart": RED}
    assert list(state["_viz_cfg_property_colors"])[-1] == NS + "hasPart", (
        "a colour just set is the newest, the last to go at the cap"
    )
    assert state["_viz_settings_dirty"] is True

    ui.viz_reset_property_color(NS + "hasPart")
    assert state["_viz_cfg_property_colors"] == {NS + "old": BLUE}


def test_set_needs_a_property_and_a_colour(monkeypatch):
    for pick, value in ((None, RED), (NS + "p", "not a colour")):
        state: dict = {
            ui.VIZ_PROPERTY_COLOR_PICK: pick,
            ui.VIZ_PROPERTY_COLOR_VALUE: value,
        }
        monkeypatch.setattr(ui.st, "session_state", state)
        ui.viz_set_property_color()
        assert "_viz_cfg_property_colors" not in state
        assert "_viz_settings_dirty" not in state


def test_picking_a_coloured_property_shows_its_colour(monkeypatch):
    state: dict = {
        "_viz_cfg_property_colors": {NS + "hasPart": RED},
        ui.VIZ_PROPERTY_COLOR_PICK: NS + "hasPart",
        ui.VIZ_PROPERTY_COLOR_VALUE: BLUE,
    }
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.viz_property_color_picked()
    assert state[ui.VIZ_PROPERTY_COLOR_VALUE] == RED


def test_the_colours_are_saved_and_restored_with_the_graph_settings(
    monkeypatch, tmp_path
):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    saving: dict = {
        "_viz_settings_dirty": True,
        "_viz_cfg_property_colors": {NS + "hasPart": RED},
    }
    monkeypatch.setattr(ui.st, "session_state", saving)
    ui._persist_viz_settings()
    stored = json.loads(cfg_file.read_text())["viz_settings"]
    assert stored["property_colors"] == {NS + "hasPart": RED}

    restored: dict = {}
    monkeypatch.setattr(ui.st, "session_state", restored)
    ui._apply_viz_settings(
        {"property_colors": {NS + "hasPart": RED, NS + "x": "nope"}},
        {"property_colors": {}},
    )
    assert restored["_viz_cfg_property_colors"] == {NS + "hasPart": RED}


def test_an_assertion_row_names_its_property(om):
    om.add_class("A")
    om.add_individual("a1", "A")
    om.add_individual("a2", "A")
    om.add_individual_property("a1", "knows", "a2")
    (ind,) = [i for i in om.get_individuals() if i["name"] == "a1"]
    (row,) = [r for r in ind["properties"] if r["property"] == "knows"]
    assert row["property_uri"] == str(om.namespace) + "knows"

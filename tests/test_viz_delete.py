"""Deleting from the Visualization details panel (issue #222).

The counterpart to adding from the graph (#221): what you can select, you can
now remove, without going to find it again on its page.

Deleting is two clicks on purpose. From the graph you are one click away from an
entity you were only looking at, and ``delete_class`` takes its references with
it, so the second click is preceded by the same impact summary the entity pages
show.

Driven through ``_render_panel_entity_editor`` rather than the page: AppTest
cannot run the Visualization page twice, and the panel is what is under test.
"""

import os

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Bicycle", "Wheel", "Engine"):
            om.add_class(name)
        om.add_class("Tandem", parent="Bicycle")
        om.add_object_property("hasPart")
        om.add_individual("bike1", "Bicycle")
        om.add_class_relation("Bicycle", "disjointWith", "Engine")
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True

    ont = st.session_state.ontology
    app._render_panel_entity_editor(
        ont,
        os.environ["VIZ_DEL_NTYPE"],
        os.environ["VIZ_DEL_ENAME"],
        {"title": "tooltip text"},
        ont.get_classes(),
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
    )


def _run(ntype, ename):
    os.environ["VIZ_DEL_NTYPE"] = ntype
    os.environ["VIZ_DEL_ENAME"] = ename
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)
    assert not at.exception, at.exception
    return at


def _uid_of(om, kind, name):
    pool = {
        "class": om.get_classes,
        "property": om.get_object_properties,
        "individual": om.get_individuals,
    }[kind]()
    return app._uid(next(e["uri"] for e in pool if e["name"] == name))


def _names(om, kind):
    pool = {
        "class": om.get_classes,
        "property": om.get_object_properties,
        "individual": om.get_individuals,
    }[kind]()
    return sorted(e["name"] for e in pool)


# --- entities ---------------------------------------------------------------


def test_the_first_click_only_asks():
    """One click from the graph must not remove a class and everything under
    it: the impact is shown and nothing has happened yet."""
    at = _run("Class", "")
    om = at.session_state["ontology"]
    at = _run("Class", _uid_of(om, "class", "Bicycle"))

    _click(at, "🗑️ Delete")
    assert "Bicycle" in _names(at.session_state["ontology"], "class")
    assert at.warning, "the delete impact was not shown"
    assert any("Confirm Delete" == b.label for b in at.button)


def test_confirming_deletes_the_class():
    at = _run("Class", "")
    om = at.session_state["ontology"]
    at = _run("Class", _uid_of(om, "class", "Engine"))

    _click(at, "🗑️ Delete")
    _click(at, "Confirm Delete")
    assert "Engine" not in _names(at.session_state["ontology"], "class")


def test_cancelling_keeps_it():
    at = _run("Class", "")
    om = at.session_state["ontology"]
    at = _run("Class", _uid_of(om, "class", "Wheel"))

    _click(at, "🗑️ Delete")
    _click(at, "Cancel")
    assert "Wheel" in _names(at.session_state["ontology"], "class")


def test_an_individual_goes_the_same_way():
    at = _run("Individual", "")
    om = at.session_state["ontology"]
    at = _run("Individual", _uid_of(om, "individual", "bike1"))

    _click(at, "🗑️ Delete")
    _click(at, "Confirm Delete")
    assert _names(at.session_state["ontology"], "individual") == []


def test_a_property_goes_the_same_way():
    at = _run("Object Property", "")
    om = at.session_state["ontology"]
    at = _run("Object Property", _uid_of(om, "property", "hasPart"))

    _click(at, "🗑️ Delete")
    _click(at, "Confirm Delete")
    assert _names(at.session_state["ontology"], "property") == []


def test_the_delete_is_undoable():
    """It moves the revision, so it can be undone, redraws the graph and is
    autosaved — the invariant test_mutation_checkpoints exists for."""
    at = _run("Class", "")
    om = at.session_state["ontology"]
    at = _run("Class", _uid_of(om, "class", "Tandem"))
    # AppTest's session_state proxy has no .get()
    try:
        before = at.session_state["_ont_mutation_count"]
    except KeyError:
        before = 0

    _click(at, "🗑️ Delete")
    _click(at, "Confirm Delete")
    assert at.session_state["_ont_mutation_count"] > before


# --- axioms drawn as edges --------------------------------------------------


def test_a_relation_edge_can_be_deleted():
    at = _run("Class Relation", "")
    om = at.session_state["ontology"]
    uris = {c["name"]: c["uri"] for c in om.get_classes()}
    ename = app._edge_id(uris["Bicycle"], "disjointWith", uris["Engine"])
    at = _run("Class Relation", ename)

    _click(at, "🗑️ Delete relation")
    _click(at, "Confirm Delete")
    relations = at.session_state["ontology"].get_class_relations()
    assert not [r for r in relations if r["relation"] == "disjointWith"]
    # The classes at either end stay: an axiom is not its endpoints.
    assert {"Bicycle", "Engine"} <= set(_names(at.session_state["ontology"], "class"))


def test_a_restriction_edge_can_be_deleted():
    at = _run("Restriction", "")
    om = at.session_state["ontology"]
    uris = {c["name"]: c["uri"] for c in om.get_classes()}
    props = {p["name"]: p["uri"] for p in om.get_object_properties()}
    ename = app._edge_id(
        uris["Bicycle"], props["hasPart"], "someValuesFrom", uris["Wheel"]
    )
    at = _run("Restriction", ename)

    _click(at, "🗑️ Delete restriction")
    _click(at, "Confirm Delete")
    assert at.session_state["ontology"].get_restrictions() == []


# --- the selection that outlives what it pointed at -------------------------


NODE_PICK = {"nodeId": "abc123", "ntype": "Class", "ename": "abc123", "selected": True}
# An edge selection carries no nodeId at all: the component sends one only for
# selectNode (lib/graph_viewer/index.html, the selectEdge handler).
EDGE_PICK = {"ntype": "Class Relation", "ename": "a|disjointWith|b", "selected": True}


def _dropped_after_delete(pick, revision=7):
    """Run the drop the way the delete does, and hand back the marker."""
    import streamlit as st

    st.session_state.clear()
    st.session_state["graph_viewer"] = dict(pick)
    st.session_state["_viz_last_selection"] = dict(pick)
    st.session_state["_ont_mutation_count"] = revision
    app._panel_drop_selection()
    return st.session_state["_viz_dropped_selection"]


def test_the_deleted_node_stops_counting_as_selected():
    """The component still reports the node it last had, which is the one just
    deleted, so the panel would reopen on an entity that is gone."""
    import streamlit as st

    dropped = _dropped_after_delete(NODE_PICK)

    assert st.session_state["_viz_last_selection"] is None
    assert app._viz_live_selection(NODE_PICK, dropped, 7) == (None, dropped)


def test_a_different_pick_clears_the_marker():
    """Otherwise the panel would stay shut for whatever came next."""
    dropped = _dropped_after_delete(NODE_PICK)

    other = {**NODE_PICK, "nodeId": "def456", "ename": "def456"}
    assert app._viz_live_selection(other, dropped, 7) == (other, None)


def test_undo_makes_the_entity_selectable_again():
    """Undo puts it back and the component reports the identical payload for
    it, so the marker has to retire on the revision rather than on a different
    pick — or the restored entity could never be selected again."""
    dropped = _dropped_after_delete(NODE_PICK, revision=7)

    assert app._viz_live_selection(NODE_PICK, dropped, 8) == (NODE_PICK, None)


def test_an_edge_pick_survives_with_no_delete_pending():
    """The regression this guard caused: an edge selection has no nodeId, so
    comparing ids alone read every edge click as the node just deleted — and no
    edge could open the panel at all, delete buttons included."""
    assert app._viz_live_selection(EDGE_PICK, None, 0) == (EDGE_PICK, None)


def test_only_the_deleted_edge_is_suppressed():
    dropped = _dropped_after_delete(EDGE_PICK)

    other_edge = {**EDGE_PICK, "ename": "a|subClassOf|b"}
    assert app._viz_live_selection(EDGE_PICK, dropped, 7) == (None, dropped)
    assert app._viz_live_selection(other_edge, dropped, 7) == (other_edge, None)


def test_a_deselect_is_still_a_deselect():
    assert app._viz_live_selection({"selected": False}, None, 0) == (None, None)


# --- saying what is not on screen -------------------------------------------


def test_no_caption_when_nothing_is_hidden():
    assert app.viz_hidden_caption(False, [], 1, 0, 0) == ""


def test_focus_names_its_seeds_and_counts_what_it_took():
    assert app.viz_hidden_caption(True, ["Class: Person"], 1, 6, 0) == (
        "Focused on Person · 1 hop · 6 hidden by focus"
    )


def test_many_seeds_stay_one_short_line():
    """Five names, then a count: a focus on half the ontology must not turn the
    caption into a paragraph."""
    seeds = [f"Class: C{i}" for i in range(9)]
    assert app.viz_hidden_caption(True, seeds, 2, 3, 0) == (
        "Focused on C0, C1, C2, C3, C4, … (+4) · 2 hops · 3 hidden by focus"
    )


def test_the_node_filter_is_reported_on_its_own():
    assert app.viz_hidden_caption(False, [], 1, 0, 4) == ("4 hidden by the node filter")

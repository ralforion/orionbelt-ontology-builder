"""The shortest path highlighted on the Visualization canvas (issue #176).

The search itself is covered in ``test_shortest_path.py``. What this checks is
the half that only exists on the page: that the path reaches the graph payload
as a repaint, that the panel around it renders whatever the search found, and
that the panel keeps a constant shape — an element that comes and goes above the
graph component re-creates its iframe and drops the canvas out of fullscreen
(issue #189).

Same harness as ``test_viz_focus_annotations``: the real
``render_visualization`` through AppTest, inspecting the graph payload it
caches, seeded through the environment because ``AppTest.from_function`` runs
the script source in a fresh namespace.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.ui import (
    PATH_HIGHLIGHT_BORDER,
    PATH_HIGHLIGHT_COLOR,
    PATH_HIGHLIGHT_WIDTH,
)


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        # A subclass chain A -> B -> C, plus an unconnected D. So A to C is two
        # hops through B, and A to D is no path at all.
        om = OntologyManager()
        om.add_class("A")
        om.add_class("B", parent="A")
        om.add_class("C", parent="B")
        om.add_class("D")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The shell initialises this at startup; this harness calls the page
        # directly, so it stands in for that.
        st.session_state["error_log"] = []
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_path_panel"] = os.environ["PATH_PANEL"] == "1"
        st.session_state["_viz_cfg_show_triples"] = os.environ["PATH_TRIPLES"] == "1"
        if os.environ["PATH_FROM"]:
            st.session_state["viz_path_source"] = os.environ["PATH_FROM"]
        if os.environ["PATH_TO"]:
            st.session_state["viz_path_target"] = os.environ["PATH_TO"]
        if os.environ.get("PATH_BROKEN") == "1":
            # Stands in for any bug inside the search — the shape that made a
            # stale process report two connected classes as unconnected.
            def _broken(*_args, **_kwargs):
                raise TypeError("unexpected keyword argument")

            om.find_shortest_path = _broken
        elif os.environ.get("PATH_LIMIT") == "1":
            # Standing in for an ontology too large to search exhaustively,
            # which is otherwise 50,000 entities to build.
            from orionbelt_ontology_builder.ontology_manager import (
                PathSearchLimitError,
            )

            def _over_budget(*_args, **_kwargs):
                raise PathSearchLimitError("gave up")

            om.find_shortest_path = _over_budget

    app.render_visualization()


def _render(
    source="Class: A",
    target="Class: C",
    over_budget=False,
    panel=True,
    triples=False,
    broken=False,
):
    """Render once and return the AppTest, with a path picked."""
    os.environ["PATH_FROM"] = source
    os.environ["PATH_TO"] = target
    os.environ["PATH_LIMIT"] = "1" if over_budget else "0"
    os.environ["PATH_PANEL"] = "1" if panel else "0"
    os.environ["PATH_TRIPLES"] = "1" if triples else "0"
    os.environ["PATH_BROKEN"] = "1" if broken else "0"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _graph(at):
    data = at.session_state["last_graph_data"]
    assert data, "the visualization built no graph"
    return json.loads(data["nodes"]), json.loads(data["edges"])


def _highlighted_edges(edges):
    return [e for e in edges if e.get("color") == PATH_HIGHLIGHT_COLOR]


def _label_of(nodes, node_id):
    return next(n["label"] for n in nodes if n["id"] == node_id)


def _panel_text(at):
    """The result line the path panel writes, whatever it has to say."""
    return " ".join(m.value for m in at.markdown)


# --- the highlight ----------------------------------------------------------


def test_the_links_along_the_path_are_repainted():
    nodes, edges = _graph(_render("Class: A", "Class: C"))
    lit = _highlighted_edges(edges)
    assert all(e["width"] == PATH_HIGHLIGHT_WIDTH for e in lit)
    assert {
        frozenset((_label_of(nodes, e["from"]), _label_of(nodes, e["to"]))) for e in lit
    } == {frozenset(("A", "B")), frozenset(("B", "C"))}


def test_a_repainted_link_remembers_the_colour_of_its_own_kind():
    """The canvas legend is built from edge colours, so a highlight that simply
    overwrote them would take the last subClassOf edge's entry off the legend."""
    _, edges = _graph(_render("Class: A", "Class: C"))
    assert [e["basecolor"] for e in _highlighted_edges(edges)] == ["#81C784"] * 2


def test_a_link_off_the_path_keeps_its_own_colour():
    _, edges = _graph(_render("Class: A", "Class: B"))
    off_path = [
        e
        for e in edges
        if e.get("color") != PATH_HIGHLIGHT_COLOR and e.get("label") == "subClassOf"
    ]
    # B -> C is not on a path that stops at B.
    assert off_path


def test_the_nodes_along_the_path_keep_their_fill_and_take_the_path_border():
    nodes, _ = _graph(_render("Class: A", "Class: C"))
    on_path = [n for n in nodes if n["label"] in {"A", "B", "C"}]
    assert len(on_path) == 3
    for node in on_path:
        assert node["color"]["border"] == PATH_HIGHLIGHT_COLOR
        # The fill is what says this is a class; the path must not spend it.
        assert node["color"]["background"] == "#4CAF50"
        # And a node box is small enough that a link-width border would.
        assert node["borderWidth"] == PATH_HIGHLIGHT_BORDER < PATH_HIGHLIGHT_WIDTH


def test_an_entity_off_the_path_is_not_bordered():
    nodes, _ = _graph(_render("Class: A", "Class: B"))
    unrelated = next(n for n in nodes if n["label"] == "D")
    assert unrelated["color"]["border"] != PATH_HIGHLIGHT_COLOR


def test_nothing_is_repainted_when_no_path_was_asked_for():
    nodes, edges = _graph(_render("", ""))
    assert _highlighted_edges(edges) == []
    assert all(n["color"]["border"] != PATH_HIGHLIGHT_COLOR for n in nodes)


def test_the_cached_graph_is_rebuilt_when_the_path_changes():
    """The payload is cached under a key; a path left out of it would be found
    and then never drawn, because nothing the key can see had changed."""
    first = _render("Class: A", "Class: B").session_state["last_graph_key"]
    second = _render("Class: A", "Class: C").session_state["last_graph_key"]
    assert first != second


# --- what the panel says ----------------------------------------------------


def test_the_panel_reads_the_path_back_with_its_links():
    text = _panel_text(_render("Class: A", "Class: C"))
    assert "2 hops" in text
    assert "Class: A ←subClassOf— Class: B ←subClassOf— Class: C" in text


def test_a_single_hop_is_not_pluralised():
    assert "1 hop:" in _panel_text(_render("Class: A", "Class: B"))


def test_two_unconnected_entities_are_reported_as_such():
    at = _render("Class: A", "Class: D")
    text = _panel_text(at)
    assert "No path between" in text
    # Named, not "them": the pickers scroll out of sight on a long page.
    assert "Class: A" in text
    assert "Class: D" in text
    assert _highlighted_edges(_graph(at)[1]) == []


def test_no_path_says_why_the_triple_lines_on_screen_were_not_walked():
    """With Triples on, two unrelated classes are both drawn joined to a shared
    rdf:type node, so a bare "no path" reads as a contradiction: you can trace
    the line yourself. Walking those would put every pair two hops apart."""
    text = _panel_text(_render("Class: A", "Class: D", triples=True))
    assert "No path between" in text
    assert "shared node such as owl:Class" in text
    assert "asserted straight between two named" in text


def test_that_explanation_is_left_out_when_no_triples_are_drawn():
    """Nothing on screen to contradict, so nothing to explain away."""
    assert "owl:Class" not in _panel_text(_render("Class: A", "Class: D"))


def test_a_search_that_breaks_is_not_reported_as_no_path():
    """ "No path" is a claim about the ontology. Answering a broken search with
    one sends the reader hunting a modelling problem that isn't there — which is
    exactly how a stale process presented two connected classes."""
    at = _render("Class: A", "Class: C", broken=True)
    text = _panel_text(at)
    assert "could not be run" in text
    assert "Class: A" in text and "Class: C" in text
    assert "No path between" not in text
    assert not at.exception, "a failed search must not take the page down"


def test_a_failed_search_is_written_to_the_log_it_sends_the_reader_to():
    """The message points at the sidebar's error log. A debug line on the
    server never arrives there, so the direction would be a dead end."""
    at = _render("Class: A", "Class: C", broken=True)
    assert "Errors" in _panel_text(at)
    logged = at.session_state["error_log"]
    assert [e for e in logged if e["context"] == "Shortest path search"]


def test_logging_a_failure_works_before_the_log_exists(session):
    """log_error is called from `except` blocks. Reading a missing key raises,
    which would replace the error being reported with a page crash — and lose
    the report as well."""
    ui.log_error(RuntimeError("boom"), context="Shortest path search")
    assert session["error_log"][0]["error"] == "boom"


def test_nothing_is_logged_when_the_search_simply_finds_nothing():
    """No path and a search past its budget are answers, not failures."""
    assert _render("Class: A", "Class: D").session_state["error_log"] == []
    assert (
        _render("Class: A", "Class: C", over_budget=True).session_state["error_log"]
        == []
    )


def test_a_search_cut_short_is_not_reported_as_no_path():
    """The two are different facts. Telling someone their entities are
    unconnected when the search simply gave up is a wrong answer."""
    text = _panel_text(_render("Class: A", "Class: C", over_budget=True))
    assert "too large to search exhaustively" in text
    assert "There may still be a path" in text
    assert "Class: A" in text and "Class: C" in text
    assert "No path between" not in text


def test_an_entity_paired_with_itself_says_so():
    text = _panel_text(_render("Class: A", "Class: A"))
    assert "the same entity twice" in text
    assert "Class: A" in text


def test_the_panel_prompts_with_the_kinds_of_entity_it_can_join():
    """ "Two entities" leaves the reader guessing which — the finder takes
    classes, individuals and SKOS concepts, and not data properties."""
    text = _panel_text(_render("", ""))
    assert "Pick two classes, individuals or SKOS concepts" in text


# --- the panel keeps its shape ---------------------------------------------


def test_the_panel_draws_the_same_elements_whether_or_not_a_path_was_found():
    """It sits above the graph component, and an element that comes and goes
    above it re-creates the iframe and drops fullscreen (issue #189)."""
    found = _render("Class: A", "Class: C")
    missing = _render("Class: A", "Class: D")
    unpicked = _render("", "")
    cut_short = _render("Class: A", "Class: C", over_budget=True)
    counts = {
        len(at.markdown) + len(at.button) + len(at.selectbox)
        for at in (found, missing, unpicked, cut_short)
    }
    assert len(counts) == 1


def test_the_focus_button_is_offered_only_once_there_is_a_path_to_focus_on():
    def _button(at):
        return next(b for b in at.button if b.label == "Focus on this path")

    assert _button(_render("Class: A", "Class: C")).disabled is False
    assert _button(_render("Class: A", "Class: D")).disabled is True
    assert _button(_render("", "")).disabled is True


# --- the switch that shows the panel at all ---------------------------------


def test_the_panel_is_not_drawn_when_the_switch_is_off():
    """It is a tool you reach for, and off it should cost no vertical space."""
    at = _render("Class: A", "Class: C", panel=False)
    assert "Shortest path" not in _panel_text(at)
    assert not [b for b in at.button if b.label == "Focus on this path"]


def test_nothing_is_highlighted_when_the_switch_is_off():
    """A path still painted on the canvas with no control in sight explaining
    it would be a puzzle, so off means off."""
    nodes, edges = _graph(_render("Class: A", "Class: C", panel=False))
    assert _highlighted_edges(edges) == []
    assert all(n["color"]["border"] != PATH_HIGHLIGHT_COLOR for n in nodes)


def test_the_switch_is_offered_beside_the_display_options_switch():
    at = _render("", "")
    labels = [t.label for t in at.toggle]
    assert "Path finder" in labels
    assert labels.index("Path finder") == labels.index("Display options") + 1


def test_the_switch_is_remembered_across_sessions():
    """It rides the persisted display settings like the other band switch, so a
    panel you opened is still open next time (#142)."""
    from orionbelt_ontology_builder.ui import _VIZ_PERSIST_KEYS

    assert "path_panel" in _VIZ_PERSIST_KEYS


def test_turning_the_switch_off_rebuilds_the_graph_without_the_highlight():
    on = _render("Class: A", "Class: C").session_state["last_graph_key"]
    off = _render("Class: A", "Class: C", panel=False).session_state["last_graph_key"]
    assert on != off


# --- what the focus button writes -------------------------------------------
#
# Tested against session state rather than by clicking it through AppTest: a
# second run of this page trips AppTest's handling of the segmented control the
# view tabs use, which has nothing to do with the button.


class _State(dict):
    """Stand-in for ``st.session_state``, which is read and written both ways."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def session(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_focusing_on_a_path_seeds_the_focus_with_every_entity_on_it(session):
    ui.viz_focus_on_path(["Class: A", "Class: B", "Class: C"])
    assert session["_viz_cfg_focus_mode"] is True
    assert session["_viz_cfg_focus_seeds"] == ["Class: A", "Class: B", "Class: C"]


def test_turning_the_mode_on_for_a_path_marks_the_settings_dirty(session):
    """focus_mode is a persisted setting (#142) and the save is gated on the
    flag, so a mode switched on from here has to lift it too."""
    session["_viz_cfg_focus_mode"] = False
    ui.viz_focus_on_path(["Class: A"])
    assert session["_viz_settings_dirty"] is True


def test_focusing_on_a_path_while_already_focused_leaves_the_flag_alone(session):
    """Nothing about the mode changed, so there is no setting to re-save."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = ["Class: Z"]
    ui.viz_focus_on_path(["Class: A", "Class: B"])
    assert "_viz_settings_dirty" not in session
    assert session["_viz_cfg_focus_seeds"] == ["Class: A", "Class: B"]


def test_an_empty_path_does_not_start_a_focus_with_nothing_in_it(session):
    """Focus mode with no seeds backfills an arbitrary node, so the graph would
    jump somewhere nobody picked (issue #328)."""
    ui.viz_focus_on_path([])
    assert "_viz_cfg_focus_mode" not in session

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
    return [e for e in edges if e.get("pathhl")]


def _label_of(nodes, node_id):
    return next(n["label"] for n in nodes if n["id"] == node_id)


def _panel_text(at):
    """The result line the path panel writes, whatever it has to say."""
    return " ".join(m.value for m in at.markdown)


# --- the highlight ----------------------------------------------------------


def test_the_links_along_the_path_are_ringed_and_otherwise_left_alone():
    nodes, edges = _graph(_render("Class: A", "Class: C"))
    lit = _highlighted_edges(edges)
    # The line itself is untouched — no width of its own, so it is drawn exactly
    # as an unhighlighted one is, with only the ring added around it.
    assert all("width" not in e for e in lit)
    assert all(
        e["pathhl"]
        == {
            "color": PATH_HIGHLIGHT_COLOR,
            "border": PATH_HIGHLIGHT_BORDER,
        }
        for e in lit
    )
    assert {
        frozenset((_label_of(nodes, e["from"]), _label_of(nodes, e["to"]))) for e in lit
    } == {frozenset(("A", "B")), frozenset(("B", "C"))}


def test_a_link_on_the_path_keeps_the_colour_of_its_own_kind():
    """The colour is what says this is a subClassOf link, on the path or not, and
    the canvas legend is built from it: a highlight that painted over it would
    cost the graph both (issue #357)."""
    _, edges = _graph(_render("Class: A", "Class: C"))
    assert [e["color"] for e in _highlighted_edges(edges)] == ["#81C784"] * 2


def test_a_link_off_the_path_is_not_ringed():
    _, edges = _graph(_render("Class: A", "Class: B"))
    off_path = [
        e for e in edges if not e.get("pathhl") and e.get("label") == "subClassOf"
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
        assert node["borderWidth"] == PATH_HIGHLIGHT_BORDER


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


# --- the path survives the node cap (issue #378) -----------------------------


def test_the_whole_path_is_drawn_even_when_the_cap_cannot_hold_it(patch_ui):
    """The reported case, in miniature: on an ontology past the cap the middle
    of a path was simply not built, so it was ringed in disconnected pieces —
    the answer to the question, drawn with the answer missing."""
    patch_ui("GRAPH_MAX_NODES", 2)  # the A -> B -> C path is three

    nodes, edges = _graph(_render("Class: A", "Class: C"))

    assert {"A", "B", "C"} <= {n["label"] for n in nodes}
    # And ringed end to end, not in pieces: both links, not one.
    assert len(_highlighted_edges(edges)) == 2


def test_a_path_is_drawn_when_the_class_filter_is_empty():
    """Pinning a class is no use if the loop that builds classes never runs.

    Its gate opened for a non-empty filter or for a Find target that was a
    class, and a pinned class satisfied neither — class node ids carry no kind
    prefix, so nothing recognised them. With the filter emptied the graph came
    out with no nodes at all and the path had nowhere to be drawn (Codex review
    of PR #379).
    """
    at = _render("Class: A", "Class: C")
    # The filter emptied, with the reveal already marked done so nothing
    # re-adds the classes behind the test's back.
    uris = {c["uri"] for c in at.session_state.ontology.get_classes()}
    at.session_state["_viz_cfg_selected_class_uris"] = []
    at.session_state["_viz_cfg_known_class_uris"] = uris
    at.session_state["_viz_find_seq"] = 1
    at.session_state["_viz_find_revealed_seq"] = 1
    at.run(timeout=300)
    assert not at.exception, at.exception

    nodes, edges = _graph(at)
    # Only the path: the filter still hides everything it was hiding.
    assert {n["label"] for n in nodes} == {"A", "B", "C"}
    assert len(_highlighted_edges(edges)) == 2


def test_a_pinned_path_does_not_lift_the_cap_for_everything_else(patch_ui):
    """The cap is what protects the browser. Pinning buys the path its own
    nodes, not a bigger graph: D is unrelated and stays out."""
    patch_ui("GRAPH_MAX_NODES", 2)

    nodes, _ = _graph(_render("Class: A", "Class: B"))

    labels = {n["label"] for n in nodes}
    assert {"A", "B"} <= labels
    assert "D" not in labels


def test_a_path_the_view_cannot_draw_says_so():
    """A path drawn in pieces with nothing accounting for it reads as a broken
    highlight rather than as a view that does not hold all of it, and this is
    the only line that names the way out.

    Focused elsewhere, because since #378 the node cap cannot do this: the
    entities on a path are pinned past it. The focus prune runs after the build
    and takes them out again, which is what is left.
    """
    at = _render("Class: A", "Class: C")
    at.session_state["_viz_cfg_focus_mode"] = True
    at.session_state["_viz_cfg_focus_seeds"] = ["Class: D"]  # not on the path
    at.run(timeout=300)
    assert not at.exception, at.exception

    notice = at.session_state["last_graph_data"]["notice"]
    assert "entities on this path are not drawn" in notice
    # Here the advice is the right advice: they are focused on something else.
    assert "Focus on this path" in notice


def test_a_focus_keeps_its_own_advice_when_the_path_is_half_drawn(patch_ui):
    """The path line replaces the generic cap line and nothing else. The focus
    messages are sharper — one of them explains an empty canvas — and their
    advice is about the focus the user is already in, which "use Focus on this
    path" would talk straight over (Codex review of PR #377)."""
    patch_ui("GRAPH_MAX_NODES", 2)
    at = _render("Class: A", "Class: C")

    at.session_state["_viz_cfg_focus_mode"] = True
    at.session_state["_viz_cfg_focus_seeds"] = ["Class: A", "Class: B", "Class: C"]
    at.run(timeout=300)
    assert not at.exception, at.exception

    notice = at.session_state["last_graph_data"]["notice"]
    assert "focus" in notice.lower()
    assert "Focus on this path" not in notice


def test_a_path_drawn_in_full_leaves_the_graph_notice_alone():
    """Nothing is missing from the path, so there is nothing for it to say."""
    notice = _render("Class: A", "Class: C").session_state["last_graph_data"]["notice"]

    assert "entities on this path" not in notice


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


def _panel(at, shown):
    """Show or hide the panel for the next run, and check that it moved.

    The *config* key is what to set: the page copies it onto the switch's widget
    key on every render (see the ``_viz_cfg`` loop), so setting the widget key
    would be overwritten and the panel would never move — which is a way this
    test can pass while proving nothing. Clicking the switch is no good either:
    that fires the persist callback, which marks the settings dirty and mounts
    the localStorage component, and that waits for a browser.
    """
    at.session_state["_viz_cfg_path_panel"] = shown
    at.run(timeout=120)
    assert not at.exception, at.exception
    drawn = bool([b for b in at.button if b.label == "Focus on this path"])
    assert drawn is shown, f"panel {'hidden' if shown else 'still drawn'}"
    return at


def test_the_pair_survives_the_panel_being_switched_off_and_on():
    """The pickers are widgets inside the panel, and Streamlit drops a widget's
    state as soon as it stops being rendered — so the pair used to have to be
    chosen again every time the panel was reopened (issue #360)."""
    at = _render("Class: A", "Class: C")
    assert at.session_state["viz_path_source"] == "Class: A"

    _panel(at, False)
    _panel(at, True)

    assert at.selectbox(key="viz_path_source").value == "Class: A"
    assert at.selectbox(key="viz_path_target").value == "Class: C"


def test_a_remembered_pick_whose_entity_is_gone_is_forgotten():
    """The remembered copy outlives the widget, so it has to be pruned with it:
    an entity that has since been deleted must not come back when the panel is
    reopened."""
    at = _render("Class: A", "Class: C")
    assert at.session_state["_viz_cfg_path_source"] == "Class: A"

    at.session_state.ontology.delete_class(
        next(
            c["uri"]
            for c in at.session_state.ontology.get_classes()
            if c["name"] == "A"
        )
    )
    at.run(timeout=300)
    assert not at.exception, at.exception

    assert "_viz_cfg_path_source" not in at.session_state
    # The picker itself comes back empty rather than naming a class that is gone.
    assert at.selectbox(key="viz_path_source").value is None
    # The other half of the pair is untouched — only the gone one is dropped.
    assert at.session_state["_viz_cfg_path_target"] == "Class: C"


def test_the_switch_is_offered_in_the_band_switch_row():
    """One row of switches above the canvas, one per band, in the order the
    bands sit in: Display options, Find & focus, Path finder (issue #381)."""
    at = _render("", "")
    labels = [t.label for t in at.toggle]
    assert labels[:3] == ["Display options", "Find & focus", "Path finder"]


def test_the_switch_is_remembered_across_sessions():
    """It rides the persisted display settings like the other band switch, so a
    panel you opened is still open next time (#142)."""
    from orionbelt_ontology_builder.ui import _VIZ_PERSIST_KEYS

    assert "path_panel" in _VIZ_PERSIST_KEYS
    # The Find & focus switch is presented as one of the same set, so it is
    # remembered like one (issue #381).
    assert "find_row_open" in _VIZ_PERSIST_KEYS


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

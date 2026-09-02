"""What a modifier-click on a graph node does to the focus.

Ctrl/Cmd-click adds the node to the focus (issue #56); Alt-click focuses on it
alone (issue #276), because wanting one node at a time is the common case and it
otherwise means emptying the picker by hand between hops.

Clicking a node that is *already* focused used to do nothing at all, leaving no
way out of focus mode except the checkbox. Each modifier now undoes its own
action (issue #328): ctrl/cmd-click removes what it would have added, alt-click
switches the mode off when the focus is already exactly that node. Every case
that changed was a no-op before.
"""

import pytest
import sources

from orionbelt_ontology_builder import app, ui

PERSON = "Class: Person"
ORG = "Class: Org"
ROLE = "Class: Role"


# --- what each modifier does on a node that is not focused yet ---------------


def test_ctrl_click_adds_to_what_is_already_focused():
    """Building a neighbourhood up out of several nodes."""
    assert app.focus_seeds_after_request([PERSON], ORG, focus_on=True) == (
        [PERSON, ORG],
        True,
    )


def test_alt_click_focuses_on_that_node_alone():
    """The point of issue #276."""
    assert app.focus_seeds_after_request(
        [PERSON, ORG], ROLE, replace=True, focus_on=True
    ) == ([ROLE], True)


def test_a_first_click_starts_the_focus_either_way():
    """Nothing focused yet, whichever modifier switched the mode on."""
    assert app.focus_seeds_after_request(None, PERSON) == ([PERSON], True)
    assert app.focus_seeds_after_request([], PERSON, replace=True) == ([PERSON], True)


# --- and on a node that is already focused (issue #328) ----------------------


def test_ctrl_clicking_a_focused_node_drops_it():
    """Ctrl/cmd-click adds, so on a node it already added it takes it back out.
    The others stay, and the mode stays on with them."""
    assert app.focus_seeds_after_request([PERSON, ORG], PERSON, focus_on=True) == (
        [ORG],
        True,
    )


def test_ctrl_clicking_the_last_focused_node_turns_the_mode_off():
    """Nothing left to focus on. The mode has to go off in the same breath: with
    it on and no seeds, the page backfills an arbitrary first node, so the graph
    would jump to a class nobody picked."""
    assert app.focus_seeds_after_request([PERSON], PERSON, focus_on=True) == ([], False)


def test_alt_clicking_the_only_focused_node_turns_the_mode_off():
    """Alt-click sets the focus to exactly one node, so on the node it is
    already set to, it is the way back out."""
    assert app.focus_seeds_after_request(
        [PERSON], PERSON, replace=True, focus_on=True
    ) == ([PERSON], False)


def test_the_alt_click_exit_keeps_the_seeds():
    """So switching focus back on returns you where you were, rather than to a
    node derived from the class selection (issue #235)."""
    seeds, focus_on = app.focus_seeds_after_request(
        [PERSON], PERSON, replace=True, focus_on=True
    )
    assert (seeds, focus_on) == ([PERSON], False)


def test_alt_clicking_one_of_several_still_narrows():
    """Not an exit: the focus is not already *exactly* that node, so "now just
    this one" is still what the user asked for and still what they get."""
    assert app.focus_seeds_after_request(
        [PERSON, ORG], PERSON, replace=True, focus_on=True
    ) == ([PERSON], True)


# --- with the mode off, a click just starts focusing (Codex review of #334) --


def test_alt_clicking_the_node_you_just_left_focuses_it_again():
    """The Alt-click exit keeps the seed, so the seed list still says
    "Person" while the mode is off. Reading focus from the seeds made the
    obvious next click refuse to do anything."""
    assert app.focus_seeds_after_request(
        [PERSON], PERSON, replace=True, focus_on=False
    ) == ([PERSON], True)


def test_ctrl_clicking_a_retained_seed_with_the_mode_off_focuses_it():
    """Not a removal: there is no focus on screen for it to be the undo of."""
    assert app.focus_seeds_after_request([PERSON], PERSON, focus_on=False) == (
        [PERSON],
        True,
    )


def test_ctrl_clicking_with_the_mode_off_keeps_the_seeds_it_finds():
    """Turning focus back on from the canvas restores what was kept, the same
    way ticking the checkbox does (issue #235), and adds the node clicked."""
    assert app.focus_seeds_after_request([PERSON], ORG, focus_on=False) == (
        [PERSON, ORG],
        True,
    )


def test_alt_clicking_with_the_mode_off_still_means_only_this_one():
    assert app.focus_seeds_after_request(
        [PERSON, ORG], ROLE, replace=True, focus_on=False
    ) == ([ROLE], True)


# --- and the invariant that made this safe to change -------------------------


def test_the_caller_s_list_is_not_mutated():
    """The seeds come out of session state; editing that list in place would
    change the stored value before the assignment that is meant to."""
    seeds = [PERSON, ORG]
    app.focus_seeds_after_request(seeds, ORG, focus_on=True)
    app.focus_seeds_after_request(seeds, PERSON, replace=True, focus_on=True)
    assert seeds == [PERSON, ORG]


# --- and what the page writes when that click arrives ------------------------


class _State(dict):
    """Stand-in for ``st.session_state``, which is read and written both ways."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def session(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_the_click_writes_the_mode_and_the_seeds_together(session):
    """Never one render apart: focus mode with no seeds backfills an arbitrary
    first label, so the graph would jump to a class nobody picked."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    seeds, focus_on = ui.viz_apply_focus_click(PERSON)

    assert (seeds, focus_on) == ([], False)
    assert session["_viz_cfg_focus_seeds"] == []
    assert session["_viz_cfg_focus_mode"] is False


def test_switching_the_mode_from_the_canvas_marks_the_settings_dirty(session):
    """focus_mode is persisted (#142) and the save is gated on that flag, which
    only the widget callbacks used to set. Without it, exiting focus by
    modifier-click left the saved settings stale across a reload."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    ui.viz_apply_focus_click(PERSON, replace=True)

    assert session["_viz_cfg_focus_mode"] is False
    assert session["_viz_settings_dirty"] is True


def test_turning_the_mode_on_from_the_canvas_marks_it_dirty_too(session):
    session["_viz_cfg_focus_mode"] = False
    ui.viz_apply_focus_click(PERSON)
    assert session["_viz_cfg_focus_mode"] is True
    assert session["_viz_settings_dirty"] is True


def test_a_click_that_leaves_the_mode_alone_does_not_mark_it_dirty(session):
    """Adding a second seed changes the seeds, which are saved against the
    linked file rather than with the display settings."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    ui.viz_apply_focus_click(ORG)

    assert session["_viz_cfg_focus_seeds"] == [PERSON, ORG]
    assert "_viz_settings_dirty" not in session


def test_a_focus_click_is_not_announced():
    """A toast confirming a click the user just made was a second telling, and
    a distracting one while working (issue #389): the canvas redraws to the
    focus, and the standing note on the Node options label names the seeds, the
    depth and what is held back, without fading.

    Pinned at the source because the click arrives through the graph component,
    which does not render under AppTest.
    """
    src = sources.viz_text()
    branch = src[src.index('selection.get("focusRequest")') :]
    branch = branch[: branch.index("# Status bar outside iframe")]

    assert "viz_apply_focus_click(" in branch, "the click must still be applied"
    assert 'icon="🎯"' not in branch
    # What is still said here is the click that did nothing at all, which
    # nothing else on the page explains.
    assert "Focus is available for classes" in branch


def test_the_focus_that_ended_itself_still_says_so():
    """The other 🎯 toast stays: focus mode ending on its own is not something
    the user did, and un-ticking the box in silence is what issue #335 was."""
    src = sources.viz_text()
    assert "_viz_focus_left_note" in src
    assert "Focus off: nothing left to focus on" in src

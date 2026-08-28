"""Clearing the "Focus node(s)" picker leaves focus mode (issue #335).

The picker could not be emptied: with the mode on and no seeds, the render
backfilled the first class, so pressing Clear all put an arbitrary entity
straight back. Focus mode is "show me this node's neighbourhood" and has nothing
to mean with nothing picked, so clearing the last seed now leaves the mode
instead, which is where the last Ctrl/Cmd-click on the canvas already lands
(issue #328). Both ways out of a focus agree.

Leaving the mode rather than allowing an empty focus is also what keeps the node
cap honest (issue #216): focus mode may assemble more nodes than can be drawn
only because the prune cuts it back afterwards, and with no seeds nothing
prunes, so an empty focus would draw the whole ontology.
"""

import pytest

from orionbelt_ontology_builder import ui

PERSON = "Class: Person"
ORG = "Class: Org"


class _State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def session(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_clearing_the_picker_leaves_focus_mode(session):
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    session["viz_focus_seeds"] = []

    ui.viz_focus_seeds_changed()

    assert session["_viz_cfg_focus_seeds"] == []
    assert session["_viz_cfg_focus_mode"] is False


def test_clearing_the_picker_marks_the_settings_dirty(session):
    """focus_mode is persisted and the save is dirty-gated, the same gate the
    canvas click had to lift (the Codex review of PR #334)."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    session["viz_focus_seeds"] = []

    ui.viz_focus_seeds_changed()

    assert session["_viz_settings_dirty"] is True


def test_removing_one_of_several_keeps_the_mode(session):
    """Only the last one out ends the focus."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON, ORG]
    session["viz_focus_seeds"] = [ORG]

    ui.viz_focus_seeds_changed()

    assert session["_viz_cfg_focus_seeds"] == [ORG]
    assert session["_viz_cfg_focus_mode"] is True
    assert "_viz_settings_dirty" not in session


def test_picking_seeds_persists_them(session):
    """The everyday case the old viz_sync callback handled."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    session["viz_focus_seeds"] = [PERSON, ORG]

    ui.viz_focus_seeds_changed()

    assert session["_viz_cfg_focus_seeds"] == [PERSON, ORG]
    assert session["_viz_cfg_focus_mode"] is True


def test_a_missing_widget_is_not_read_as_cleared(session):
    """The page was not rendered, so there is nothing to sync. Reading the
    absent key as an empty pick would wipe the seeds and drop the mode
    (issue #219's failure mode)."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    ui.viz_focus_seeds_changed()

    assert session["_viz_cfg_focus_seeds"] == [PERSON]
    assert session["_viz_cfg_focus_mode"] is True


def test_clearing_with_the_mode_already_off_touches_nothing(session):
    """Nothing to leave, so nothing to save either."""
    session["_viz_cfg_focus_mode"] = False
    session["viz_focus_seeds"] = []

    ui.viz_focus_seeds_changed()

    assert session["_viz_cfg_focus_seeds"] == []
    assert "_viz_settings_dirty" not in session


def test_a_focus_whose_seeds_have_all_gone_leaves_the_mode(session):
    """The other route to an empty focus, and the one no callback sees: the
    entity was deleted, or its whole type was switched off, so the saved labels
    resolve to nothing on the next render. That used to move the focus onto an
    arbitrary first entity behind the user's back."""
    session["_viz_cfg_focus_mode"] = True

    ui.viz_leave_empty_focus()

    assert session["_viz_cfg_focus_mode"] is False
    assert session["_viz_settings_dirty"] is True


def test_leaving_a_focus_that_is_already_off_changes_nothing(session):
    """So a render that finds no seeds with the mode already off does not
    keep marking the settings dirty on every pass."""
    session["_viz_cfg_focus_mode"] = False

    ui.viz_leave_empty_focus()

    assert "_viz_settings_dirty" not in session


def test_turning_the_mode_back_on_starts_over_from_the_selection(session):
    """The "start over" the request asked for: re-ticking the checkbox after a
    clear derives fresh seeds rather than restoring what was cleared."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    session["viz_focus_seeds"] = []
    ui.viz_focus_seeds_changed()

    session["_viz_cfg_selected_classes"] = ["Person", "Org"]
    session["_viz_cfg_class_count"] = 5
    session["viz_focus_mode"] = True
    ui.viz_focus_toggle()

    assert session["_viz_cfg_focus_mode"] is True
    assert session["_viz_cfg_focus_seeds"] == [PERSON, ORG]


def test_the_render_no_longer_stands_in_a_first_entity():
    """The backfill itself is gone, not merely unreachable from the picker:
    every route to an empty focus now ends the mode instead."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "orionbelt_ontology_builder"
        / "views"
        / "visualization.py"
    ).read_text(encoding="utf-8")
    assert "focus_labels[0]" not in src, (
        "an empty focus is being filled with an arbitrary first entity again"
    )
    assert "viz_leave_empty_focus()" in src

"""Undo for the Node options panel (issue #491).

Every control that edits the node filters, the focus seeds or focus mode takes
a snapshot first; Undo puts the last one back. The render's own reconciling
(entities created, deleted or renamed) is the ontology changing, not the user,
so it is neither recorded nor walked back.
"""

import pytest

from orionbelt_ontology_builder import ui

A = "http://example.org/o#A"
B = "http://example.org/o#B"
C = "http://example.org/o#C"
NEW = "http://example.org/o#New"
PERSON = "Class: Person"
ORG = "Class: Org"


class _State(dict):
    """Stand-in for ``st.session_state``, which is read and written both ways."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def session(monkeypatch):
    state = _State()
    state["_viz_cfg_selected_class_uris"] = [A, B, C]
    state["_viz_cfg_known_class_uris"] = [A, B, C]
    state["_viz_cfg_selected_ind_uris"] = []
    state["_viz_cfg_known_ind_uris"] = []
    state["_viz_cfg_focus_mode"] = False
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def _pick(session, *uris):
    """What the class multiselect's on_change does with a new pick."""
    by_display = {"A": A, "B": B, "C": C}
    session["viz_selected_class"] = [d for d, u in by_display.items() if u in uris]
    ui.viz_filter_changed("class", by_display)


def test_nothing_to_undo_at_first(session):
    assert ui.viz_node_undo_available() is False
    ui.viz_node_undo()
    assert session["_viz_cfg_selected_class_uris"] == [A, B, C]


def test_undo_takes_back_a_filter_change(session):
    _pick(session, A)
    assert session["_viz_cfg_selected_class_uris"] == [A]

    ui.viz_node_undo()

    assert session["_viz_cfg_selected_class_uris"] == [A, B, C]
    assert ui.viz_node_undo_available() is False


def test_undo_steps_back_one_change_at_a_time(session):
    _pick(session, A, B)
    _pick(session, A)

    ui.viz_node_undo()
    assert session["_viz_cfg_selected_class_uris"] == [A, B]
    ui.viz_node_undo()
    assert session["_viz_cfg_selected_class_uris"] == [A, B, C]


def test_a_change_that_changes_nothing_costs_no_step(session):
    _pick(session, A, B, C)
    assert ui.viz_node_undo_available() is False


def test_history_is_capped(session):
    for _ in range(ui.VIZ_NODE_UNDO_MAX + 5):
        _pick(session, A)
        _pick(session, B)
    assert len(session[ui.VIZ_NODE_UNDO_KEY]) == ui.VIZ_NODE_UNDO_MAX


def test_an_entity_created_since_keeps_its_place(session):
    """Undoing a narrowing made before a class was created must not hide it:
    the snapshot never had an opinion about it."""
    _pick(session, A)
    # The render reconciles a creation: the new class is known, and say the
    # user has added it to the narrowed view.
    session["_viz_cfg_known_class_uris"] = [A, B, C, NEW]
    session["_viz_cfg_selected_class_uris"] = [A, NEW]

    ui.viz_node_undo()

    assert set(session["_viz_cfg_selected_class_uris"]) == {A, B, C, NEW}


def test_undoing_show_new_offers_them_again(session):
    session["_viz_cfg_selected_class_uris"] = [A]
    session["_viz_new_hidden_class"] = [C]
    ui.viz_node_undo_checkpoint()
    session["_viz_cfg_selected_class_uris"] = [A, C]
    session["_viz_new_hidden_class"] = []

    ui.viz_node_undo()

    assert session["_viz_cfg_selected_class_uris"] == [A]
    assert session["_viz_new_hidden_class"] == [C]


def test_undo_takes_back_a_canvas_focus_click_mode_and_all(session):
    session["_viz_cfg_focus_seeds"] = [ORG]
    ui.viz_apply_focus_click(PERSON, replace=True)
    assert session["_viz_cfg_focus_mode"] is True
    session.pop("_viz_settings_dirty")

    ui.viz_node_undo()

    assert session["_viz_cfg_focus_seeds"] == [ORG]
    assert session["_viz_cfg_focus_mode"] is False
    # focus_mode is a persisted setting, saved only once the gate is lifted.
    assert session["_viz_settings_dirty"] is True


def test_undo_takes_back_focusing_on_a_path(session):
    session["_viz_cfg_focus_seeds"] = [ORG]
    ui.viz_focus_on_path([PERSON, ORG])

    ui.viz_node_undo()

    assert session["_viz_cfg_focus_seeds"] == [ORG]
    assert session["_viz_cfg_focus_mode"] is False


def test_seeds_that_were_never_set_stay_unset(session):
    """None means "derive from the class selection"; [] would mean an empty
    focus, which leaves the mode on the next render."""
    ui.viz_apply_focus_click(PERSON)

    ui.viz_node_undo()

    assert "_viz_cfg_focus_seeds" not in session


def test_switching_files_forgets_the_history(session):
    _pick(session, A)
    ui._clear_viz_file_session_state()
    assert ui.VIZ_NODE_UNDO_KEY not in session


# --- redo ---------------------------------------------------------------------


def test_nothing_to_redo_until_something_is_undone(session):
    _pick(session, A)
    assert ui.viz_node_redo_available() is False


def test_redo_puts_back_what_undo_took_back(session):
    _pick(session, A, B)
    _pick(session, A)
    ui.viz_node_undo()
    ui.viz_node_undo()

    ui.viz_node_redo()
    assert session["_viz_cfg_selected_class_uris"] == [A, B]
    ui.viz_node_redo()
    assert session["_viz_cfg_selected_class_uris"] == [A]
    assert ui.viz_node_redo_available() is False
    # And the redone change can be undone again.
    ui.viz_node_undo()
    assert session["_viz_cfg_selected_class_uris"] == [A, B]


def test_a_new_change_drops_the_redo_steps(session):
    """It branches off from the undone ones, so replaying them would apply
    changes made to a view that is no longer there."""
    _pick(session, A)
    ui.viz_node_undo()
    _pick(session, B)

    assert ui.viz_node_redo_available() is False
    ui.viz_node_redo()
    assert session["_viz_cfg_selected_class_uris"] == [B]


def test_redo_takes_back_a_canvas_focus_click_again(session):
    session["_viz_cfg_focus_seeds"] = [ORG]
    ui.viz_apply_focus_click(PERSON, replace=True)
    ui.viz_node_undo()

    ui.viz_node_redo()

    assert session["_viz_cfg_focus_seeds"] == [PERSON]
    assert session["_viz_cfg_focus_mode"] is True


def test_auto_show_new_with_nothing_queued_keeps_the_redo_steps(session):
    """Switching it on changes no filter then, so it is not a new change."""
    _pick(session, A)
    ui.viz_node_undo()
    session["viz_auto_show_new"] = True
    ui.viz_auto_show_new_toggled()

    assert ui.viz_node_redo_available() is True


def test_switching_files_forgets_the_redo_steps_too(session):
    _pick(session, A)
    ui.viz_node_undo()
    ui._clear_viz_file_session_state()
    assert ui.VIZ_NODE_REDO_KEY not in session

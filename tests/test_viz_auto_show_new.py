"""Choosing whether new entities join a narrowed filter (issue #326).

A narrowed filter is a view the user built, so an entity created afterwards
waits behind "Show new" rather than pushing into it (issue #194). Which of the
two is wanted turns out to depend on the ontology rather than on taste: curating
a handful of key classes out of five hundred, a new class forcing its way in is
noise; building a small ontology class by class, being told every time that what
you just made is not on the canvas is friction. "Auto-show new" is that choice.

The default is off, so everything test_viz_new_class_hidden.py pins still holds.
"""

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app, ui

NS = "http://test.org/ont#"


# --- the reconcile itself ----------------------------------------------------


def _uris(*names):
    return [NS + n for n in names]


def test_off_keeps_a_new_entity_out_of_a_narrowed_filter():
    """Issue #194's behaviour, which stays the default."""
    selected, known = app.reconcile_filter_selection(
        _uris("Shown", "Hidden", "Bicycle"),
        _uris("Shown"),
        set(_uris("Shown", "Hidden")),
    )
    assert selected == _uris("Shown")
    assert known == set(_uris("Shown", "Hidden", "Bicycle"))


def test_on_lets_a_new_entity_into_a_narrowed_filter():
    selected, _known = app.reconcile_filter_selection(
        _uris("Shown", "Hidden", "Bicycle"),
        _uris("Shown"),
        set(_uris("Shown", "Hidden")),
        auto_show_new=True,
    )
    # In entity-list order, and the class deselected on purpose stays out: only
    # what the previous render had never seen is let in.
    assert selected == _uris("Shown", "Bicycle")


def test_on_still_drops_what_was_deleted():
    selected, _known = app.reconcile_filter_selection(
        _uris("Shown"),
        _uris("Shown", "Gone"),
        set(_uris("Shown", "Gone")),
        auto_show_new=True,
    )
    assert selected == _uris("Shown")


def test_on_leaves_a_deliberately_emptied_filter_empty():
    """An empty view is a view, and the one auto-add could never be undone from:
    every entity created afterwards would walk straight back into it.

    The new entity has to be in ``all_uris`` for this to test anything — with
    nothing new to add, the setting has no way to refill the filter and the
    assertion holds whatever the rule is (Codex review of PR #332).
    """
    selected, _known = app.reconcile_filter_selection(
        _uris("Shown", "Hidden", "Bicycle"),
        [],
        set(_uris("Shown", "Hidden")),
        auto_show_new=True,
    )
    assert selected == []


def test_an_emptied_filter_still_queues_what_was_created():
    """It degrades to the setting-off behaviour rather than swallowing the
    creation: "Show new" is still the way in."""
    all_uris = _uris("Shown", "Hidden", "Bicycle")
    selected, _known = app.reconcile_filter_selection(
        all_uris, [], set(_uris("Shown", "Hidden")), auto_show_new=True
    )
    assert app.newly_hidden_uris(all_uris, selected, set(_uris("Shown", "Hidden"))) == [
        NS + "Bicycle"
    ]


def test_taking_the_queue_in_makes_the_filter_non_empty_again():
    """And then it is a narrowed filter like any other, so the next creation
    joins it: emptiness is a state, not a permanent opt-out."""
    selected, known = app.reconcile_filter_selection(
        _uris("Shown", "Hidden", "Bicycle"),
        _uris("Bicycle"),
        set(_uris("Shown", "Hidden", "Bicycle")),
        auto_show_new=True,
    )
    assert selected == _uris("Bicycle")
    selected, _known = app.reconcile_filter_selection(
        _uris("Shown", "Hidden", "Bicycle", "Wheel"),
        selected,
        known,
        auto_show_new=True,
    )
    assert selected == _uris("Bicycle", "Wheel")


def test_on_does_not_change_a_replacement():
    """A load/import/undo shows everything either way."""
    for auto in (False, True):
        selected, _known = app.reconcile_filter_selection(
            _uris("A", "B"),
            _uris("A"),
            set(_uris("A", "B")),
            replaced=True,
            auto_show_new=auto,
        )
        assert selected == _uris("A", "B"), auto


# --- switching it on lets in what is already queued --------------------------


class _State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def session(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_switching_it_on_takes_in_what_show_new_was_offering(session):
    """Those are exactly the entities the setting says should have come in, and
    the reconcile can no longer see them as new — it has them in ``known``."""
    session["viz_auto_show_new"] = True
    session["_viz_cfg_selected_class_uris"] = _uris("Shown")
    session["_viz_new_hidden_class"] = _uris("Bicycle")
    session["_viz_cfg_selected_ind_uris"] = _uris("alice")
    session["_viz_new_hidden_ind"] = _uris("bob")

    app.viz_auto_show_new_toggled()

    assert session["_viz_cfg_auto_show_new"] is True
    assert set(session["_viz_cfg_selected_class_uris"]) == set(
        _uris("Shown", "Bicycle")
    )
    # Every filterable kind, not just the segment that happened to be on screen.
    assert set(session["_viz_cfg_selected_ind_uris"]) == set(_uris("alice", "bob"))


def test_switching_it_off_changes_no_selection(session):
    """Off is only a statement about entities created from now on; it must not
    retract anything already on the canvas."""
    session["viz_auto_show_new"] = False
    session["_viz_cfg_selected_class_uris"] = _uris("Shown", "Bicycle")
    session["_viz_new_hidden_class"] = _uris("Bicycle")

    app.viz_auto_show_new_toggled()

    assert session["_viz_cfg_auto_show_new"] is False
    assert session["_viz_cfg_selected_class_uris"] == _uris("Shown", "Bicycle")


def test_switching_it_on_with_nothing_queued_is_a_no_op(session):
    session["viz_auto_show_new"] = True
    session["_viz_cfg_selected_class_uris"] = _uris("Shown")

    app.viz_auto_show_new_toggled()

    assert session["_viz_cfg_selected_class_uris"] == _uris("Shown")


def test_a_missing_widget_is_not_read_as_unticked(session):
    """The page was not rendered, so the callback has nothing to sync — reading
    the absent key as False would silently turn the setting off (issue #219's
    failure mode)."""
    session["_viz_cfg_auto_show_new"] = True
    app.viz_auto_show_new_toggled()
    assert session["_viz_cfg_auto_show_new"] is True


# --- end to end on the page --------------------------------------------------


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app as _app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Shown")
        om.add_class("Hidden")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        uris = [c["uri"] for c in om.get_classes()]
        st.session_state["_viz_cfg_selected_class_uris"] = [
            u for u in uris if u.endswith("Shown")
        ]
        st.session_state["_viz_cfg_known_class_uris"] = set(uris)
    if st.session_state.pop("_test_add_class", False):
        st.session_state.ontology.add_class("Bicycle")
    _app.render_visualization()


def _rerun(at):
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _selected(at):
    return [
        u.rsplit("#", 1)[-1] for u in at.session_state["_viz_cfg_selected_class_uris"]
    ]


def test_the_page_defaults_to_holding_new_classes_back():
    at = AppTest.from_function(_script).run(timeout=300)
    assert not at.exception, at.exception
    assert at.session_state["_viz_cfg_auto_show_new"] is False


def test_with_the_setting_on_a_new_class_appears_and_nothing_is_announced():
    at = AppTest.from_function(_script).run(timeout=300)
    assert not at.exception, at.exception
    at.session_state["_viz_cfg_auto_show_new"] = True
    at.session_state["_test_add_class"] = True
    _rerun(at)

    assert _selected(at) == ["Bicycle", "Shown"]
    # Nothing was held back, so there is nothing to say and nothing to offer.
    assert not [t for t in at.toast if "hidden by your class filter" in t.value]
    assert not [b for b in at.button if b.label.startswith("Show new")]
    # The class deselected on purpose is still deselected.
    assert "Hidden" not in _selected(at)

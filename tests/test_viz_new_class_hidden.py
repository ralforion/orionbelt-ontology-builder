"""A class created while the node filter is narrowed (issue #194).

Auto-adding every new class into the filter was right for the default view and
wrong for a curated one, so a narrowed filter now keeps the class out. That
makes the creation invisible on the canvas, which is exactly the confusion that
opened issue #190 — so the page says what it held back and offers a way in.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Shown")
        om.add_class("Hidden")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        # A filter narrowed on purpose: `known` carries both classes, so the
        # deselected one reads as hidden rather than as never seen.
        uris = [c["uri"] for c in om.get_classes()]
        st.session_state["_viz_cfg_selected_class_uris"] = [
            u for u in uris if u.endswith("Shown")
        ]
        st.session_state["_viz_cfg_known_class_uris"] = set(uris)
    if st.session_state.pop("_test_add_class", False):
        st.session_state.ontology.add_class("Bicycle")
    if st.session_state.pop("_test_rename_shown", False):
        om = st.session_state.ontology
        old_uri = next(c["uri"] for c in om.get_classes() if c["name"] == "Shown")
        om.rename_class(old_uri, "Renamed")
        new_uri = next(c["uri"] for c in om.get_classes() if c["name"] == "Renamed")
        app.viz_note_rename("class", old_uri, new_uri)
    app.render_visualization()


def _rerun(at):
    """Run the page again.

    AppTest reads every button group's value as a list, but a single-select
    ``st.segmented_control`` (the page's tab picker, and the filter's kind
    picker) stores a plain string — so replaying the widget states for a second
    run raises inside Streamlit's own element tree. Handing each group the list
    form first is what lets this page be driven across renders at all.
    """
    for group in at.get("button_group"):
        value = group.value
        if not isinstance(value, list):
            group.set_value([value])
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _started():
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _add_a_class(at):
    at.session_state["_test_add_class"] = True
    return _rerun(at)


def _selected(at):
    return [
        u.rsplit("#", 1)[-1] for u in at.session_state["_viz_cfg_selected_class_uris"]
    ]


def test_the_new_class_stays_out_of_the_narrowed_filter():
    at = _add_a_class(_started())
    assert _selected(at) == ["Shown"]


def test_the_page_says_what_it_held_back():
    at = _add_a_class(_started())
    messages = [t.value for t in at.toast]
    assert "Bicycle created, hidden by your class filter" in messages


def test_the_panel_offers_a_one_click_way_in():
    at = _add_a_class(_started())
    button = at.button(key="viz_show_new_class")
    assert button.label == "Show new (1)"
    button.click()
    _rerun(at)
    # Added to the curated view rather than replacing it: Hidden stays hidden.
    assert _selected(at) == ["Bicycle", "Shown"]
    # And the offer goes away once it has been taken.
    assert at.session_state["_viz_new_hidden_class"] == []


def test_nothing_is_announced_while_the_filter_shows_everything():
    at = _started()
    uris = [c["uri"] for c in at.session_state.ontology.get_classes()]
    at.session_state["_viz_cfg_selected_class_uris"] = list(uris)
    _rerun(at)
    at = _add_a_class(at)
    assert _selected(at) == ["Bicycle", "Hidden", "Shown"]
    assert not [t for t in at.toast if "hidden by your class filter" in t.value]
    assert not [b for b in at.button if b.label.startswith("Show new")]


def test_the_offer_survives_a_rerun_that_changes_nothing():
    at = _rerun(_add_a_class(_started()))
    assert at.button(key="viz_show_new_class").label == "Show new (1)"
    # The toast is a one-off, though — it belongs to the render that created it.
    assert not [t for t in at.toast if "hidden by your class filter" in t.value]


def test_a_deleted_class_drops_out_of_the_offer():
    at = _add_a_class(_started())
    at.session_state.ontology.delete_class("Bicycle")
    _rerun(at)
    assert at.session_state["_viz_new_hidden_class"] == []


def test_renaming_the_one_class_on_screen_keeps_it_there():
    """The regression the review of #194 found.

    A rename mints a new URI, so a URI-keyed filter reads it as the class you
    were looking at being deleted and a stranger being created. With new
    entities no longer forcing themselves into a narrowed filter, that emptied
    the view and announced the rename as a creation.
    """
    at = _started()
    at.session_state["_test_rename_shown"] = True
    _rerun(at)
    assert _selected(at) == ["Renamed"]
    assert not [t for t in at.toast if "hidden by your class filter" in t.value]
    assert not [b for b in at.button if b.label.startswith("Show new")]


def test_the_rename_notes_are_still_consumed_once():
    # The filter only peeks at the notes: the focus-seed block below it owns
    # the pop, and taking them early would leave a renamed focus seed pointing
    # at nothing again (issue #275).
    at = _started()
    at.session_state["_test_rename_shown"] = True
    _rerun(at)
    assert "_viz_pending_renames" not in at.session_state

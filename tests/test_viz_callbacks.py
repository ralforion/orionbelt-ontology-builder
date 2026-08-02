"""The Visualization page's widget callbacks (issue #219).

Streamlit runs an ``on_change`` callback before the script reruns, and a widget
key is dropped from session_state once a run goes by without that widget being
rendered. This page mounts and unmounts widgets constantly, so a callback can
fire for a key that is no longer there — which used to kill the session with an
uncaught KeyError, or (for the node filters) quietly store an empty filter that
hid every node of a kind.

The callbacks were nested inside ``render_visualization``, so no test could
reach them. They are module-level now and driven directly here, inside an
``AppTest`` run so ``st.session_state`` is real.
"""

import ast
import inspect
import os

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app

URI = "http://example.org/ontology#a"


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app

    # The stored settings a callback writes into. Deliberately set to values a
    # skipped callback must leave exactly as they are.
    st.session_state["_viz_cfg_show_classes"] = True
    st.session_state["_viz_cfg_focus_mode"] = False
    st.session_state["_viz_cfg_selected_ind_uris"] = [os.environ["URI"]]
    uri_by_display = {"alice": os.environ["URI"]}

    scenario = os.environ["SCENARIO"]
    if scenario == "sync_widget_gone":
        st.session_state.pop("viz_show_classes", None)
        app.viz_sync("_viz_cfg_show_classes", "viz_show_classes")
    elif scenario == "sync_unticked":
        st.session_state["viz_show_classes"] = False
        app.viz_sync("_viz_cfg_show_classes", "viz_show_classes")
    elif scenario == "filter_widget_gone":
        st.session_state.pop("viz_selected_ind", None)
        app.viz_filter_changed("ind", uri_by_display)
    elif scenario == "filter_cleared":
        st.session_state["viz_selected_ind"] = []
        app.viz_filter_changed("ind", uri_by_display)
    elif scenario == "filter_picked":
        st.session_state["viz_selected_ind"] = ["alice"]
        app.viz_filter_changed("ind", uri_by_display)
    elif scenario == "focus_widget_gone":
        st.session_state.pop("viz_focus_mode", None)
        app.viz_focus_toggle()
    elif scenario == "focus_turned_on":
        st.session_state["_viz_cfg_selected_classes"] = ["Person"]
        st.session_state["viz_focus_mode"] = True
        app.viz_focus_toggle()
    elif scenario == "find_changed":
        app.viz_find_changed()

    # Only reached when the callback returned instead of raising.
    st.session_state["_callback_returned"] = True


def _run(scenario):
    os.environ["SCENARIO"] = scenario
    os.environ["URI"] = URI
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert at.session_state["_callback_returned"]
    return at.session_state


# --- a callback firing for a widget that is gone ----------------------------


def test_a_display_toggle_whose_widget_is_gone_is_left_alone():
    state = _run("sync_widget_gone")
    assert state["_viz_cfg_show_classes"] is True
    # Nothing was persisted, so the cross-session save gate stays shut.
    assert "_viz_settings_dirty" not in state


def test_a_node_filter_whose_widget_is_gone_is_left_alone():
    """The dangerous one: read as "nothing picked", it would store an empty
    filter and hide every individual — and persist that."""
    state = _run("filter_widget_gone")
    assert state["_viz_cfg_selected_ind_uris"] == [URI]


def test_the_focus_toggle_whose_widget_is_gone_is_left_alone():
    state = _run("focus_widget_gone")
    assert state["_viz_cfg_focus_mode"] is False
    assert "_viz_settings_dirty" not in state


# --- and still doing its job when the widget is there ------------------------


def test_an_unticked_checkbox_is_stored_rather_than_mistaken_for_absent():
    """Presence, not truthiness: False is a value the user chose."""
    state = _run("sync_unticked")
    assert state["_viz_cfg_show_classes"] is False
    assert state["_viz_settings_dirty"] is True


def test_a_cleared_filter_is_stored_rather_than_mistaken_for_absent():
    """Empty is a value the user chose too — it hides everything of that kind."""
    state = _run("filter_cleared")
    assert state["_viz_cfg_selected_ind_uris"] == []


def test_a_picked_filter_is_stored_by_uri():
    state = _run("filter_picked")
    assert state["_viz_cfg_selected_ind_uris"] == [URI]


def test_turning_focus_on_persists_it_and_seeds_from_the_selection():
    state = _run("focus_turned_on")
    assert state["_viz_cfg_focus_mode"] is True
    assert state["_viz_cfg_focus_seeds"] == ["Class: Person"]
    assert state["_viz_settings_dirty"] is True


def test_the_find_sequence_bumps():
    assert _run("find_changed")["_viz_find_seq"] == 1


# --- keep them reachable -----------------------------------------------------


def test_every_viz_callback_is_a_module_level_function():
    """These were nested inside render_visualization, which is why the crash
    survived: no test could call them. A new one hidden in there again would be
    just as unreachable."""
    tree = ast.parse(inspect.getsource(app))
    wired = {
        kw.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "on_change" and isinstance(kw.value, ast.Name)
    }
    assert wired, "no on_change wiring found — did the widgets change?"
    for name in sorted(wired):
        assert callable(getattr(app, name, None)), (
            f"{name} is wired as on_change but is not a module-level function"
        )

"""Regression tests for the View Classes page selector (issue #140 / PR #143).

These render the real ``render_classes`` via Streamlit's ``AppTest`` so the
session-state interplay between the auto-jump and the manual page selector is
exercised end to end. Each case is a single run (no widget-interaction rerun),
seeded through the environment because ``AppTest.from_function`` executes the
script source in a fresh namespace without the test's closures.
"""

import os

from streamlit.testing.v1 import AppTest


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for i in range(120):  # 3 pages at 50 per page
            om.add_class(f"Class{i:03d}")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

        classes = om.get_classes()  # sorted by name, matching the render order
        open_idx = int(os.environ["OPEN_IDX"])
        if open_idx >= 0:
            uid = app._uid(classes[open_idx]["uri"])
            st.session_state[f"view_class_{uid}"] = True
            if os.environ.get("SET_TRACKER") == "1":
                st.session_state["_cls_active_page_uid"] = uid
        if os.environ.get("SET_PAGE"):
            st.session_state["cls_view_page"] = int(os.environ["SET_PAGE"])

    app.render_classes()


def _run(open_idx, set_page, set_tracker):
    os.environ["OPEN_IDX"] = str(open_idx)
    os.environ["SET_PAGE"] = str(set_page) if set_page is not None else ""
    os.environ["SET_TRACKER"] = "1" if set_tracker else "0"
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _shown_range(at):
    for c in at.caption:
        if "of 120" in c.value:
            return c.value
    return None


def test_manual_page_change_sticks_while_card_open():
    # A card is open on page 1 and already jumped to (tracker set); the user then
    # moves to page 2. The auto-jump must NOT drag them back to page 1.
    at = _run(open_idx=0, set_page=2, set_tracker=True)
    assert _shown_range(at) == "Showing classes 51–100 of 120."


def test_opening_a_card_jumps_to_its_page_once():
    # Same open card and page 2, but this is the first render after opening it
    # (no tracker yet): the page should jump to the card's page (1).
    at = _run(open_idx=0, set_page=2, set_tracker=False)
    assert _shown_range(at) == "Showing classes 1–50 of 120."
    # And the jump is recorded so it won't fire again on later renders.
    assert at.session_state["_cls_active_page_uid"]


def test_no_card_open_leaves_the_chosen_page_alone():
    at = _run(open_idx=-1, set_page=3, set_tracker=False)
    assert _shown_range(at) == "Showing classes 101–120 of 120."


def _script_multi():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for i in range(120):
            om.add_class(f"Class{i:03d}")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

        classes = om.get_classes()
        for idx in os.environ["OPEN_IDXS"].split(","):
            st.session_state[f"view_class_{app._uid(classes[int(idx)]['uri'])}"] = True
        _lo = int(os.environ["LAST_OPENED_IDX"])
        st.session_state["_last_opened_entity"] = (
            "class",
            app._uid(classes[_lo]["uri"]),
        )
        _tr = os.environ["TRACKER_IDX"]
        if _tr:
            st.session_state["_cls_active_page_uid"] = app._uid(
                classes[int(_tr)]["uri"]
            )
        st.session_state["cls_view_page"] = int(os.environ["SET_PAGE"])

    app.render_classes()


def _class_uids(n=120):
    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    om = OntologyManager()
    for i in range(n):
        om.add_class(f"Class{i:03d}")
    return [app._uid(c["uri"]) for c in om.get_classes()]


def test_clicking_a_class_on_a_later_page_wins_over_a_hidden_open_one():
    # A class opened on page 1 is still flagged (hidden) while the user is on
    # page 2 and clicks View on a class there. The just-clicked class must win:
    # it stays open, the stale one is cleared, and the page follows the new card.
    uids = _class_uids()
    os.environ["OPEN_IDXS"] = "0,60"  # class 0 (page 1, hidden) + class 60 (page 2)
    os.environ["LAST_OPENED_IDX"] = "60"
    os.environ["TRACKER_IDX"] = "0"  # previously jumped to class 0
    os.environ["SET_PAGE"] = "2"
    at = AppTest.from_function(_script_multi)
    at.run(timeout=120)
    assert not at.exception, at.exception

    assert _shown_range(at) == "Showing classes 51–100 of 120."
    assert at.session_state[f"view_class_{uids[60]}"] is True
    _stale = f"view_class_{uids[0]}"
    assert _stale not in at.session_state or at.session_state[_stale] is False
    assert at.session_state["_cls_active_page_uid"] == uids[60]

"""Pagination coverage for the other per-item list views (issue #146).

Classes are covered in test_classes_page_ui.py; these exercise the same shared
helpers on the Individuals view (an expander list via _resolve_list_view) and the
Relations view (plain rows via _paginate_rows). Each case is a single AppTest run
seeded through the environment, since AppTest.from_function runs the script source
in a fresh namespace.
"""

import os

from streamlit.testing.v1 import AppTest


def _ind_script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Thing")
        for i in range(120):  # 3 pages at 50 per page
            om.add_individual(f"Ind{i:03d}", class_name="Thing")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        _p = os.environ.get("IND_PAGE")
        if _p:
            st.session_state["ind_view_page"] = int(_p)
        _f = os.environ.get("IND_FILTER")
        if _f:
            st.session_state["ind_view_page__filter"] = _f
        _a = os.environ.get("IND_ACTIVE")
        if _a:
            from orionbelt_ontology_builder.ui import _uid

            uri = next(i["uri"] for i in om.get_individuals() if i["name"] == _a)
            st.session_state["active_ind"] = (_uid(uri), "view")

    app.render_individuals()


def _rel_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Thing")
        om.add_individual("Hub", class_name="Thing")
        for i in range(120):
            om.add_individual(f"Ind{i:03d}", class_name="Thing")
            om.add_individual_relation("Hub", "differentFrom", f"Ind{i:03d}")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    app.render_relations()


def _shown(at, needle):
    return next((c.value for c in at.caption if needle in c.value), None)


def _run_individuals(**env) -> AppTest:
    for name in ("IND_PAGE", "IND_FILTER", "IND_ACTIVE"):
        os.environ.pop(name, None)
    os.environ.update(env)
    at = AppTest.from_function(_ind_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def test_individuals_view_paginates():
    os.environ.pop("IND_PAGE", None)
    os.environ.pop("IND_FILTER", None)
    os.environ.pop("IND_ACTIVE", None)
    at = AppTest.from_function(_ind_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert _shown(at, "of 120") == "Showing individuals 1–50 of 120."
    # Count the individual cards (each also nests a "Show Usages" expander).
    cards = [e for e in at.expander if "👤" in e.label]
    assert len(cards) == 50  # bounded, not 120


def test_individuals_view_last_page_is_short_and_clamps():
    os.environ.pop("IND_FILTER", None)
    os.environ.pop("IND_ACTIVE", None)
    os.environ["IND_PAGE"] = "99"  # out of range -> clamps to the last page
    at = AppTest.from_function(_ind_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert _shown(at, "of 120") == "Showing individuals 101–120 of 120."
    cards = [e for e in at.expander if "👤" in e.label]
    assert len(cards) == 20


def test_relations_view_paginates_rows():
    at = AppTest.from_function(_rel_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert _shown(at, "of 120") == "Showing individual relations 1–50 of 120."
    # Each relation row renders one delete button; the page bounds them to 50.
    del_buttons = [b for b in at.button if b.key and b.key.startswith("del_irel_")]
    assert len(del_buttons) == 50


def test_a_filter_narrows_the_list_and_drops_the_pager():
    at = _run_individuals(IND_FILTER="ind00*")
    assert (
        _shown(at, "filtered") == "Showing individuals 1–10 of 10 (filtered from 120)."
    )
    cards = [e for e in at.expander if "👤" in e.label]
    assert len(cards) == 10
    assert not [n for n in at.number_input if n.key == "ind_view_page"]


def test_a_filter_matching_nothing_says_so():
    at = _run_individuals(IND_FILTER="Nobody")
    assert _shown(at, "match") == "No individuals match “Nobody”."
    assert not [e for e in at.expander if "👤" in e.label]


def test_a_card_opened_elsewhere_clears_a_filter_that_hides_it():
    # As the graph or the sidebar search would open it.
    at = _run_individuals(IND_FILTER="ind00*", IND_ACTIVE="Ind075")
    assert at.text_input(key="ind_view_page__filter").value == ""
    assert [e.label for e in at.expander if "👤" in e.label and e.proto.expanded] == [
        next(e.label for e in at.expander if "Ind075" in e.label)
    ]

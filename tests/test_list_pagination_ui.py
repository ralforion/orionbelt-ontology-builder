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


def test_individuals_view_paginates():
    os.environ.pop("IND_PAGE", None)
    at = AppTest.from_function(_ind_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert _shown(at, "of 120") == "Showing individuals 1–50 of 120."
    # Count the individual cards (each also nests a "Show Usages" expander).
    cards = [e for e in at.expander if "👤" in e.label]
    assert len(cards) == 50  # bounded, not 120


def test_individuals_view_last_page_is_short_and_clamps():
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

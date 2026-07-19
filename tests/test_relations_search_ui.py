"""End-to-end: the Relations search box narrows the rendered rows (issue #148).

Single AppTest run seeded via session_state, matching the other UI tests here.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ["Dog", "Cat", "Animal", "Creature", "Plant"]:
            om.add_class(name)
        # subClassOf: Dog->Animal, Cat->Animal, Plant->Creature
        om.add_class_relation("Dog", "subClassOf", "Animal")
        om.add_class_relation("Cat", "subClassOf", "Animal")
        om.add_class_relation("Plant", "subClassOf", "Creature")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["rel_active_tab"] = "View Relations"
        st.session_state["rel_search"] = "dog"  # seed the search query

    from orionbelt_ontology_builder import app

    app.render_relations()


def test_relations_search_filters_rendered_rows():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    # Only the Dog->Animal class relation matches "dog"; one delete button remains.
    del_buttons = [b for b in at.button if b.key and b.key.startswith("del_crel_")]
    assert len(del_buttons) == 1

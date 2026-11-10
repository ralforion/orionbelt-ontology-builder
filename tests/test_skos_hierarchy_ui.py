"""The concept hierarchy is one text block, like the class tree (WP3)."""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st
    from rdflib.namespace import SKOS

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/k#")
        om.add_concept_scheme("Things")
        om.add_concept("Animal", scheme="Things", pref_label="Animal")
        om.add_concept("Pet", scheme="Things", pref_label="Pet")
        om.add_concept("Dog", scheme="Things", pref_label="Dog", broader="Animal")
        # A second broader concept, and a cycle of two.
        om.graph.add((om._uri("Dog"), SKOS.broader, om._uri("Pet")))
        om.graph.add((om._uri("Pet"), SKOS.narrower, om._uri("Dog")))
        om.add_concept("Ping", scheme="Things", pref_label="Ping")
        om.add_concept("Pong", scheme="Things", pref_label="Pong", broader="Ping")
        om.graph.add((om._uri("Ping"), SKOS.broader, om._uri("Pong")))
        om.graph.add((om._uri("Pong"), SKOS.narrower, om._uri("Ping")))
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
    st.session_state["skos_active_tab"] = "Concept Hierarchy"
    app.render_skos_vocabulary()


def test_the_hierarchy_is_one_block_that_survives_a_cycle():
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    assert len(at.code) == 1
    tree = at.code[0].value
    # Under both of its broader concepts, its own subtree once.
    assert tree.count("Dog (Dog)") == 2
    assert "(cycle)" in tree
    assert {"Animal", "Pet", "Ping", "Pong"} <= {
        line.strip(" └─").split(" ")[0] for line in tree.splitlines()
    }

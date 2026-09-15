"""The Source page shows a large ontology only on request (issue #437)."""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.views import source as source_view


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    app.render_source()


def test_a_small_source_renders_at_once():
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert len(at.code) == 1
    assert "Bicycle" in at.code[0].value
    assert not at.button


def test_a_large_source_waits_for_a_click(monkeypatch):
    monkeypatch.setattr(source_view, "SOURCE_AUTO_RENDER_MAX_CHARS", 10)
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert not at.code
    assert "lines" in at.caption[0].value
    at.button(key="btn_source_show").click().run(timeout=60)
    assert len(at.code) == 1
    assert "Bicycle" in at.code[0].value
    # Once asked for, it stays shown for the session.
    at.run(timeout=60)
    assert len(at.code) == 1

"""The Source page writes the Turtle only on request (issues #437, WP3)."""

from streamlit.testing.v1 import AppTest


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


def _spy_exports(monkeypatch):
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    calls = []
    real = OntologyManager.export_to_string.__wrapped__

    def counting(self, format="turtle", content="all"):
        calls.append(format)
        return real(self, format=format, content=content)

    monkeypatch.setattr(OntologyManager, "export_to_string", counting)
    return calls


def test_a_visit_writes_nothing_until_asked(monkeypatch):
    exports = _spy_exports(monkeypatch)
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert not at.code
    assert "triples" in at.caption[0].value
    assert exports == []

    at.button(key="btn_source_generate").click().run(timeout=60)
    assert len(at.code) == 1
    assert "Bicycle" in at.code[0].value


def test_the_source_stays_shown_while_the_ontology_is_unchanged():
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    at.button(key="btn_source_generate").click().run(timeout=60)
    at.run(timeout=60)
    assert len(at.code) == 1
    assert not at.button


def test_an_edit_waits_for_a_regenerate():
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    at.button(key="btn_source_generate").click().run(timeout=60)
    at.session_state["ontology"].add_class("Tandem")
    at.run(timeout=60)
    assert not at.code
    assert "changed since" in at.caption[0].value
    regenerate = at.button(key="btn_source_generate")
    assert regenerate.label == "Regenerate source"
    regenerate.click().run(timeout=60)
    assert "Tandem" in at.code[0].value

"""What the app says when an ontology is large (WP3)."""

from streamlit.testing.v1 import AppTest


def _main_script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    app.LARGE_ONTOLOGY_TRIPLES = int(os.environ.get("LARGE_AT", "100000"))
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/n#")
        om.add_class("Bicycle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["nav_radio"] = "Dashboard"
    app.main()


def _sidebar_captions(at):
    return [c.value for c in at.sidebar.caption]


def test_the_sidebar_says_when_an_ontology_is_large(monkeypatch):
    monkeypatch.setenv("LARGE_AT", "2")
    at = AppTest.from_function(_main_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    assert any("Large ontology" in c for c in _sidebar_captions(at))


def test_a_small_ontology_gets_no_such_note(monkeypatch):
    monkeypatch.delenv("LARGE_AT", raising=False)
    at = AppTest.from_function(_main_script)
    at.run(timeout=60)
    assert not any("Large ontology" in c for c in _sidebar_captions(at))


def _reasoning_script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.views import validation

    validation.REASONING_SLOW_TRIPLES = int(os.environ.get("SLOW_AT", "20000"))
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/n#")
        om.add_class("Bicycle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_quality_configs_restored"] = True
    st.session_state["val_active_tab"] = "Reasoning"
    app.render_validation()


def test_reasoning_warns_before_a_slow_owlrl_run(monkeypatch):
    monkeypatch.setenv("SLOW_AT", "2")
    at = AppTest.from_function(_reasoning_script)
    at.run(timeout=60)
    assert not at.warning  # RDFS, computed natively, takes seconds
    at.selectbox[0].set_value(("OWL-RL", "owl-rl")).run(timeout=60)
    assert any("many minutes" in w.value for w in at.warning)

    monkeypatch.delenv("SLOW_AT")
    at = AppTest.from_function(_reasoning_script)
    at.run(timeout=60)
    at.selectbox[0].set_value(("OWL-RL", "owl-rl")).run(timeout=60)
    assert not at.warning

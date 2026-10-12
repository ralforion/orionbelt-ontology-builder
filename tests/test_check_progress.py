"""The quality and SHACL runs say where they are while they run."""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import QualityConfig, analyze


def test_analyze_reports_each_rule_before_running_it():
    om = OntologyManager(base_uri="http://test.org/q#")
    om.add_class("A", label="A")
    config = QualityConfig()
    calls = []
    run = analyze(
        om, config, progress=lambda done, total, rule: calls.append((done, total, rule))
    )
    enabled = config.enabled_rules()
    assert calls == [(i, len(enabled), rule) for i, rule in enumerate(enabled)]
    assert [s.rule_id for s in run.rules] == enabled


def _page(section):
    def page():
        import streamlit as st

        from orionbelt_ontology_builder import app
        from orionbelt_ontology_builder.ontology_manager import OntologyManager

        if "ontology" not in st.session_state:
            om = OntologyManager(base_uri="http://test.org/q#")
            om.add_class("Labelled", label="Labelled")
            om.add_class("Unlabelled")
            st.session_state.ontology = om
            st.session_state["_autosave_restored"] = True
            st.session_state["_viz_settings_restored"] = True
            st.session_state["_local_storage"] = None
            st.session_state["_quality_configs_restored"] = True
        st.session_state["val_active_tab"] = st.session_state.get("_section", "Quality")
        app.render_validation()

    at = AppTest.from_function(page)
    at.session_state["_section"] = section
    return at


def test_the_quality_run_leaves_no_progress_bar_behind():
    at = _page("Quality")
    at.run(timeout=120)
    next(b for b in at.button if b.label == "Run Quality Checks").click().run()
    assert not at.exception, at.exception
    assert not at.get("progress")
    assert any("Message" in f.value.columns for f in at.dataframe)


def test_the_shacl_run_leaves_no_progress_bar_behind():
    at = _page("SHACL")
    at.run(timeout=120)
    next(c for c in at.checkbox if c.label == "OrionBelt quality policy").check().run()
    next(c for c in at.checkbox if c.label == "Generated from the model").check().run()
    next(b for b in at.button if b.label == "Run SHACL check").click().run()
    assert not at.exception, at.exception
    assert not at.get("progress")
    assert any("(built-in)" in md.value for md in at.markdown)

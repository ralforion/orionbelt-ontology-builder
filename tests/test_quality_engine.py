"""The quality analyzer's contract: config, isolation, applicability, determinism."""

import json

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, SKOS
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import quality
from orionbelt_ontology_builder.quality import (
    RULES,
    QualityConfig,
    QualityConfigError,
    RuleSettings,
    analyze,
)
from orionbelt_ontology_builder.quality.registry import Rule, RuleResult


def _om():
    om = OntologyManager(base_uri="http://test.org/q#")
    om.add_class("C", label="C")
    om.add_class("A", parent="C", label="A")
    om.add_class("B", parent="A", label="B")
    om.add_class_relation("B", "subClassOf", "C")
    om.add_class("NoLabel")
    return om


# -- configuration -----------------------------------------------------------


class TestConfig:
    def test_defaults_follow_the_rules(self):
        config = QualityConfig()
        assert config.enabled("Q019") and not config.enabled("Q022")
        assert config.severity("Q019") == "warning"

    def test_override_beats_default(self):
        config = QualityConfig(rules={"Q022": RuleSettings(True, "warning")})
        assert config.enabled("Q022")
        assert config.severity("Q022") == "warning"

    @pytest.mark.parametrize(
        ("data", "field"),
        [
            ({"rules": {"Q999": {"enabled": True}}}, "rules.Q999"),
            ({"rules": {"Q001": {"severity": "fatal"}}}, "rules.Q001.severity"),
            ({"rules": {"Q001": {"enabled": "yes"}}}, "rules.Q001.enabled"),
            ({"rules": {"Q001": {"colour": "red"}}}, "rules.Q001"),
            ({"profile": "nope"}, "profile"),
            ({"include_imports": 1}, "include_imports"),
            ({"extra": True}, "config"),
            ([], "config"),
        ],
    )
    def test_invalid_configs_name_the_field(self, data, field):
        with pytest.raises(QualityConfigError, match=field.replace(".", r"\.")):
            QualityConfig.from_dict(data)

    def test_json_round_trip(self):
        config = QualityConfig(
            include_imports=True,
            rules={
                "Q022": RuleSettings(enabled=True),
                "Q001": RuleSettings(severity="info"),
            },
        )
        again = QualityConfig.from_json(config.to_json())
        assert again == config
        assert json.loads(config.to_json())["rules"]["Q001"] == {"severity": "info"}

    def test_bad_json_is_a_config_error(self):
        with pytest.raises(QualityConfigError, match="not valid JSON"):
            QualityConfig.from_json("{")

    def test_fingerprint_tracks_the_effective_config(self):
        base = QualityConfig()
        assert base.fingerprint == QualityConfig().fingerprint
        # Restating a default changes nothing that runs.
        same = QualityConfig(rules={"Q019": RuleSettings(enabled=True)})
        assert same.fingerprint == base.fingerprint
        assert QualityConfig(include_imports=True).fingerprint != base.fingerprint
        off = QualityConfig(rules={"Q019": RuleSettings(enabled=False)})
        assert off.fingerprint != base.fingerprint


# -- the run -----------------------------------------------------------------


class TestRun:
    def test_disabled_rules_do_not_run(self):
        run = analyze(_om(), QualityConfig(rules={"Q001": RuleSettings(False)}))
        assert run.status("Q001") is None
        assert run.by_rule("Q001") == []

    def test_configured_severity_is_reported(self):
        config = QualityConfig(rules={"Q019": RuleSettings(severity="error")})
        [finding] = analyze(_om(), config).by_rule("Q019")
        assert finding.severity == "error"

    def test_findings_are_sorted_by_severity_then_rule(self):
        config = QualityConfig(rules={"Q007": RuleSettings(severity="error")})
        run = analyze(_om(), config)
        keys = [(f.severity, f.rule_id) for f in run.findings]
        order = {"error": 0, "warning": 1, "info": 2}
        assert keys == sorted(keys, key=lambda k: (order[k[0]], k[1]))
        assert run.findings[0].severity == "error"

    def test_runs_are_deterministic(self):
        om = _om()
        first, second = analyze(om), analyze(om)
        assert first.findings == second.findings
        assert first.graph_fingerprint == second.graph_fingerprint

    def test_counts_and_metadata(self):
        run = analyze(_om())
        assert run.counts()["warning"] == len(
            [f for f in run.findings if f.severity == "warning"]
        )
        assert run.analyzer_version
        assert run.started_at.endswith("+00:00")
        assert run.config_fingerprint == QualityConfig().fingerprint

    def test_graph_fingerprint_moves_with_edits(self):
        om = _om()
        before = analyze(om).graph_fingerprint
        assert om.revision_token() == before
        om.add_class("Later", label="Later")
        assert om.revision_token() != before

    def test_a_failing_rule_is_reported_not_swallowed(self, monkeypatch):
        def boom(ctx, severity):
            raise RuntimeError("kaboom")

        monkeypatch.setitem(RULES, "Q019", _replace(RULES["Q019"], evaluate=boom))
        run = analyze(_om())
        status = run.status("Q019")
        assert status.state == "failed" and "RuntimeError: kaboom" in status.reason
        # The rest of the run went on.
        assert run.status("Q001").state == "ran"
        assert run.by_rule("Q001")

    def test_duplicate_findings_are_dropped(self, monkeypatch):
        original = RULES["Q019"]

        def twice(ctx, severity):
            result = original.evaluate(ctx, severity)
            return RuleResult(
                findings=result.findings * 2,
                checked=result.checked,
                affected=result.affected,
            )

        monkeypatch.setitem(RULES, "Q019", _replace(original, evaluate=twice))
        assert len(analyze(_om()).by_rule("Q019")) == 1

    def test_rules_never_write_to_the_graph(self, monkeypatch):
        om = _om()

        def refuse(*args, **kwargs):
            raise AssertionError("a quality rule wrote to the graph")

        everything = QualityConfig(rules={r: RuleSettings(enabled=True) for r in RULES})
        before = len(om.graph)
        monkeypatch.setattr(om.graph, "add", refuse)
        monkeypatch.setattr(om.graph, "remove", refuse)
        run = analyze(om, everything)
        assert all(s.state == "ran" for s in run.rules), run.rules
        assert len(om.graph) == before


def _replace(rule: Rule, **changes) -> Rule:
    from dataclasses import replace

    return replace(rule, **changes)


class TestApplicability:
    def test_owl_rules_skip_a_skos_only_graph(self):
        om = OntologyManager(base_uri="http://test.org/v#")
        concept = URIRef("http://test.org/v#c1")
        om.graph.add((concept, RDF.type, SKOS.Concept))
        om.graph.add((concept, SKOS.prefLabel, Literal("c1", lang="en")))
        run = analyze(om)
        assert run.status("Q019").state == "skipped"
        assert "OWL" in run.status("Q019").reason
        assert run.findings == ()

    def test_every_rule_declares_a_known_vocabulary(self):
        from orionbelt_ontology_builder.quality.registry import (
            OWL_PROFILE,
            SKOS_PROFILE,
        )

        for rule in RULES.values():
            assert rule.applies_to and rule.applies_to <= {OWL_PROFILE, SKOS_PROFILE}


def test_analyzer_does_not_import_streamlit():
    """The analyzer must run headless, from a test or a command line."""
    import subprocess
    import sys

    code = (
        "import sys, orionbelt_ontology_builder.quality as q;"
        "print('streamlit' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


def test_public_names():
    for name in quality.__all__:
        assert hasattr(quality, name), name


# -- page ----------------------------------------------------------------------


def _quality_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("C", label="C")
        om.add_class("B", parent="C", label="B")
        om.add_class("A", parent="B", label="A")
        # A second parent for A that its first one already implies.
        om.add_class_relation("A", "subClassOf", "C")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
    st.session_state["val_active_tab"] = (
        st.session_state.get("_quality_tab_override") or "Quality"
    )
    app.render_validation()


def _run_button(at):
    return next(b for b in at.button if b.label == "Run Quality Checks")


def test_page_runs_rules_and_opens_a_finding():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    assert not at.exception, at.exception
    _run_button(at).click().run()
    assert not at.exception, at.exception
    assert any("already implied by A ⊑ B ⊑ C" in md.value for md in at.markdown)
    assert not at.warning  # fresh results
    assert not at.metric  # no headline score

    next(b for b in at.button if b.label == "Open").click().run()
    assert not at.exception, at.exception
    assert at.session_state["search_navigate_to"] == "Classes"


def test_page_marks_results_stale_after_an_edit():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    _run_button(at).click().run()
    at.session_state["ontology"].add_class("Later", label="Later")
    at.run()
    assert any("changed since this run" in w.value for w in at.warning)
    # The old findings stay up until the next run.
    assert any("already implied" in md.value for md in at.markdown)


# -- review fixes (PR #504) ------------------------------------------------------


def test_a_new_manager_never_shares_a_token():
    """Loading a file builds a new manager whose revision counter can land on
    the same number as the old one's; the token must still differ."""
    first, second = _om(), _om()
    assert first.revision_token() != second.revision_token()


def test_replacing_the_graph_changes_the_token():
    om = _om()
    before = om.revision_token()
    om.load_from_string(om.graph.serialize(format="turtle"))
    assert om.revision_token() != before


def test_replaced_ontology_marks_results_stale():
    """The linked-file reload swaps in a new manager for the same ontology."""
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    _run_button(at).click().run()
    old = at.session_state["ontology"]
    fresh = OntologyManager(base_uri="http://test.org/q#")
    fresh.load_from_string(old.graph.serialize(format="turtle"))
    at.session_state["ontology"] = fresh
    at.run()
    assert any("changed since this run" in w.value for w in at.warning)


def test_rule_selection_survives_leaving_the_quality_section():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    q022 = next(c for c in at.checkbox if c.label.startswith("Q022"))
    imports = next(c for c in at.checkbox if c.label == "Include imported vocabularies")
    q022.check()
    imports.check()
    at.run()
    # Away to another section, where the Quality widgets are not rendered...
    at.session_state["_quality_tab_override"] = "Validation"
    at.run()
    assert not [c for c in at.checkbox if c.label.startswith("Q022")]
    # ...and back.
    at.session_state["_quality_tab_override"] = None
    at.run()
    assert next(c for c in at.checkbox if c.label.startswith("Q022")).value
    assert next(
        c for c in at.checkbox if c.label == "Include imported vocabularies"
    ).value


def test_rule_toggles_still_flip_both_ways():
    """Seeding the widgets from the stored config must not pin them."""
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)

    def q022():
        return next(c for c in at.checkbox if c.label.startswith("Q022"))

    q022().check()
    at.run()
    assert q022().value
    q022().uncheck()
    at.run()
    assert not q022().value
    stored = [
        v
        for k, v in at.session_state.filtered_state.items()
        if k.startswith("_quality_config_")
    ]
    assert stored and not stored[0].enabled("Q022")

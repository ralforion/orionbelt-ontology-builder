"""M4: findings table, rule settings kept per ontology, and exports."""

import csv
import io
import json

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import QualityConfig, RuleSettings, analyze
from orionbelt_ontology_builder.quality.exports import (
    CSV_COLUMNS,
    findings_csv,
    findings_json,
)

IRI = "http://test.org/q"


def _om():
    om = OntologyManager(base_uri=IRI + "#")
    om.add_class("C", label="C")
    om.add_class("B", parent="C", label="B")
    om.add_class("A", parent="B", label="A")
    om.add_class_relation("A", "subClassOf", "C")
    om.add_class("NoLabel")
    return om


# -- exports -------------------------------------------------------------------------


def test_json_export_carries_the_run_and_every_finding():
    run = analyze(_om())
    document = json.loads(findings_json(run.findings, run=run))
    assert document["source"] == "quality"
    assert document["run"]["graph_fingerprint"] == run.graph_fingerprint
    assert document["run"]["config_fingerprint"] == run.config_fingerprint
    assert {r["rule_id"] for r in document["run"]["rules"]} == {
        s.rule_id for s in run.rules
    }
    assert len(document["findings"]) == len(run.findings)
    redundant = next(f for f in document["findings"] if f["rule_id"] == "Q019")
    assert redundant["rule"] == "Redundant subclass edges"
    assert redundant["evidence"]["path"]


def test_csv_export_has_one_row_per_finding():
    run = analyze(_om())
    rows = list(csv.DictReader(io.StringIO(findings_csv(run.findings))))
    assert len(rows) == len(run.findings)
    assert tuple(rows[0]) == CSV_COLUMNS
    redundant = next(r for r in rows if r["rule_id"] == "Q019")
    assert json.loads(redundant["evidence"])["redundant_parent"].endswith("#C")


# -- settings persistence ------------------------------------------------------------


class _FakeLS:
    def __init__(self, value):
        self.value = value
        self.written = None

    def getItem(self, key):
        return self.value

    def setItem(self, item_key, value, **kwargs):
        self.written = value


@pytest.fixture
def state(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def test_disk_persist_and_restore_roundtrip(monkeypatch, state, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(ui.local_store, "config_file", lambda: cfg_file)
    config = QualityConfig(rules={"Q022": RuleSettings(enabled=True)})
    state[ui.QUALITY_CONFIGS_STATE] = {IRI: config.to_dict()}
    state["_quality_configs_dirty"] = True
    ui.persist_quality_configs()
    assert json.loads(cfg_file.read_text())[ui.QUALITY_CONFIGS_KEY] == {
        IRI: config.to_dict()
    }

    state.clear()
    ui.restore_quality_configs()
    assert state["_quality_configs_restored"] is True
    assert QualityConfig.from_dict(state[ui.QUALITY_CONFIGS_STATE][IRI]).enabled("Q022")
    assert state[ui.QUALITY_CONFIGS_GENERATION] == 1


def test_persist_requires_a_change(monkeypatch, state, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(ui.local_store, "config_file", lambda: cfg_file)
    state[ui.QUALITY_CONFIGS_STATE] = {IRI: QualityConfig().to_dict()}
    ui.persist_quality_configs()
    assert not cfg_file.exists()


def test_browser_restore_retries_until_a_value_arrives(monkeypatch, state):
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    monkeypatch.setattr(ui, "_get_local_storage", lambda: _FakeLS(None))
    ui.restore_quality_configs()
    assert "_quality_configs_restored" not in state


def test_restore_drops_settings_that_no_longer_validate(monkeypatch, state):
    saved = json.dumps(
        {
            IRI: {"rules": {"Q022": {"enabled": True}}},
            "http://other": {"rules": {"Q999": {"enabled": True}}},
        }
    )
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    monkeypatch.setattr(ui, "_get_local_storage", lambda: _FakeLS(saved))
    ui.restore_quality_configs()
    assert set(state[ui.QUALITY_CONFIGS_STATE]) == {IRI}


def test_browser_persist_writes_the_settings(monkeypatch, state):
    storage = _FakeLS(None)
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    monkeypatch.setattr(ui, "_get_local_storage", lambda: storage)
    state[ui.QUALITY_CONFIGS_STATE] = {IRI: QualityConfig().to_dict()}
    state["_quality_configs_dirty"] = True
    ui.persist_quality_configs()
    assert json.loads(storage.written) == {IRI: QualityConfig().to_dict()}


# -- page ------------------------------------------------------------------------------


def _quality_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("C", label="C")
        om.add_class("B", parent="C", label="B")
        om.add_class("A", parent="B", label="A")
        om.add_class_relation("A", "subClassOf", "C")
        om.add_class("NoLabel")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["_quality_configs_restored"] = True
    st.session_state["val_active_tab"] = "Quality"
    app.render_validation()


def _run(at):
    next(b for b in at.button if b.label == "Run Quality Checks").click().run()
    assert not at.exception, at.exception


def _table(at):
    return next(f.value for f in at.dataframe if "Message" in f.value.columns)


def _stored(at):
    [raw] = at.session_state[ui.QUALITY_CONFIGS_STATE].values()
    return QualityConfig.from_dict(raw)


def test_severity_override_reaches_the_findings():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    sev = next(
        s for s in at.selectbox if s.label == "Severity of Redundant subclass edges"
    )
    sev.select("error").run()
    assert _stored(at).severity("Q019") == "error"
    _run(at)
    table = _table(at)
    assert (
        table[table["Rule"] == "Redundant subclass edges"]["Severity"].iloc[0]
        == "🔴 error"
    )


def test_changing_the_profile_resets_the_rules():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    next(c for c in at.checkbox if c.label == "Multiple parents").check().run()
    assert _stored(at).enabled("Q022")
    next(s for s in at.selectbox if s.label == "Profile").select(
        "strict_documentation"
    ).run()
    stored = _stored(at)
    assert stored.profile == "strict_documentation" and stored.rules == {}
    # strict_documentation turns Q022 on itself, and the widget shows it.
    assert next(c for c in at.checkbox if c.label == "Multiple parents").value


def test_reset_drops_per_rule_changes():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    next(c for c in at.checkbox if c.label == "Multiple parents").check().run()
    next(b for b in at.button if b.label == "Reset to profile defaults").click().run()
    assert _stored(at).rules == {}
    assert not next(c for c in at.checkbox if c.label == "Multiple parents").value


def test_filters_narrow_the_table():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    _run(at)
    everything = len(_table(at))
    assert everything >= 2
    severity = next(m for m in at.multiselect if m.label == "Severity")
    severity.set_value(["warning"]).run()
    assert set(_table(at)["Severity"]) == {"🟡 warning"}
    severity.set_value(["error", "warning", "info"]).run()
    next(t for t in at.text_input if t.label == "Search").input("NoLabel").run()
    assert list(_table(at)["Resource"]) == ["NoLabel"] * len(_table(at))


def test_details_offer_related_resources_to_open():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    _run(at)
    table = _table(at)
    row = int(table.index[table["Rule"] == "Redundant subclass edges"][0])
    key = next(
        k
        for k in at.session_state.filtered_state
        if k.startswith("quality_") and "_table_" in k
    )
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    at.run()
    assert not at.exception, at.exception
    # The finding's own Open, plus one per related class (B and C).
    assert len([b for b in at.button if b.label == "Open"]) == 3
    assert any(e.label == "Evidence" for e in at.expander)


def test_settings_survive_leaving_and_reloading():
    """The settings live per ontology IRI, apart from the widgets."""
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    next(c for c in at.checkbox if c.label == "Multiple parents").check().run()
    at.session_state["val_active_tab"] = "Validation"
    configs = at.session_state[ui.QUALITY_CONFIGS_STATE]
    assert QualityConfig.from_dict(configs["http://test.org/q"]).enabled("Q022")


# -- review fixes (PR #507) ------------------------------------------------------------


def test_drawing_the_defaults_does_not_mark_settings_for_saving():
    """#1: before the browser's saved settings arrive, the page shows defaults;
    writing those back would overwrite the saved ones and block the restore."""
    at = AppTest.from_function(_quality_page)
    at.session_state["_quality_configs_restored"] = False
    at.run(timeout=120)
    at.run()
    assert "_quality_configs_dirty" not in at.session_state.filtered_state
    # A real change still is one.
    next(c for c in at.checkbox if c.label == "Multiple parents").check().run()
    assert at.session_state["_quality_configs_dirty"] is True


def test_a_severity_that_appears_on_a_rerun_is_shown():
    """#2: the severity filter must not keep only the severities of the last run."""
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    _run(at)
    sev = next(
        s for s in at.selectbox if s.label == "Severity of Redundant subclass edges"
    )
    sev.select("error").run()
    _run(at)
    assert "🔴 error" in set(_table(at)["Severity"])


def test_the_table_key_follows_the_rows_shown():
    """#3: a selection is a row position, so a new set of rows gets a fresh,
    unselected table rather than the old position pointing elsewhere."""
    from orionbelt_ontology_builder.views.findings import table_key

    findings = list(analyze(_om()).findings)
    assert len(findings) >= 2
    assert table_key("k", findings) == table_key("k", list(findings))
    assert table_key("k", findings) != table_key("k", findings[1:])
    assert table_key("k", findings) != table_key("k", findings[::-1])

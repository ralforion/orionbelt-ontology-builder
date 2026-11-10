"""The quality, SHACL and reasoning runs say where they are while they run."""

from rdflib import Literal, URIRef
from rdflib.namespace import RDFS
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


def test_applying_reasoning_leaves_no_progress_bar_behind():
    at = _page("Reasoning")
    at.run(timeout=120)
    next(b for b in at.button if b.label == "Apply Reasoning").click().run()
    assert not at.exception, at.exception
    assert not at.get("progress")
    assert not any(b.label == "Cancel" for b in at.button)
    assert any("New triple count" in md.value for md in at.markdown)


def test_a_cancelled_reasoning_run_says_nothing_changed_once():
    """The Cancel click stops the run itself; the next run reports it."""
    at = _page("Reasoning")
    at.session_state["_reasoning_cancelled"] = True
    at.run(timeout=120)
    assert any("cancelled" in info.value for info in at.info)
    at.run(timeout=120)
    assert not any("cancelled" in info.value for info in at.info)


# ---- a Cancel click that arrives while the result is being applied ---------


class _Click(BaseException):
    """What Streamlit raises at the next session access once a click came in."""


class _ClickableState(dict):
    """Session state that raises at its ``click_at``-th access.

    Streamlit checks for a pending rerun before every ``st.session_state``
    read and write, as well as before drawing an element, so this models a
    Cancel click landing at any point of the commit.
    """

    def __init__(self, click_at=None):
        super().__init__()
        self.click_at = click_at
        self.accesses = 0

    def _yield(self):
        self.accesses += 1
        if self.accesses == self.click_at:
            raise _Click

    def __getitem__(self, key):
        self._yield()
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self._yield()
        super().__setitem__(key, value)

    def __contains__(self, key):
        self._yield()
        return super().__contains__(key)

    def get(self, key, default=None):
        self._yield()
        return super().get(key, default)

    def pop(self, key, *default):
        self._yield()
        return super().pop(key, *default)


class _FakeSt:
    def __init__(self, state):
        self.session_state = state


def _commit_setup(patch_ui, click_at):
    from orionbelt_ontology_builder.ontology_manager import UndoManager
    from orionbelt_ontology_builder.reasoning import ClosureChange

    om = OntologyManager(base_uri="http://test.org/q#")
    om.add_class("A")
    undo = UndoManager(om)
    undo.checkpoint("Add A")
    state = _ClickableState(click_at)
    state.update(undo_manager=undo, _ont_mutation_count=7)
    patch_ui("st", _FakeSt(state))
    a = URIRef("http://test.org/q#A")
    change = ClosureChange(added=[(a, RDFS.comment, Literal("inferred"))], removed=[])
    return om, undo, state, change


def test_a_cancel_click_anywhere_in_the_commit_is_reported_truthfully(patch_ui):
    """Either the ontology is unchanged and the message says so, or the change
    landed whole, as an undo step autosave knows about, and the message says
    that. Never a changed graph without an undo step (Codex review, #545)."""
    from orionbelt_ontology_builder.views import validation

    om, _, state, change = _commit_setup(patch_ui, click_at=None)
    validation._commit_reasoning(om, change)
    accesses = state.accesses
    assert accesses

    for click_at in range(1, accesses + 2):
        om, undo, state, change = _commit_setup(patch_ui, click_at)
        before = set(om.graph)
        try:
            validation._commit_reasoning(om, change)
        except _Click:
            pass
        state.click_at = None
        state["_reasoning_cancelled"] = True  # the button's callback, next run
        text, _kind = validation._cancel_message(om)
        if set(om.graph) == before:
            assert "not changed" in text, click_at
        else:
            assert "already finished" in text and "1 triples" in text, click_at
            assert state["_ont_mutation_count"] > 7, click_at  # autosave looks
            assert undo.undo() == "Add A", click_at
            assert set(om.graph) == before, click_at

"""Previewing the import of a large ontology (reported on streamlit.app with a
273k-triple file: Preview Import ran for minutes and seemed to do nothing)."""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ontology_manager import OntologyManager


def _incoming(classes: int) -> str:
    om = OntologyManager(base_uri="http://test.org/in#")
    for i in range(classes):
        om.add_class(f"C{i}", label=f"Class {i}")
    return om.export_to_string("turtle")


def test_the_comparison_builds_its_subject_sets_once(monkeypatch):
    """Built per changed subject, they made the comparison quadratic: 113 s of
    a 128 s preview at 65,000 subjects."""
    seen = []
    real = OntologyManager._classify_resource_change

    def spying(self, subject, added, removed):
        seen.append((id(added), id(removed)))
        return real(self, subject, added, removed)

    monkeypatch.setattr(OntologyManager, "_classify_resource_change", spying)
    om = OntologyManager(base_uri="http://test.org/cur#")
    om.add_class("Current")
    om.preview_import(_incoming(50))
    assert len(seen) > 50
    assert len(set(seen)) == 1


def test_the_preview_reports_its_steps_in_order():
    om = OntologyManager(base_uri="http://test.org/cur#")
    om.add_class("Current")
    steps = []
    om.preview_import(_incoming(5), progress=lambda step, done: steps.append(done))
    assert steps == sorted(steps)
    assert steps[0] == 0.0
    assert len(steps) >= 3


def _preview_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.views import import_export

    import_export.PREVIEW_MAX_SUMMARY_LINES = 3
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/cur#")
        om.add_class("Current")
        incoming = OntologyManager(base_uri="http://test.org/in#")
        for i in range(8):
            incoming.add_class(f"C{i}")
        content = incoming.export_to_string("turtle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state.import_preview = om.preview_import(content)
        st.session_state.import_content = content
        st.session_state.import_format = "turtle"
    app.render_import_export()


def test_the_change_list_stops_at_its_cap():
    """One element per changed resource was 65,000 elements for a 50k-class
    file; the list is now one block, capped, and says how many it leaves out."""
    at = AppTest.from_function(_preview_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    block = next(md.value for md in at.markdown if "Added" in md.value)
    assert block.count("Added") == 3
    assert any("more changes" in c.value for c in at.caption)

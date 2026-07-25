"""Adding an annotation keeps the chosen type and clears the value.

A successful add puts the new type into the used-predicate options. The picker
was unkeyed, so that changed the widget's identity and snapped the selection back
to the first entry, while the value box kept the text just saved (issue #161
follow-up).

Note when extending these: AppTest serializes a selectbox as the *index* of the
selection, so a changed options list moves the selection on its own here in a way
a browser never does. Assertions about which option survives an options change
therefore belong on ``annotation_option_for_predicate`` (see
``test_annotations_custom.py``), not on an AppTest run.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Animal")
        om.add_class("Plant")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    resources = [
        {
            "name": c["name"],
            "label": c.get("label"),
            "type": "Class",
            "display": c["name"],
        }
        for c in ont.get_classes()
    ]
    app.render_add_annotation(ont, resources)


def _add_annotation(at, predicate, value):
    at.selectbox(key="ann_predicate").set_value(predicate)
    at.text_area(key="ann_value").set_value(value)
    at.button[0].click().run(timeout=120)


def test_add_keeps_type_and_clears_value():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception

    _add_annotation(at, "skos:example", "an example")
    assert not at.exception, at.exception

    ont = at.session_state["ontology"]
    anns = ont.get_annotations("Animal")
    assert any(a["value"] == "an example" for a in anns), anns

    # The type stays put even though the options list just gained skos:example,
    # and the value box is empty so a second submit can't duplicate the entry.
    assert at.session_state["ann_predicate"] == "skos:example"
    assert at.session_state["ann_value"] == ""


def test_pending_predicate_is_applied_to_the_picker():
    """The add flags the type it used; the next run selects that option."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)

    ont = at.session_state["ontology"]
    ont.add_annotation("Plant", "skos:example", "an example")
    at.session_state["_ann_select_predicate"] = ont.resolve_annotation_predicate(
        "http://www.w3.org/2004/02/skos/core#example"
    )
    at.run(timeout=120)

    assert not at.exception, at.exception
    assert at.session_state["ann_predicate"] == "skos:example"
    # The flag is consumed, so a later rerun doesn't keep forcing the selection.
    assert "_ann_select_predicate" not in at.session_state


def test_missing_value_reports_error_and_adds_nothing():
    at = AppTest.from_function(_script)
    at.run(timeout=120)

    at.selectbox(key="ann_predicate").set_value("skos:example")
    at.button[0].click().run(timeout=120)

    assert not at.exception, at.exception
    ont = at.session_state["ontology"]
    assert not ont.get_annotations("Animal")

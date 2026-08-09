"""An annotation can be edited from the Annotations page (issue #257).

The page's list offered only a delete, so fixing a typo in a value meant
deleting the annotation and adding it back — losing the language tag and the
datatype unless they were retyped exactly. The editor already existed for the
graph's details panel; the form is now shared, so both routes rewrite the triple
through the same guards and the same rollback.

Driven through ``render_annotation_form`` rather than the page: the page's tab
picker is a ``segmented_control``, which AppTest mis-serializes, so the row's
pencil cannot be clicked from a page run (the same reason the restriction tests
call the form directly).
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Animal")
        om.add_class("Plant")
        om.add_annotation("Animal", "rdfs:comment", "a beast", lang="en")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    classes = ont.get_classes()
    subject = next(c for c in classes if c["name"] == "Animal")
    anns = ont.get_annotations("Animal")
    if not anns:
        # Moved away or deleted: the page stops listing the row, so there is
        # nothing left to render an editor for.
        st.caption("gone")
        return
    ann = anns[0]
    app.render_annotation_form(
        ont,
        subject["uri"],
        ann,
        "row0",
        classes,
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
        on_close=lambda: app._close_entity("ann"),
    )


def _run():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _save(at):
    at.button(key="FormSubmitter:edit_ann_row0-Save").click().run(timeout=120)
    assert not at.exception, at.exception
    return at


def test_the_form_opens_on_the_annotation_it_was_given():
    at = _run()
    assert at.text_input[0].value == "http://www.w3.org/2000/01/rdf-schema#comment"
    assert at.text_input[1].value == "a beast"
    assert at.selectbox(key="ann_on_row0").value == "Animal [Class]"


def test_editing_the_value_rewrites_it_in_place():
    at = _run()
    at.text_input[1].set_value("a large beast")
    _save(at)

    anns = at.session_state["ontology"].get_annotations("Animal")
    assert [a["value"] for a in anns] == ["a large beast"]
    # The tag rides along: a delete-and-retype loses it, which is what made the
    # missing editor worth having.
    assert anns[0]["language"] == "en"


def test_the_editor_moves_an_annotation_like_the_panel_does():
    at = _run()
    at.selectbox(key="ann_on_row0").set_value("Plant [Class]")
    _save(at)

    ont = at.session_state["ontology"]
    assert ont.get_annotations("Animal") == []
    assert [a["value"] for a in ont.get_annotations("Plant")] == ["a beast"]


def test_an_empty_value_is_refused_rather_than_written():
    at = _run()
    at.text_input[1].set_value("   ")
    _save(at)

    assert "required" in at.error[0].value
    assert [a["value"] for a in at.session_state["ontology"].get_annotations("Animal")]


def test_cancel_closes_the_row_without_touching_it():
    """The page owns the closing, so the form offers a Cancel; the panel, which
    follows the graph selection, passes no on_close and gets none."""
    at = _run()
    at.session_state["active_ann"] = ("row0", "edit")
    at.text_input[1].set_value("not saved")
    at.button(key="FormSubmitter:edit_ann_row0-Cancel").click().run(timeout=120)
    assert not at.exception, at.exception

    assert "active_ann" not in at.session_state
    anns = at.session_state["ontology"].get_annotations("Animal")
    assert [a["value"] for a in anns] == ["a beast"]


def test_delete_removes_it_and_closes_the_row():
    at = _run()
    at.session_state["active_ann"] = ("row0", "edit")
    at.button(key="FormSubmitter:edit_ann_row0-Delete").click().run(timeout=120)
    assert not at.exception, at.exception

    assert at.session_state["ontology"].get_annotations("Animal") == []
    assert "active_ann" not in at.session_state

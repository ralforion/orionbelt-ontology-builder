"""The "Annotation Types" tab renames a custom annotation type (issue #287).

Driven through the tab's own render function rather than the page: the page's
tab picker is a ``segmented_control``, which AppTest mis-serializes (see
``test_annotations_add_ui``).
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ui import _uid

NS = "http://test.org/ont#"
ROW = _uid(NS + "wikidataId")


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Person")
        om.add_annotation("Person", "wikidataId", "Q215627")
        om.add_annotation("Person", "comment", "A human being")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    app.render_annotation_types(st.session_state.ontology)


def _open_rename(at):
    at.button(key=f"edit_anntype_{ROW}").click().run(timeout=120)
    return at


def _submit(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)
    return at


def test_the_custom_type_is_listed_and_the_standard_one_is_not():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception

    rendered = " ".join(m.value for m in at.markdown)
    assert "wikidataId" in rendered
    assert "comment" not in rendered
    assert at.button(key=f"edit_anntype_{ROW}") is not None


def test_rename_rewrites_the_annotations():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_rename(at)

    at.text_input(key=f"anntype_name_{ROW}").set_value("wikidataItem")
    _submit(at, "Rename")
    assert not at.exception, at.exception

    ont = at.session_state["ontology"]
    anns = ont.get_annotations("Person")
    assert any(
        a["predicate"] == "wikidataItem" and a["value"] == "Q215627" for a in anns
    ), anns
    # The row's editor is closed again, and the rename is undoable.
    assert "active_anntype" not in at.session_state
    assert at.session_state["flash_message"]["type"] == "success"


def test_a_refused_rename_reports_why_and_changes_nothing():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_rename(at)

    at.text_input(key=f"anntype_name_{ROW}").set_value("rdfs:label")
    _submit(at, "Rename")
    assert not at.exception, at.exception

    assert at.error, "no reason shown"
    assert "standard vocabulary" in at.error[0].value
    ont = at.session_state["ontology"]
    assert any(a["predicate"] == "wikidataId" for a in ont.get_annotations("Person"))


def test_an_empty_name_is_reported():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_rename(at)

    at.text_input(key=f"anntype_name_{ROW}").set_value("   ")
    _submit(at, "Rename")

    assert at.error, "no reason shown"
    ont = at.session_state["ontology"]
    assert any(a["predicate"] == "wikidataId" for a in ont.get_annotations("Person"))


def test_cancel_closes_the_editor():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_rename(at)
    assert at.session_state["active_anntype"] == (ROW, "edit")

    _submit(at, "Cancel")
    assert "active_anntype" not in at.session_state


def test_an_ontology_without_custom_types_says_so():
    def _empty():
        import streamlit as st

        from orionbelt_ontology_builder.ontology_manager import OntologyManager

        if "ontology" not in st.session_state:
            om = OntologyManager()
            om.add_class("Person")
            om.add_annotation("Person", "comment", "A human being")
            st.session_state.ontology = om
            st.session_state["_autosave_restored"] = True

        from orionbelt_ontology_builder import app

        app.render_annotation_types(st.session_state.ontology)

    at = AppTest.from_function(_empty)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert at.info, "no empty-state message"
    assert not [b for b in at.button if b.key and b.key.startswith("edit_anntype_")]

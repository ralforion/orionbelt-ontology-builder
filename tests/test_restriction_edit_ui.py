"""Editing a restriction row in place (issue #152).

Drives ``render_restriction_row`` directly: the Restrictions page's tab picker
is a ``segmented_control``, which AppTest mis-serializes once interacted with.
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Bicycle", "Wheel", "Engine", "Frame"):
            om.add_class(name)
        om.add_object_property("hasPart")
        om.add_object_property("madeOf")
        # Two restrictions differing only by value: the editor must act on the
        # row it was opened for, not the first match.
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Engine")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    rows = sorted(ont.get_restrictions(), key=lambda r: r["value"])
    class_names = [c["name"] for c in ont.get_classes()]
    props = [p["name"] for p in ont.get_object_properties()]
    # Row 0 is Engine, row 1 is Wheel (sorted), so the test can address either.
    for index, rest in enumerate(rows):
        app.render_restriction_row(ont, rest, str(index), class_names, props)


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)


def _open_row(at, index):
    at.session_state["active_rest"] = (str(index), "edit")
    at.run(timeout=120)


def _rows(om):
    return sorted((r["property"], r["type"], r["value"]) for r in om.get_restrictions())


def test_editor_opens_with_the_rows_own_values():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)  # the Engine restriction

    assert not at.exception, at.exception
    assert at.selectbox(key="er_type_0").value == "someValuesFrom"
    assert at.text_input(key="er_val_0").value == "Engine"


def test_saving_edits_the_row_it_was_opened_for():
    """The sibling restriction on the same property and type stays untouched."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.text_input(key="er_val_0").set_value("Frame")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Frame"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]
    assert "active_rest" not in at.session_state


def test_saving_can_change_the_property_and_type():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 1)  # the Wheel restriction

    at.selectbox(key="er_prop_1").set_value("madeOf")
    at.selectbox(key="er_type_1").set_value("allValuesFrom")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert ("madeOf", "allValuesFrom", "Wheel") in _rows(at.session_state["ontology"])


def test_cancel_leaves_the_restriction_alone():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.text_input(key="er_val_0").set_value("Frame")
    _click(at, "Cancel")

    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]
    assert "active_rest" not in at.session_state


def test_a_bad_cardinality_is_reported_and_changes_nothing():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_type_0").set_value("exactCardinality")
    at.text_input(key="er_val_0").set_value("two")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("whole number" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_a_negative_cardinality_is_reported_and_changes_nothing():
    """The Add form's number input blocks this; the edit form takes free text."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_type_0").set_value("maxCardinality")
    at.text_input(key="er_val_0").set_value("-1")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("negative" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]

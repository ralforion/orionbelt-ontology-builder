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
    classes = ont.get_classes()
    props = ont.get_object_properties()
    # Row 0 is Engine, row 1 is Wheel (sorted), so the test can address either.
    for index, rest in enumerate(rows):
        app.render_restriction_row(ont, rest, str(index), classes, props)


def _click(at, label):
    next(b for b in at.button if b.label == label).click().run(timeout=120)


def _pick_class(at, key, name):
    """Choose a class in a value selectbox. Options are padded for search
    ranking (see app.SEARCH_PAD_WIDTH), so match on the stripped label."""
    box = at.selectbox(key=key)
    option = next(
        o for o in box.options if o.strip() == name or o.strip().startswith(name + " ")
    )
    box.set_value(option)


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
    assert at.selectbox(key="er_valcls_0").value.strip() == "Engine"


def test_saving_edits_the_row_it_was_opened_for():
    """The sibling restriction on the same property and type stays untouched."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    _pick_class(at, "er_valcls_0", "Frame")
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

    _pick_class(at, "er_valcls_0", "Frame")
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

    at.selectbox(key="er_type_0").set_value("exactCardinality").run(timeout=120)
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

    at.selectbox(key="er_type_0").set_value("maxCardinality").run(timeout=120)
    at.text_input(key="er_val_0").set_value("-1")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("negative" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def _imported_script():
    """A restriction whose class, property and value all live in an import."""
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        ttl = """
        @prefix : <http://test.org/ont#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix other: <http://other.example/vocab#> .
        :Local a owl:Class .
        other:Foo a owl:Class . other:Bar a owl:Class .
        other:relatedTo a owl:ObjectProperty .
        other:Foo rdfs:subClassOf [ a owl:Restriction ;
            owl:onProperty other:relatedTo ; owl:someValuesFrom other:Bar ] .
        """
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.load_from_string(ttl, format="turtle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_restriction_row(
        ont,
        ont.get_restrictions()[0],
        "0",
        ont.get_classes(),
        ont.get_object_properties(),
    )


def test_an_imported_restriction_keeps_its_namespace_through_an_edit():
    """Selecting by local name resolved into the base namespace, rewriting
    other:Foo / other:relatedTo / other:Bar as :Foo / :relatedTo / :Bar."""
    at = AppTest.from_function(_imported_script)
    at.run(timeout=120)
    _open_row(at, 0)

    assert not at.exception, at.exception
    # The imported class is a proper option now rather than a raw URI, and it
    # maps back to its own URI, so saving round-trips it (issue #250). The
    # assertions after the save are what prove that.
    assert at.selectbox(key="er_valcls_0").value.strip() == "Bar"

    at.selectbox(key="er_type_0").set_value("allValuesFrom")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    row = at.session_state["ontology"].get_restrictions()[0]
    assert row["type"] == "allValuesFrom"
    assert row["applied_to_uris"] == ["http://other.example/vocab#Foo"]
    assert row["property_uri"] == "http://other.example/vocab#relatedTo"
    assert row["value_uri"] == "http://other.example/vocab#Bar"


def test_an_empty_value_is_reported_and_changes_nothing():
    """It used to write owl:someValuesFrom : and destroy the original.

    Driven through hasValue, which is still a free-text field. A class-valued
    type cannot reach this any more: its picker has no empty option, which is
    the point of #250 and is asserted below.
    """
    at = AppTest.from_function(_has_value_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.text_input(key="er_val_0").set_value("")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("needs a value" in e.value for e in at.error)
    assert at.session_state["ontology"].get_restrictions()[0]["value"] is not None


def test_a_class_valued_restriction_cannot_be_emptied():
    """The picker offers classes only, so there is no empty value to submit."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    options = at.selectbox(key="er_valcls_0").options
    assert options and all(o.strip() for o in options)


def _has_value_script():
    """A hasValue restriction pointing at a local individual."""
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("Person")
        om.add_object_property("owns")
        om.add_individual("alice", "Person")
        om.add_restriction("Person", "owns", "hasValue", "http://test.org/ont#alice")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_restriction_row(
        ont,
        ont.get_restrictions()[0],
        "0",
        ont.get_classes(),
        ont.get_object_properties(),
    )


def test_a_hasvalue_individual_survives_an_unchanged_save():
    """A bare local name is stored as a literal, so owl:hasValue :alice would
    quietly become owl:hasValue "alice" (review P2)."""
    at = AppTest.from_function(_has_value_script)
    at.run(timeout=120)
    _open_row(at, 0)

    # Pre-filled as the URI, precisely so an unchanged save round-trips.
    assert at.text_input(key="er_val_0").value == "http://test.org/ont#alice"

    _click(at, "💾 Save")

    assert not at.exception, at.exception
    row = at.session_state["ontology"].get_restrictions()[0]
    assert row["type"] == "hasValue"
    assert row["value_uri"] == "http://test.org/ont#alice", (
        "the individual became a literal"
    )


def test_a_hasvalue_literal_stays_a_literal():
    """The pre-fill must not turn a genuine literal into a URI."""
    at = AppTest.from_function(_has_value_script)
    at.run(timeout=120)
    ont = at.session_state["ontology"]
    ont.delete_restriction("Person", "owns", "hasValue")
    ont.add_restriction("Person", "owns", "hasValue", "42")
    _open_row(at, 0)

    assert at.text_input(key="er_val_0").value == "42"
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    row = at.session_state["ontology"].get_restrictions()[0]
    assert row["value"] == "42" and row["value_uri"] is None


def test_switching_a_hasvalue_row_to_a_class_type_offers_only_classes():
    """A hasValue row's value is an individual or a literal. Carrying it into
    the class picker let a type change write owl:someValuesFrom :alice, which
    names an individual where a class belongs (#250 review)."""
    at = AppTest.from_function(_has_value_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_type_0").set_value("someValuesFrom").run(timeout=120)

    options = [o.strip() for o in at.selectbox(key="er_valcls_0").options]
    assert options == ["Person"], options
    assert "alice" not in " ".join(options)


# --- clearing a required dropdown --------------------------------------------


def test_a_required_dropdown_can_be_cleared():
    """The clear cross only exists when a selectbox may hold nothing, so the
    current value is seeded into the widget rather than preselected."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    box = at.selectbox(key="er_cls_0")
    assert box.value is not None and box.value.strip() == "Bicycle"
    box.set_value(None).run(timeout=120)
    assert at.selectbox(key="er_cls_0").value is None


def test_clearing_the_class_and_saving_reports_it_and_changes_nothing():
    """It used to fall back to the value the row started with, rewriting the
    axiom against a class the user had explicitly cleared."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_cls_0").set_value(None).run(timeout=120)
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("Applies to Class is required" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_clearing_the_property_and_saving_reports_it():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_prop_0").set_value(None).run(timeout=120)
    _click(at, "💾 Save")

    assert any("Property is required" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_clearing_the_class_value_and_saving_reports_it():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    at.selectbox(key="er_valcls_0").set_value(None).run(timeout=120)
    _click(at, "💾 Save")

    assert any("Value (Class) is required" in e.value for e in at.error)
    assert _rows(at.session_state["ontology"]) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_an_untouched_row_still_saves():
    """The seeding must not leave a required field looking empty."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_row(at, 0)

    _click(at, "💾 Save")

    assert not any("is required" in e.value for e in at.error)

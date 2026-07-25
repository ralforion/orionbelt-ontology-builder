"""Editing a relation row in place (issue #152).

Drives ``render_relation_rows`` directly rather than the whole Relations page:
the page's tab picker is a ``segmented_control``, and AppTest mis-serializes a
single-select one, so any interaction after the first run fails before reaching
the row.
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.app import _uid


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Capacitor", "Inductor", "Resistor"):
            om.add_class(name)
        om.add_class_relation("Capacitor", "disjointWith", "Inductor")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_relation_rows(
        ont,
        ont.get_class_relations(),
        {
            "icon": "📦",
            "kind": "crel",
            "noun": "classes",
            "label": "class relation",
            "entities": ont.get_classes(),
            "relation_types": ont.CLASS_RELATIONS,
            "remove": ont.remove_class_relation,
            "update": ont.update_class_relation,
        },
    )


def _rel_uid(om, subject, relation, obj):
    rel = next(
        r
        for r in om.get_class_relations()
        if r["subject"] == subject and r["object"] == obj
    )
    return _uid(f"{rel['subject_uri']}|{relation}|{rel['object_uri']}")


def _click(at, label):
    """Click a button by label: the row's own ✏️/🗑️ come before the form's
    Save/Cancel, so positional indexing picks the wrong one."""
    button = next(b for b in at.button if b.label == label)
    button.click().run(timeout=120)


def _open_editor(at):
    om = at.session_state["ontology"]
    uid = _rel_uid(om, "Capacitor", "disjointWith", "Inductor")
    at.session_state["active_crel"] = (uid, "edit")
    at.run(timeout=120)
    return uid


def test_editor_opens_with_the_rows_own_values():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    _open_editor(at)

    assert not at.exception, at.exception
    labels = {s.label for s in at.selectbox}
    assert {"Subject", "Relation", "Object"} <= labels
    assert at.selectbox(
        key=f"et_{_rel_uid(at.session_state['ontology'], 'Capacitor', 'disjointWith', 'Inductor')}"
    ).value == ("disjointWith")


def test_saving_a_changed_object_rewrites_the_relation():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    uid = _open_editor(at)

    at.selectbox(key=f"eo_{uid}").set_value("Resistor")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    om = at.session_state["ontology"]
    rels = [
        (r["subject"], r["relation"], r["object"]) for r in om.get_class_relations()
    ]
    assert rels == [("Capacitor", "disjointWith", "Resistor")]
    # The card closes on a successful save.
    assert "active_crel" not in at.session_state


def test_saving_a_changed_relation_type_rewrites_the_relation():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    uid = _open_editor(at)

    at.selectbox(key=f"et_{uid}").set_value("subClassOf")
    _click(at, "💾 Save")

    om = at.session_state["ontology"]
    rels = [
        (r["subject"], r["relation"], r["object"]) for r in om.get_class_relations()
    ]
    assert rels == [("Capacitor", "subClassOf", "Inductor")]


def test_cancel_leaves_the_relation_alone():
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    uid = _open_editor(at)

    at.selectbox(key=f"eo_{uid}").set_value("Resistor")
    _click(at, "Cancel")

    om = at.session_state["ontology"]
    rels = [
        (r["subject"], r["relation"], r["object"]) for r in om.get_class_relations()
    ]
    assert rels == [("Capacitor", "disjointWith", "Inductor")]
    assert "active_crel" not in at.session_state


# The "row is gone" branch in render_relation_rows cannot be reached from here:
# removing the relation makes the rerun rebuild the list without that row, so the
# form never re-renders and its handler never runs. It stays as a guard against a
# stale row resurrecting a deleted relation, and update_class_relation returning
# False for exactly that case is covered in test_relation_editing.py.


def _external_script():
    """A relation whose object is an external URI, which no local entity holds."""
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Alpha")
        om.add_class("Beta")
        om.add_class_relation("Alpha", "subClassOf", "http://external.example/Thing")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_relation_rows(
        ont,
        ont.get_class_relations(),
        {
            "icon": "📦",
            "kind": "crel",
            "noun": "classes",
            "label": "class relation",
            "entities": ont.get_classes(),
            "relation_types": ont.CLASS_RELATIONS,
            "remove": ont.remove_class_relation,
            "update": ont.update_class_relation,
        },
    )


def _open_external_editor(at):
    om = at.session_state["ontology"]
    rel = om.get_class_relations()[0]
    uid = _uid(f"{rel['subject_uri']}|{rel['relation']}|{rel['object_uri']}")
    at.session_state["active_crel"] = (uid, "edit")
    at.run(timeout=120)
    return uid


def test_an_external_target_is_offered_as_its_own_option():
    at = AppTest.from_function(_external_script)
    at.run(timeout=120)
    uid = _open_external_editor(at)

    assert not at.exception, at.exception
    assert at.selectbox(key=f"eo_{uid}").value == "http://external.example/Thing"


def test_editing_only_the_type_keeps_an_external_target():
    """The object isn't a local entity, so the picker used to fall back to the
    first class and silently rewrite it on save (review P2)."""
    at = AppTest.from_function(_external_script)
    at.run(timeout=120)
    uid = _open_external_editor(at)

    at.selectbox(key=f"et_{uid}").set_value("equivalentClass")
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    om = at.session_state["ontology"]
    rels = [
        (r["subject"], r["relation"], r["object_uri"]) for r in om.get_class_relations()
    ]
    assert rels == [("Alpha", "equivalentClass", "http://external.example/Thing")]


def test_pointing_a_relation_at_itself_is_refused():
    """The add forms reject this, so the editor must not become the way in."""
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    uid = _open_editor(at)

    at.selectbox(key=f"eo_{uid}").set_value("Capacitor")  # same as the subject
    _click(at, "💾 Save")

    assert not at.exception, at.exception
    assert any("two different classes" in e.value for e in at.error)
    om = at.session_state["ontology"]
    rels = [
        (r["subject"], r["relation"], r["object"]) for r in om.get_class_relations()
    ]
    assert rels == [("Capacitor", "disjointWith", "Inductor")]
    # The editor stays open so the mistake can be corrected in place.
    assert "active_crel" in at.session_state

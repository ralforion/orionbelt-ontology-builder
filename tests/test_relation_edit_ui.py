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

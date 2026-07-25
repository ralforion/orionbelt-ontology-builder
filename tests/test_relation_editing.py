"""Editing a relation in place, rather than delete-and-recreate (issue #152)."""

import pytest

from orionbelt_ontology_builder.ontology_manager import OntologyManager


@pytest.fixture
def rel_om():
    m = OntologyManager(base_uri="http://test.org/ont#")
    for name in ("Capacitor", "Inductor", "Resistor", "Component"):
        m.add_class(name)
    m.add_class_relation("Capacitor", "disjointWith", "Inductor")
    m.add_object_property("worksFor")
    m.add_object_property("employs")
    m.add_object_property("hires")
    m.add_property_relation("worksFor", "inverseOf", "employs")
    m.add_class("Person")
    for who in ("alice", "bob", "robert"):
        m.add_individual(who, "Person")
    m.add_individual_relation("bob", "sameAs", "robert")
    return m


def _class_rel(om):
    return [
        (r["subject"], r["relation"], r["object"]) for r in om.get_class_relations()
    ]


def test_change_the_object(rel_om):
    assert rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Capacitor", "disjointWith", "Resistor"),
    )
    assert _class_rel(rel_om) == [("Capacitor", "disjointWith", "Resistor")]


def test_change_the_relation_type(rel_om):
    assert rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Capacitor", "subClassOf", "Inductor"),
    )
    assert _class_rel(rel_om) == [("Capacitor", "subClassOf", "Inductor")]


def test_change_the_subject(rel_om):
    assert rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Resistor", "disjointWith", "Inductor"),
    )
    assert _class_rel(rel_om) == [("Resistor", "disjointWith", "Inductor")]


def test_change_all_three_at_once(rel_om):
    assert rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Resistor", "subClassOf", "Component"),
    )
    assert _class_rel(rel_om) == [("Resistor", "subClassOf", "Component")]


def test_editing_a_stale_row_changes_nothing(rel_om):
    """The row was already deleted or edited elsewhere: report it, don't add."""
    assert not rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Resistor"),
        ("Capacitor", "disjointWith", "Component"),
    )
    assert _class_rel(rel_om) == [("Capacitor", "disjointWith", "Inductor")]


def test_an_unknown_new_type_leaves_the_original_intact(rel_om):
    """Both types resolve before anything is written, so a bad edit can't
    delete the relation and then fail to write its replacement."""
    with pytest.raises(ValueError, match="class relation"):
        rel_om.update_class_relation(
            ("Capacitor", "disjointWith", "Inductor"),
            ("Capacitor", "subPropertyOf", "Inductor"),
        )
    assert _class_rel(rel_om) == [("Capacitor", "disjointWith", "Inductor")]


def test_an_unknown_old_type_raises(rel_om):
    with pytest.raises(ValueError, match="class relation"):
        rel_om.update_class_relation(
            ("Capacitor", "nonsense", "Inductor"),
            ("Capacitor", "disjointWith", "Resistor"),
        )


def test_a_no_op_edit_keeps_the_relation(rel_om):
    assert rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Capacitor", "disjointWith", "Inductor"),
    )
    assert _class_rel(rel_om) == [("Capacitor", "disjointWith", "Inductor")]


def test_property_relations_edit_the_same_way(rel_om):
    assert rel_om.update_property_relation(
        ("worksFor", "inverseOf", "employs"),
        ("worksFor", "subPropertyOf", "hires"),
    )
    rels = [
        (r["subject"], r["relation"], r["object"])
        for r in rel_om.get_property_relations()
    ]
    assert rels == [("worksFor", "subPropertyOf", "hires")]


def test_individual_relations_edit_the_same_way(rel_om):
    assert rel_om.update_individual_relation(
        ("bob", "sameAs", "robert"),
        ("bob", "differentFrom", "alice"),
    )
    rels = [
        (r["subject"], r["relation"], r["object"])
        for r in rel_om.get_individual_relations()
    ]
    assert rels == [("bob", "differentFrom", "alice")]


def test_edit_is_undoable(rel_om):
    """Editing goes through the graph, so the app's checkpoints cover it."""
    before = rel_om.export_to_string("turtle")
    rel_om.update_class_relation(
        ("Capacitor", "disjointWith", "Inductor"),
        ("Capacitor", "subClassOf", "Component"),
    )
    after = rel_om.export_to_string("turtle")
    assert before != after
    restored = OntologyManager(base_uri="http://test.org/ont#")
    restored.load_from_string(before, "turtle")
    assert _class_rel(restored) == [("Capacitor", "disjointWith", "Inductor")]

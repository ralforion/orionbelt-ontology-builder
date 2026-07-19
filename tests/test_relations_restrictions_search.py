"""Search + sort helpers for Relations and Restrictions (issue #148)."""

from orionbelt_ontology_builder.app import (
    _filter_relations,
    _filter_restrictions,
    _sort_relations,
    _sort_restrictions,
)

RELS = [
    {"subject": "Dog", "relation": "subClassOf", "object": "Animal"},
    {"subject": "Cat", "relation": "disjointWith", "object": "Dog"},
    {"subject": "Animal", "relation": "equivalentClass", "object": "Creature"},
]

RESTS = [
    {
        "property": "hasPart",
        "type": "someValuesFrom",
        "value": "Wheel",
        "on_class": "",
        "applied_to": ["Vehicle"],
    },
    {
        "property": "hasAge",
        "type": "maxCardinality",
        "value": "1",
        "on_class": "",
        "applied_to": ["Person"],
    },
    {
        "property": "owns",
        "type": "allValuesFrom",
        "value": "House",
        "on_class": "Truck",
        "applied_to": ["Driver"],
    },
]


def test_filter_relations_matches_subject_or_object():
    # "dog" is the subject of row 0 and the object of row 1.
    got = _filter_relations(RELS, "dog")
    assert {r["subject"] for r in got} == {"Dog", "Cat"}


def test_filter_relations_matches_relation_predicate():
    got = _filter_relations(RELS, "subclass")
    assert len(got) == 1 and got[0]["subject"] == "Dog"


def test_filter_relations_empty_query_returns_all():
    assert _filter_relations(RELS, "") == RELS
    assert _filter_relations(RELS, "   ") == RELS


def test_filter_relations_no_match():
    assert _filter_relations(RELS, "zzz") == []


def test_sort_relations_orders_by_subject_relation_object():
    assert [r["subject"] for r in _sort_relations(RELS)] == ["Animal", "Cat", "Dog"]


def test_filter_restrictions_matches_each_field():
    assert [r["property"] for r in _filter_restrictions(RESTS, "haspart")] == [
        "hasPart"
    ]
    assert [r["property"] for r in _filter_restrictions(RESTS, "wheel")] == ["hasPart"]
    assert [r["property"] for r in _filter_restrictions(RESTS, "allvaluesfrom")] == [
        "owns"
    ]
    assert [r["property"] for r in _filter_restrictions(RESTS, "person")] == ["hasAge"]
    assert [r["property"] for r in _filter_restrictions(RESTS, "truck")] == ["owns"]


def test_filter_restrictions_empty_and_no_match():
    assert _filter_restrictions(RESTS, "") == RESTS
    assert _filter_restrictions(RESTS, "nope") == []


def test_sort_restrictions_orders_by_property_then_type():
    assert [r["property"] for r in _sort_restrictions(RESTS)] == [
        "hasAge",
        "hasPart",
        "owns",
    ]

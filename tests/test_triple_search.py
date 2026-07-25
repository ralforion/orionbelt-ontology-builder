"""Pasting a whole triple into the search box narrows to that one row (issue #170).

The single-word search from issue #148 keeps working; see
``test_relations_restrictions_search.py`` for those cases.
"""

from orionbelt_ontology_builder.app import (
    _filter_relations,
    _filter_restrictions,
    parse_search_query,
)

RELS = [
    {"subject": "capacitor", "relation": "disjointWith", "object": "inductor"},
    {"subject": "capacitor", "relation": "disjointWith", "object": "resistor"},
    {"subject": "capacitor", "relation": "subClassOf", "object": "component"},
    {"subject": "inductor", "relation": "disjointWith", "object": "capacitor"},
]

RESTS = [
    {
        "property": "hasPart",
        "type": "someValuesFrom",
        "value": "Wheel",
        "on_class": "",
        "applied_to": ["Bicycle"],
    },
    {
        "property": "hasPart",
        "type": "someValuesFrom",
        "value": "Engine",
        "on_class": "",
        "applied_to": ["Car"],
    },
    {
        "property": "owns",
        "type": "allValuesFrom",
        "value": "House",
        "on_class": "Truck",
        "applied_to": ["Driver"],
    },
]


# --- parsing ----------------------------------------------------------------


def test_three_words_parse_as_slots():
    slots, terms = parse_search_query("capacitor disjointWith inductor")
    assert slots == ("capacitor", "disjointwith", "inductor")
    assert terms == []


def test_wildcards_leave_a_slot_open():
    slots, _terms = parse_search_query("* disjointWith inductor")
    assert slots == (None, "disjointwith", "inductor")
    assert parse_search_query("capacitor - -")[0] == ("capacitor", None, None)


def test_other_word_counts_parse_as_terms():
    assert parse_search_query("capacitor") == (None, ["capacitor"])
    assert parse_search_query("capacitor inductor") == (None, ["capacitor", "inductor"])
    assert parse_search_query("a b c d") == (None, ["a", "b", "c", "d"])


def test_empty_query_parses_to_nothing():
    assert parse_search_query("") == (None, [])
    assert parse_search_query("   ") == (None, [])
    assert parse_search_query(None) == (None, [])


def test_extra_whitespace_is_ignored():
    slots, _ = parse_search_query("  capacitor   disjointWith\tinductor  ")
    assert slots == ("capacitor", "disjointwith", "inductor")


# --- relations --------------------------------------------------------------


def test_pasted_triple_isolates_one_relation():
    got = _filter_relations(RELS, "capacitor disjointWith inductor")
    assert len(got) == 1
    assert got[0]["object"] == "inductor"


def test_direction_matters():
    """capacitor->inductor and inductor->capacitor are different rows."""
    got = _filter_relations(RELS, "inductor disjointWith capacitor")
    assert len(got) == 1 and got[0]["subject"] == "inductor"


def test_triple_matching_is_case_insensitive_and_partial():
    got = _filter_relations(RELS, "CAPACITOR disjoint induct")
    assert len(got) == 1 and got[0]["object"] == "inductor"


def test_wildcard_slot_matches_any_value():
    got = _filter_relations(RELS, "* disjointWith capacitor")
    assert [r["subject"] for r in got] == ["inductor"]
    got = _filter_relations(RELS, "capacitor disjointWith *")
    assert {r["object"] for r in got} == {"inductor", "resistor"}


def test_two_words_require_both_somewhere():
    """Not a triple, so both words just have to appear in the row."""
    got = _filter_relations(RELS, "capacitor resistor")
    assert len(got) == 1 and got[0]["object"] == "resistor"


def test_single_word_still_matches_any_column():
    got = _filter_relations(RELS, "component")
    assert len(got) == 1 and got[0]["relation"] == "subClassOf"


def test_triple_with_no_match_returns_nothing():
    assert _filter_relations(RELS, "capacitor disjointWith transistor") == []


# --- restrictions -----------------------------------------------------------


def test_pasted_restriction_isolates_one_row():
    got = _filter_restrictions(RESTS, "Bicycle hasPart Wheel")
    assert len(got) == 1 and got[0]["value"] == "Wheel"


def test_restriction_middle_slot_also_matches_the_type():
    got = _filter_restrictions(RESTS, "Bicycle someValuesFrom Wheel")
    assert len(got) == 1 and got[0]["applied_to"] == ["Bicycle"]


def test_restriction_last_slot_also_matches_the_qualified_class():
    got = _filter_restrictions(RESTS, "Driver owns Truck")
    assert len(got) == 1 and got[0]["on_class"] == "Truck"


def test_restriction_wildcard_narrows_by_property_alone():
    got = _filter_restrictions(RESTS, "* hasPart *")
    assert {r["value"] for r in got} == {"Wheel", "Engine"}


def test_restriction_single_word_still_matches_any_field():
    assert len(_filter_restrictions(RESTS, "wheel")) == 1
    assert len(_filter_restrictions(RESTS, "hasPart")) == 2


def test_restriction_triple_tolerates_none_fields():
    """Unmapped restrictions (e.g. owl:hasSelf) carry None fields."""
    rows = [
        {
            "property": "hasSelf",
            "type": None,
            "value": None,
            "on_class": None,
            "applied_to": None,
        }
    ]
    assert _filter_restrictions(rows, "Bicycle hasPart Wheel") == []
    assert _filter_restrictions(rows, "* hasSelf *") == rows

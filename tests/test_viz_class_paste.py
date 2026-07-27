"""Pasting a class list into the Visualization "Filter Classes" (issue #179).

The filter lists namespace-tagged display names so same-named classes from two
namespaces are separately selectable, and accepts a pasted list of names,
prefixed names or URIs to restore a saved selection in one go.
"""

import pytest

from orionbelt_ontology_builder import app


CLASSES = [
    {"name": "Person", "uri": "http://ex.org/base#Person"},
    {"name": "zero", "uri": "http://ex.org/fn#zero"},
    {"name": "zero", "uri": "http://ex.org/math#zero"},
    {"name": "Organization", "uri": "http://ex.org/base#Organization"},
]

PREFIXES = {
    "http://ex.org/base#": "",
    "http://ex.org/fn#": "fn",
    "http://ex.org/math#": "math",
}


@pytest.fixture
def entries(monkeypatch):
    """Class-filter entries built with a stubbed prefix lookup.

    ``_prefix_for_uri`` reads the ontology out of session state, which does not
    exist outside a Streamlit run, so bind the prefixes directly.
    """

    def _prefix(uri):
        for ns, prefix in PREFIXES.items():
            if uri.startswith(ns):
                return prefix
        return ""

    monkeypatch.setattr(app, "_prefix_for_uri", _prefix)
    return app.build_class_filter_entries(CLASSES)


def _displays(entries):
    return [e["display"] for e in entries]


def test_same_name_classes_get_distinct_options(entries):
    assert _displays(entries) == [
        "Person",
        "zero (fn)",
        "zero (math)",
        "Organization",
    ]


def test_entries_flag_only_the_ambiguous_name(entries):
    assert [e["ambiguous"] for e in entries] == [False, True, True, False]


def test_unprefixed_namespace_falls_back_to_the_namespace(monkeypatch):
    monkeypatch.setattr(app, "_prefix_for_uri", lambda uri: "")
    entries = app.build_class_filter_entries(CLASSES[1:3])
    assert _displays(entries) == [
        "zero (http://ex.org/fn#)",
        "zero (http://ex.org/math#)",
    ]


def test_tokens_round_trip_through_the_parser(entries):
    tokens = " ".join(app.class_filter_token(e) for e in entries)
    assert tokens == "Person fn:zero math:zero Organization"
    assert app.parse_class_filter_text(tokens, entries) == (_displays(entries), [])


def test_token_for_an_unprefixed_ambiguous_class_is_its_uri(monkeypatch):
    monkeypatch.setattr(app, "_prefix_for_uri", lambda uri: "")
    entries = app.build_class_filter_entries(CLASSES[1:3])
    assert [app.class_filter_token(e) for e in entries] == [
        "http://ex.org/fn#zero",
        "http://ex.org/math#zero",
    ]


def test_spaces_commas_semicolons_and_newlines_all_separate(entries):
    for text in (
        "Person Organization",
        "Person, Organization",
        "Person;Organization",
        "Person\nOrganization",
        "  Person ,\n\n Organization  ",
    ):
        assert app.parse_class_filter_text(text, entries) == (
            ["Person", "Organization"],
            [],
        )


def test_result_follows_class_list_order_not_input_order(entries):
    matched, _ = app.parse_class_filter_text("Organization Person", entries)
    assert matched == ["Person", "Organization"]


def test_repeated_names_are_listed_once(entries):
    assert app.parse_class_filter_text("Person Person", entries)[0] == ["Person"]


def test_plain_ambiguous_name_selects_every_namespace(entries):
    assert app.parse_class_filter_text("zero", entries)[0] == [
        "zero (fn)",
        "zero (math)",
    ]


def test_prefixed_name_selects_one_namespace(entries):
    assert app.parse_class_filter_text("fn:zero", entries)[0] == ["zero (fn)"]


def test_display_form_survives_being_split_on_whitespace(entries):
    # Copied straight out of the multiselect, "zero (math)" contains a space.
    assert app.parse_class_filter_text("Person zero (math)", entries)[0] == [
        "Person",
        "zero (math)",
    ]


def test_full_uri_selects_one_namespace(entries):
    assert app.parse_class_filter_text("http://ex.org/fn#zero", entries)[0] == [
        "zero (fn)"
    ]


def test_uri_in_angle_brackets_and_quotes(entries):
    assert app.parse_class_filter_text("<http://ex.org/fn#zero>", entries)[0] == [
        "zero (fn)"
    ]
    assert app.parse_class_filter_text("'Person'", entries)[0] == ["Person"]


def test_case_insensitive_fallback(entries):
    assert app.parse_class_filter_text("person FN:ZERO", entries)[0] == [
        "Person",
        "zero (fn)",
    ]


def test_exact_case_wins_over_a_case_insensitive_match():
    entries = app.build_class_filter_entries(
        [
            {"name": "Person", "uri": "http://ex.org/base#Person"},
            {"name": "person", "uri": "http://ex.org/other#person"},
        ]
    )
    assert app.parse_class_filter_text("person", entries)[0] == ["person"]


def test_unknown_names_are_reported_and_the_rest_applied(entries):
    matched, unknown = app.parse_class_filter_text(
        "Person Nope Person Missing", entries
    )
    assert matched == ["Person"]
    assert unknown == ["Nope", "Missing"]


def test_empty_text_matches_nothing(entries):
    assert app.parse_class_filter_text("", entries) == ([], [])
    assert app.parse_class_filter_text("   \n ", entries) == ([], [])


def test_pasted_selection_reconciles_like_any_other(entries):
    # What Apply stores must survive the next render's reconciliation unchanged.
    pasted, _ = app.parse_class_filter_text("Person fn:zero", entries)
    all_names = _displays(entries)
    selected, known = app.reconcile_class_filter(all_names, pasted, set(all_names))
    assert selected == ["Person", "zero (fn)"]
    assert known == set(all_names)

"""Pasting a class list into the Visualization "Filter Classes" (issue #179).

The filter lists namespace-tagged display names so same-named classes from two
namespaces are separately selectable, and accepts a pasted list of names,
prefixed names or URIs to restore a saved selection in one go. Both the parser
and the stored selection work in URIs — display labels change under the filter
whenever a second class takes the same local name.
"""

import pytest

from orionbelt_ontology_builder import app


BASE = "http://ex.org/base#"
FN = "http://ex.org/fn#"
MATH = "http://ex.org/math#"

CLASSES = [
    {"name": "Person", "uri": f"{BASE}Person"},
    {"name": "zero", "uri": f"{FN}zero"},
    {"name": "zero", "uri": f"{MATH}zero"},
    {"name": "Organization", "uri": f"{BASE}Organization"},
]

PREFIXES = {BASE: "base", FN: "fn", MATH: "math"}


@pytest.fixture
def prefixes(monkeypatch):
    """Bind the test namespaces to prefixes.

    ``_prefix_for_uri`` reads the ontology out of session state, which does not
    exist outside a Streamlit run, so resolve the prefixes directly.
    """

    def _prefix(uri):
        for ns, prefix in PREFIXES.items():
            if uri.startswith(ns):
                return prefix
        return ""

    monkeypatch.setattr(app, "_prefix_for_uri", _prefix)


@pytest.fixture
def entries(prefixes):
    return app.build_class_filter_entries(CLASSES)


def _displays(entries):
    return [e["display"] for e in entries]


def _uris(*names):
    return [
        {"Person": f"{BASE}Person", "Organization": f"{BASE}Organization"}[n]
        for n in names
    ]


def test_same_name_classes_get_distinct_options(entries):
    assert _displays(entries) == [
        "Person",
        "zero (fn)",
        "zero (math)",
        "Organization",
    ]


def test_entries_flag_only_the_ambiguous_name(entries):
    assert [e["ambiguous"] for e in entries] == [False, True, True, False]


def test_every_entry_carries_its_prefix(entries):
    # Not just the ambiguous ones: 'base:Person' has to parse too (review of
    # #179), even though the printed token for it stays unprefixed.
    assert [e["prefix"] for e in entries] == ["base", "fn", "math", "base"]


def test_unprefixed_namespace_falls_back_to_the_namespace(monkeypatch):
    monkeypatch.setattr(app, "_prefix_for_uri", lambda uri: "")
    entries = app.build_class_filter_entries(CLASSES[1:3])
    assert _displays(entries) == [f"zero ({FN})", f"zero ({MATH})"]


def test_tokens_round_trip_through_the_parser(entries):
    tokens = " ".join(app.class_filter_token(e) for e in entries)
    assert tokens == "Person fn:zero math:zero Organization"
    assert app.parse_class_filter_text(tokens, entries) == (
        [e["uri"] for e in entries],
        [],
    )


def test_token_for_an_unprefixed_ambiguous_class_is_its_uri(monkeypatch):
    monkeypatch.setattr(app, "_prefix_for_uri", lambda uri: "")
    entries = app.build_class_filter_entries(CLASSES[1:3])
    assert [app.class_filter_token(e) for e in entries] == [f"{FN}zero", f"{MATH}zero"]


def test_spaces_commas_semicolons_and_newlines_all_separate(entries):
    for text in (
        "Person Organization",
        "Person, Organization",
        "Person;Organization",
        "Person\nOrganization",
        "  Person ,\n\n Organization  ",
    ):
        assert app.parse_class_filter_text(text, entries) == (
            _uris("Person", "Organization"),
            [],
        )


def test_result_follows_class_list_order_not_input_order(entries):
    matched, _ = app.parse_class_filter_text("Organization Person", entries)
    assert matched == _uris("Person", "Organization")


def test_repeated_names_are_listed_once(entries):
    assert app.parse_class_filter_text("Person Person", entries)[0] == _uris("Person")


def test_plain_ambiguous_name_selects_every_namespace(entries):
    assert app.parse_class_filter_text("zero", entries)[0] == [
        f"{FN}zero",
        f"{MATH}zero",
    ]


def test_prefixed_name_selects_one_namespace(entries):
    assert app.parse_class_filter_text("fn:zero", entries)[0] == [f"{FN}zero"]


def test_prefixed_name_works_for_an_unambiguous_class(entries):
    # 'Person' is unique, so nothing forces the prefix — but pasting the
    # prefixed form back must still resolve (review of #179).
    assert app.parse_class_filter_text("base:Person", entries)[0] == _uris("Person")


def test_display_form_survives_being_split_on_whitespace(entries):
    # Copied straight out of the multiselect, "zero (math)" contains a space.
    assert app.parse_class_filter_text("Person zero (math)", entries)[0] == [
        f"{BASE}Person",
        f"{MATH}zero",
    ]


def test_full_uri_selects_one_namespace(entries):
    assert app.parse_class_filter_text(f"{FN}zero", entries)[0] == [f"{FN}zero"]


def test_uri_in_angle_brackets_and_quotes(entries):
    assert app.parse_class_filter_text(f"<{FN}zero>", entries)[0] == [f"{FN}zero"]
    assert app.parse_class_filter_text("'Person'", entries)[0] == _uris("Person")


def test_case_insensitive_fallback(entries):
    assert app.parse_class_filter_text("person FN:ZERO", entries)[0] == [
        f"{BASE}Person",
        f"{FN}zero",
    ]


def test_exact_case_wins_over_a_case_insensitive_match(prefixes):
    entries = app.build_class_filter_entries(
        [
            {"name": "Person", "uri": f"{BASE}Person"},
            {"name": "person", "uri": f"{FN}person"},
        ]
    )
    assert app.parse_class_filter_text("person", entries)[0] == [f"{FN}person"]


def test_unknown_names_are_reported_and_the_rest_applied(entries):
    matched, unknown = app.parse_class_filter_text(
        "Person Nope Person Missing", entries
    )
    assert matched == _uris("Person")
    assert unknown == ["Nope", "Missing"]


def test_empty_text_matches_nothing(entries):
    assert app.parse_class_filter_text("", entries) == ([], [])
    assert app.parse_class_filter_text("   \n ", entries) == ([], [])


def test_pasted_selection_reconciles_like_any_other(entries):
    # What Apply stores must survive the next render's reconciliation unchanged.
    pasted, _ = app.parse_class_filter_text("Person fn:zero", entries)
    all_uris = [e["uri"] for e in entries]
    selected, known = app.reconcile_class_filter(all_uris, pasted, set(all_uris))
    assert selected == [f"{BASE}Person", f"{FN}zero"]
    assert known == set(all_uris)


def test_a_new_namespace_twin_does_not_unhide_its_sibling(prefixes):
    """Regression for the review of #179.

    A hidden class keeps its URI when a same-named class arrives, but its
    display label gains a namespace tag. Reconciling on labels would read both
    ``zero (fn)`` and ``zero (math)`` as brand new and show the class the user
    had deliberately hidden — so the state is keyed by URI.
    """
    before = app.build_class_filter_entries(CLASSES[:2])
    assert _displays(before) == ["Person", "zero"]

    # User hides 'zero', leaving just Person selected.
    selected, known = app.reconcile_class_filter(
        [e["uri"] for e in before], [f"{BASE}Person"], {f"{BASE}Person", f"{FN}zero"}
    )
    assert selected == [f"{BASE}Person"]

    # math:zero is imported; fn:zero is relabelled 'zero (fn)' but unchanged.
    after = app.build_class_filter_entries(CLASSES[:3])
    assert _displays(after) == ["Person", "zero (fn)", "zero (math)"]
    selected, known = app.reconcile_class_filter(
        [e["uri"] for e in after], selected, known
    )
    # Only the genuinely new class joins; fn:zero stays hidden.
    assert selected == [f"{BASE}Person", f"{MATH}zero"]

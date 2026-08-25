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
def prefixes(patch_ui, monkeypatch):
    """Bind the test namespaces to prefixes.

    ``_prefix_for_uri`` reads the ontology out of session state, which does not
    exist outside a Streamlit run, so resolve the prefixes directly.
    """

    def _prefix(uri):
        for ns, prefix in PREFIXES.items():
            if uri.startswith(ns):
                return prefix
        return ""

    patch_ui("_prefix_for_uri", _prefix)


@pytest.fixture
def entries(prefixes):
    return app.build_filter_entries(CLASSES)


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


def test_unprefixed_namespace_falls_back_to_the_namespace(monkeypatch, patch_ui):
    patch_ui("_prefix_for_uri", lambda uri: "")
    entries = app.build_filter_entries(CLASSES[1:3])
    assert _displays(entries) == [f"zero ({FN})", f"zero ({MATH})"]


def test_tokens_round_trip_through_the_parser(entries):
    tokens = " ".join(app.filter_entry_token(e) for e in entries)
    assert tokens == "Person fn:zero math:zero Organization"
    assert app.parse_filter_text(tokens, entries) == (
        [e["uri"] for e in entries],
        [],
    )


def test_token_for_an_unprefixed_ambiguous_class_is_its_uri(monkeypatch, patch_ui):
    patch_ui("_prefix_for_uri", lambda uri: "")
    entries = app.build_filter_entries(CLASSES[1:3])
    assert [app.filter_entry_token(e) for e in entries] == [f"{FN}zero", f"{MATH}zero"]


def test_spaces_commas_semicolons_and_newlines_all_separate(entries):
    for text in (
        "Person Organization",
        "Person, Organization",
        "Person;Organization",
        "Person\nOrganization",
        "  Person ,\n\n Organization  ",
    ):
        assert app.parse_filter_text(text, entries) == (
            _uris("Person", "Organization"),
            [],
        )


def test_result_follows_class_list_order_not_input_order(entries):
    matched, _ = app.parse_filter_text("Organization Person", entries)
    assert matched == _uris("Person", "Organization")


def test_repeated_names_are_listed_once(entries):
    assert app.parse_filter_text("Person Person", entries)[0] == _uris("Person")


def test_plain_ambiguous_name_selects_every_namespace(entries):
    assert app.parse_filter_text("zero", entries)[0] == [
        f"{FN}zero",
        f"{MATH}zero",
    ]


def test_prefixed_name_selects_one_namespace(entries):
    assert app.parse_filter_text("fn:zero", entries)[0] == [f"{FN}zero"]


def test_prefixed_name_works_for_an_unambiguous_class(entries):
    # 'Person' is unique, so nothing forces the prefix — but pasting the
    # prefixed form back must still resolve (review of #179).
    assert app.parse_filter_text("base:Person", entries)[0] == _uris("Person")


def test_display_form_survives_being_split_on_whitespace(entries):
    # Copied straight out of the multiselect, "zero (math)" contains a space.
    assert app.parse_filter_text("Person zero (math)", entries)[0] == [
        f"{BASE}Person",
        f"{MATH}zero",
    ]


def test_full_uri_selects_one_namespace(entries):
    assert app.parse_filter_text(f"{FN}zero", entries)[0] == [f"{FN}zero"]


def test_uri_in_angle_brackets_and_quotes(entries):
    assert app.parse_filter_text(f"<{FN}zero>", entries)[0] == [f"{FN}zero"]
    assert app.parse_filter_text("'Person'", entries)[0] == _uris("Person")


def test_case_insensitive_fallback(entries):
    assert app.parse_filter_text("person FN:ZERO", entries)[0] == [
        f"{BASE}Person",
        f"{FN}zero",
    ]


def test_exact_case_wins_over_a_case_insensitive_match(prefixes):
    entries = app.build_filter_entries(
        [
            {"name": "Person", "uri": f"{BASE}Person"},
            {"name": "person", "uri": f"{FN}person"},
        ]
    )
    assert app.parse_filter_text("person", entries)[0] == [f"{FN}person"]


def test_unknown_names_are_reported_and_the_rest_applied(entries):
    matched, unknown = app.parse_filter_text("Person Nope Person Missing", entries)
    assert matched == _uris("Person")
    assert unknown == ["Nope", "Missing"]


def test_empty_text_matches_nothing(entries):
    assert app.parse_filter_text("", entries) == ([], [])
    assert app.parse_filter_text("   \n ", entries) == ([], [])


def test_pasted_selection_reconciles_like_any_other(entries):
    # What Apply stores must survive the next render's reconciliation unchanged.
    pasted, _ = app.parse_filter_text("Person fn:zero", entries)
    all_uris = [e["uri"] for e in entries]
    selected, known = app.reconcile_filter_selection(all_uris, pasted, set(all_uris))
    assert selected == [f"{BASE}Person", f"{FN}zero"]
    assert known == set(all_uris)


def test_a_new_namespace_twin_does_not_unhide_its_sibling(prefixes):
    """Regression for the review of #179.

    A hidden class keeps its URI when a same-named class arrives, but its
    display label gains a namespace tag. Reconciling on labels would read both
    ``zero (fn)`` and ``zero (math)`` as brand new and show the class the user
    had deliberately hidden — so the state is keyed by URI.
    """
    before = app.build_filter_entries(CLASSES[:2])
    assert _displays(before) == ["Person", "zero"]

    # User hides 'zero', leaving just Person selected.
    selected, known = app.reconcile_filter_selection(
        [e["uri"] for e in before], [f"{BASE}Person"], {f"{BASE}Person", f"{FN}zero"}
    )
    assert selected == [f"{BASE}Person"]

    # math:zero is imported; fn:zero is relabelled 'zero (fn)' but unchanged.
    after = app.build_filter_entries(CLASSES[:3])
    all_uris = [e["uri"] for e in after]
    assert _displays(after) == ["Person", "zero (fn)", "zero (math)"]
    before_known = known
    selected, known = app.reconcile_filter_selection(all_uris, selected, known)
    # The filter is narrowed, so neither joins (issue #194) — and in particular
    # the relabelled fn:zero the user hid does not come back.
    assert selected == [f"{BASE}Person"]
    # The genuinely new class is the one reported as held back, keyed by URI:
    # a label-keyed reconcile would have named the hidden fn:zero as well.
    assert app.newly_hidden_uris(all_uris, selected, before_known) == [f"{MATH}zero"]


# --- The box on the page -----------------------------------------------------


def _page_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Person", "Organization", "Department"):
            om.add_class(name)
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
    app.render_visualization()


def _page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_page_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _rerun(at):
    """Run the page again; see tests/test_viz_new_class_hidden.py for the
    button-group shim this needs."""
    for group in at.get("button_group"):
        value = group.value
        if not isinstance(value, list):
            group.set_value([value])
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def _apply(at, text):
    at.text_area(key="viz_paste_class").set_value(text)
    at.button(key="viz_apply_paste_class").click()
    return _rerun(at)


def test_a_partly_matching_paste_still_reports_what_it_dropped():
    """Regression: it applied silently.

    Applying narrows the filter, which changes the "N hidden" note, which
    reruns the page — and the warning was drawn on the pass that reran, so it
    went with it. Recorded in session instead, it survives to the pass the user
    sees.
    """
    at = _apply(_page(), "Organization Bicycle")
    assert [
        u.rsplit("#", 1)[-1] for u in at.session_state["_viz_cfg_selected_class_uris"]
    ] == ["Organization"]
    assert any("Bicycle" in w.value for w in at.warning), [w.value for w in at.warning]


def test_the_report_stands_until_the_next_apply_replaces_it():
    at = _apply(_page(), "Organization Bicycle")
    at = _rerun(at)
    assert any("Bicycle" in w.value for w in at.warning)
    at = _apply(at, "Person")
    assert not [w for w in at.warning if "Bicycle" in w.value]


def test_a_paste_matching_nothing_says_so_and_changes_nothing():
    at = _page()
    before = list(at.session_state["_viz_cfg_selected_class_uris"])
    at = _apply(at, "Bicycle Tandem")
    assert at.session_state["_viz_cfg_selected_class_uris"] == before
    assert any("Bicycle" in w.value for w in at.warning), [w.value for w in at.warning]

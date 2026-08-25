"""Pasting and copying the focus nodes (issue #283).

Focus mode gets the node filter's restore-a-view box (issue #179): the seeds
are written down as the names the picker lists, and read back into the labels
the multiselect holds them under. A name two kinds share is qualified with the
kind, which is what the picker's own labels do.
"""

from orionbelt_ontology_builder import app

BASE = "http://ex.org/base#"
FN = "http://ex.org/fn#"

TARGETS = [
    {
        "kind": "Class",
        "name": "Person",
        "uri": f"{BASE}Person",
        "label": "Class: Person",
    },
    {
        "kind": "Class",
        "name": "zero (fn)",
        "uri": f"{FN}zero",
        "label": "Class: zero (fn)",
    },
    {
        "kind": "Individual",
        "name": "Person",
        "uri": f"{BASE}personInstance",
        "label": "Individual: Person",
    },
    {
        "kind": "Data Property",
        "name": "hasName",
        "uri": f"{BASE}hasName",
        "label": "Data Property: hasName",
    },
    # A concept's node is keyed by name, so it reaches the box without a URI.
    {"kind": "Concept", "name": "Dog", "uri": None, "label": "Concept: Dog"},
]


def _built():
    return app.build_focus_seed_entries(TARGETS)


def _parse(text):
    entries, _ = _built()
    # The entries' identity is the picker's label, so this answers in labels.
    return app.parse_filter_text(text, entries)


def _tokens(labels):
    _, tokens_by_label = _built()
    return [tokens_by_label[label] for label in labels]


def test_a_plain_name_resolves_to_its_label():
    assert _parse("hasName") == (["Data Property: hasName"], [])


def test_a_name_two_kinds_share_focuses_on_both():
    # The node filter's rule for namespace twins, one level up: the plain name
    # takes everything that answers to it, and the qualified form narrows.
    assert _parse("Person")[0] == ["Class: Person", "Individual: Person"]


def test_the_kind_qualifier_picks_one_of_them():
    assert _parse("Class:Person") == (["Class: Person"], [])
    assert _parse("Individual:Person") == (["Individual: Person"], [])


def test_a_uri_resolves_too():
    assert _parse(f"{BASE}personInstance") == (["Individual: Person"], [])


def test_a_concept_without_a_uri_still_resolves_by_name():
    assert _parse("Dog") == (["Concept: Dog"], [])


def test_the_namespace_tag_the_picker_shows_is_accepted():
    # Names arrive already disambiguated, so the tagged form is the name.
    assert _parse("zero (fn)") == (["Class: zero (fn)"], [])
    assert _parse("zero(fn)") == (["Class: zero (fn)"], [])


def test_separators_and_wrapping_follow_the_filter_box():
    labels, unknown = _parse(f"hasName, Dog\n<{BASE}Person>")
    assert labels == ["Class: Person", "Data Property: hasName", "Concept: Dog"]
    assert unknown == []


def test_unknown_names_are_reported_not_dropped_silently():
    labels, unknown = _parse("hasName Bicycle")
    assert labels == ["Data Property: hasName"]
    assert unknown == ["Bicycle"]


def test_empty_text_matches_nothing():
    assert _parse("   ") == ([], [])


def test_results_follow_the_picker_order_not_the_paste_order():
    labels, _ = _parse("Dog hasName")
    assert labels == ["Data Property: hasName", "Concept: Dog"]


def test_a_unique_name_is_written_plainly():
    assert _tokens(["Data Property: hasName", "Concept: Dog"]) == ["hasName", "Dog"]


def test_a_shared_name_is_written_with_its_kind():
    assert _tokens(["Class: Person", "Individual: Person"]) == [
        "Class:Person",
        "Individual:Person",
    ]


def test_the_kind_token_carries_no_space():
    # "Data Property: hasName" cannot be one token, so the qualifier closes up.
    shared = [
        {"kind": "Class", "name": "Name", "uri": f"{BASE}Name", "label": "Class: Name"},
        {
            "kind": "Data Property",
            "name": "Name",
            "uri": f"{BASE}nameProp",
            "label": "Data Property: Name",
        },
    ]
    entries, tokens_by_label = app.build_focus_seed_entries(shared)
    tokens = list(tokens_by_label.values())
    assert tokens == ["Class:Name", "DataProperty:Name"]
    assert all(" " not in t for t in tokens)
    assert app.parse_filter_text(" ".join(tokens), entries) == (
        ["Class: Name", "Data Property: Name"],
        [],
    )


def test_what_is_copied_pastes_back_unchanged():
    picked = ["Class: zero (fn)", "Individual: Person", "Concept: Dog"]
    labels, unknown = _parse(" ".join(_tokens(picked)))
    assert sorted(labels) == sorted(picked)
    assert unknown == []


def test_nothing_focusable_yields_no_entries():
    assert app.build_focus_seed_entries([]) == ([], {})


# --- One IRI, two focus targets ----------------------------------------------

# An imported vocabulary may type a resource both owl:Class and skos:Concept
# (OWL punning), and the app then lists it under Classes and under Concepts.
# Both targets carry the same IRI, so the picker's label is what tells them
# apart — keying the box on the IRI collapsed them into one.
PUNNED = [
    {
        "kind": "Class",
        "name": "Agent",
        "uri": f"{BASE}Agent",
        "label": "Class: Agent",
    },
    {
        "kind": "Concept",
        "name": "Agent",
        "uri": f"{BASE}Agent",
        "label": "Concept: Agent",
    },
]


def test_a_punned_resource_keeps_both_of_its_seeds():
    entries, tokens_by_label = app.build_focus_seed_entries(PUNNED)
    assert tokens_by_label == {
        "Class: Agent": "Class:Agent",
        "Concept: Agent": "Concept:Agent",
    }
    assert app.parse_filter_text("Class:Agent Concept:Agent", entries) == (
        ["Class: Agent", "Concept: Agent"],
        [],
    )


def test_the_kind_qualifier_still_picks_one_side_of_a_pun():
    entries, _ = app.build_focus_seed_entries(PUNNED)
    assert app.parse_filter_text("Concept:Agent", entries) == (["Concept: Agent"], [])


def test_a_punned_iri_focuses_on_both_targets_it_names():
    # The IRI is an alias of both, and it genuinely names both.
    entries, _ = app.build_focus_seed_entries(PUNNED)
    assert app.parse_filter_text(f"{BASE}Agent", entries) == (
        ["Class: Agent", "Concept: Agent"],
        [],
    )


def test_an_alias_never_becomes_the_identity():
    # Regression guard for the shape itself: whatever else an entry answers to,
    # what comes back is the label.
    entries, _ = _built()
    assert [e["uri"] for e in entries] == [t["label"] for t in TARGETS]


def test_entries_without_aliases_are_unaffected():
    # The node filters build entries with no aliases key at all.
    plain = app.build_filter_entries([{"name": "Person", "uri": f"{BASE}Person"}])
    assert app.parse_filter_text("Person", plain) == ([f"{BASE}Person"], [])


def test_a_tagged_name_is_written_without_the_gap():
    # It has to survive being split out of a pasted line.
    assert _tokens(["Class: zero (fn)"]) == ["zero(fn)"]


# --- The box on the page -----------------------------------------------------


def _page_script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        for name in ("Person", "Organization", "Department"):
            om.add_class(name)
        om.add_object_property("worksFor")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_focus_mode"] = True
        st.session_state["_viz_cfg_focus_seeds"] = ["Class: Person"]
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


def test_the_box_prints_the_current_focus():
    at = _page()
    assert any(block.value == "Person" for block in at.code), [
        block.value for block in at.code
    ]


def test_applying_a_pasted_list_replaces_the_focus():
    at = _page()
    at.text_area(key="viz_focus_paste").set_value("Organization Department")
    at.button(key="viz_focus_apply_paste").click()
    _rerun(at)
    # Picker order, not paste order: the picker is what the labels come from.
    assert at.session_state["_viz_cfg_focus_seeds"] == [
        "Class: Department",
        "Class: Organization",
    ]


def test_a_paste_that_matches_nothing_leaves_the_focus_alone():
    at = _page()
    at.text_area(key="viz_focus_paste").set_value("Bicycle")
    at.button(key="viz_focus_apply_paste").click()
    _rerun(at)
    assert at.session_state["_viz_cfg_focus_seeds"] == ["Class: Person"]
    assert any("Bicycle" in w.value for w in at.warning), [w.value for w in at.warning]


def test_a_partly_matching_paste_applies_and_still_reports_the_rest():
    at = _page()
    at.text_area(key="viz_focus_paste").set_value("Organization Bicycle")
    at.button(key="viz_focus_apply_paste").click()
    _rerun(at)
    assert at.session_state["_viz_cfg_focus_seeds"] == ["Class: Organization"]
    assert any("Bicycle" in w.value for w in at.warning), [w.value for w in at.warning]


def test_a_punned_resource_round_trips_through_the_page():
    """End to end on the real thing: an ontology whose Agent is both.

    The picker lists it twice, and copying the focus and pasting it back has to
    return both seeds rather than one.
    """
    from streamlit.testing.v1 import AppTest

    def _script():
        import streamlit as st
        from rdflib import RDF, URIRef
        from rdflib.namespace import SKOS

        from orionbelt_ontology_builder import app
        from orionbelt_ontology_builder.ontology_manager import OntologyManager

        if "ontology" not in st.session_state:
            om = OntologyManager()
            om.add_class("Agent")
            uri = URIRef(om.get_classes()[0]["uri"])
            om.graph.add((uri, RDF.type, SKOS.Concept))
            st.session_state.ontology = om
            st.session_state["_autosave_restored"] = True
            st.session_state["_viz_settings_restored"] = True
            st.session_state["_viz_cfg_focus_mode"] = True
            st.session_state["_viz_cfg_focus_seeds"] = [
                "Class: Agent",
                "Concept: Agent",
            ]
        app.render_visualization()

    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    # What the box printed for the two seeds...
    copied = [block.value for block in at.code]
    assert "Class:Agent Concept:Agent" in copied, copied
    # ...pastes back as both of them.
    at.text_area(key="viz_focus_paste").set_value("Class:Agent Concept:Agent")
    at.button(key="viz_focus_apply_paste").click()
    for group in at.get("button_group"):
        value = group.value
        if not isinstance(value, list):
            group.set_value([value])
    at.run(timeout=300)
    assert not at.exception, at.exception
    assert at.session_state["_viz_cfg_focus_seeds"] == [
        "Class: Agent",
        "Concept: Agent",
    ]

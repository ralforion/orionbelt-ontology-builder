"""Adding a class from the Visualization panel (issue #221).

The form itself is Streamlit wiring, but two decisions in front of it are not:
which class the graph offers as the parent, and where that class sits in the
dropdown. Both can silently parent a new class onto the wrong one, so both are
covered here.
"""

from orionbelt_ontology_builder.app import (
    _panel_add_parent,
    _uid,
    build_class_options,
    parent_option_index,
)

NS = "http://example.org/o#"
CLASSES = [
    {"uri": NS + "Person", "name": "Person", "label": ""},
    {"uri": NS + "Organization", "name": "Organization", "label": ""},
]


# --- which class the graph offers as the parent -----------------------------


def test_a_selected_class_becomes_the_parent():
    """The whole point: hang the new class where you clicked."""
    assert _panel_add_parent(CLASSES, "Class", _uid(NS + "Person")) == NS + "Person"


def test_selecting_something_that_is_not_a_class_offers_no_parent():
    """An individual or a property cannot be a superclass."""
    assert _panel_add_parent(CLASSES, "Individual", _uid(NS + "Person")) is None
    assert _panel_add_parent(CLASSES, "Class Relation", "whatever") is None


def test_selecting_nothing_offers_no_parent():
    """Adding a top-level class from an empty selection stays possible."""
    assert _panel_add_parent(CLASSES, None, None) is None


def test_a_class_that_has_since_gone_offers_no_parent():
    """The selection can name a class that was deleted or renamed underneath."""
    assert _panel_add_parent(CLASSES, "Class", _uid(NS + "Vanished")) is None


# --- where that class sits in the dropdown ----------------------------------


def test_the_parent_is_preselected_by_uri():
    options, lookup = build_class_options(CLASSES, include_none=True)
    index = parent_option_index(options, lookup, NS + "Organization")
    assert lookup[options[index]] == NS + "Organization"


def test_no_parent_selects_none():
    options, lookup = build_class_options(CLASSES, include_none=True)
    assert parent_option_index(options, lookup, None) == 0
    assert options[0] == "None"


def test_a_stale_parent_uri_falls_back_to_none():
    """It must not land on whatever now occupies that position in the list.

    The panel seeds the parent from the graph selection, and that class can be
    deleted or filtered away before the form is submitted.
    """
    options, lookup = build_class_options(CLASSES, include_none=True)
    assert parent_option_index(options, lookup, NS + "Deleted") == 0


def test_a_name_collision_across_namespaces_picks_the_right_one():
    """Local names repeat across namespaces, which is why the lookup is by URI."""
    classes = [
        {"uri": "http://a#Organization", "name": "Organization", "label": ""},
        {"uri": "http://b#Organization", "name": "Organization", "label": ""},
    ]
    options, lookup = build_class_options(classes, include_none=True)
    index = parent_option_index(options, lookup, "http://b#Organization")
    assert lookup[options[index]] == "http://b#Organization"

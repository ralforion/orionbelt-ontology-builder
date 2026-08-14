"""What a modifier-click on a graph node does to the focus seeds.

Ctrl/Cmd-click adds the node to the focus (issue #56); Alt-click focuses on it
alone (issue #276), because wanting one node at a time is the common case and
it otherwise means emptying the picker by hand between hops.
"""

from orionbelt_ontology_builder import app


def test_ctrl_click_adds_to_what_is_already_focused():
    """Building a neighbourhood up out of several nodes."""
    assert app.focus_seeds_after_request(["Class: Person"], "Class: Org") == [
        "Class: Person",
        "Class: Org",
    ]


def test_alt_click_focuses_on_that_node_alone():
    """The point of issue #276."""
    assert app.focus_seeds_after_request(
        ["Class: Person", "Class: Org"], "Class: Role", replace=True
    ) == ["Class: Role"]


def test_ctrl_clicking_a_node_that_is_already_focused_changes_nothing():
    """Not a duplicate entry in the multiselect."""
    seeds = ["Class: Person", "Class: Org"]
    assert app.focus_seeds_after_request(seeds, "Class: Person") == seeds


def test_alt_clicking_the_only_focused_node_changes_nothing():
    """Idempotent, so hopping back onto the node you are on is not a special
    case the caller has to think about."""
    assert app.focus_seeds_after_request(["Class: Person"], "Class: Person", True) == [
        "Class: Person"
    ]


def test_a_first_click_starts_the_focus_either_way():
    """Nothing focused yet, whichever modifier switched the mode on."""
    assert app.focus_seeds_after_request(None, "Class: Person") == ["Class: Person"]
    assert app.focus_seeds_after_request([], "Class: Person", replace=True) == [
        "Class: Person"
    ]


def test_the_caller_s_list_is_not_mutated():
    """The seeds come out of session state; adding to that list in place would
    edit the stored value before the assignment that is meant to."""
    seeds = ["Class: Person"]
    app.focus_seeds_after_request(seeds, "Class: Org")
    assert seeds == ["Class: Person"]

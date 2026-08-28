"""What a modifier-click on a graph node does to the focus.

Ctrl/Cmd-click adds the node to the focus (issue #56); Alt-click focuses on it
alone (issue #276), because wanting one node at a time is the common case and it
otherwise means emptying the picker by hand between hops.

Clicking a node that is *already* focused used to do nothing at all, leaving no
way out of focus mode except the checkbox. Each modifier now undoes its own
action (issue #328): ctrl/cmd-click removes what it would have added, alt-click
switches the mode off when the focus is already exactly that node. Every case
that changed was a no-op before.
"""

from orionbelt_ontology_builder import app

PERSON = "Class: Person"
ORG = "Class: Org"
ROLE = "Class: Role"


# --- what each modifier does on a node that is not focused yet ---------------


def test_ctrl_click_adds_to_what_is_already_focused():
    """Building a neighbourhood up out of several nodes."""
    assert app.focus_seeds_after_request([PERSON], ORG) == ([PERSON, ORG], True)


def test_alt_click_focuses_on_that_node_alone():
    """The point of issue #276."""
    assert app.focus_seeds_after_request([PERSON, ORG], ROLE, replace=True) == (
        [ROLE],
        True,
    )


def test_a_first_click_starts_the_focus_either_way():
    """Nothing focused yet, whichever modifier switched the mode on."""
    assert app.focus_seeds_after_request(None, PERSON) == ([PERSON], True)
    assert app.focus_seeds_after_request([], PERSON, replace=True) == ([PERSON], True)


# --- and on a node that is already focused (issue #328) ----------------------


def test_ctrl_clicking_a_focused_node_drops_it():
    """Ctrl/cmd-click adds, so on a node it already added it takes it back out.
    The others stay, and the mode stays on with them."""
    assert app.focus_seeds_after_request([PERSON, ORG], PERSON) == ([ORG], True)


def test_ctrl_clicking_the_last_focused_node_turns_the_mode_off():
    """Nothing left to focus on. The mode has to go off in the same breath: with
    it on and no seeds, the page backfills an arbitrary first node, so the graph
    would jump to a class nobody picked."""
    assert app.focus_seeds_after_request([PERSON], PERSON) == ([], False)


def test_alt_clicking_the_only_focused_node_turns_the_mode_off():
    """Alt-click sets the focus to exactly one node, so on the node it is
    already set to, it is the way back out."""
    assert app.focus_seeds_after_request([PERSON], PERSON, replace=True) == (
        [PERSON],
        False,
    )


def test_the_alt_click_exit_keeps_the_seeds():
    """So switching focus back on returns you where you were, rather than to a
    node derived from the class selection (issue #235)."""
    seeds, focus_on = app.focus_seeds_after_request([PERSON], PERSON, replace=True)
    assert (seeds, focus_on) == ([PERSON], False)


def test_alt_clicking_one_of_several_still_narrows():
    """Not an exit: the focus is not already *exactly* that node, so "now just
    this one" is still what the user asked for and still what they get."""
    assert app.focus_seeds_after_request([PERSON, ORG], PERSON, replace=True) == (
        [PERSON],
        True,
    )


# --- and the invariant that made this safe to change -------------------------


def test_the_caller_s_list_is_not_mutated():
    """The seeds come out of session state; editing that list in place would
    change the stored value before the assignment that is meant to."""
    seeds = [PERSON, ORG]
    app.focus_seeds_after_request(seeds, ORG)
    app.focus_seeds_after_request(seeds, PERSON, replace=True)
    assert seeds == [PERSON, ORG]

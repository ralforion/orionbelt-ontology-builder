"""What "Focus on one node" starts from when it is switched on (issue #224).

Seeding from the class selection is right when that selection is a narrowing the
user made. It is wrong when nothing has been filtered, because "everything
selected" is just the default state: seeding from it opened focus mode on every
class at once, leaving the post-build prune nothing to narrow.
"""

from orionbelt_ontology_builder.app import focus_seeds_from_selection


def test_a_narrowed_selection_seeds_all_of_it():
    """The narrowing is the intent, so the neighbourhood grows from all of it."""
    assert focus_seeds_from_selection(["Person", "Org"], 10) == [
        "Class: Person",
        "Class: Org",
    ]


def test_selecting_everything_seeds_one_class():
    """Nothing was filtered, so focus starts where the control's name says."""
    assert focus_seeds_from_selection(["Person", "Org", "Role"], 3) == ["Class: Person"]


def test_one_class_in_a_one_class_ontology_still_seeds_it():
    """The only class is both "everything" and the single seed."""
    assert focus_seeds_from_selection(["Person"], 1) == ["Class: Person"]


def test_an_empty_selection_seeds_nothing():
    """The caller falls back to the first available node, as it always did."""
    assert focus_seeds_from_selection([], 4) == []


def test_an_unknown_total_keeps_the_whole_selection():
    """The count mirror is refreshed on render, so a callback can fire before it
    exists. Seeding from the selection is the old behaviour, and the render pass
    that follows re-derives it with the real count."""
    assert focus_seeds_from_selection(["Person", "Org"], 0) == [
        "Class: Person",
        "Class: Org",
    ]


def test_a_stale_count_below_the_selection_still_seeds_one():
    """A count that lags the selection must not read as a narrowing."""
    assert focus_seeds_from_selection(["Person", "Org", "Role"], 2) == ["Class: Person"]

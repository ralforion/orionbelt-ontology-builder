"""Visualization "Filter Classes" reconciliation (issue #180).

Adding a class or a restriction must not wipe a narrowed filter; only deleted
classes drop out, and newly created ones appear.
"""

from orionbelt_ontology_builder import app


def _reconcile(all_names, selected, known):
    """Run one render's reconciliation, returning the new (selected, known)."""
    return app.reconcile_class_filter(all_names, selected, known)


def test_first_render_selects_everything():
    selected, known = _reconcile(["A", "B"], None, None)
    assert selected == ["A", "B"]
    assert known == {"A", "B"}


def test_adding_a_class_keeps_the_narrowed_filter():
    # User narrowed to just {A}; a new class C is created.
    selected, known = _reconcile(["A", "B", "C"], ["A"], {"A", "B"})
    # A stays, B stays hidden, and the brand-new C shows by default.
    assert selected == ["A", "C"]
    assert known == {"A", "B", "C"}


def test_adding_a_class_with_full_selection_shows_it_too():
    selected, _ = _reconcile(["A", "B", "C"], ["A", "B"], {"A", "B"})
    assert selected == ["A", "B", "C"]


def test_deleted_class_drops_out_only():
    selected, _ = _reconcile(["A", "C"], ["A", "B", "C"], {"A", "B", "C"})
    assert selected == ["A", "C"]  # B removed, A and C untouched


def test_rename_shows_the_new_name():
    # A -> A2 reads as a delete + create at the name level.
    selected, _ = _reconcile(["A2", "B"], ["A", "B"], {"A", "B"})
    assert selected == ["A2", "B"]


def test_cleared_filter_stays_empty_when_nothing_new():
    # User cleared the ✕ (empty selection); a plain rerun must not repopulate it.
    selected, _ = _reconcile(["A", "B"], [], {"A", "B"})
    assert selected == []


def test_cleared_filter_still_admits_a_newly_created_class():
    selected, _ = _reconcile(["A", "B", "C"], [], {"A", "B"})
    assert selected == ["C"]


def test_wholesale_replacement_resets_to_all():
    # Load/import/undo swaps in a fresh set of names -> everything shown.
    selected, known = _reconcile(["X", "Y", "Z"], ["A"], {"A", "B"})
    assert selected == ["X", "Y", "Z"]
    assert known == {"X", "Y", "Z"}


def test_selection_order_follows_class_list():
    selected, _ = _reconcile(["A", "B", "C"], ["C", "A"], {"A", "B", "C"})
    assert selected == ["A", "C"]  # ordered by the class list, not the input

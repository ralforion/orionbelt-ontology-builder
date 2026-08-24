"""Visualization "Filter Classes" reconciliation (issues #180, #194).

Adding a class or a restriction must not wipe a narrowed filter; only deleted
classes drop out. A newly created class joins the selection while the filter is
showing everything, and stays out of a filter the user narrowed on purpose.
"""

from orionbelt_ontology_builder import app


def _reconcile(all_names, selected, known):
    """Run one render's reconciliation, returning the new (selected, known)."""
    return app.reconcile_filter_selection(all_names, selected, known)


def test_first_render_selects_everything():
    selected, known = _reconcile(["A", "B"], None, None)
    assert selected == ["A", "B"]
    assert known == {"A", "B"}


def test_adding_a_class_keeps_the_narrowed_filter():
    # User narrowed to just {A}; a new class C is created.
    selected, known = _reconcile(["A", "B", "C"], ["A"], {"A", "B"})
    # A stays, B stays hidden, and C stays out of the view the user curated
    # (issue #194) — the page announces it instead, see newly_hidden_uris.
    assert selected == ["A"]
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


def test_cleared_filter_stays_empty_when_a_class_is_created():
    # An emptied filter is a narrowed filter: nothing pushes itself back in.
    selected, _ = _reconcile(["A", "B", "C"], [], {"A", "B"})
    assert selected == []


def test_disjoint_replacement_shows_everything():
    # A load whose names don't overlap the old set is a replacement whatever the
    # counters said, so a narrowing from the previous ontology cannot survive
    # into it and leave the graph empty.
    selected, known = _reconcile(["X", "Y", "Z"], ["A"], {"A", "B"})
    assert selected == ["X", "Y", "Z"]
    assert known == {"X", "Y", "Z"}


def test_overlapping_replacement_would_hide_classes_without_the_flag():
    # Regression: previous ontology hid B; a NEW ontology of just ["B"] must not
    # inherit that hidden state (review of #180). Diffing alone returns []...
    assert _reconcile(["B"], [], {"A", "B"})[0] == []
    # ...so the replacement flag forces "show everything".
    selected, known = app.reconcile_filter_selection(
        ["B"], [], {"A", "B"}, replaced=True
    )
    assert selected == ["B"]
    assert known == {"B"}


def test_replaced_flag_ignores_prior_narrowing():
    selected, _ = app.reconcile_filter_selection(
        ["Person", "Org"], ["Org"], {"Person", "Org"}, replaced=True
    )
    assert selected == ["Person", "Org"]


def test_selection_order_follows_class_list():
    selected, _ = _reconcile(["A", "B", "C"], ["C", "A"], {"A", "B", "C"})
    assert selected == ["A", "C"]  # ordered by the class list, not the input


def test_new_class_joins_a_filter_that_was_showing_everything():
    # The counterpart of the narrowed case: nothing was hidden, so nothing is
    # being curated, and new content keeps arriving by default.
    selected, _ = _reconcile(["A", "B", "C"], ["A", "B"], {"A", "B"})
    assert selected == ["A", "B", "C"]


def test_showing_everything_survives_a_delete_and_a_create_together():
    # Selection still equals the previous class set even though B is gone, so
    # this is still "showing everything" and C comes along.
    selected, _ = _reconcile(["A", "C"], ["A", "B"], {"A", "B"})
    assert selected == ["A", "C"]


def test_an_empty_ontology_gaining_classes_shows_them():
    # Nothing to narrow before, so nothing to preserve.
    selected, _ = _reconcile(["A", "B"], [], set())
    assert selected == ["A", "B"]


def test_newly_hidden_reports_what_the_narrowed_filter_held_back():
    selected, _ = _reconcile(["A", "B", "C"], ["A"], {"A", "B"})
    assert app.newly_hidden_uris(["A", "B", "C"], selected, {"A", "B"}) == ["C"]


def test_newly_hidden_ignores_classes_that_were_already_hidden():
    # B was hidden by the user, not created just now.
    selected, _ = _reconcile(["A", "B"], ["A"], {"A", "B"})
    assert app.newly_hidden_uris(["A", "B"], selected, {"A", "B"}) == []


def test_newly_hidden_is_empty_when_the_filter_shows_everything():
    selected, _ = _reconcile(["A", "B", "C"], ["A", "B"], {"A", "B"})
    assert app.newly_hidden_uris(["A", "B", "C"], selected, {"A", "B"}) == []


def test_newly_hidden_is_empty_on_the_first_render():
    selected, _ = _reconcile(["A", "B"], None, None)
    assert app.newly_hidden_uris(["A", "B"], selected, None) == []


def test_newly_hidden_follows_the_entity_list_order():
    selected, _ = _reconcile(["C", "A", "D"], ["A"], {"A", "B"})
    assert app.newly_hidden_uris(["C", "A", "D"], selected, {"A", "B"}) == ["C", "D"]


def test_the_toast_names_a_single_new_entity():
    assert app.viz_new_hidden_message(["Bicycle"], "class", "classes") == (
        "Bicycle created, hidden by your class filter"
    )


def test_the_toast_lists_a_small_batch():
    assert app.viz_new_hidden_message(["Bicycle", "Car"], "class", "classes") == (
        "Bicycle, Car created, hidden by your class filter"
    )


def test_the_toast_counts_a_large_batch():
    names = ["A", "B", "C", "D"]
    assert app.viz_new_hidden_message(names, "individual", "individuals") == (
        "4 individuals created, hidden by your individual filter"
    )


def test_the_toast_is_empty_with_nothing_to_report():
    assert app.viz_new_hidden_message([], "class", "classes") == ""


def _renames(kind, pairs):
    """The rename notes a session would hold for ``old -> new`` URI pairs."""
    return {
        app.viz_node_id(kind, old): app.viz_node_id(kind, new) for old, new in pairs
    }


def _renamed(all_uris, selected, known, kind, pairs):
    """Reconcile the way the page does: follow the renames, then diff."""
    selected, known = app.follow_filter_renames(
        all_uris, selected, known, _renames(kind, pairs), kind
    )
    return app.reconcile_filter_selection(all_uris, selected, known)


def test_renaming_the_selected_class_keeps_it_in_a_narrowed_filter():
    # The regression the #194 review found: A was the one class shown, and
    # renaming it read as "A deleted, A2 created" — so the view went empty.
    selected, known = _renamed(["A2", "B"], ["A"], {"A", "B"}, "class", [("A", "A2")])
    assert selected == ["A2"]
    assert known == {"A2", "B"}


def test_a_renamed_class_is_not_announced_as_newly_created():
    selected, known = app.follow_filter_renames(
        ["A2", "B"], ["A"], {"A", "B"}, _renames("class", [("A", "A2")]), "class"
    )
    selected, _ = app.reconcile_filter_selection(["A2", "B"], selected, known)
    assert app.newly_hidden_uris(["A2", "B"], selected, known) == []


def test_renaming_a_hidden_class_leaves_it_hidden():
    selected, _ = _renamed(["A", "B2"], ["A"], {"A", "B"}, "class", [("B", "B2")])
    assert selected == ["A"]


def test_renaming_while_showing_everything_still_shows_everything():
    selected, _ = _renamed(["A2", "B"], ["A", "B"], {"A", "B"}, "class", [("A", "A2")])
    assert selected == ["A2", "B"]


def test_a_rename_chain_lands_on_the_final_name():
    # Two renames between Visualization renders, the way focus seeds handle it.
    selected, _ = _renamed(
        ["A3", "B"], ["A"], {"A", "B"}, "class", [("A", "A2"), ("A2", "A3")]
    )
    assert selected == ["A3"]


def test_individuals_follow_their_own_node_ids():
    # Individual node ids carry a prefix, so a filter that computed them as
    # classes would match nothing and the rename would not be followed.
    selected, _ = _renamed(["i2", "j"], ["i"], {"i", "j"}, "individual", [("i", "i2")])
    assert selected == ["i2"]


def test_a_rename_to_something_that_is_gone_drops_out():
    # Renamed, then deleted before the next render: nothing to carry forward.
    selected, _ = _renamed(["B"], ["A"], {"A", "B"}, "class", [("A", "A2")])
    assert selected == []


def test_no_rename_notes_leave_the_selection_alone():
    assert app.follow_filter_renames(["A", "B"], ["A"], {"A", "B"}, None, "class") == (
        ["A"],
        {"A", "B"},
    )


def test_a_first_render_has_nothing_to_re_point():
    assert app.follow_filter_renames(
        ["A"], None, None, _renames("class", [("A", "A2")]), "class"
    ) == (None, None)

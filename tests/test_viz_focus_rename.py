"""Focus seeds follow an entity that is renamed (issue #275).

Seeds are held as the labels the "Focus node(s)" multiselect shows, so renaming
the very class you were focused on left a seed naming nothing: it was pruned and
focus mode fell back to an arbitrary first node, dropping the class you were
looking at out of the graph. The rename leaves a note behind, and the next
Visualization render turns it back into the new label.
"""

import pytest

from orionbelt_ontology_builder import app

NS = "http://test.org/ont#"


def _class_targets(*names):
    """The label -> node id map render_visualization builds for classes."""
    return {f"Class: {n}": app.viz_node_id("class", NS + n) for n in names}


def _seen(targets, *labels):
    """What the previous render recorded for those seeds."""
    return {label: targets[label] for label in labels}


@pytest.fixture
def session(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    return state


def test_a_renamed_seed_moves_to_its_new_label(session):
    """The point of the issue: the focus stays on the class you renamed."""
    before = _class_targets("Person", "Org")
    after = _class_targets("Human", "Org")
    app.viz_note_rename("class", NS + "Person", NS + "Human")

    seeds, seen = app.follow_focus_seed_renames(
        ["Class: Person"],
        _seen(before, "Class: Person"),
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Human"]
    # The recorded id has to move with it, or the reuse prune that runs next
    # reads the seed as a label that has come to name something else.
    assert seen == {"Class: Human": after["Class: Human"]}
    assert app.prune_reused_focus_seeds(seeds, seen, after) == ["Class: Human"]


def test_untouched_seeds_are_left_alone(session):
    """Only the renamed entity moves; the rest of the selection is preserved."""
    before = _class_targets("Person", "Org")
    after = _class_targets("Human", "Org")
    app.viz_note_rename("class", NS + "Person", NS + "Human")

    seeds, seen = app.follow_focus_seed_renames(
        ["Class: Org", "Class: Person"],
        _seen(before, "Class: Org", "Class: Person"),
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Org", "Class: Human"]
    assert seen == {
        "Class: Org": after["Class: Org"],
        "Class: Human": after["Class: Human"],
    }


def test_a_chain_of_renames_lands_on_the_last_name(session):
    """Seeds are only re-pointed on a Visualization render, so an entity can be
    renamed more than once in between."""
    before = _class_targets("Person")
    after = _class_targets("Being")
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    app.viz_note_rename("class", NS + "Human", NS + "Being")

    seeds, _ = app.follow_focus_seed_renames(
        ["Class: Person"],
        _seen(before, "Class: Person"),
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Being"]


def test_a_rename_back_to_the_old_name_does_not_spin(session):
    """A -> B -> A is a cycle in the notes; it resolves to the name in force."""
    targets = _class_targets("Person")
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    app.viz_note_rename("class", NS + "Human", NS + "Person")

    seeds, _ = app.follow_focus_seed_renames(
        ["Class: Person"],
        _seen(targets, "Class: Person"),
        targets,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Person"]


def test_a_no_op_rename_is_not_recorded(session):
    """Saving the edit form without touching the name changes nothing."""
    app.viz_note_rename("class", NS + "Person", NS + "Person")
    assert "_viz_pending_renames" not in session


def test_individuals_and_data_properties_follow_too(session):
    """Every focusable kind is keyed by its own node id, and each is noted."""
    before = {
        "Individual: alice": app.viz_node_id("individual", NS + "alice"),
        "Data Property: age": app.viz_node_id("property", NS + "age"),
    }
    after = {
        "Individual: alicia": app.viz_node_id("individual", NS + "alicia"),
        "Data Property: ageInYears": app.viz_node_id("property", NS + "ageInYears"),
    }
    app.viz_note_rename("individual", NS + "alice", NS + "alicia")
    app.viz_note_rename("property", NS + "age", NS + "ageInYears")

    seeds, _ = app.follow_focus_seed_renames(
        list(before),
        dict(before),
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Individual: alicia", "Data Property: ageInYears"]


def test_a_renamed_concept_follows_by_name(session):
    """SKOS concept nodes are keyed by local name rather than by URI."""
    before = {"Concept: Widget": app.viz_node_id("concept", "Widget")}
    after = {"Concept: Gadget": app.viz_node_id("concept", "Gadget")}
    app.viz_note_rename("concept", "Widget", "Gadget")

    seeds, _ = app.follow_focus_seed_renames(
        ["Concept: Widget"],
        dict(before),
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Concept: Gadget"]


def test_a_seed_whose_type_is_switched_off_is_left_to_the_prune(session):
    """The renamed class is not focusable with classes hidden, so the seed is
    left exactly as it was and the existing prune deals with it."""
    before = _class_targets("Person")
    app.viz_note_rename("class", NS + "Person", NS + "Human")

    seeds, seen = app.follow_focus_seed_renames(
        ["Class: Person"],
        _seen(before, "Class: Person"),
        {},
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Person"]
    assert app.prune_reused_focus_seeds(seeds, seen, {}) == []


def test_a_freshly_picked_seed_has_no_recorded_id(session):
    """Nothing to follow it by, and nothing that needs following."""
    after = _class_targets("Person", "Org")
    app.viz_note_rename("class", NS + "Widget", NS + "Gadget")

    seeds, _ = app.follow_focus_seed_renames(
        ["Class: Person", "Class: Org"],
        {"Class: Person": after["Class: Person"]},
        after,
        session["_viz_pending_renames"],
    )

    assert seeds == ["Class: Person", "Class: Org"]


def test_no_renames_leaves_the_seeds_untouched(session):
    """The common case: nothing was renamed, so nothing is rewritten."""
    targets = _class_targets("Person", "Org")
    seeds, seen = app.follow_focus_seed_renames(
        ["Class: Person"], _seen(targets, "Class: Person"), targets, {}
    )
    assert seeds == ["Class: Person"]
    assert seen == {"Class: Person": targets["Class: Person"]}


def test_saved_seed_ids_follow_a_rename_too(session):
    """The seeds saved against a linked file are node ids (#164). Renaming the
    entity before the first Visualization render of the session leaves the saved
    id naming nothing, and there are no labels in session yet to follow."""
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    saved = [app.viz_node_id("class", NS + "Person")]

    followed = app.follow_renamed_node_ids(saved, session["_viz_pending_renames"])

    assert followed == [app.viz_node_id("class", NS + "Human")]
    # Which is what the restore turns back into a label.
    after = _class_targets("Human", "Org")
    label_by_id = {node_id: label for label, node_id in after.items()}
    assert [label_by_id[i] for i in followed if i in label_by_id] == ["Class: Human"]


def test_saved_seed_ids_follow_a_chain_of_renames(session):
    """Same chain-following as the label path."""
    app.viz_note_rename("class", NS + "Person", NS + "Human")
    app.viz_note_rename("class", NS + "Human", NS + "Being")

    followed = app.follow_renamed_node_ids(
        [app.viz_node_id("class", NS + "Person")],
        session["_viz_pending_renames"],
    )

    assert followed == [app.viz_node_id("class", NS + "Being")]


def test_saved_seed_ids_are_untouched_without_notes(session):
    """The common case: nothing was renamed, so the saved ids restore as they
    always did, including ids that resolve to nothing."""
    saved = [app.viz_node_id("class", NS + "Person"), "gone"]
    assert app.follow_renamed_node_ids(saved, None) == saved
    assert app.follow_renamed_node_ids(saved, {}) == saved
    assert app.follow_renamed_node_ids(None, {}) == []


def test_dropping_the_seeds_forgets_the_notes(session):
    """With no seeds left there is nothing for a note to re-point, and keeping
    them would apply a rename made against the file that was just closed."""
    session["_viz_cfg_focus_seeds"] = ["Class: Person"]
    app.viz_note_rename("class", NS + "Person", NS + "Human")

    app.viz_drop_focus_seeds()

    assert "_viz_pending_renames" not in session

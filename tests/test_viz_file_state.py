"""Per-linked-file Visualization state: node filters and focus seeds (issue #164).

Issue #142 kept these two out of the cross-session settings because they name
entities, so restoring them into a different ontology would be meaningless. The
desktop app's linked working file identifies the ontology, so they are saved
against its path and only restored while that same file is still linked.
"""

import json

import pytest

from orionbelt_ontology_builder import app

FILE_A = "/tmp/onto-a.ttl"
FILE_B = "/tmp/onto-b.ttl"
NS = "http://test.org/ont#"

# label -> node id, the way render_visualization builds it. Class and individual
# ids derive from the URI, which is why seeds are stored as ids (issue #179).
FOCUS_TARGETS = {
    "Class: Person": app._uid(NS + "Person"),
    "Class: Org": app._uid(NS + "Org"),
    "Individual: alice": f"ind_{app._uid(NS + 'alice')}",
}


def _filters(class_uris=(), class_selected=None, ind_uris=(), ind_selected=None):
    """A stand-in for the per-kind filter dict render_visualization builds."""
    return {
        "class": {
            "uris": list(class_uris),
            "selected_uris": list(
                class_uris if class_selected is None else class_selected
            ),
        },
        "ind": {
            "uris": list(ind_uris),
            "selected_uris": list(ind_uris if ind_selected is None else ind_selected),
        },
    }


def _hid_one(**kwargs):
    """The common case: two classes, the second hidden."""
    return _filters(
        class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"], **kwargs
    )


class _Session(dict):
    """Session state stand-in: app code reaches for both keys and attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value


def _desktop(monkeypatch, tmp_path, linked=FILE_A):
    """Point local_store at a temp config.json with ``linked`` linked."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    if linked:
        app.local_store.set_linked_path(linked)
    return cfg_file


def _stored(cfg_file):
    return json.loads(cfg_file.read_text()).get(app.VIZ_FILE_STATE_KEY, {})


# ---- What gets stored -------------------------------------------------------


def test_payload_stores_what_is_hidden_not_what_is_selected(monkeypatch):
    # Everything is shown by default, so recording the hidden set keeps
    # config.json small for an ontology with thousands of entities.
    monkeypatch.setattr(app.st, "session_state", {})
    payload = app._viz_file_state_payload(
        _filters(class_uris=[NS + "A", NS + "B", NS + "C"], class_selected=[NS + "A"]),
        FOCUS_TARGETS,
    )
    assert payload == {"hidden_class_uris": [NS + "B", NS + "C"]}


def test_payload_omits_untouched_filters_and_absent_seeds(monkeypatch):
    monkeypatch.setattr(app.st, "session_state", {})
    payload = app._viz_file_state_payload(
        _filters(class_uris=[NS + "A"]), FOCUS_TARGETS
    )
    assert payload == {}


def test_payload_stores_seeds_as_node_ids_not_labels(monkeypatch):
    # A display label gains a namespace tag as soon as a second entity takes the
    # same local name, so a saved label would stop matching (issue #179).
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Person"]}
    )
    payload = app._viz_file_state_payload(_filters(), FOCUS_TARGETS)
    assert payload == {"focus_seed_ids": [app._uid(NS + "Person")]}


def test_payload_drops_seeds_with_no_current_node(monkeypatch):
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Vanished"]}
    )
    assert app._viz_file_state_payload(_filters(), FOCUS_TARGETS) == {}


def test_saved_seed_id_survives_a_label_that_gained_a_namespace_tag(monkeypatch):
    # Same entity, but a second Person appeared while the app was closed, so its
    # label is now disambiguated. Mapping id -> label still finds it.
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Person"]}
    )
    saved = app._viz_file_state_payload(_filters(), FOCUS_TARGETS)["focus_seed_ids"]
    later_targets = {
        "Class: Person (foaf)": app._uid(NS + "Person"),
        "Class: Person (gist)": app._uid("http://other#Person"),
    }
    label_by_id = {node_id: label for label, node_id in later_targets.items()}
    assert [label_by_id[i] for i in saved if i in label_by_id] == [
        "Class: Person (foaf)"
    ]


# ---- Round trip -------------------------------------------------------------


def test_disk_roundtrip_for_the_linked_file(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Person"]}
    )
    app._persist_viz_file_state(_hid_one(ind_uris=[NS + "i1"]), FOCUS_TARGETS)

    assert _stored(cfg_file)[FILE_A] == {
        "hidden_class_uris": [NS + "B"],
        "focus_seed_ids": [app._uid(NS + "Person")],
    }

    # A fresh session restores it.
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == _stored(cfg_file)[FILE_A]


def test_restore_seeds_the_filter_so_hidden_entities_stay_hidden():
    selected, known = app.seed_filter_from_saved(
        [NS + "A", NS + "B"], {NS + "B"}, None, None
    )
    result, _ = app.reconcile_filter_selection([NS + "A", NS + "B"], selected, known)
    assert result == [NS + "A"]


def test_restore_still_shows_entities_added_to_the_file_since():
    # The file gained C while the app was closed. C is not in the hidden set, so
    # it must show, exactly as newly created content always does.
    all_uris = [NS + "A", NS + "B", NS + "C"]
    selected, known = app.seed_filter_from_saved(all_uris, {NS + "B"}, None, None)
    result, _ = app.reconcile_filter_selection(all_uris, selected, known)
    assert result == [NS + "A", NS + "C"]


def test_restore_drops_entities_deleted_from_the_file_since():
    selected, known = app.seed_filter_from_saved([NS + "A"], {NS + "B"}, None, None)
    result, _ = app.reconcile_filter_selection([NS + "A"], selected, known)
    assert result == [NS + "A"]


def test_seeding_defers_to_a_selection_the_session_already_has():
    # Only the first render of a linked file may seed; later renders must keep
    # whatever the user has since picked.
    selected, known = app.seed_filter_from_saved(
        [NS + "A", NS + "B"], {NS + "B"}, [NS + "B"], {NS + "A", NS + "B"}
    )
    assert selected == [NS + "B"]
    assert known == {NS + "A", NS + "B"}


# ---- Scoping ----------------------------------------------------------------


def test_state_is_scoped_to_the_linked_file(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path, linked=FILE_A)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)

    # Linking a different file must not inherit the first file's filters.
    app.local_store.set_linked_path(FILE_B)
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


def test_relinking_mid_session_clears_the_previous_files_state(monkeypatch, tmp_path):
    """Regression: the state in session belongs to the file being left.

    A session that has rendered the graph already holds a selection and seeds.
    Left in place they would win over the newly linked file's saved state (a
    selection already in session suppresses it), and then be written back out
    under the new file's key.
    """
    _desktop(monkeypatch, tmp_path, linked=FILE_A)
    session = {
        "_viz_file_state_for": FILE_B,
        "_viz_cfg_selected_class_uris": [NS + "OLD"],
        "_viz_cfg_known_class_uris": {NS + "OLD"},
        "_viz_cfg_selected_ind_uris": [NS + "oldind"],
        "_viz_cfg_known_ind_uris": {NS + "oldind"},
        "_viz_cfg_focus_seeds": ["Class: FromTheOtherFile"],
    }
    monkeypatch.setattr(app.st, "session_state", session)

    app._restore_viz_file_state()

    for stale in (
        "_viz_cfg_selected_class_uris",
        "_viz_cfg_known_class_uris",
        "_viz_cfg_selected_ind_uris",
        "_viz_cfg_known_ind_uris",
        "_viz_cfg_focus_seeds",
    ):
        assert stale not in session, stale
    # With the selection cleared, the new file's saved state is what applies.
    selected, known = app.seed_filter_from_saved(
        [NS + "A", NS + "B"],
        {NS + "B"},
        session.get("_viz_cfg_selected_class_uris"),
        session.get("_viz_cfg_known_class_uris"),
    )
    assert selected == [NS + "A"]
    assert known == {NS + "A", NS + "B"}


def test_relinking_does_not_read_the_new_file_as_a_replaced_ontology(
    monkeypatch, tmp_path
):
    """Regression: loading the newly linked file looked like an ontology swap.

    ``_load_linked_file`` bumps the mutation counter without a matching edit, so
    the counters left over from the previous file made ``replaced`` true. That
    resets the filter to everything shown, which both discards the state being
    restored for the new file and then writes that empty result back over it.
    """
    _desktop(monkeypatch, tmp_path, linked=FILE_A)
    session = _Session(
        {
            "_viz_file_state_for": FILE_B,
            # Seen on the last render, while FILE_B was linked.
            "_viz_cfg_seen_mutation": 4,
            "_viz_cfg_seen_edits": 0,
            # Loading FILE_A bumped the ontology counter, with no user edit.
            "_ont_mutation_count": 5,
            "_ont_edit_count": 0,
        }
    )
    monkeypatch.setattr(app.st, "session_state", session)
    assert app.viz_ontology_was_replaced() is True  # before the switch is seen

    app._restore_viz_file_state()

    assert app.viz_ontology_was_replaced() is False
    # So the new file's saved hidden set survives the reconcile.
    selected, known = app.seed_filter_from_saved(
        [NS + "A", NS + "B"], {NS + "B"}, None, None
    )
    result, _ = app.reconcile_filter_selection(
        [NS + "A", NS + "B"], selected, known, replaced=app.viz_ontology_was_replaced()
    )
    assert result == [NS + "A"]


def test_a_real_ontology_swap_still_resets_the_filter(monkeypatch, tmp_path):
    # Importing over the same linked file is a genuine replacement: the saved
    # hidden set names entities that may be gone, so everything shows again.
    _desktop(monkeypatch, tmp_path, linked=FILE_A)
    session = _Session(
        {
            "_viz_file_state_for": FILE_A,  # same file, no switch
            "_viz_cfg_seen_mutation": 4,
            "_viz_cfg_seen_edits": 0,
            "_ont_mutation_count": 5,
            "_ont_edit_count": 0,
        }
    )
    monkeypatch.setattr(app.st, "session_state", session)
    app._restore_viz_file_state()
    assert app.viz_ontology_was_replaced() is True


def test_an_ordinary_edit_is_not_a_replacement(monkeypatch):
    monkeypatch.setattr(
        app.st,
        "session_state",
        {
            "_viz_cfg_seen_mutation": 4,
            "_viz_cfg_seen_edits": 1,
            "_ont_mutation_count": 5,
            "_ont_edit_count": 2,
        },
    )
    assert app.viz_ontology_was_replaced() is False


def test_relinking_does_not_write_the_old_files_seeds_under_the_new_file(
    monkeypatch, tmp_path
):
    cfg_file = _desktop(monkeypatch, tmp_path, linked=FILE_B)
    session = _Session()
    monkeypatch.setattr(app.st, "session_state", session)

    # Render 1: the user picks a seed while FILE_B is linked. render_visualization
    # always restores before it persists, so mirror that order here.
    app._restore_viz_file_state()
    session["_viz_cfg_focus_seeds"] = ["Class: Person"]
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)

    # Render 2: same session, now pointed at a file with nothing saved.
    app.local_store.set_linked_path(FILE_A)
    app._restore_viz_file_state()
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"]), FOCUS_TARGETS
    )

    stored = _stored(cfg_file)
    assert FILE_A not in stored
    assert stored[FILE_B]["focus_seed_ids"] == [app._uid(NS + "Person")]


def test_relinking_mid_session_restores_the_new_file(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path, linked=FILE_B)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)

    monkeypatch.setattr(app.st, "session_state", {})
    app.local_store.set_linked_path(FILE_A)
    assert app._restore_viz_file_state() == {}  # nothing saved for A
    app.local_store.set_linked_path(FILE_B)
    assert app._restore_viz_file_state() == {"hidden_class_uris": [NS + "B"]}


def test_restore_runs_once_per_file(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() != {}
    # Session state now holds the reconciled selection; re-seeding it would undo
    # whatever the user changed since.
    assert app._restore_viz_file_state() == {}


def test_cloud_neither_saves_nor_restores(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    assert _stored(cfg_file) == {}
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


def test_no_linked_file_neither_saves_nor_restores(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path, linked=None)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    assert not cfg_file.exists() or _stored(cfg_file) == {}
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


# ---- Housekeeping -----------------------------------------------------------


def test_untouched_filters_write_nothing(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    before = cfg_file.read_text()
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_filters(class_uris=[NS + "A"]), FOCUS_TARGETS)
    assert cfg_file.read_text() == before


def test_clearing_a_filter_removes_the_entry(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    assert FILE_A in _stored(cfg_file)
    # Re-showing everything leaves nothing worth remembering.
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"]), FOCUS_TARGETS
    )
    assert _stored(cfg_file) == {}


def test_remembered_files_are_capped(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path, linked=None)
    monkeypatch.setattr(app.st, "session_state", {})
    total = app.VIZ_FILE_STATE_MAX_FILES + 3
    for i in range(total):
        app.local_store.set_linked_path(f"/tmp/onto-{i}.ttl")
        app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    stored = _stored(cfg_file)
    assert len(stored) == app.VIZ_FILE_STATE_MAX_FILES
    assert "/tmp/onto-0.ttl" not in stored  # oldest evicted
    assert f"/tmp/onto-{total - 1}.ttl" in stored  # newest kept


def test_unchanged_state_is_not_rewritten(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.st, "session_state", {})
    filters = _hid_one()
    app._persist_viz_file_state(filters, FOCUS_TARGETS)
    stamp = cfg_file.stat().st_mtime_ns
    for _ in range(3):
        app._persist_viz_file_state(filters, FOCUS_TARGETS)
    assert cfg_file.stat().st_mtime_ns == stamp


def test_a_failed_write_is_retried(monkeypatch, tmp_path):
    """Regression: recording the attempt before it succeeded gave up silently.

    An unwritable config.json must not stop later reruns from trying again, or
    a transient failure would lose the state for the rest of the session.
    """
    cfg_file = _desktop(monkeypatch, tmp_path)
    session = _Session(error_log=[])
    monkeypatch.setattr(app.st, "session_state", session)

    calls = []

    def _boom(_config):
        calls.append(1)
        raise OSError("read-only file system")

    monkeypatch.setattr(app.local_store, "save_config", _boom)
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    assert "_viz_file_state_fingerprint" not in session

    # The disk comes back; the same unchanged state still gets written.
    monkeypatch.undo()
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(app.st, "session_state", session)
    app._persist_viz_file_state(_hid_one(), FOCUS_TARGETS)
    assert calls == [1]
    assert _stored(cfg_file)[FILE_A] == {"hidden_class_uris": [NS + "B"]}


@pytest.mark.parametrize(
    "raw",
    [
        {"hidden_class_uris": [NS + "A", 7, None], "focus_seed_ids": "not-a-list"},
        {"hidden_class_uris": "not-a-list"},
    ],
)
def test_junk_on_disk_is_ignored(monkeypatch, tmp_path, raw):
    cfg_file = _desktop(monkeypatch, tmp_path)
    cfg_file.write_text(
        json.dumps({"linked_path": FILE_A, app.VIZ_FILE_STATE_KEY: {FILE_A: raw}})
    )
    monkeypatch.setattr(app.st, "session_state", {})
    entry = app._restore_viz_file_state()
    assert all(
        isinstance(u, str) for u in app._str_list(entry.get("hidden_class_uris"))
    )
    assert app._str_list(entry.get("focus_seed_ids")) == []


def test_non_dict_store_is_ignored(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    cfg_file.write_text(
        json.dumps({"linked_path": FILE_A, app.VIZ_FILE_STATE_KEY: ["nope"]})
    )
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}

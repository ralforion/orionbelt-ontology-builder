"""Per-linked-file Visualization state: node filters and focus seeds (issue #164).

Issue #142 kept these two out of the cross-session settings because they name
entities, so restoring them into a different ontology would be meaningless. The
desktop app's linked working file identifies the ontology, so they are saved
against its path and only restored while that same file is still linked.
"""

import json

from orionbelt_ontology_builder import app

FILE_A = "/tmp/onto-a.ttl"
FILE_B = "/tmp/onto-b.ttl"
NS = "http://test.org/ont#"


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


def _desktop(monkeypatch, tmp_path, linked=FILE_A):
    """Point local_store at a temp config.json with ``linked`` linked."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    if linked:
        app.local_store.set_linked_path(linked)
    return cfg_file


# ---- What gets stored -------------------------------------------------------


def test_payload_stores_what_is_hidden_not_what_is_selected(monkeypatch):
    # Everything is shown by default, so recording the hidden set keeps
    # config.json small for an ontology with thousands of entities.
    monkeypatch.setattr(app.st, "session_state", {})
    payload = app._viz_file_state_payload(
        _filters(class_uris=[NS + "A", NS + "B", NS + "C"], class_selected=[NS + "A"])
    )
    assert payload == {"hidden_class_uris": [NS + "B", NS + "C"]}


def test_payload_omits_untouched_filters_and_absent_seeds(monkeypatch):
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._viz_file_state_payload(_filters(class_uris=[NS + "A"])) == {}


def test_payload_includes_focus_seeds(monkeypatch):
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Person"]}
    )
    assert app._viz_file_state_payload(_filters())["focus_seeds"] == ["Class: Person"]


# ---- Round trip -------------------------------------------------------------


def test_disk_roundtrip_for_the_linked_file(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app.st, "session_state", {"_viz_cfg_focus_seeds": ["Class: Person"]}
    )
    app._persist_viz_file_state(
        _filters(
            class_uris=[NS + "A", NS + "B"],
            class_selected=[NS + "A"],
            ind_uris=[NS + "i1"],
        )
    )

    stored = json.loads(cfg_file.read_text())[app.VIZ_FILE_STATE_KEY]
    assert stored[FILE_A] == {
        "hidden_class_uris": [NS + "B"],
        "focus_seeds": ["Class: Person"],
    }

    # A fresh session restores it.
    restore_state: dict = {}
    monkeypatch.setattr(app.st, "session_state", restore_state)
    assert app._restore_viz_file_state() == stored[FILE_A]


def test_restore_seeds_the_filter_so_hidden_entities_stay_hidden():
    saved = {NS + "B"}
    selected, known = app.seed_filter_from_saved(
        [NS + "A", NS + "B"], saved, None, None
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
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )

    # Linking a different file must not inherit the first file's filters.
    app.local_store.set_linked_path(FILE_B)
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


def test_relinking_mid_session_restores_the_new_file(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path, linked=FILE_B)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )

    session: dict = {}
    monkeypatch.setattr(app.st, "session_state", session)
    app.local_store.set_linked_path(FILE_A)
    assert app._restore_viz_file_state() == {}  # nothing saved for A
    app.local_store.set_linked_path(FILE_B)
    assert app._restore_viz_file_state() == {"hidden_class_uris": [NS + "B"]}


def test_restore_runs_once_per_file(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )
    session: dict = {}
    monkeypatch.setattr(app.st, "session_state", session)
    assert app._restore_viz_file_state() != {}
    # Session state now holds the reconciled selection; re-seeding it would undo
    # whatever the user changed since.
    assert app._restore_viz_file_state() == {}


def test_cloud_neither_saves_nor_restores(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )
    assert app.VIZ_FILE_STATE_KEY not in json.loads(cfg_file.read_text())
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


def test_no_linked_file_neither_saves_nor_restores(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path, linked=None)
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )
    assert not cfg_file.exists() or app.VIZ_FILE_STATE_KEY not in json.loads(
        cfg_file.read_text()
    )
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}


# ---- Housekeeping -----------------------------------------------------------


def test_untouched_filters_write_nothing(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    before = cfg_file.read_text()
    monkeypatch.setattr(app.st, "session_state", {})
    app._persist_viz_file_state(_filters(class_uris=[NS + "A"]))
    assert cfg_file.read_text() == before


def test_clearing_a_filter_removes_the_entry(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    session: dict = {}
    monkeypatch.setattr(app.st, "session_state", session)
    app._persist_viz_file_state(
        _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    )
    assert FILE_A in json.loads(cfg_file.read_text())[app.VIZ_FILE_STATE_KEY]
    # Re-showing everything leaves nothing worth remembering.
    app._persist_viz_file_state(_filters(class_uris=[NS + "A", NS + "B"]))
    assert json.loads(cfg_file.read_text())[app.VIZ_FILE_STATE_KEY] == {}


def test_remembered_files_are_capped(monkeypatch, tmp_path):
    _desktop(monkeypatch, tmp_path, linked=None)
    monkeypatch.setattr(app.st, "session_state", {})
    total = app.VIZ_FILE_STATE_MAX_FILES + 3
    for i in range(total):
        app.local_store.set_linked_path(f"/tmp/onto-{i}.ttl")
        app._persist_viz_file_state(
            _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
        )
    stored = json.loads((tmp_path / "config.json").read_text())[app.VIZ_FILE_STATE_KEY]
    assert len(stored) == app.VIZ_FILE_STATE_MAX_FILES
    assert "/tmp/onto-0.ttl" not in stored  # oldest evicted
    assert f"/tmp/onto-{total - 1}.ttl" in stored  # newest kept


def test_unchanged_state_is_not_rewritten(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    session: dict = {}
    monkeypatch.setattr(app.st, "session_state", session)
    filters = _filters(class_uris=[NS + "A", NS + "B"], class_selected=[NS + "A"])
    app._persist_viz_file_state(filters)
    stamp = cfg_file.stat().st_mtime_ns
    for _ in range(3):
        app._persist_viz_file_state(filters)
    assert cfg_file.stat().st_mtime_ns == stamp


def test_junk_on_disk_is_ignored(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    cfg_file.write_text(
        json.dumps(
            {
                "linked_path": FILE_A,
                app.VIZ_FILE_STATE_KEY: {
                    FILE_A: {
                        "hidden_class_uris": [NS + "A", 7, None],  # non-strings
                        "focus_seeds": "Class: Person",  # not a list
                    }
                },
            }
        )
    )
    monkeypatch.setattr(app.st, "session_state", {})
    entry = app._restore_viz_file_state()
    assert app._str_list(entry.get("hidden_class_uris")) == [NS + "A"]
    assert app._str_list(entry.get("focus_seeds")) == []


def test_non_dict_store_is_ignored(monkeypatch, tmp_path):
    cfg_file = _desktop(monkeypatch, tmp_path)
    cfg_file.write_text(
        json.dumps({"linked_path": FILE_A, app.VIZ_FILE_STATE_KEY: ["nope"]})
    )
    monkeypatch.setattr(app.st, "session_state", {})
    assert app._restore_viz_file_state() == {}

"""Persistence of Visualization display settings across sessions (issue #142)."""

import json

from orionbelt_ontology_builder import app

# A representative slice of the _viz_cfg defaults, incl. a non-persisted key
# (selected_classes) that must be ignored.
DEFAULTS = {
    "show_classes": True,
    "show_obj_props": True,
    "graph_height": 670,
    "node_spacing": 150,
    "fit": True,
    "focus_mode": False,
    "focus_depth": 1,
    "selected_classes": [],  # not in _VIZ_PERSIST_KEYS
}


def test_apply_validates_types_and_clamps_ints(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_viz_settings(
        {
            "show_classes": False,  # bool -> applied
            "graph_height": 99999,  # clamped to 1200
            "node_spacing": 10,  # clamped to 50
            "focus_depth": 3,  # in range
            "fit": "yes",  # wrong type -> ignored
            "selected_classes": ["X"],  # not persisted -> ignored
            "bogus": 1,  # not a known setting -> ignored
        },
        DEFAULTS,
    )
    assert fake["_viz_cfg_show_classes"] is False
    assert fake["_viz_cfg_graph_height"] == 1200
    assert fake["_viz_cfg_node_spacing"] == 50
    assert fake["_viz_cfg_focus_depth"] == 3
    assert "_viz_cfg_fit" not in fake  # wrong type left at default
    assert "_viz_cfg_selected_classes" not in fake
    assert "_viz_cfg_bogus" not in fake


def test_apply_ignores_non_dict(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_viz_settings(None, DEFAULTS)
    assert fake == {}


def test_disk_persist_and_restore_roundtrip(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)

    # Save from one "session".
    save_state: dict = {
        "_viz_settings_restored": True,
        "_viz_cfg_show_classes": False,
        "_viz_cfg_graph_height": 800,
        "_viz_cfg_fit": False,
    }
    monkeypatch.setattr(app.st, "session_state", save_state)
    app._persist_viz_settings()
    stored = json.loads(cfg_file.read_text())["viz_settings"]
    assert stored == {"show_classes": False, "graph_height": 800, "fit": False}

    # Restore into a fresh "session".
    restore_state: dict = {}
    monkeypatch.setattr(app.st, "session_state", restore_state)
    app._restore_viz_settings(DEFAULTS)
    assert restore_state["_viz_settings_restored"] is True
    assert restore_state["_viz_cfg_show_classes"] is False
    assert restore_state["_viz_cfg_graph_height"] == 800
    assert restore_state["_viz_cfg_fit"] is False


def test_persist_waits_for_restore(monkeypatch, tmp_path):
    # Before restore resolves, saving is skipped so starting defaults can't
    # clobber a previously saved set.
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(app.st, "session_state", {"_viz_cfg_show_classes": True})
    app._persist_viz_settings()
    assert not cfg_file.exists()


def test_persist_noops_when_unchanged(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    state: dict = {"_viz_settings_restored": True, "_viz_cfg_fit": True}
    monkeypatch.setattr(app.st, "session_state", state)
    app._persist_viz_settings()
    first = cfg_file.stat().st_mtime_ns
    app._persist_viz_settings()  # nothing changed
    assert cfg_file.stat().st_mtime_ns == first  # not rewritten

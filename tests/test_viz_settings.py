"""Persistence of Visualization display settings across sessions (issue #142)."""

import json

from orionbelt_ontology_builder import app

# A representative slice of the _viz_cfg defaults, incl. a non-persisted key
# (selected_classes) that must be ignored.
DEFAULTS = {
    "show_classes": True,
    "show_obj_props": True,
    "show_skos": True,
    "graph_height": 670,
    "node_spacing": 150,
    "fit": True,
    "focus_mode": False,
    "focus_depth": 1,
    "selected_classes": [],  # not in _VIZ_PERSIST_KEYS
}


class _FakeLS:
    """Minimal stand-in for the streamlit_local_storage handle."""

    def __init__(self, value=None):
        self._value = value
        self.saved = None
        self.writes: list = []

    def getItem(self, _key):
        return self._value

    def setItem(self, _key, value, key=None):
        self.saved = value
        self.writes.append((value, key))


def test_apply_validates_types_and_clamps_ints(monkeypatch, patch_ui):
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


def test_apply_ignores_non_dict(monkeypatch, patch_ui):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_viz_settings(None, DEFAULTS)
    assert fake == {}


def test_disk_persist_and_restore_roundtrip(monkeypatch, patch_ui, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)

    # Save from one "session" — a user change lifts the gate.
    save_state: dict = {
        "_viz_settings_dirty": True,
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


def test_persist_requires_a_user_change(monkeypatch, patch_ui, tmp_path):
    # Merely rendering the page (no change) must not write anything, so a cloud
    # reload can't overwrite saved settings with the starting defaults (P1).
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(app.st, "session_state", {"_viz_cfg_show_classes": True})
    app._persist_viz_settings()
    assert not cfg_file.exists()


def test_persist_noops_when_unchanged(monkeypatch, patch_ui, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    state: dict = {"_viz_settings_dirty": True, "_viz_cfg_fit": True}
    monkeypatch.setattr(app.st, "session_state", state)
    app._persist_viz_settings()
    first = cfg_file.stat().st_mtime_ns
    app._persist_viz_settings()  # nothing changed
    assert cfg_file.stat().st_mtime_ns == first  # not rewritten


def test_browser_restore_retries_until_real_value(monkeypatch, patch_ui):
    # The localStorage value hasn't arrived yet (getItem returns None). Restore
    # must NOT resolve (it retries next rerun) — otherwise a later save would
    # write defaults over the real saved set before it is read (P1).
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(None))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._restore_viz_settings(DEFAULTS)
    assert "_viz_settings_restored" not in state
    # And with no user change, nothing is persisted regardless.
    app._persist_viz_settings()
    assert "_viz_settings_saved_json" not in state


def test_browser_restore_applies_real_value(monkeypatch, patch_ui):
    val = json.dumps({"show_skos": False, "graph_height": 900})
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(val))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._restore_viz_settings(DEFAULTS)
    assert state["_viz_settings_restored"] is True
    assert state["_viz_cfg_show_skos"] is False
    assert state["_viz_cfg_graph_height"] == 900


def test_browser_dirty_change_is_saved(monkeypatch, patch_ui):
    # A brand-new user (nothing saved) still persists once they change a setting.
    ls = _FakeLS(None)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: ls)
    state: dict = {"_viz_settings_dirty": True, "_viz_cfg_show_skos": False}
    monkeypatch.setattr(app.st, "session_state", state)
    app._persist_viz_settings()
    assert ls.saved is not None
    assert json.loads(ls.saved)["show_skos"] is False


def test_browser_save_is_re_offered_until_a_pass_survives(monkeypatch, patch_ui):
    """A pass that ends in ``st.rerun()`` is discarded along with everything it
    drew, and the browser save is a component render — so a save made on such a
    pass never reaches the browser. Recording it as saved made that permanent:
    the next pass found nothing to do and the setting was gone on reload. It has
    to keep being offered (issue #326 hit this on the toggle's very first use,
    because taking in the queued entities moves the hidden-note count and that
    recompute reruns the page).
    """
    ls = _FakeLS(None)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: ls)
    state: dict = {"_viz_settings_dirty": True, "_viz_cfg_show_skos": False}
    monkeypatch.setattr(app.st, "session_state", state)

    app._persist_viz_settings()
    app._persist_viz_settings()

    assert len(ls.writes) == 2, "the payload was offered once and then dropped"
    # The same component writing the same value, not a queue of writes: the key
    # is the payload's hash, so the browser sees one localStorage entry.
    assert ls.writes[0] == ls.writes[1]


def test_disk_save_still_happens_once(monkeypatch, patch_ui, tmp_path):
    """The disk write is finished by the time it returns, so it keeps its
    no-op — nothing there can discard it."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    state: dict = {"_viz_settings_dirty": True, "_viz_cfg_fit": False}
    monkeypatch.setattr(app.st, "session_state", state)

    app._persist_viz_settings()
    assert state["_viz_settings_saved_json"] == json.dumps({"fit": False})
    first = cfg_file.stat().st_mtime_ns
    app._persist_viz_settings()
    assert cfg_file.stat().st_mtime_ns == first


def test_restore_defers_to_in_progress_changes(monkeypatch, patch_ui):
    # If the user already changed a setting this session, a late restore must not
    # override it.
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(json.dumps({"show_skos": True})))
    state: dict = {"_viz_settings_dirty": True, "_viz_cfg_show_skos": False}
    monkeypatch.setattr(app.st, "session_state", state)
    app._restore_viz_settings(DEFAULTS)
    assert state["_viz_settings_restored"] is True
    assert state["_viz_cfg_show_skos"] is False  # user's change kept

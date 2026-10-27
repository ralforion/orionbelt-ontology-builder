"""The app's text size (issue #387).

Kept where the language packs and the SPARQL editor state are kept: the local
config file on a run that may write to disk, the browser's localStorage on the
cloud, with the same retry and dirty gate (see ``test_sparql_state.py``).

The size is applied in the browser, which reports it back; the page is keyed
by that report, so a new size draws it afresh. The tables are a canvas that
reads the root font size once, when it is drawn, and kept the old size when
the page was not redrawn, or was redrawn before the browser had applied it.
"""

import json

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui


class _FakeLS:
    """Minimal stand-in for the streamlit_local_storage handle."""

    def __init__(self, value=None):
        self._value = value
        self.writes: list = []

    def getItem(self, _key):
        return self._value

    def setItem(self, _key, value, key=None):
        self.writes.append((value, key))


def test_only_an_offered_size_is_applied(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    for stored in (None, "115", 117, True, {"size": 7}, [115]):
        ui._apply_text_size(stored)
    assert state == {}, "a stored value that is not an offered size is ignored"

    ui._apply_text_size({"size": 130})
    assert ui.text_size() == 130


def test_the_size_in_use_falls_back_to_the_default(monkeypatch):
    monkeypatch.setattr(ui.st, "session_state", {ui.TEXT_SIZE_STATE: 117})
    assert ui.text_size() == ui.TEXT_SIZE_DEFAULT


def test_the_root_size_is_a_share_of_streamlits_16px():
    assert ui.text_size_px(100) == 16
    assert ui.text_size_px(130) == 20.8


def test_disk_persist_and_restore_roundtrip(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(ui.local_store, "config_file", lambda: cfg_file)

    state: dict = {ui.TEXT_SIZE_WIDGET: 115}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.text_size_changed()
    ui.persist_text_size()
    assert json.loads(cfg_file.read_text())[ui.TEXT_SIZE_KEY] == {"size": 115}

    restored: dict = {}
    monkeypatch.setattr(ui.st, "session_state", restored)
    ui.restore_text_size()
    assert restored["_text_size_restored"] is True
    assert ui.text_size() == 115


def test_nothing_is_saved_without_a_change(monkeypatch, tmp_path):
    # Opening the app must not write the default over a stored size.
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(ui.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(ui.st, "session_state", {})
    ui.persist_text_size()
    assert not cfg_file.exists()


def test_an_unoffered_pick_changes_nothing(monkeypatch):
    state: dict = {ui.TEXT_SIZE_WIDGET: None}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.text_size_changed()
    assert ui.TEXT_SIZE_STATE not in state
    assert "_text_size_dirty" not in state


def test_browser_restore_waits_for_a_real_value(monkeypatch, patch_ui):
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(None))
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.restore_text_size()
    assert "_text_size_restored" not in state


def test_browser_restore_applies_a_wrapped_value(monkeypatch, patch_ui):
    # The component sometimes hands the value back wrapped in a dict.
    wrapped = {ui.TEXT_SIZE_KEY: json.dumps({"size": 90})}
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(wrapped))
    state: dict = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.restore_text_size()
    assert state["_text_size_restored"] is True
    assert ui.text_size() == 90


def test_browser_save_is_keyed_by_the_size(monkeypatch, patch_ui):
    monkeypatch.setattr(ui.local_store, "local_persist_enabled", lambda: False)
    fake = _FakeLS()
    patch_ui("_get_local_storage", lambda: fake)
    state: dict = {ui.TEXT_SIZE_STATE: 130, "_text_size_dirty": True}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui.persist_text_size()
    assert fake.writes == [('{"size": 130}', "orionbelt_text_size_set_130")]


def test_only_a_reported_size_counts_as_applied(monkeypatch):
    for reported, expected in (
        (None, None),
        ({}, None),
        ({"applied": 117}, None),
        ({"applied": 115}, 115),
    ):
        monkeypatch.setattr(ui.st, "session_state", {ui.TEXT_SIZE_APPLY: reported})
        assert ui.text_size_applied() == expected


def _script():
    from orionbelt_ontology_builder import ui

    ui.render_text_size_sidebar()


def test_a_pick_is_sent_to_the_browser_and_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIONBELT_LOCAL_PERSIST", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    at = AppTest.from_function(_script)
    at.run()
    assert at.sidebar.selectbox(key=ui.TEXT_SIZE_WIDGET).value == 100

    at.sidebar.selectbox(key=ui.TEXT_SIZE_WIDGET).set_value(130).run()

    assert at.session_state[ui.TEXT_SIZE_STATE] == 130
    saved = json.loads(ui.local_store.config_file().read_text())
    assert saved[ui.TEXT_SIZE_KEY] == {"size": 130}
    assert not at.exception

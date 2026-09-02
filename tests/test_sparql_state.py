"""The SPARQL page remembers the query and the editor choice (issue #388).

Both are kept where the viz settings and the language packs are kept: the local
config file on a run that may write to disk, the browser's localStorage on the
cloud. The retry and the dirty gate are the same ones, and they matter for the
same reasons — see ``test_viz_settings.py`` for the fuller story.
"""

import json

from orionbelt_ontology_builder import app


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


def test_apply_validates_types(monkeypatch, patch_ui):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_sparql_state({"query": 12, "plain_editor": "yes"})
    assert fake == {}, "a value of the wrong type is left at its default"

    app._apply_sparql_state({"query": "ASK { ?s ?p ?o }", "plain_editor": True})
    assert fake["sparql_query_text"] == "ASK { ?s ?p ?o }"
    assert fake["_sparql_cfg_plain_editor"] is True


def test_apply_ignores_non_dict(monkeypatch, patch_ui):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_sparql_state(None)
    assert fake == {}


def test_a_stored_query_is_capped(monkeypatch, patch_ui):
    """The store is shared with the ontology's own autosave, so a pasted-in wall
    of SPARQL must not be able to crowd it out."""
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    app._apply_sparql_state({"query": "x" * (app.SPARQL_QUERY_MAX_CHARS + 500)})
    assert len(fake["sparql_query_text"]) == app.SPARQL_QUERY_MAX_CHARS

    fake["sparql_query_text"] = "y" * (app.SPARQL_QUERY_MAX_CHARS + 500)
    payload = json.loads(app._sparql_state_payload())
    assert len(payload["query"]) == app.SPARQL_QUERY_MAX_CHARS


def test_the_limit_ranges_come_from_the_engine():
    """Written out again here, they could outlive a change to either ceiling —
    and a stored value outside its widget's range does not merely read stale, it
    stops the widget rendering at all."""
    from orionbelt_ontology_builder import sparql

    ranges = app._sparql_limit_ranges()
    assert ranges["max_rows"] == (1, sparql.MAX_ROWS_CEILING)
    assert ranges["timeout_seconds"] == (
        int(sparql.MIN_TIMEOUT_SECONDS),
        int(sparql.MAX_TIMEOUT_SECONDS),
    )


def test_a_stored_limit_is_clamped_and_type_checked(monkeypatch, patch_ui):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)
    ranges = app._sparql_limit_ranges()

    app._apply_sparql_state({"max_rows": 10**9, "timeout_seconds": 0})
    assert fake["_sparql_cfg_max_rows"] == ranges["max_rows"][1]
    assert fake["_sparql_cfg_timeout_seconds"] == ranges["timeout_seconds"][0]

    app._apply_sparql_state({"max_rows": "500", "timeout_seconds": True})
    assert fake["_sparql_cfg_max_rows"] == ranges["max_rows"][1], (
        "a string is not a limit"
    )
    assert fake["_sparql_cfg_timeout_seconds"] == ranges["timeout_seconds"][0], (
        "nor is a bool, which Python would otherwise pass off as an int"
    )


def test_disk_persist_and_restore_roundtrip(monkeypatch, patch_ui, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)

    save_state: dict = {
        "_sparql_state_dirty": True,
        "sparql_query_text": "SELECT * WHERE { ?s ?p ?o }",
        "_sparql_cfg_plain_editor": True,
        "_sparql_cfg_max_rows": 25,
        "_sparql_cfg_timeout_seconds": 3,
    }
    monkeypatch.setattr(app.st, "session_state", save_state)
    app.persist_sparql_state()
    stored = json.loads(cfg_file.read_text())["orionbelt_sparql_state"]
    assert stored == {
        "query": "SELECT * WHERE { ?s ?p ?o }",
        "plain_editor": True,
        "max_rows": 25,
        "timeout_seconds": 3,
    }

    restore_state: dict = {}
    monkeypatch.setattr(app.st, "session_state", restore_state)
    app.restore_sparql_state()
    assert restore_state["_sparql_state_restored"] is True
    assert restore_state["sparql_query_text"] == "SELECT * WHERE { ?s ?p ?o }"
    assert restore_state["_sparql_cfg_plain_editor"] is True
    assert restore_state["_sparql_cfg_max_rows"] == 25
    assert restore_state["_sparql_cfg_timeout_seconds"] == 3


def test_persist_requires_a_user_change(monkeypatch, patch_ui, tmp_path):
    # Merely opening the page writes nothing, so a reload cannot overwrite a
    # stored query with the empty one the page starts with.
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(app.st, "session_state", {"sparql_query_text": ""})
    app.persist_sparql_state()
    assert not cfg_file.exists()


def test_persist_noops_when_unchanged(monkeypatch, patch_ui, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    state: dict = {"_sparql_state_dirty": True, "sparql_query_text": "ASK {}"}
    monkeypatch.setattr(app.st, "session_state", state)
    app.persist_sparql_state()
    first = cfg_file.stat().st_mtime_ns
    app.persist_sparql_state()
    assert cfg_file.stat().st_mtime_ns == first


def test_browser_restore_retries_until_real_value(monkeypatch, patch_ui):
    # Nothing has arrived from localStorage yet. Resolving here would let the
    # empty starting query be saved over the stored one.
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(None))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.restore_sparql_state()
    assert "_sparql_state_restored" not in state
    app.persist_sparql_state()
    assert "_sparql_state_saved_json" not in state


def test_browser_restore_applies_real_value(monkeypatch, patch_ui):
    val = json.dumps({"query": "DESCRIBE :Person", "plain_editor": True})
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(val))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.restore_sparql_state()
    assert state["_sparql_state_restored"] is True
    assert state["sparql_query_text"] == "DESCRIBE :Person"
    assert state["_sparql_cfg_plain_editor"] is True


def test_browser_dirty_change_is_saved(monkeypatch, patch_ui):
    # A first-time user has nothing stored, and the retry above never resolves
    # for them: their own change is what lets the first save through.
    ls = _FakeLS(None)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: ls)
    state: dict = {"_sparql_state_dirty": True, "sparql_query_text": "ASK {}"}
    monkeypatch.setattr(app.st, "session_state", state)
    app.persist_sparql_state()
    assert ls.saved is not None
    assert json.loads(ls.saved)["query"] == "ASK {}"


def test_browser_save_is_re_offered_until_a_pass_survives(monkeypatch, patch_ui):
    """The browser save is a component render, and a pass that ends in
    ``st.rerun()`` is discarded along with everything it drew. Recording it as
    saved would make that loss permanent (the reason spelled out in
    ``_persist_viz_settings``)."""
    ls = _FakeLS(None)
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: ls)
    state: dict = {"_sparql_state_dirty": True, "sparql_query_text": "ASK {}"}
    monkeypatch.setattr(app.st, "session_state", state)

    app.persist_sparql_state()
    app.persist_sparql_state()

    assert len(ls.writes) == 2
    # One component writing one value: the key is the payload's hash.
    assert ls.writes[0] == ls.writes[1]


def test_restore_defers_to_in_progress_changes(monkeypatch, patch_ui):
    # The user is already typing. A value that arrives from the browser now must
    # not take the query out from under them.
    val = json.dumps({"query": "DESCRIBE :Person", "plain_editor": True})
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(val))
    state: dict = {"_sparql_state_dirty": True, "sparql_query_text": "ASK {}"}
    monkeypatch.setattr(app.st, "session_state", state)
    app.restore_sparql_state()
    assert state["_sparql_state_restored"] is True
    assert state["sparql_query_text"] == "ASK {}"


def _late_restore(monkeypatch, state, applied):
    """Drive the page's restore with a store that answers only now."""
    from orionbelt_ontology_builder.views import sparql as page

    monkeypatch.setattr(page.st, "session_state", state)
    monkeypatch.setattr(page, "restore_sparql_state", lambda: state.update(applied))
    page._restore_editor_state()
    return page


def test_a_late_restore_reaches_the_editor_already_on_screen(monkeypatch):
    """On the cloud the store answers on a later rerun, by which time the plain
    box is holding its own state — so a restore that wrote only the query would
    show up nowhere, and the empty box would be written back over it."""
    state = {
        "sparql_query_text": "",
        "sparql_query_box": "",  # the plain box has already rendered once
        "sparql_plain_editor": False,  # ...and so has the toggle
    }
    _late_restore(
        monkeypatch,
        state,
        {"sparql_query_text": "ASK {}", "_sparql_cfg_plain_editor": True},
    )
    assert state["sparql_query_box"] == "ASK {}"
    assert state["sparql_plain_editor"] is True, "the toggle follows the choice"
    assert "_sparql_state_dirty" not in state, "what was restored is what is stored"
    assert "sparql_editor_nonce" not in state, "the plain box needs no remount"


def test_a_late_restore_remounts_the_highlighted_editor(monkeypatch):
    """Ace takes ``value`` as initial content and ignores it afterwards, so a
    query that arrives after it mounted needs a fresh instance to show it — the
    same remount picking an example does."""
    state = {"sparql_query_text": "", "sparql_plain_editor": False}
    _late_restore(monkeypatch, state, {"sparql_query_text": "ASK {}"})
    assert state["sparql_editor_nonce"] == 1


def test_a_restore_that_changes_nothing_leaves_the_editors_alone(monkeypatch):
    """The usual case: the store answered before anything was drawn, or it holds
    what is already on screen. Remounting Ace for that would cost a fresh
    component iframe for no change (issue #356)."""
    state = {"sparql_query_text": "ASK {}", "sparql_query_box": "ASK {}"}
    _late_restore(monkeypatch, state, {"sparql_query_text": "ASK {}"})
    assert "sparql_editor_nonce" not in state


def test_a_late_restore_reaches_a_limit_already_on_screen(monkeypatch):
    """The limits are seeded the same way the toggle is, so a value that lands
    after they have rendered has to be written to them as well."""
    state = {"sparql_query_text": "", "sparql_max_rows": 1000, "sparql_timeout": 10}
    _late_restore(monkeypatch, state, {"_sparql_cfg_max_rows": 25})
    assert state["sparql_max_rows"] == 25
    assert state["sparql_timeout"] == 10, "a limit nothing restored is left alone"

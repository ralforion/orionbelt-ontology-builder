"""Tests for disk-backed autosave behaviour (PR #59 review fixes).

These functions live in app.py and read/write ``st.session_state``, so we drive
them with a tiny fake ``st`` and a temp home directory. Covered:

* a failed restore pauses disk writes so an unreadable/corrupt file is never
  overwritten;
* linking to an existing file loads it instead of overwriting it;
* recovery and linked targets use independent hashes, so a failed linked write
  is retried even when the ontology hasn't changed.
"""

import pytest

import orionbelt_ontology_builder.app as app
from orionbelt_ontology_builder import local_store
from ontology_manager import OntologyManager


class _FakeSessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


class _FakeSidebar:
    def warning(self, *a, **k):
        pass


class _FakeSt:
    def __init__(self):
        self.session_state = _FakeSessionState()
        self.sidebar = _FakeSidebar()

    def toast(self, *a, **k):
        pass

    def rerun(self):
        pass


@pytest.fixture
def fake_st(tmp_path, monkeypatch):
    """Patch app.st with a fake and redirect the data dir to a temp home."""
    monkeypatch.setattr(local_store.Path, "home", lambda: tmp_path)
    st = _FakeSt()
    st.session_state.error_log = []  # log_error appends here
    monkeypatch.setattr(app, "st", st)
    local_store.set_linked_path(None)
    return st


def _populated():
    om = OntologyManager()
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatedTo")
    return om


# ---- High: failed restore must pause disk writes -------------------------


def test_restore_corrupt_recovery_blocks_persist(fake_st, tmp_path):
    # A recovery file that exists but doesn't parse.
    local_store.atomic_write(local_store.recovery_file(), "this is not turtle {{{")
    ont = OntologyManager()
    fake_st.session_state.ontology = ont

    app._restore_autosave_from_disk(ont)

    assert fake_st.session_state.get("_disk_persist_blocked") is True

    # Persist must now be a no-op: the corrupt file is left intact.
    before = local_store.read_text(local_store.recovery_file())
    fake_st.session_state.ontology = _populated()
    app._persist_autosave_to_disk()
    assert local_store.read_text(local_store.recovery_file()) == before


def test_restore_unreadable_file_blocks_persist(fake_st, tmp_path, monkeypatch):
    local_store.atomic_write(local_store.recovery_file(), ":A a owl:Class .")
    monkeypatch.setattr(local_store, "read_text", lambda p: None)  # simulate IO error
    ont = OntologyManager()
    fake_st.session_state.ontology = ont

    app._restore_autosave_from_disk(ont)

    assert fake_st.session_state.get("_disk_persist_blocked") is True


# ---- High: linking an existing file loads it, never overwrites ------------


def test_load_linked_file_replaces_working_ontology(fake_st, tmp_path):
    target = tmp_path / "mine.ttl"
    source = _populated()
    local_store.atomic_write(target, source.export_to_string(format="turtle"))

    fake_st.session_state.ontology = OntologyManager()  # empty workspace
    assert app._load_linked_file(target) is True

    loaded = fake_st.session_state.ontology
    assert {c["name"] for c in loaded.get_classes()} == {"A", "B"}
    # The linked hash matches the file, so persist won't immediately rewrite it.
    assert fake_st.session_state.get("_linked_last_hash")


def test_load_linked_file_does_not_overwrite_existing(fake_st, tmp_path):
    """Loading must not clobber the file with the (empty) current graph."""
    target = tmp_path / "mine.ttl"
    original = _populated().export_to_string(format="turtle")
    local_store.atomic_write(target, original)
    local_store.set_linked_path(str(target))

    # Simulate the link-and-load handler outcome, then run a persist pass.
    fake_st.session_state.ontology = OntologyManager()
    assert app._load_linked_file(target) is True
    app._persist_autosave_to_disk()

    # File still holds A and B, not an empty graph.
    reloaded = OntologyManager()
    reloaded.load_from_string(local_store.read_text(target), format="turtle")
    assert {c["name"] for c in reloaded.get_classes()} == {"A", "B"}


# ---- Medium: failed linked write is retried for unchanged content --------


def test_failed_linked_write_retries_when_unchanged(fake_st, tmp_path, monkeypatch):
    linked = tmp_path / "linked.ttl"
    local_store.set_linked_path(str(linked))
    fake_st.session_state.ontology = _populated()

    calls = {"recovery": 0, "linked": 0}
    real_write = local_store.atomic_write

    def flaky_write(path, text):
        if str(path) == str(linked):
            calls["linked"] += 1
            raise OSError("permission denied")
        calls["recovery"] += 1
        real_write(path, text)

    monkeypatch.setattr(local_store, "atomic_write", flaky_write)

    app._persist_autosave_to_disk()  # recovery ok, linked fails
    app._persist_autosave_to_disk()  # content unchanged -> linked retried anyway

    assert calls["linked"] == 2  # retried despite no content change
    assert calls["recovery"] == 1  # recovery deduped after its first success
    assert fake_st.session_state.get("_linked_last_hash") is None  # never recorded


def test_successful_writes_are_deduped(fake_st, tmp_path):
    linked = tmp_path / "linked.ttl"
    local_store.set_linked_path(str(linked))
    fake_st.session_state.ontology = _populated()

    app._persist_autosave_to_disk()
    h1 = fake_st.session_state.get("_linked_last_hash")
    assert h1 and local_store.read_text(linked)

    # Second pass with unchanged content shouldn't error and keeps the hash.
    app._persist_autosave_to_disk()
    assert fake_st.session_state.get("_linked_last_hash") == h1


def test_blocked_persist_writes_nothing(fake_st, tmp_path, monkeypatch):
    fake_st.session_state.ontology = _populated()
    fake_st.session_state["_disk_persist_blocked"] = True
    called = {"n": 0}
    monkeypatch.setattr(
        local_store,
        "atomic_write",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    app._persist_autosave_to_disk()
    assert called["n"] == 0

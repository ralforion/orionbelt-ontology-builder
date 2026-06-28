"""Tests for disk-backed autosave (PR #59) and its large-file reshape.

These functions live in app.py and read/write ``st.session_state``, so we drive
them with a tiny fake ``st`` and a temp home directory. Covered:

* a failed restore pauses disk writes so a bad file is never overwritten;
* linking to an existing file loads it instead of overwriting it;
* mutation-count gating: an unchanged graph does no work on a rerun;
* debounce: dirty edits flush only once settled, and force bypasses it;
* recovery and linked file track save state separately, so a failed linked
  write neither suppresses recovery nor blocks its own retry;
* destination-based serialization and extension-based format detection.
"""

import time

import pytest

import orionbelt_ontology_builder.app as app
from orionbelt_ontology_builder import local_store
from ontology_manager import OntologyManager, rdf_format_for_path


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


def _spy_save(monkeypatch, om):
    """Record (path, format) for each save_to_file call; never touch disk."""
    calls = []
    monkeypatch.setattr(
        type(om),
        "save_to_file",
        lambda self, path, format=None: calls.append((str(path), format)),
    )
    return calls


def _set_state(st, *, mc, recovery=None, linked=None, settled=True):
    st.session_state["_ont_mutation_count"] = mc
    st.session_state["_recovery_saved_rev"] = recovery
    st.session_state["_linked_saved_rev"] = linked
    st.session_state["_autosave_seen_rev"] = mc  # avoid re-stamping
    st.session_state["_autosave_mutated_at"] = 0.0 if settled else time.time()


# ---- format detection / destination serialization ------------------------


def test_rdf_format_for_path():
    assert rdf_format_for_path("x.ttl") == "turtle"
    assert rdf_format_for_path("x.owl") == "xml"
    assert rdf_format_for_path("x.rdf") == "xml"
    assert rdf_format_for_path("x.nt") == "nt"
    assert rdf_format_for_path("x.jsonld") == "json-ld"
    assert rdf_format_for_path("x.unknown") == "turtle"  # default


def test_save_to_file_is_atomic_and_parseable(tmp_path):
    out = tmp_path / "o.ttl"
    _populated().save_to_file(out, "turtle")
    assert out.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["o.ttl"]  # no temp leftover
    reloaded = OntologyManager()
    reloaded.load_from_file(str(out), "turtle")
    assert {c["name"] for c in reloaded.get_classes()} == {"A", "B"}


def test_save_to_file_detects_format_from_extension(tmp_path):
    out = tmp_path / "o.owl"
    _populated().save_to_file(out)  # no format -> xml from .owl
    assert "RDF" in out.read_text(encoding="utf-8")


# ---- mutation-count gating + debounce ------------------------------------


def test_no_work_when_not_dirty(fake_st, monkeypatch):
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=3, recovery=3)  # already saved, no linked
    calls = _spy_save(monkeypatch, om)
    app._persist_autosave_to_disk()
    assert calls == []


def test_debounce_skips_then_flushes(fake_st, monkeypatch):
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, recovery=None, settled=False)
    calls = _spy_save(monkeypatch, om)

    app._persist_autosave_to_disk()
    assert calls == []  # dirty but not settled -> debounced

    fake_st.session_state["_autosave_mutated_at"] = 0.0  # edits settle
    app._persist_autosave_to_disk()
    assert any("recovery" in path for path, _ in calls)
    assert fake_st.session_state["_recovery_saved_rev"] == 1


def test_force_flush_bypasses_debounce(fake_st, monkeypatch):
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, recovery=None, settled=False)
    fake_st.session_state["_force_autosave_flush"] = True
    calls = _spy_save(monkeypatch, om)

    app._persist_autosave_to_disk()
    assert calls  # saved despite not settled
    assert not fake_st.session_state.get("_force_autosave_flush")  # consumed


# ---- one write per change: linked is the store, recovery is a fallback ----


def test_healthy_linked_file_does_not_also_write_recovery(fake_st, tmp_path):
    """With a linked file set, recovery.ttl is not written on every change."""
    linked = tmp_path / "linked.ttl"
    local_store.set_linked_path(str(linked))
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, recovery=None, linked=None, settled=True)

    app._persist_autosave_to_disk()

    assert linked.exists()  # linked written
    assert not local_store.recovery_file().exists()  # recovery NOT written
    assert fake_st.session_state["_linked_saved_rev"] == 1
    assert fake_st.session_state.get("_recovery_saved_rev") is None


def test_linked_failure_falls_back_to_recovery_and_retries(
    fake_st, tmp_path, monkeypatch
):
    linked = tmp_path / "linked.ttl"
    local_store.set_linked_path(str(linked))
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, recovery=None, linked=None, settled=True)

    real_save = type(om).save_to_file

    def flaky(self, path, format=None):
        if str(path) == str(linked):
            raise OSError("permission denied")
        real_save(self, path, format=format)

    monkeypatch.setattr(type(om), "save_to_file", flaky)

    app._persist_autosave_to_disk()
    assert fake_st.session_state["_recovery_saved_rev"] == 1  # recovery succeeded
    assert fake_st.session_state.get("_linked_saved_rev") is None  # not recorded

    # Same revision (no new edit): recovery is deduped, linked is retried.
    fake_st.session_state["_autosave_mutated_at"] = 0.0
    calls = []
    monkeypatch.setattr(
        type(om),
        "save_to_file",
        lambda self, path, format=None: calls.append(str(path)),
    )
    app._persist_autosave_to_disk()
    assert calls == [str(linked)]  # only the linked retry, no recovery rewrite


def test_blocked_persist_writes_nothing(fake_st, monkeypatch):
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, recovery=None, settled=True)
    fake_st.session_state["_disk_persist_blocked"] = True
    fake_st.session_state["_force_autosave_flush"] = True
    calls = _spy_save(monkeypatch, om)
    app._persist_autosave_to_disk()
    assert calls == []


# ---- restore failure pauses persistence ----------------------------------


def test_restore_corrupt_recovery_blocks_persist(fake_st):
    local_store.atomic_write(local_store.recovery_file(), "this is not turtle {{{")
    ont = OntologyManager()
    fake_st.session_state.ontology = ont

    app._restore_autosave_from_disk(ont)
    assert fake_st.session_state.get("_disk_persist_blocked") is True

    # Even a forced flush must not overwrite the file we couldn't load.
    before = local_store.read_text(local_store.recovery_file())
    fake_st.session_state.ontology = _populated()
    fake_st.session_state["_force_autosave_flush"] = True
    _set_state(fake_st, mc=1, recovery=None, settled=True)
    fake_st.session_state["_disk_persist_blocked"] = True
    app._persist_autosave_to_disk()
    assert local_store.read_text(local_store.recovery_file()) == before


# ---- linking an existing file loads it (does not overwrite) ---------------


def test_load_linked_file_replaces_workspace_and_marks_saved(fake_st, tmp_path):
    target = tmp_path / "mine.ttl"
    _populated().save_to_file(target, "turtle")

    fake_st.session_state.ontology = OntologyManager()  # empty workspace
    assert app._load_linked_file(target) is True

    loaded = fake_st.session_state.ontology
    assert {c["name"] for c in loaded.get_classes()} == {"A", "B"}
    mc = fake_st.session_state["_ont_mutation_count"]
    assert fake_st.session_state["_linked_saved_rev"] == mc  # won't be rewritten
    # Recovery is a fallback only; loading a linked file doesn't mark it saved.
    assert fake_st.session_state.get("_recovery_saved_rev") is None


def test_link_load_does_not_overwrite_existing_file(fake_st, tmp_path):
    target = tmp_path / "mine.ttl"
    _populated().save_to_file(target, "turtle")
    local_store.set_linked_path(str(target))

    fake_st.session_state.ontology = OntologyManager()
    assert app._load_linked_file(target) is True
    # Persist pass: linked is already at the current revision, so it isn't
    # rewritten with the (now non-empty, but freshly loaded) graph anyway.
    fake_st.session_state["_autosave_mutated_at"] = 0.0
    app._persist_autosave_to_disk()

    reloaded = OntologyManager()
    reloaded.load_from_file(str(target), "turtle")
    assert {c["name"] for c in reloaded.get_classes()} == {"A", "B"}


# ---- browser localStorage backend uses the same gate ---------------------


class _FakeLS:
    def __init__(self):
        self.items = {}

    def setItem(self, k, v, key=None):
        self.items[k] = v


def _use_fake_ls(monkeypatch):
    ls = _FakeLS()
    monkeypatch.setattr(app, "_get_local_storage", lambda: ls)
    return ls


def test_localstorage_no_serialize_when_not_dirty(fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch)
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=2, settled=True)
    fake_st.session_state["_ls_saved_rev"] = 2  # already saved

    calls = []
    monkeypatch.setattr(
        type(om),
        "export_to_string",
        lambda self, format="turtle": calls.append(1) or "",
    )
    app._persist_autosave_to_localstorage()
    assert calls == []  # not dirty -> never serialized
    assert ls.items == {}


def test_localstorage_oversized_disables_until_mutation(fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch)
    monkeypatch.setattr(app, "AUTOSAVE_MAX_BYTES", 5)  # force "too big"
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, settled=True)

    serialized = []
    real_export = type(om).export_to_string
    monkeypatch.setattr(
        type(om),
        "export_to_string",
        lambda self, format="turtle": (
            serialized.append(1) or real_export(self, format=format)
        ),
    )

    app._persist_autosave_to_localstorage()  # serializes once, finds it too big
    assert fake_st.session_state["_ls_oversized_rev"] == 1
    assert ls.items == {}

    app._persist_autosave_to_localstorage()  # same revision -> no re-serialize
    assert len(serialized) == 1


def test_localstorage_writes_when_dirty_and_settled(fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch)
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, settled=True)

    app._persist_autosave_to_localstorage()
    assert app.AUTOSAVE_KEY in ls.items  # written
    assert fake_st.session_state["_ls_saved_rev"] == 1

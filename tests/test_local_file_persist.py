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
from rdflib import Graph
from rdflib.compare import isomorphic

from ontology_manager import OntologyManager, rdf_format_for_path
from orionbelt_ontology_builder import app, local_store, ui


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
def fake_st(patch_ui, tmp_path, monkeypatch):
    """Patch app.st with a fake and redirect the data dir to a temp home."""
    monkeypatch.setattr(local_store.Path, "home", lambda: tmp_path)
    st = _FakeSt()
    st.session_state.error_log = []  # log_error appends here
    patch_ui("st", st)
    local_store.set_linked_path(None)
    return st


def _populated():
    om = OntologyManager()
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatedTo")
    return om


def _spy_save(monkeypatch, om):
    """Record (path, format) for each save_to_file and save_snapshot call;
    never touch disk."""
    calls = []
    monkeypatch.setattr(
        type(om),
        "save_to_file",
        lambda self, path, format=None: calls.append((str(path), format)),
    )
    monkeypatch.setattr(
        type(om),
        "save_snapshot",
        lambda self, path: calls.append((str(path), "snapshot")),
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


# ---- the recovery snapshot: N-Triples with a prefix header ----------------


def _with_restriction_and_prefix() -> OntologyManager:
    om = _populated()
    om.add_restriction("A", "relatedTo", "someValuesFrom", "B")  # blank nodes
    om.add_prefix("unused", "http://unused.example/ns#")  # Turtle would drop it
    return om


def test_snapshot_round_trip_keeps_triples_and_bindings(tmp_path):
    om = _with_restriction_and_prefix()
    out = tmp_path / "recovery.nt"
    om.save_snapshot(out)
    assert [p.name for p in tmp_path.iterdir()] == ["recovery.nt"]

    reloaded = OntologyManager()
    reloaded.load_snapshot(out)

    assert isomorphic(reloaded.graph, om.graph)
    assert reloaded._store.bindings() == om._store.bindings()
    assert reloaded._user_added_prefixes == {"unused": "http://unused.example/ns#"}
    assert (reloaded.base_uri, reloaded.ontology_uri) == (om.base_uri, om.ontology_uri)


def test_snapshot_is_plain_n_triples(tmp_path):
    om = _with_restriction_and_prefix()
    out = tmp_path / "recovery.nt"
    om.save_snapshot(out)
    assert isomorphic(Graph().parse(str(out), format="nt"), om.graph)


def test_load_snapshot_rejects_a_file_without_the_header(tmp_path):
    out = tmp_path / "recovery.nt"
    out.write_text(_populated().graph.serialize(format="nt"), encoding="utf-8")
    om = _populated()
    with pytest.raises(ValueError, match="not an OrionBelt snapshot"):
        om.load_snapshot(out)
    assert {c["name"] for c in om.get_classes()} == {"A", "B"}  # left as it was


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


# ---- the Turtle recovery file of an earlier release ------------------------


def test_restore_reads_the_legacy_turtle_recovery_then_replaces_it(fake_st):
    legacy = local_store.legacy_recovery_file()
    _populated().save_to_file(legacy, "turtle")
    ont = OntologyManager()
    fake_st.session_state.ontology = ont

    app._restore_autosave_from_disk(ont)
    assert not fake_st.session_state.get("_disk_persist_blocked")
    assert {c["name"] for c in ont.get_classes()} == {"A", "B"}

    # The next write is the new snapshot, which takes the old file's place.
    ont.add_class("C")
    _set_state(fake_st, mc=2, recovery=None, settled=True)
    app._persist_autosave_to_disk()
    assert not legacy.exists()
    restored = OntologyManager()
    restored.load_snapshot(local_store.recovery_file())
    assert {c["name"] for c in restored.get_classes()} == {"A", "B", "C"}


def test_restore_prefers_the_snapshot_over_a_legacy_file(fake_st):
    _populated().save_to_file(local_store.legacy_recovery_file(), "turtle")
    newer = _populated()
    newer.add_class("Newer")
    newer.save_snapshot(local_store.recovery_file())
    ont = OntologyManager()
    fake_st.session_state.ontology = ont

    app._restore_autosave_from_disk(ont)
    assert "Newer" in {c["name"] for c in ont.get_classes()}


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


def _use_fake_ls(monkeypatch, patch_ui):
    ls = _FakeLS()
    patch_ui("_get_local_storage", lambda: ls)
    return ls


def test_localstorage_no_serialize_when_not_dirty(patch_ui, fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch, patch_ui)
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


def test_localstorage_oversized_disables_until_mutation(patch_ui, fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch, patch_ui)
    patch_ui("AUTOSAVE_MAX_BYTES", 5)  # force "too big"
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
    assert fake_st.session_state["_ls_oversized"][1:] == (
        len(om.graph),
        len(om.export_to_string("turtle").encode("utf-8")),
    )
    serialized.clear()
    assert ls.items == {}

    app._persist_autosave_to_localstorage()  # same revision -> no re-serialize
    assert serialized == []


def test_localstorage_oversized_waits_until_the_graph_shrinks(
    patch_ui, fake_st, monkeypatch
):
    """An edit that grows a too-big graph does not pay for another serialize;
    one that shrinks it below the cap at the measured bytes per triple does."""
    ls = _use_fake_ls(monkeypatch, patch_ui)
    om = _populated()
    patch_ui("AUTOSAVE_MAX_BYTES", len(om.export_to_string("turtle").encode()) - 1)
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, settled=True)
    app._persist_autosave_to_localstorage()
    assert fake_st.session_state["_ls_oversized"] is not None

    serialized = []
    real_export = type(om).export_to_string
    monkeypatch.setattr(
        type(om),
        "export_to_string",
        lambda self, format="turtle": (
            serialized.append(1) or real_export(self, format=format)
        ),
    )

    om.add_class("C")
    _set_state(fake_st, mc=2, settled=True)
    app._persist_autosave_to_localstorage()
    assert serialized == []  # bigger still: not serialized again

    om.delete_class("C")
    om.delete_class("B")
    _set_state(fake_st, mc=3, settled=True)
    app._persist_autosave_to_localstorage()
    assert serialized == [1]
    assert app.AUTOSAVE_KEY in ls.items
    assert fake_st.session_state.get("_ls_oversized") is None


def test_localstorage_oversized_estimate_ignores_a_new_graph(
    patch_ui, fake_st, monkeypatch
):
    """A load replaces the graph, whose triples may be of another size."""
    _use_fake_ls(monkeypatch, patch_ui)
    om = _populated()
    fake_st.session_state.ontology = om
    fake_st.session_state["_ls_oversized"] = (str(om.graph.identifier), 1, 10**9)
    assert ui._still_too_big_for_localstorage(om)
    om.load_from_string(_populated().export_to_string("turtle"))
    assert not ui._still_too_big_for_localstorage(om)


def test_localstorage_writes_when_dirty_and_settled(patch_ui, fake_st, monkeypatch):
    ls = _use_fake_ls(monkeypatch, patch_ui)
    om = _populated()
    fake_st.session_state.ontology = om
    _set_state(fake_st, mc=1, settled=True)

    app._persist_autosave_to_localstorage()
    assert app.AUTOSAVE_KEY in ls.items  # written
    assert fake_st.session_state["_ls_saved_rev"] == 1


# ---- autosave is best-effort and never crashes the app (issue #121) -------


def test_persist_autosave_swallows_unexpected_disk_error(
    patch_ui, fake_st, monkeypatch
):
    """A non-OSError escaping the disk backend must not propagate; it is logged
    and disk autosave is paused so it isn't retried (issue #121)."""
    monkeypatch.setattr(local_store, "local_persist_enabled", lambda: True)
    fake_st.session_state["_autosave_restored"] = True

    def _boom():
        raise ValueError("serialization blew up")

    patch_ui("_persist_autosave_to_disk", _boom)

    app.persist_autosave()  # must not raise

    assert fake_st.session_state.get("_disk_persist_blocked") is True
    assert fake_st.session_state.error_log  # the cause was logged


def test_link_flush_with_bad_write_does_not_crash(fake_st, tmp_path, monkeypatch):
    """Linking forces an immediate flush; a non-OSError on that write is caught
    and pauses autosave rather than stopping the app (issue #121)."""
    monkeypatch.setattr(local_store, "local_persist_enabled", lambda: True)
    linked = tmp_path / "linked.ttl"
    local_store.set_linked_path(str(linked))
    om = _populated()
    fake_st.session_state.ontology = om
    fake_st.session_state["_autosave_restored"] = True
    _set_state(fake_st, mc=1, recovery=None, linked=None, settled=True)
    fake_st.session_state["_force_autosave_flush"] = True

    def bad_save(self, path, format=None):
        raise ValueError("rdflib serialize failed")

    monkeypatch.setattr(type(om), "save_to_file", bad_save)

    app.persist_autosave()  # must not raise

    assert fake_st.session_state.get("_disk_persist_blocked") is True
    assert fake_st.session_state["_linked_saved_rev"] is None  # never recorded
    assert fake_st.session_state.error_log

"""Tests for the local-filesystem persistence helpers."""

import json

import pytest

from orionbelt_ontology_builder import local_store


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` to a temp dir so tests never touch the real home."""
    monkeypatch.setattr(local_store.Path, "home", lambda: tmp_path)
    return tmp_path


def test_persist_disabled_by_default(monkeypatch):
    """Without the env flag (the cloud case) disk persistence stays off."""
    monkeypatch.delenv(local_store.ENV_FLAG, raising=False)
    assert local_store.local_persist_enabled() is False


@pytest.mark.parametrize("value", ["", "0", "false", "False"])
def test_persist_disabled_for_falsey_flag(monkeypatch, value):
    monkeypatch.setenv(local_store.ENV_FLAG, value)
    assert local_store.local_persist_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_persist_enabled_for_truthy_flag(monkeypatch, value):
    monkeypatch.setenv(local_store.ENV_FLAG, value)
    assert local_store.local_persist_enabled() is True


def test_data_dir_and_recovery_path(home):
    assert local_store.data_dir() == home / ".orionbelt_ontology_builder"
    assert local_store.data_dir().is_dir()
    assert local_store.recovery_file() == local_store.data_dir() / "recovery.ttl"


def test_atomic_write_roundtrip(home):
    target = home / "sub" / "ont.ttl"
    local_store.atomic_write(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"
    # No stray temp files left behind in the directory.
    assert [p.name for p in target.parent.iterdir()] == ["ont.ttl"]


def test_atomic_write_leaves_no_partial_file_on_failure(home, monkeypatch):
    target = home / "ont.ttl"
    target.write_text("original", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(local_store.os, "replace", _boom)
    with pytest.raises(OSError):
        local_store.atomic_write(target, "new content")

    # Original file is untouched and no temp file remains.
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in target.parent.iterdir()] == ["ont.ttl"]


def test_read_text_missing_returns_none(home):
    assert local_store.read_text(home / "nope.ttl") is None


def test_config_roundtrip(home):
    assert local_store.load_config() == {}
    local_store.save_config({"linked_path": "/tmp/x.ttl", "n": 1})
    assert local_store.load_config() == {"linked_path": "/tmp/x.ttl", "n": 1}
    # Written as readable JSON.
    assert json.loads(local_store.config_file().read_text(encoding="utf-8"))["n"] == 1


def test_load_config_handles_corrupt_file(home):
    local_store.config_file().write_text("{not json", encoding="utf-8")
    assert local_store.load_config() == {}


def test_linked_path_set_get_clear(home):
    assert local_store.get_linked_path() is None

    local_store.set_linked_path("/data/backup/my.ttl")
    assert local_store.get_linked_path() == local_store.Path("/data/backup/my.ttl")

    local_store.set_linked_path(None)
    assert local_store.get_linked_path() is None


def test_set_linked_path_preserves_other_config(home):
    local_store.save_config({"other": "keep"})
    local_store.set_linked_path("/x.ttl")
    config = local_store.load_config()
    assert config["other"] == "keep"
    assert config["linked_path"] == "/x.ttl"


def test_get_linked_path_expands_user(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    local_store.set_linked_path("~/backup.ttl")
    assert local_store.get_linked_path() == home / "backup.ttl"

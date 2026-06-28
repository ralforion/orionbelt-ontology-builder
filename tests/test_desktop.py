"""Tests for the native desktop launcher (``orionbelt-ontology-builder-desktop``)."""

import os
import sys
import types
from importlib.metadata import entry_points

import pytest

import orionbelt_ontology_builder.desktop as desktop
from orionbelt_ontology_builder.app import APP_NAME
from orionbelt_ontology_builder.local_store import BRAND_PRIMARY_COLOR, ENV_FLAG


def test_entry_point_registered():
    """The console_scripts entry point should map to ``desktop:run``."""
    eps = [
        ep
        for ep in entry_points(group="console_scripts")
        if ep.name == "orionbelt-ontology-builder-desktop"
    ]
    assert eps, "orionbelt-ontology-builder-desktop console script not registered"
    assert eps[0].value == "orionbelt_ontology_builder.desktop:run"


def test_run_invokes_start_desktop_app(monkeypatch, tmp_path):
    """``run()`` should open the in-package entry script in a native window."""
    captured = {}

    def _fake_start_desktop_app(**kwargs):
        captured.update(kwargs)

    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = _fake_start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    # pywebview ships only with the optional desktop extra, so stub it out to
    # keep this test runnable without that extra installed.
    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    # Keep the persistent-storage setup off the real home directory.
    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert captured["script_path"].endswith("streamlit_entry.py")
    assert captured["title"] == APP_NAME
    # A native launch runs locally, so disk-backed persistence is opted in.
    assert os.environ[ENV_FLAG] == "1"
    # Brand colour passed as an explicit Streamlit option (not via env) so it
    # applies in the subprocess regardless of CWD.
    assert captured["options"]["theme.primaryColor"] == BRAND_PRIMARY_COLOR


def test_run_enables_persistent_webview_storage(monkeypatch, tmp_path):
    """The launcher should make pywebview persist localStorage across launches.

    streamlit_desktop_app calls ``webview.start()`` with no arguments, which
    defaults to private mode and wipes the saved Streamlit theme on close
    (issue #70). ``run()`` should inject a persistent ``storage_path`` and
    disable private mode, then restore the original ``webview.start``.
    """
    captured = {}

    fake_webview = types.ModuleType("webview")

    def _record_start(*args, **kwargs):
        captured.update(kwargs)

    fake_webview.start = _record_start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    fake_sda = types.ModuleType("streamlit_desktop_app")

    def _start_desktop_app(**kwargs):
        # The real library starts pywebview with no storage arguments.
        import webview

        webview.start()

    fake_sda.start_desktop_app = _start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_sda)

    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert captured["private_mode"] is False
    assert captured["storage_path"] == str(tmp_path / "webview")
    assert (tmp_path / "webview").is_dir()
    # The wrapper must not leak: the original start is restored afterwards.
    assert fake_webview.start is _record_start


def test_run_without_dependency_exits_cleanly(monkeypatch):
    """Missing the optional ``desktop`` extra should exit non-zero, not crash."""
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", None)

    with pytest.raises(SystemExit) as excinfo:
        desktop.run()

    assert excinfo.value.code == 1

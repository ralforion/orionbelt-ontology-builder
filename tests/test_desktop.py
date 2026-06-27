"""Tests for the native desktop launcher (``orionbelt-ontology-builder-desktop``)."""

import sys
import types
from importlib.metadata import entry_points

import pytest

import orionbelt_ontology_builder.desktop as desktop
from orionbelt_ontology_builder.app import APP_NAME


def test_entry_point_registered():
    """The console_scripts entry point should map to ``desktop:run``."""
    eps = [
        ep
        for ep in entry_points(group="console_scripts")
        if ep.name == "orionbelt-ontology-builder-desktop"
    ]
    assert eps, "orionbelt-ontology-builder-desktop console script not registered"
    assert eps[0].value == "orionbelt_ontology_builder.desktop:run"


def test_run_invokes_start_desktop_app(monkeypatch):
    """``run()`` should open the in-package entry script in a native window."""
    captured = {}

    def _fake_start_desktop_app(**kwargs):
        captured.update(kwargs)

    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = _fake_start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    desktop.run()

    assert captured["script_path"].endswith("streamlit_entry.py")
    assert captured["title"] == APP_NAME


def test_run_without_dependency_exits_cleanly(monkeypatch):
    """Missing the optional ``desktop`` extra should exit non-zero, not crash."""
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", None)

    with pytest.raises(SystemExit) as excinfo:
        desktop.run()

    assert excinfo.value.code == 1

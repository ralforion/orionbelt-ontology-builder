"""Tests for the console entry point (``orionbelt-ontology-builder``)."""

import os
import sys
from importlib.metadata import entry_points
from pathlib import Path

import orionbelt_ontology_builder.cli as cli
from orionbelt_ontology_builder.local_store import BRAND_PRIMARY_COLOR, ENV_FLAG


def test_entry_point_registered():
    """The console_scripts entry point should map to ``cli:run``."""
    eps = [
        ep
        for ep in entry_points(group="console_scripts")
        if ep.name == "orionbelt-ontology-builder"
    ]
    assert eps, "orionbelt-ontology-builder console script not registered"
    assert eps[0].value == "orionbelt_ontology_builder.cli:run"


def test_streamlit_entry_file_exists():
    """The launcher targets an in-package Streamlit entry script."""
    entry = Path(cli.__file__).parent / "streamlit_entry.py"
    assert entry.is_file()


def test_run_invokes_streamlit_with_entry_and_forwards_args(monkeypatch):
    """``run()`` should call ``streamlit run <entry>`` and forward extra args."""
    captured = {}

    class _FakeStcli:
        @staticmethod
        def main():
            captured["argv"] = list(sys.argv)

    import streamlit.web

    monkeypatch.setattr(streamlit.web, "cli", _FakeStcli, raising=False)
    monkeypatch.setattr(
        sys, "argv", ["orionbelt-ontology-builder", "--server.port", "8502"]
    )
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    cli.run()

    argv = captured["argv"]
    assert argv[:2] == ["streamlit", "run"]
    assert argv[2].endswith("streamlit_entry.py")
    assert argv[-2:] == ["--server.port", "8502"]


def test_run_opts_into_persistence_and_brand_theme(monkeypatch):
    """A local launch enables disk persistence and passes the brand colour."""
    monkeypatch.delenv(ENV_FLAG, raising=False)
    captured = {}

    class _FakeStcli:
        @staticmethod
        def main():
            captured["argv"] = list(sys.argv)

    import streamlit.web

    monkeypatch.setattr(streamlit.web, "cli", _FakeStcli, raising=False)
    monkeypatch.setattr(sys, "argv", ["orionbelt-ontology-builder"])
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    cli.run()

    assert os.environ[ENV_FLAG] == "1"
    # Brand colour passed as an explicit flag so config.toml isn't needed.
    assert f"--theme.primaryColor={BRAND_PRIMARY_COLOR}" in captured["argv"]


def test_run_reapplies_saved_theme_base(monkeypatch):
    """A saved light/dark preference is forwarded as --theme.base (issue #70)."""
    captured = {}

    class _FakeStcli:
        @staticmethod
        def main():
            captured["argv"] = list(sys.argv)

    import streamlit.web

    monkeypatch.setattr(streamlit.web, "cli", _FakeStcli, raising=False)
    monkeypatch.setattr(cli, "get_theme_base", lambda: "dark")
    monkeypatch.setattr(sys, "argv", ["orionbelt-ontology-builder"])
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    cli.run()

    assert "--theme.base=dark" in captured["argv"]


def test_run_omits_theme_base_when_unset(monkeypatch):
    captured = {}

    class _FakeStcli:
        @staticmethod
        def main():
            captured["argv"] = list(sys.argv)

    import streamlit.web

    monkeypatch.setattr(streamlit.web, "cli", _FakeStcli, raising=False)
    monkeypatch.setattr(cli, "get_theme_base", lambda: None)
    monkeypatch.setattr(sys, "argv", ["orionbelt-ontology-builder"])
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    cli.run()

    assert not any(a.startswith("--theme.base") for a in captured["argv"])

"""Settings from a ``.env`` file, for the launcher and the MCP server."""

import os
import re
import sys
from pathlib import Path

import pytest

from orionbelt_ontology_builder import env_file

# Taken before conftest's autouse fixture swaps it out for every test.
from orionbelt_ontology_builder.env_file import env_files as real_env_files

EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_parse_reads_simple_shell_assignments():
    text = """
# a comment
ORIONBELT_API=1
export ORIONBELT_API_PORT = 9000
ORIONBELT_API_HOST=127.0.0.1  # where it listens
ORIONBELT_API_TOKEN="se#cret value"
ORIONBELT_API_URL='http://h:1/#x'
not an assignment
# ORIONBELT_MCP_HTTP=1
1BAD=x
EMPTY=
"""
    assert env_file.parse(text) == {
        "ORIONBELT_API": "1",
        "ORIONBELT_API_PORT": "9000",
        "ORIONBELT_API_HOST": "127.0.0.1",
        "ORIONBELT_API_TOKEN": "se#cret value",
        "ORIONBELT_API_URL": "http://h:1/#x",
        "EMPTY": "",
    }


def test_environment_then_first_file_then_second(monkeypatch, tmp_path):
    for name in ("ORIONBELT_API_PORT", "ORIONBELT_API_HOST", "ORIONBELT_API"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORIONBELT_API_TOKEN", "from-the-environment")
    monkeypatch.delenv("PYTHONSOMETHING", raising=False)
    here = tmp_path / "here.env"
    here.write_text("ORIONBELT_API_PORT=9001\nORIONBELT_API_TOKEN=from-a-file\n")
    home = tmp_path / "home.env"
    home.write_text(
        "ORIONBELT_API_PORT=9002\nORIONBELT_API_HOST=0.0.0.0\n"
        "ORIONBELT_API=yes\nPYTHONSOMETHING=1\n"
    )

    read = env_file.load([here, tmp_path / "missing.env", home])

    assert read == [here, home]
    assert os.environ["ORIONBELT_API_TOKEN"] == "from-the-environment"
    assert os.environ["ORIONBELT_API_PORT"] == "9001"
    assert os.environ["ORIONBELT_API_HOST"] == "0.0.0.0"
    assert env_file.flag("ORIONBELT_API")
    assert "PYTHONSOMETHING" not in os.environ  # only ORIONBELT_* / STREAMLIT_*


def test_files_are_the_start_directory_then_the_app_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    here, home = real_env_files()
    assert here == tmp_path / ".env"
    assert home == Path.home() / ".orionbelt_ontology_builder" / ".env"


def test_launcher_flags_win_over_the_file(monkeypatch, tmp_path):
    from orionbelt_ontology_builder import cli
    from orionbelt_ontology_builder.api.server import ENV_ENABLE, ENV_HOST, ENV_PORT

    for name in (ENV_ENABLE, ENV_HOST, ENV_PORT):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ORIONBELT_API=1\nORIONBELT_API_PORT=9000\nORIONBELT_API_HOST=h\n"
    )
    monkeypatch.setattr(env_file, "env_files", lambda: [dotenv])

    class _FakeStcli:
        @staticmethod
        def main():
            return 0

    import streamlit.web

    monkeypatch.setattr(streamlit.web, "cli", _FakeStcli, raising=False)
    monkeypatch.setattr(sys, "argv", ["orionbelt-ontology-builder", "--api-port=9100"])
    monkeypatch.setattr(sys, "exit", lambda code=0: None)

    cli.run()

    assert os.environ[ENV_PORT] == "9100"  # the flag
    assert os.environ[ENV_HOST] == "h"  # the file
    assert env_file.flag(ENV_ENABLE)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ("streamable-http", "0.0.0.0", 9900)),
        (["--port", "9999"], ("streamable-http", "0.0.0.0", 9999)),
    ],
)
def test_mcp_server_flags_come_from_the_file(monkeypatch, tmp_path, argv, expected):
    from orionbelt_ontology_builder import mcp_server

    for name in ("ORIONBELT_MCP_HTTP", "ORIONBELT_MCP_HOST", "ORIONBELT_MCP_PORT"):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ORIONBELT_MCP_HTTP=1\nORIONBELT_MCP_HOST=0.0.0.0\nORIONBELT_MCP_PORT=9900\n"
    )
    monkeypatch.setattr(env_file, "env_files", lambda: [dotenv])
    ran = []
    monkeypatch.setattr(
        mcp_server.mcp,
        "run",
        lambda transport, **kw: ran.append((transport, kw["host"], kw["port"])),
    )

    mcp_server.run(argv)

    assert ran == [expected]


def test_the_example_lists_every_setting_and_no_other():
    """``.env.example`` is the one list of settings; keep it complete."""
    from orionbelt_ontology_builder import mcp_server
    from orionbelt_ontology_builder.api import server

    in_code = {
        value
        for module in (server, mcp_server)
        for name, value in vars(module).items()
        if name.startswith("ENV_") and isinstance(value, str)
    }
    listed = set(
        re.findall(r"^#?\s*(ORIONBELT_\w+)=", EXAMPLE.read_text(), re.MULTILINE)
    )
    assert listed == in_code

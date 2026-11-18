"""Settings from a ``.env`` file, for the console launcher and the MCP server.

Every setting they read from the environment can also go in a ``.env`` file,
one ``NAME=value`` per line (``.env.example`` lists them all):

* ``./.env``, in the directory the command is started from, then
* ``~/.orionbelt_ontology_builder/.env``, which applies to every start.

A variable already set in the environment wins over both files, the first file
over the second, and a command-line flag over all of them. Only ``ORIONBELT_*``
and ``STREAMLIT_*`` names are taken, so another project's ``.env`` in the same
directory leaks nothing else into the app, or into the worker processes that
inherit its environment.

The hosted app runs ``streamlit run app.py``, which reads no ``.env``, so a
file there can never turn its API on.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from .local_store import _DIR_NAME

#: The names a ``.env`` may set.
PREFIXES = ("ORIONBELT_", "STREAMLIT_")

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INLINE_COMMENT = re.compile(r"\s+#")


def env_files() -> list[Path]:
    """Where a ``.env`` is looked for, the one that wins first."""
    files = []
    try:
        files.append(Path.cwd() / ".env")
    except OSError:  # started from a directory that no longer exists
        pass
    files.append(Path.home() / _DIR_NAME / ".env")
    return files


def parse(text: str) -> dict[str, str]:
    """``NAME=value`` lines, as a shell would read the simple ones.

    Blank lines and ``#`` comments are skipped, as is anything that is not an
    assignment. ``export`` in front is allowed. A value in single or double
    quotes is taken as written; an unquoted one ends at a ``#`` after a space.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not _NAME.fullmatch(name):
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = _INLINE_COMMENT.split(value, maxsplit=1)[0]
        values[name] = value
    return values


def load(files: Iterable[Path] | None = None) -> list[Path]:
    """Set what the files say wherever the environment has nothing yet.

    Returns the files that were read.
    """
    read = []
    for path in env_files() if files is None else files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        read.append(path)
        for name, value in parse(text).items():
            if name.startswith(PREFIXES):
                os.environ.setdefault(name, value)
    return read


def flag(name: str) -> bool:
    """Whether the variable ``name`` is set to a yes (``1``, ``true``, ...)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

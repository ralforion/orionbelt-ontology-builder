"""Guards that the version is in sync across the places that declare it.

A 1.9.3 release shipped with ``pyproject.toml`` at 1.9.3 but ``APP_VERSION``
left at 1.9.2 (the bump was edited but never staged), so the package reported
the wrong version at runtime (issue #74). These tests fail CI on any such drift.
"""

import re
from pathlib import Path

from orionbelt_ontology_builder.app import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "(.+?)"', text, re.MULTILINE)
    assert match, "could not find version in pyproject.toml"
    return match.group(1)


def test_app_version_matches_pyproject():
    assert APP_VERSION == _pyproject_version(), (
        "APP_VERSION in app.py is out of sync with pyproject.toml "
        f"({APP_VERSION!r} != {_pyproject_version()!r})"
    )


def test_readme_badge_matches_pyproject():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    version = _pyproject_version()
    assert f"version-{version}-" in readme, (
        "README version badge is out of sync with pyproject.toml "
        f"(expected version-{version}-)"
    )

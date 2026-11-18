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


def test_readme_pin_hint_matches_pyproject():
    # The version badge is now a dynamic PyPI badge (auto-updates), so the only
    # hardcoded version left in the README is the Docker image pin example.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    version = _pyproject_version()
    assert f"`:{version}`" in readme, (
        "README Docker pin hint is out of sync with pyproject.toml "
        f"(expected `:{version}`)"
    )


def test_changelog_has_the_version_as_its_newest_release():
    """A release names its version in CHANGELOG.md, under ``[Unreleased]``.

    The GitHub release notes are that entry, so a bump without one would
    publish a release with nothing to say.
    """
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[(.+?)\]", changelog, re.MULTILINE)
    assert headings[:1] == ["Unreleased"], "CHANGELOG.md opens with [Unreleased]"
    assert headings[1:2] == [_pyproject_version()], (
        "the newest release in CHANGELOG.md is not pyproject.toml's version "
        f"({headings[1:2]} != {[_pyproject_version()]})"
    )

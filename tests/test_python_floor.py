"""The advertised Python floor is the one CI actually tests.

`requires-python` used to say 3.10 while the matrix tested only 3.12 and 3.14,
so two of the five advertised versions were never exercised. Nothing caught it:
mypy is pinned to 3.12, and ruff does not reject newer syntax under an older
target, so 3.12-only code (a PEP 701 nested-quote f-string, say) type-checked
and linted clean while being a SyntaxError on the floor we claimed.

These read the three places the floor is written down and fail if they drift.
"""

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _floor() -> tuple[int, int]:
    """The (major, minor) in ``requires-python``."""
    spec = PYPROJECT["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec.strip())
    assert match, f"expected a simple >=X.Y floor, got {spec!r}"
    return int(match[1]), int(match[2])


def _matrix() -> list[tuple[int, int]]:
    """The interpreters the check job runs, from the workflow matrix."""
    match = re.search(r"^\s*python:\s*\[(.+?)\]\s*$", CI, re.MULTILINE)
    assert match, "could not find the `python:` matrix in ci.yml"
    found = re.findall(r"(\d+)\.(\d+)", match[1])
    assert found, f"no versions in matrix line {match[1]!r}"
    return sorted((int(a), int(b)) for a, b in found)


def test_the_floor_is_in_the_ci_matrix():
    """Otherwise the oldest supported version is never run."""
    floor, matrix = _floor(), _matrix()
    listed = ", ".join(f"{major}.{minor}" for major, minor in matrix)
    assert floor in matrix, (
        f"requires-python floor {floor[0]}.{floor[1]} is not in the CI matrix "
        f"({listed}): either test it or raise the floor"
    )


def test_the_floor_is_the_oldest_version_tested():
    """A matrix leg below the floor tests a version we do not support."""
    assert _floor() == _matrix()[0]


def test_mypy_targets_the_floor():
    """Pinned above the floor, mypy green-lights code the floor cannot run."""
    floor = _floor()
    configured = PYPROJECT["tool"]["mypy"]["python_version"]
    assert configured == f"{floor[0]}.{floor[1]}", (
        f"mypy python_version is {configured!r} but the floor is {floor[0]}.{floor[1]}"
    )


def test_classifiers_start_at_the_floor():
    """A classifier below the floor advertises a version pip would refuse."""
    floor = _floor()
    pattern = re.compile(r"Programming Language :: Python :: (\d+)\.(\d+)")
    matches = (pattern.fullmatch(c) for c in PYPROJECT["project"]["classifiers"])
    versions = sorted((int(m[1]), int(m[2])) for m in matches if m is not None)
    assert versions, "no versioned Python classifiers found"
    assert versions[0] == floor


def test_the_readme_badge_matches_the_floor():
    floor = _floor()
    assert f"python-{floor[0]}.{floor[1]}+-blue" in README, (
        f"README badge does not advertise {floor[0]}.{floor[1]}+"
    )

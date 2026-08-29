"""Every third-party work we redistribute ships its licence text.

The wheel carries a vendored copy of vis-network and seven third-party
vocabularies. Redistributing them means carrying their terms, and the terms are
no use to a recipient if they stay on the developer's disk: these assertions are
about what the *package* contains, not about what is in the repository.

The gap this guards was real. Tom Select shipped under Apache-2.0 with no licence
file anywhere until the dead-vendored-libs cleanup removed it, and the sample
ontologies shipped with no terms at all while gist and gUFO, alone, carried
theirs.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "orionbelt_ontology_builder"
NOTICES = REPO / "THIRD_PARTY_NOTICES.md"

#: Licence texts that must be present and non-empty, and the marker that shows
#: the file is the licence rather than a stub.
LICENCES = {
    "MIT-vis-network.txt": "The MIT License",
    "CC-BY-1.0.txt": "Creative Commons",
    "CC-BY-3.0.txt": "Creative Commons",
    "W3C-Document-License.txt": "W3C Document License",
}

#: Third-party files that ship, mapped to how the notices refer to them and the
#: licence they are attributed to. The reference is given rather than derived
#: from the filename because gist ships four files under one glob entry, and
#: spelling all four out in the notices would be noise.
BUNDLED = {
    "samples/foaf.rdf": ("foaf.rdf", "CC BY 1.0"),
    "samples/goodrelations.owl": ("goodrelations.owl", "CC BY 3.0"),
    "samples/pizza.owl": ("pizza.owl", "CC BY 3.0"),
    "samples/prov-o.ttl": ("prov-o.ttl", "W3C Document License"),
    "samples/wine.owl": ("wine.owl", "W3C Document License"),
    "samples/gist/gistCore14.1.0.ttl": ("samples/gist/", "CC BY 4.0"),
    "samples/gufo/gufo.ttl": ("gufo.ttl", "CC BY 4.0"),
    "lib/graph_viewer/vis-network.min.js": ("vis-network.min.js", "MIT"),
}


def test_every_licence_text_is_present():
    for name, marker in LICENCES.items():
        path = PKG / "licenses" / name
        assert path.is_file(), f"{name} is missing"
        assert marker in path.read_text(encoding="utf-8"), (
            f"{name} is not the licence text"
        )


def test_gist_and_gufo_keep_their_own_licence_files():
    """Those two carry their text beside the data, which is where a reader of
    the sample looks first. Kept that way rather than moved into licenses/."""
    for vocab in ("gist", "gufo"):
        assert (PKG / "samples" / vocab / "LICENSE-CC-BY-4.0.txt").is_file()


def test_every_bundled_third_party_file_is_accounted_for():
    """A file shipped but not named in the notices is one being redistributed
    with no stated terms, which is the thing this whole exercise was about."""
    notices = NOTICES.read_text(encoding="utf-8")
    for rel, (reference, licence) in BUNDLED.items():
        assert (PKG / rel).is_file(), f"{rel} is gone; update the notices too"
        assert reference in notices, (
            f"{rel} ships but is not named in THIRD_PARTY_NOTICES.md"
        )
        assert licence in notices, f"{licence} is not stated in THIRD_PARTY_NOTICES.md"


def _build_wheel(out_dir: Path) -> Path | None:
    """Build a wheel into ``out_dir``, or None when no builder is available.

    Takes about half a second. Worth it: the thing being asserted is what the
    *artifact* contains, and every cheaper proxy for that has already been wrong
    once. MANIFEST.in governs the sdist only, so listing the notices there left
    the wheel without them while a config-reading test stayed green.
    """
    for argv in (
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
    ):
        try:
            done = subprocess.run(
                argv, cwd=REPO, capture_output=True, timeout=300, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            wheels = list(out_dir.glob("*.whl"))
            if wheels:
                return wheels[0]
    return None


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory) -> list[str]:
    wheel = _build_wheel(tmp_path_factory.mktemp("dist"))
    if wheel is None:
        pytest.skip("no wheel builder available (uv or build)")
    with zipfile.ZipFile(wheel) as zf:
        return zf.namelist()


def test_the_project_declares_the_right_spdx_licence(wheel_names, tmp_path_factory):
    """BUSL-1.1 is the Business Source License 1.1. BSL-1.0 is the Boost Software
    License, and BSL-1.1 is not an SPDX identifier at all, so the value this used
    to carry named nothing while looking like it named Boost. Asserted on the
    built metadata rather than on pyproject.toml, because what a consumer reads
    is the METADATA."""
    wheel = next(iter(tmp_path_factory.getbasetemp().glob("**/*.whl")))
    with zipfile.ZipFile(wheel) as zf:
        meta = zf.read(
            next(n for n in zf.namelist() if n.endswith("METADATA"))
        ).decode()
    assert "License-Expression: BUSL-1.1" in meta, (
        "the wheel does not declare BUSL-1.1 as an SPDX expression"
    )
    assert "Classifier: License ::" not in meta, (
        "a License classifier alongside a PEP 639 expression is rejected by PyPI"
    )


def test_the_notices_reach_the_wheel(wheel_names):
    """The licence texts inside the package point at THIRD_PARTY_NOTICES.md for
    the map from file to licence. Shipping them without it leaves that pointer
    dangling for anyone who installs the wheel, which is everyone."""
    assert any(n.endswith("THIRD_PARTY_NOTICES.md") for n in wheel_names), (
        "THIRD_PARTY_NOTICES.md is not in the wheel"
    )


def test_every_licence_text_reaches_the_wheel(wheel_names):
    for name in LICENCES:
        assert any(n.endswith(f"licenses/{name}") for n in wheel_names), (
            f"{name} is not in the wheel"
        )
    for vocab in ("gist", "gufo"):
        assert any(
            n.endswith(f"samples/{vocab}/LICENSE-CC-BY-4.0.txt") for n in wheel_names
        ), f"{vocab}'s licence is not in the wheel"


def test_every_covered_file_reaches_the_wheel(wheel_names):
    """A licence carried for a file that no longer ships is stale; a file that
    ships without one is the problem this guards."""
    for rel in BUNDLED:
        assert any(n.endswith(rel) for n in wheel_names), f"{rel} is not in the wheel"

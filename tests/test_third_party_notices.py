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

import re
from pathlib import Path

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


def test_the_licence_texts_are_packaged():
    """package-data decides what reaches the wheel, and a licence that does not
    ship is not carried with the work it covers."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    package_data = re.search(
        r"\[tool\.setuptools\.package-data\](.*?)(?:\n\[|\Z)", pyproject, re.DOTALL
    )
    assert package_data, "package-data section not found"
    assert '"licenses/*"' in package_data.group(1), (
        "licenses/ is not in package-data, so the texts would not reach the wheel"
    )
    assert "include THIRD_PARTY_NOTICES.md" in (REPO / "MANIFEST.in").read_text(
        encoding="utf-8"
    )

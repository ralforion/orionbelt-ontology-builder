"""The BUSL parameter block must not go stale.

The Licensed Work used to name a version ("OrionBelt Ontology Builder 0.8"),
which nothing bumped, so the licence named a release from long before the code
it shipped with. The Change Date here is a single fixed date rather than one per
version, so the licence covers every version and says so instead of pinning one.
"""

import re
from pathlib import Path

_LICENSE = Path(__file__).resolve().parent.parent / "LICENSE"


def test_the_licensed_work_is_not_pinned_to_a_version():
    """A version here is a number no release bumps. Name the work, not a build."""
    text = _LICENSE.read_text()
    assert "Licensed Work:        OrionBelt Ontology Builder, all versions" in text
    assert not re.search(r"OrionBelt Ontology Builder,? v?\d", text)


def test_the_copyright_runs_from_the_first_year():
    """A range, so a later year is added rather than replacing 2025."""
    assert re.search(
        r"The Licensed Work is \(c\) 2025-20\d\d RALFORION d\.o\.o\.",
        _LICENSE.read_text(),
    )


def test_the_conversion_parameters_are_still_there():
    text = _LICENSE.read_text()
    assert "Change Date:          2030-03-30" in text
    assert "Change License:       Apache License, Version 2.0" in text

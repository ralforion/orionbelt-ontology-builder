"""Where the UI source lives, for the tests that read it rather than run it.

``app.py`` was split into ``ui.py``, a ``views`` package and the shell, so a
test that names one file scans a fraction of the UI and passes on the rest by
accident. These helpers follow the code instead: a module counts as UI if it
imports streamlit, which covers a page added tomorrow without anyone
remembering to update a list.
"""

import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder"


def ui_sources() -> list[pathlib.Path]:
    """Every module that draws UI, deepest first for stable output."""
    return sorted(
        p for p in PKG.rglob("*.py") if "import streamlit" in p.read_text("utf-8")
    )


def ui_text() -> str:
    """All of the UI source as one string, for plain substring checks."""
    return "\n".join(p.read_text("utf-8") for p in ui_sources())


def viz_text() -> str:
    """The Visualization page and the helpers it renders through."""
    return "\n".join(
        (PKG / name).read_text("utf-8") for name in ("views/visualization.py", "ui.py")
    )

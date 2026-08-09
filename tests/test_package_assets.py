"""The package's own files resolve from wherever the code lives.

Splitting app.py into a ``pages`` package broke the graph: the component
directory was resolved from ``__file__``, which had become
``pages/lib/graph_viewer``. Every test passed — none of them renders the custom
component, and an import cannot notice a path that is only built at render time.

So the paths are asserted directly. They are anchored to the package, not to the
module that happens to use them, and this is what says so.
"""

import pathlib

from orionbelt_ontology_builder import ui

ASSETS = [
    pathlib.Path("lib/graph_viewer/index.html"),
    pathlib.Path("lib/graph_viewer/vis-network.min.js"),
    pathlib.Path("favicon.png"),
    pathlib.Path("assets/ORIONBELT_Logo.png"),
    pathlib.Path("assets/ORIONBELT Logo w.png"),
    pathlib.Path("samples"),
]


def test_the_package_anchor_is_the_package():
    assert ui.PKG_DIR.name == "orionbelt_ontology_builder"
    assert (ui.PKG_DIR / "app.py").is_file()


def test_every_bundled_asset_resolves():
    missing = [str(rel) for rel in ASSETS if not (ui.PKG_DIR / rel).exists()]
    assert not missing, f"not found under {ui.PKG_DIR}: {missing}"


def test_no_ui_module_builds_an_asset_path_from_its_own_file():
    """``__file__`` here is the module, which moves; the package does not."""
    import sources

    offenders = []
    for path in sources.ui_sources():
        for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if (
                "__file__" in line
                and "PKG_DIR" not in line
                and not line.lstrip().startswith("#")
            ):
                offenders.append(f"{path.name}:{lineno} {line.strip()}")
    assert not offenders, (
        "asset paths must hang off ui.PKG_DIR, not the module using them:\n  "
        + "\n  ".join(offenders)
    )

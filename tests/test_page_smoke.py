"""Every page and every sub-tab renders at least once.

Splitting app.py moved six ``from .templates import ...`` and
``from .ontology_manager import ...`` statements into a subpackage, where the
single dot resolves one level too shallow. Nothing noticed: they sit inside tab
branches, so importing the module cannot reach them, and the suite never
rendered those tabs. Templates, Upper and Reference Ontologies, New Ontology and
Clear Ontology would all have raised on first use (PR #262 review P1).

So each tab is rendered here. It asserts only that rendering does not raise —
what each one *does* belongs in the focused tests — because a page that raises
is a blank panel with a traceback, and that is the floor worth holding.

The tab picker is a ``segmented_control``, which AppTest mis-serializes, so the
tab is chosen by seeding its session key, the way the pages' own tests do. The
list of tabs is read off the source rather than written out, so a tab added
later is covered without anyone remembering.
"""

import ast
import os
import pathlib

import pytest
import sources
from streamlit.testing.v1 import AppTest

PAGES = pathlib.Path(sources.PKG) / "views"


def _tabs_by_page() -> dict[str, tuple[str, list[str]]]:
    """``{module: (session key, [tab, ...])}`` for every page that has tabs."""
    found: dict[str, tuple[str, list[str]]] = {}
    for path in sorted(PAGES.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr != "segmented_control":
                continue
            key = next(
                (
                    k.value.value
                    for k in node.keywords
                    if k.arg == "key" and isinstance(k.value, ast.Constant)
                ),
                None,
            )
            options = node.args[1] if len(node.args) > 1 else None
            values = None
            if isinstance(options, ast.List):
                values = [e.value for e in options.elts if isinstance(e, ast.Constant)]
            elif isinstance(options, ast.Name):
                for assign in ast.walk(tree):
                    if (
                        isinstance(assign, ast.Assign)
                        and isinstance(assign.value, ast.List)
                        and any(
                            isinstance(t, ast.Name) and t.id == options.id
                            for t in assign.targets
                        )
                    ):
                        values = [
                            e.value
                            for e in assign.value.elts
                            if isinstance(e, ast.Constant)
                        ]
            if isinstance(key, str) and values:
                found[path.stem] = (key, [str(v) for v in values])
    return found


TABS = _tabs_by_page()
PAGE_FUNCTIONS = {
    "dashboard": "render_dashboard",
    "classes": "render_classes",
    "properties": "render_properties",
    "individuals": "render_individuals",
    "relations": "render_relations",
    "restrictions": "render_restrictions",
    "advanced": "render_advanced",
    "annotations": "render_annotations",
    "skos": "render_skos_vocabulary",
    "import_export": "render_import_export",
    "source": "render_source",
    "sparql": "render_sparql",
    "validation": "render_validation",
}
CASES = [
    (module, tab)
    for module in PAGE_FUNCTIONS
    for tab in (TABS[module][1] if module in TABS else [""])
]


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle")
        om.add_class("Wheel")
        om.add_class("Tandem", parent="Bicycle")
        om.add_object_property("hasPart", domain="Bicycle", range_="Wheel")
        om.add_data_property("serial", domain="Bicycle")
        om.add_individual("bike1", "Bicycle")
        om.add_class_relation("Bicycle", "disjointWith", "Wheel")
        om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
        om.add_annotation("Bicycle", "rdfs:comment", "two wheels", lang="en")
        om.add_concept_scheme("Parts")
        om.add_concept("Frame", scheme="Parts")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session restore mounts the localStorage component, which
        # blocks forever without a browser to answer it.
        st.session_state["_viz_settings_restored"] = True

    tab_key, tab = os.environ["SMOKE_TAB"].split("|", 1)
    if tab_key:
        st.session_state[tab_key] = tab
    getattr(app, os.environ["SMOKE_PAGE"])()


@pytest.mark.parametrize(
    ("module", "tab"), CASES, ids=[f"{m}:{t or 'page'}" for m, t in CASES]
)
def test_the_tab_renders(module, tab):
    os.environ["SMOKE_PAGE"] = PAGE_FUNCTIONS[module]
    os.environ["SMOKE_TAB"] = f"{TABS[module][0] if tab else ''}|{tab}"

    at = AppTest.from_function(_script)
    at.run(timeout=120)

    assert not at.exception, at.exception


def test_the_tab_list_was_actually_found():
    """The cases are read off the source, so an empty read would make every
    test above pass by rendering nothing."""
    assert TABS["import_export"][1][0] == "Import"
    assert len(CASES) > 30, len(CASES)

"""The Visualization page renders under awkward setting combinations.

Every display toggle, the node filters and focus mode are persisted separately,
so they can disagree: a session comes back with focus on and nothing focusable,
with every entity type off, or with seeds pointing at a class that has since
been deleted. Each combination takes a different branch through
``render_visualization``, and several of those branches leave variables the code
below them reads — which is how a persisted-settings pair took the whole page
down with an ``UnboundLocalError`` (PR #261 review P1).

A crash here is a blank page with a traceback, not a degraded graph, so this
sweeps the combinations that a real session can arrive in and asserts only that
the page renders. Behaviour belongs in the focused tests; this is the guard that
the next thing wired into this function trips over in CI rather than in review.

One AppTest per case, deliberately: AppTest cannot run this page twice in a
single script run.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest


def _script():
    import json
    import os

    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        if os.environ["VIZ_MATRIX_ONTOLOGY"] == "full":
            for name in ("Bicycle", "Wheel", "Engine"):
                om.add_class(name)
            om.add_class("Tandem", parent="Bicycle")
            om.add_object_property("hasPart")
            om.add_data_property("serial", domain="Bicycle")
            om.add_individual("bike1", "Bicycle")
            om.add_class_relation("Bicycle", "disjointWith", "Engine")
            om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
            om.add_annotation("Bicycle", "rdfs:comment", "two wheels", lang="en")
            om.add_concept_scheme("Parts")
            om.add_concept("Frame", scheme="Parts")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session restore mounts the localStorage component, which
        # blocks forever without a browser to answer it.
        st.session_state["_viz_settings_restored"] = True
        for key, value in json.loads(os.environ["VIZ_MATRIX_SETTINGS"]).items():
            if value == "__all__":
                value = {c["uri"] for c in om.get_classes()}
            st.session_state[f"_viz_cfg_{key}"] = value

    from orionbelt_ontology_builder import app

    app.render_visualization()


ALL_TYPES_OFF = {
    "show_classes": False,
    "show_obj_props": False,
    "show_data_props": False,
    "show_annotations": False,
    "show_individuals": False,
    "show_skos": False,
    "show_ind_edges": False,
    "show_triples": False,
}
EVERYTHING_ON = {k: True for k in ALL_TYPES_OFF}

CASES = {
    "defaults": ({}, "full"),
    "every type on": (EVERYTHING_ON, "full"),
    "every type off": (ALL_TYPES_OFF, "full"),
    # The P1: focus mode survives its persisted partner being switched off.
    "focus with nothing focusable": ({**ALL_TYPES_OFF, "focus_mode": True}, "full"),
    "focus with no seeds": ({"focus_mode": True, "focus_seeds": []}, "full"),
    "focus on a class that is gone": (
        {"focus_mode": True, "focus_seeds": ["Class: Deleted"]},
        "full",
    ),
    "focus at full depth": (
        {"focus_mode": True, "focus_seeds": ["Class: Bicycle"], "focus_depth": 5},
        "full",
    ),
    # An emptied filter is not the same as an unset one: nothing is "new", so it
    # stays empty and every per-kind loop is skipped. "__all__" is expanded to
    # the ontology's class URIs in the script — the session stores that as a set,
    # which JSON cannot carry.
    "node filter emptied": (
        {"selected_class_uris": [], "known_class_uris": "__all__"},
        "full",
    ),
    "fixed height, no fit": ({"fit": False, "graph_height": 300}, "full"),
    "highlight issues": ({"highlight_issues": True}, "full"),
    "status bar instead of the panel": ({"details_panel": False}, "full"),
    "options collapsed": ({"options_open": False}, "full"),
    # Nothing to draw at all, which is its own set of early returns.
    "empty ontology": ({}, "empty"),
    "empty ontology, focus on": ({"focus_mode": True}, "empty"),
}


@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
def test_the_page_renders(case):
    settings, ontology = CASES[case]
    os.environ["VIZ_MATRIX_SETTINGS"] = json.dumps(settings)
    os.environ["VIZ_MATRIX_ONTOLOGY"] = ontology

    at = AppTest.from_function(_script)
    at.run(timeout=120)

    assert not at.exception, at.exception

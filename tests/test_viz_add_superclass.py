"""Adding a class *above* the selected one, from the graph (issue #327).

The panel could only ever grow a hierarchy downwards: everything it creates
hangs under the class you clicked. Realising a level is missing above one is
just as ordinary, and doing it meant leaving the graph, adding the class on the
Classes page and coming back to re-parent the first one.

What the new class does to the parents the selected class already has was the
open question, and the reporter answered it: nothing. It is added alongside
them, the way "Add subclass" writes one ``rdfs:subClassOf`` and rewires nothing.
Moving a class from one parent to another is a different act.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://example.org/ontology#"


@pytest.fixture
def ont():
    om = OntologyManager()
    om.add_class("Vehicle")
    om.add_class("Bicycle", parent="Vehicle")
    return om


def _parents(om, name):
    return sorted(next(c["parents"] for c in om.get_classes() if c["name"] == name))


# --- what the write does ----------------------------------------------------


def test_the_new_class_joins_the_parents_the_class_already_had(ont):
    """The reporter's answer: alongside, not spliced in between."""
    ont.add_class("WheeledThing")
    ont.update_class(NS + "Bicycle", new_parent="WheeledThing")

    assert _parents(ont, "Bicycle") == ["Vehicle", "WheeledThing"]
    # And nothing was moved under the new class but the one that was selected.
    assert _parents(ont, "WheeledThing") == []


def test_a_class_with_no_parent_simply_gains_one(ont):
    """Where the two readings of "add a superclass" agree."""
    ont.add_class("Machine")
    ont.update_class(NS + "Vehicle", new_parent="Machine")
    assert _parents(ont, "Vehicle") == ["Machine"]


# --- what the form is given -------------------------------------------------


def test_the_child_is_not_offered_as_the_new_class_s_own_parent(ont):
    """Otherwise one dropdown makes a cycle: the class about to become the new
    one's child, picked as its parent."""
    classes = ont.get_classes()
    kept = [c for c in classes if c["uri"] != NS + "Bicycle"]
    options, lookup = ui.build_class_options(kept, include_none=True)

    assert not any(lookup.get(o) == NS + "Bicycle" for o in options)
    assert any(lookup.get(o) == NS + "Vehicle" for o in options), "the rest remain"


def test_the_form_takes_the_write_before_the_checkpoint():
    """Creating the class and hanging the old one under it is one action, so it
    is one entry in the undo history: the hook runs before save_checkpoint."""
    import inspect

    src = inspect.getsource(ui.render_add_class_form)
    assert "after_add(name)" in src
    assert src.index("after_add(name)") < src.index("save_checkpoint(")


# --- and through the page ---------------------------------------------------


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    ns = "http://example.org/ontology#"
    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Vehicle")
        om.add_class("Bicycle", parent="Vehicle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["_viz_cfg_details_panel"] = True
        st.session_state["_viz_last_selection"] = {
            "selected": True,
            "ntype": "Class",
            "ename": app._uid(ns + "Bicycle"),
            "label": "Bicycle",
            "flabel": "Bicycle",
            "title": "Class: Bicycle",
        }
        if os.environ.get("OPEN_SUPERCLASS") == "1":
            st.session_state["_viz_add_kind"] = "super"
    app.render_visualization()


def test_the_panel_offers_the_button_with_a_class_selected():
    os.environ["OPEN_SUPERCLASS"] = "0"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    assert any(b.key == "panel_add_open_super" for b in at.button), [
        b.key for b in at.button
    ]


def test_the_form_says_what_it_will_do():
    os.environ["OPEN_SUPERCLASS"] = "1"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    said = " ".join(m.value for m in at.markdown) + " ".join(
        c.value for c in at.caption
    )
    assert "New superclass of Bicycle" in said, said
    assert "keeps the parents it has" in said, said

"""The Triples layer draws what nothing else draws.

"Show all RDF triples for visible nodes" used to mean *all* of them, including
the ones the graph was already showing: `rdfs:subClassOf` came out twice, once
as the green class-hierarchy edge and again as a grey triple edge beside it, and
`rdf:type` the same. The layer now skips a triple whose edge is already on the
canvas.

Read off the edges that were built rather than from a list of predicates, so it
follows what is actually drawn: with Classes switched off nothing else draws the
hierarchy, and the triple is the only thing left to show it.
"""

import json
import os

from streamlit.testing.v1 import AppTest


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Organization")
        om.add_class("Department", parent="Organization")
        # A raw triple between the same two classes that no layer draws: same
        # pair, different predicate.
        from rdflib import URIRef

        om.graph.add(
            (
                URIRef(om.namespace + "Department"),
                URIRef(om.namespace + "reportsTo"),
                URIRef(om.namespace + "Organization"),
            )
        )
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["_viz_cfg_show_triples"] = os.environ["TRIPLES"] == "1"
        st.session_state["_viz_cfg_show_classes"] = os.environ["CLASSES"] == "1"
    app.render_visualization()


def _edges(triples=True, classes=True):
    os.environ["TRIPLES"] = "1" if triples else "0"
    os.environ["CLASSES"] = "1" if classes else "0"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    nodes = {n["id"]: n.get("label") for n in json.loads(data["nodes"])}
    return [
        (nodes.get(e["from"]), nodes.get(e["to"]), e.get("label"))
        for e in json.loads(data["edges"])
    ]


def _subclass(edges):
    return [e for e in edges if e[2] == "subClassOf"]


def test_the_hierarchy_edge_is_drawn_once_without_the_triples_layer():
    """The baseline: one axiom, one edge."""
    assert _subclass(_edges(triples=False)) == [
        ("Department", "Organization", "subClassOf")
    ]


def test_the_triples_layer_does_not_draw_it_a_second_time():
    """The report: with Triples on it used to come out twice, the same pair and
    the same label, once green and once grey."""
    assert _subclass(_edges(triples=True)) == [
        ("Department", "Organization", "subClassOf")
    ]


def test_the_triples_layer_still_draws_what_nothing_else_does():
    """It is not simply suppressing subClassOf: the type and label triples that
    no other layer draws are still there."""
    labels = {e[2] for e in _edges(triples=True)}
    assert "type" in labels, labels


def test_a_different_predicate_between_the_same_pair_is_still_drawn():
    """The guard is (from, to, label), not (from, to): a triple that says
    something else about the same two classes is not what is already on screen,
    and is drawn."""
    edges = _edges(triples=True)
    pair = [e for e in edges if e[0] == "Department" and e[1] == "Organization"]
    labels = sorted(label for _, _, label in pair)

    assert labels == ["reportsTo", "subClassOf"], labels


def test_the_docstring_rule_is_what_the_code_does():
    """Read off the edges already built rather than from a list of predicates,
    so the layer follows what is on screen rather than a guess about it."""
    import inspect

    from orionbelt_ontology_builder.views import visualization

    src = inspect.getsource(visualization.render_visualization)
    assert "_already_drawn = {" in src
    assert 'edge.get("label")' in src, "keyed by the label the edge draws"

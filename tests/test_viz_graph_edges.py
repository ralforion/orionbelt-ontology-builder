"""Every graph edge must connect two nodes the builder emitted (issue #200).

The builder does not validate edge endpoints — an edge naming a node that was
never added is silently dropped by vis-network, so a relation just fails to
draw with nothing in the logs. Annotation and raw-triple edges for classes and
individuals were built from local names while the nodes are keyed by a URI
hash, so none of them ever drew.

These run the real ``render_visualization`` through ``AppTest`` and inspect the
graph payload it caches, seeded through the environment because
``AppTest.from_function`` executes the script source in a fresh namespace
without the test's closures.
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_prefix("other", "http://other.example.org/ns#")

        om.add_class("Person", comment="A person")
        om.add_class("Employee", parent="Person")
        om.add_class("Organization")
        # Same local name in a second namespace: node ids are URI-keyed, so
        # anything built from the local name points at the wrong node or none.
        om.add_class("Person", namespace="http://other.example.org/ns#")

        om.add_object_property("worksFor", domain="Person", range_="Organization")
        om.add_data_property("age", domain="Person", range_="integer")

        om.add_individual("alice", "Person")
        om.add_individual("acme", "Organization")
        om.add_individual_property("alice", "worksFor", "acme")

        om.add_annotation("Person", "seeAlso", "http://example.org/person-docs")
        om.add_annotation("alice", "seeAlso", "http://example.org/alice")

        om.add_concept("Widget", pref_label="Widget")
        om.add_concept("Gadget", broader="Widget")

        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done.
        st.session_state["_viz_settings_restored"] = True

        # Turn everything on so every edge-building branch runs.
        for key in (
            "show_classes",
            "show_obj_props",
            "show_data_props",
            "show_annotations",
            "show_individuals",
            "show_ind_edges",
            "show_skos",
            "show_triples",
        ):
            st.session_state[f"_viz_cfg_{key}"] = True

        if os.environ.get("HIDE_CLASSES"):
            hidden = set(os.environ["HIDE_CLASSES"].split(","))
            entries = app.build_class_filter_entries(om.get_classes())
            st.session_state["_viz_cfg_selected_class_uris"] = [
                e["uri"] for e in entries if e["display"] not in hidden
            ]
            st.session_state["_viz_cfg_known_class_uris"] = {e["uri"] for e in entries}
            st.session_state["_viz_cfg_seen_mutation"] = st.session_state.get(
                "_ont_mutation_count", 0
            )

    app.render_visualization()


def _graph(hide_classes=None):
    """Render the visualization once and return its (nodes, edges)."""
    os.environ["HIDE_CLASSES"] = ",".join(hide_classes or [])
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    data = at.session_state["last_graph_data"]
    assert data, "the visualization built no graph"
    return json.loads(data["nodes"]), json.loads(data["edges"])


def _dangling(nodes, edges):
    ids = {n["id"] for n in nodes}
    return [
        (e["from"], e["to"])
        for e in edges
        if e["from"] not in ids or e["to"] not in ids
    ]


@pytest.fixture(scope="module")
def graph():
    return _graph()


def test_the_graph_has_nodes_and_edges(graph):
    nodes, edges = graph
    assert len(nodes) > 5 and len(edges) > 5


def test_no_edge_points_at_a_missing_node(graph):
    nodes, edges = graph
    assert _dangling(nodes, edges) == []


def test_annotation_edges_hang_off_their_subject(graph):
    nodes, edges = graph
    by_id = {n["id"]: n for n in nodes}
    ann_ids = {n["id"] for n in nodes if n["id"].startswith("ann_")}
    assert ann_ids
    # Every annotation node is reachable, which none were while the edge named
    # the subject's local name instead of its node id.
    assert {e["to"] for e in edges if e["to"] in ann_ids} == ann_ids
    sources = [by_id[e["from"]] for e in edges if e["to"] in ann_ids]
    assert {s.get("ntype") for s in sources} == {"Class", "Individual"}
    # Only one class carries an annotation: they are looked up by URI, so the
    # second class named Person does not inherit the first one's.
    assert sum(1 for s in sources if s.get("ntype") == "Class") == 1


def test_individual_object_property_edge_is_drawn(graph):
    nodes, edges = graph
    ind_ids = {n["id"] for n in nodes if n["id"].startswith("ind_")}
    assert len(ind_ids) == 2
    assert any(
        e["from"] in ind_ids and e["to"] in ind_ids and e.get("label") == "worksFor"
        for e in edges
    )


def test_hiding_a_class_leaves_no_dangling_edges():
    # The class filter removes nodes that annotation, triple and property edges
    # would otherwise still reference.
    nodes, edges = _graph(hide_classes=["Person", "Organization"])
    assert _dangling(nodes, edges) == []


def test_hiding_one_of_two_same_named_classes_keeps_the_other_linked():
    nodes, edges = _graph(hide_classes=["Person (other)"])
    assert _dangling(nodes, edges) == []
    # Exactly one of the two Person nodes survives, with its subclass edge and
    # its annotation still attached.
    persons = [
        n
        for n in nodes
        if n.get("ntype") == "Class" and str(n.get("label", "")).startswith("Person")
    ]
    assert len(persons) == 1
    person_id = persons[0]["id"]
    assert any(e["to"] == person_id and e.get("label") == "subClassOf" for e in edges)
    assert any(e["from"] == person_id and e["to"].startswith("ann_") for e in edges)

"""Tests for the shortest-path search between two entities (issue #176)."""

import pytest

from ontology_manager import PATH_EDGE_KINDS, OntologyManager, bfs_path
from orionbelt_ontology_builder.ui import (
    path_chain_text,
    path_edge_kinds,
    path_highlight,
    path_nodes,
)

BASE = "http://test.org/ont#"


def cls(name):
    return ("class", f"{BASE}{name}")


def ind(name):
    return ("individual", f"{BASE}{name}")


@pytest.fixture
def path_om():
    """A graph whose entities are reachable by several different link kinds."""
    m = OntologyManager(base_uri=BASE)
    m.add_class("Agent")
    m.add_class("Person", parent="Agent")
    m.add_class("Organization", parent="Agent")
    m.add_class("Rock")
    m.add_object_property("worksFor", domain="Person", range_="Organization")
    m.add_individual("alice", "Person")
    m.add_individual("acme", "Organization")
    return m


# ---- the engine ---------------------------------------------------------


def test_finds_the_shortest_chain_of_subclass_links(path_om):
    hops = path_om.find_shortest_path(
        cls("Person"), cls("Organization"), kinds=("subclass",)
    )
    assert [h["relation"] for h in hops] == ["subClassOf", "subClassOf"]
    assert [h["target"] for h in hops] == [cls("Agent"), cls("Organization")]


def test_a_link_walked_against_its_direction_is_marked_as_such(path_om):
    hops = path_om.find_shortest_path(
        cls("Person"), cls("Organization"), kinds=("subclass",)
    )
    # Person subClassOf Agent is asserted from Person's side; Agent to
    # Organization is the same link read backwards.
    assert [h["forward"] for h in hops] == [True, False]


def test_an_object_property_is_a_shorter_route_than_the_hierarchy(path_om):
    # Two classes joined both by a shared parent and by a property's
    # domain/range: the property gets there in one hop, so that is the answer.
    assert [
        h["relation"]
        for h in path_om.find_shortest_path(cls("Person"), cls("Organization"))
    ] == ["worksFor"]
    assert (
        len(
            path_om.find_shortest_path(
                cls("Person"), cls("Organization"), kinds=("subclass",)
            )
        )
        == 2
    )


def test_no_path_between_disconnected_entities(path_om):
    assert path_om.find_shortest_path(cls("Person"), cls("Rock")) is None


def test_an_entity_reached_only_by_an_excluded_link_kind_is_unreachable(path_om):
    assert (
        path_om.find_shortest_path(cls("Person"), cls("Organization"), kinds=("skos",))
        is None
    )


def test_the_same_entity_twice_is_a_path_of_no_hops(path_om):
    assert path_om.find_shortest_path(cls("Person"), cls("Person")) == []


def test_an_unknown_entity_has_no_path(path_om):
    assert path_om.find_shortest_path(cls("Person"), cls("Nonexistent")) is None


def test_individuals_reach_each_other_through_their_classes(path_om):
    hops = path_om.find_shortest_path(ind("alice"), ind("acme"))
    assert [h["target"] for h in hops] == [
        cls("Person"),
        cls("Organization"),
        ind("acme"),
    ]
    assert [h["relation"] for h in hops] == ["type", "worksFor", "type"]


def test_an_asserted_relation_between_individuals_is_the_shorter_route(path_om):
    path_om.add_individual_property("alice", "worksFor", "acme")
    hops = path_om.find_shortest_path(ind("alice"), ind("acme"))
    assert [h["relation"] for h in hops] == ["worksFor"]


def test_skos_concepts_connect_through_broader(skos_om):
    hops = skos_om.find_shortest_path(("concept", "Dog"), ("concept", "Cat"))
    assert [h["relation"] for h in hops] == ["broader", "broader"]
    assert [h["target"] for h in hops] == [("concept", "Animal"), ("concept", "Cat")]


def test_restrictions_link_the_classes_they_are_applied_to(om):
    om.add_class("Wheel")
    om.add_class("Car")
    om.add_class("Boat")
    om.add_restriction("Car", "hasPart", "someValuesFrom", "Wheel")
    om.add_restriction("Boat", "hasPart", "someValuesFrom", "Wheel")
    src = ("class", str(om._uri("Car")))
    dst = ("class", str(om._uri("Boat")))
    hops = om.find_shortest_path(src, dst, kinds=("restrictions",))
    assert [h["relation"] for h in hops] == ["hasPart", "hasPart"]


def test_the_adjacency_is_undirected(path_om):
    adjacency = path_om.build_path_graph()
    assert cls("Agent") in adjacency[cls("Person")]
    assert cls("Person") in adjacency[cls("Agent")]


def test_a_search_that_settles_too_many_nodes_gives_up(path_om):
    # Reachable in two subclass hops, but not within a one-node budget.
    assert (
        path_om.find_shortest_path(
            cls("Person"), cls("Organization"), kinds=("subclass",), max_visited=1
        )
        is None
    )


def test_bfs_is_stable_when_several_routes_are_equally_short():
    # Two routes of the same length from a to d. Sorted neighbours make the
    # answer the same every time rather than whichever order the dict held.
    adjacency = {
        "a": {"b": ("via", True), "c": ("via", True)},
        "b": {"a": ("via", False), "d": ("via", True)},
        "c": {"a": ("via", False), "d": ("via", True)},
        "d": {"b": ("via", False), "c": ("via", False)},
    }
    first = bfs_path(adjacency, "a", "d")
    assert [h["target"] for h in first] == ["b", "d"]
    assert bfs_path(dict(reversed(list(adjacency.items()))), "a", "d") == first


def test_every_declared_edge_kind_builds_an_adjacency(path_om):
    # A kind naming something build_path_graph does not handle would silently
    # walk nothing, and the page would report "no path" for a link on screen.
    for kind in PATH_EDGE_KINDS:
        assert isinstance(path_om.build_path_graph(kinds=(kind,)), dict)


# ---- the page helpers ---------------------------------------------------


def test_edge_kinds_follow_the_display_toggles():
    everything = path_edge_kinds(True, True, True, True, True)
    assert set(everything) == set(PATH_EDGE_KINDS)
    assert path_edge_kinds(False, True, False, False, False) == ()
    assert path_edge_kinds(True, False, False, False, False) == (
        "subclass",
        "class_relations",
    )


def test_object_property_links_need_the_classes_they_join():
    # The canvas only draws a domain/range edge between two class nodes, so a
    # path must not be allowed to walk one when classes are switched off.
    assert "object_properties" not in path_edge_kinds(False, True, True, True, True)


def test_individual_links_need_their_own_toggles():
    assert "individual_relations" not in path_edge_kinds(True, True, True, False, True)
    assert "individual_types" not in path_edge_kinds(True, True, False, True, True)


def test_highlight_covers_the_path_nodes_and_the_links_between_them(path_om):
    src = cls("Person")
    hops = path_om.find_shortest_path(src, cls("Organization"), kinds=("subclass",))
    ids, pairs = path_highlight(hops, src)
    assert len(ids) == 3
    assert pairs == {frozenset(ids[:2]), frozenset(ids[1:])}


def test_a_path_to_the_same_entity_highlights_one_node_and_no_links():
    ids, pairs = path_highlight([], cls("Person"))
    assert len(ids) == 1
    assert pairs == set()


def test_the_chain_reads_each_link_in_the_direction_it_was_asserted(path_om):
    src = cls("Person")
    hops = path_om.find_shortest_path(src, cls("Organization"), kinds=("subclass",))
    labels = {
        cls("Person"): "Class: Person",
        cls("Agent"): "Class: Agent",
        cls("Organization"): "Class: Organization",
    }
    assert path_chain_text(hops, src, labels) == (
        "Class: Person —subClassOf→ Class: Agent ←subClassOf— Class: Organization"
    )


def test_the_chain_falls_back_to_the_reference_for_an_unlabelled_entity(path_om):
    src = cls("Person")
    hops = path_om.find_shortest_path(src, cls("Organization"), kinds=("subclass",))
    assert f"{BASE}Agent" in path_chain_text(hops, src, {})


def test_a_path_of_no_hops_is_still_named(path_om):
    assert path_chain_text([], cls("Person"), {cls("Person"): "Class: Person"}) == (
        "Class: Person"
    )


def test_path_nodes_start_at_the_source(path_om):
    src = cls("Person")
    hops = path_om.find_shortest_path(src, cls("Organization"), kinds=("subclass",))
    assert path_nodes(hops, src)[0] == src
    assert path_nodes([], src) == [src]

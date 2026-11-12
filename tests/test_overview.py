"""The dashboard's overview of an ontology (``overview.py``)."""

from collections import Counter
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Literal, Namespace, URIRef

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.overview import _ranked, ontology_overview

SAMPLES = Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder" / "samples"
NS = Namespace("http://test.org/o#")


def _load(name: str, fmt: str) -> OntologyManager:
    om = OntologyManager()
    om.load_from_file(str(SAMPLES / name), format=fmt)
    return om


@pytest.fixture(scope="module")
def pizza():
    return ontology_overview(_load("pizza.owl", "xml"))


def test_classes_are_counted_as_the_classes_page_lists_them(pizza):
    """pizza declares 143 owl:Class subjects, 44 of them anonymous unions and
    complements; the Classes page lists the 99 named ones, and so does the tile."""
    assert pizza.counts["Classes"] == 99
    assert list(pizza.counts) == [
        "Classes",
        "Object properties",
        "Data properties",
        "Individuals",
        "Restrictions",
    ]


def test_pizza_coverage_hierarchy_and_spread(pizza):
    coverage = {c.label: (c.have, c.total) for c in pizza.coverage}
    assert coverage["Class labels"] == (99, 99)
    assert coverage["Class definitions"] == (19, 99)
    assert coverage["Property labels"] == (0, 8)
    assert coverage["Property domains"] == (3, 8)
    assert coverage["Property ranges"] == (4, 8)

    shape = pizza.hierarchy
    assert shape.classes == 99
    assert sum(shape.per_depth) == 99
    assert shape.per_depth[0] == shape.roots == 16
    assert shape.max_depth == 6
    assert shape.in_cycles == 0

    assert pizza.instances_per_class == (("Country", 5),)  # owl:Thing left out
    assert dict(pizza.label_languages) == {"en": 174, "pt": 95}
    assert (pizza.title, pizza.version) == ("pizza", "2.0")


def test_a_dublin_core_title_names_the_ontology():
    assert ontology_overview(_load("foaf.rdf", "xml")).title == (
        "Friend of a Friend (FOAF) vocabulary"
    )


def test_a_skos_vocabulary_gets_skos_tiles_and_concept_coverage():
    overview = ontology_overview(_load("skos-showcase.ttl", "turtle"))
    assert overview.uses_skos and not overview.uses_owl
    assert overview.counts == {"Concept schemes": 2, "Concepts": 9}
    assert [c.label for c in overview.coverage] == [
        "Concept labels",
        "Concept definitions",
    ]
    assert overview.hierarchy.classes == 0


def test_an_empty_ontology_is_empty():
    overview = ontology_overview(OntologyManager())
    assert overview.is_empty
    assert overview.uses_owl  # an empty graph gets the OWL tiles, at zero
    assert overview.coverage == ()
    assert overview.hierarchy.per_depth == ()
    assert overview.hierarchy.max_depth == 0


def test_a_class_sits_at_its_deepest_position():
    """A ⊑ Root, B ⊑ A, B ⊑ Root: B is two levels down, not one."""
    om = OntologyManager(base_uri=str(NS))
    om.add_class("Root")
    om.add_class("A", parent="Root")
    om.add_class("B", parent="A")
    om.graph.add((NS.B, RDFS.subClassOf, NS.Root))
    shape = ontology_overview(om).hierarchy
    assert shape.per_depth == (1, 1, 1)
    assert (shape.roots, shape.leaves, shape.multi_parent) == (1, 1, 1)


def test_a_subclass_cycle_neither_hangs_nor_gets_a_depth():
    om = OntologyManager(base_uri=str(NS))
    for name in ("A", "B", "Below", "Alone"):
        om.add_class(name)
    om.graph.add((NS.A, RDFS.subClassOf, NS.B))
    om.graph.add((NS.B, RDFS.subClassOf, NS.A))
    om.graph.add((NS.Below, RDFS.subClassOf, NS.A))
    shape = ontology_overview(om).hierarchy
    assert shape.in_cycles == 3  # A and B, and Below, which hangs off them
    assert shape.per_depth == (1,)  # Alone


def test_a_deep_chain_needs_no_recursion():
    om = OntologyManager(base_uri=str(NS))
    g = om.graph
    for i in range(3000):
        g.add((NS[f"C{i}"], RDF.type, OWL.Class))
        if i:
            g.add((NS[f"C{i}"], RDFS.subClassOf, NS[f"C{i - 1}"]))
    assert ontology_overview(om).hierarchy.max_depth == 2999


def test_coverage_counts_only_the_ontologys_own_entities():
    om = OntologyManager(base_uri=str(NS))
    om.add_class("Mine", label="Mine")
    om.add_class("Undocumented")
    foreign = URIRef("http://elsewhere.org/x#Foreign")
    om.graph.add((foreign, RDF.type, OWL.Class))
    om.graph.add((foreign, RDFS.label, Literal("Foreign")))
    overview = ontology_overview(om)
    assert overview.counts["Classes"] == 3
    assert overview.own_scope_only
    labels = next(c for c in overview.coverage if c.label == "Class labels")
    assert (labels.have, labels.total) == (1, 2)


def test_nothing_left_out_means_no_scope_note():
    om = OntologyManager(base_uri=str(NS))
    om.add_class("Mine")
    assert not ontology_overview(om).own_scope_only


def test_the_tail_folds_into_one_other_row():
    counts = Counter({"a": 5, "b": 4, "c": 1, "d": 1, "e": 1})
    assert _ranked(counts, 2) == (("a", 5), ("b", 4), ("Other (3)", 3))
    assert _ranked(counts, 9) == (("a", 5), ("b", 4), ("c", 1), ("d", 1), ("e", 1))

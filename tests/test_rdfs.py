"""The native RDFS closure is owlrl's, only faster (large ontologies WP4).

owlrl run to a fixpoint (``_owlrl_fixpoint``) is the reference: on every
bundled sample, on a generated tree and on a graph built to fire every rule,
the native closure must come out with exactly the same triples.
"""

import sys
from pathlib import Path

import owlrl
import pytest
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, XSD

from orionbelt_ontology_builder.ontology_manager import (
    _owlrl_fixpoint,
    reason_to_fixpoint,
)

SAMPLES = (
    Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "samples"
)
FORMATS = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml"}
SAMPLE_FILES = sorted(path for path in SAMPLES.rglob("*") if path.suffix in FORMATS)
EX = Namespace("http://test.org/rdfs#")


def _both_ways(graph: Graph) -> tuple[set, set]:
    by_owlrl, native = Graph(), Graph()
    for triple in graph:
        by_owlrl.add(triple)
        native.add(triple)
    _owlrl_fixpoint(by_owlrl, owlrl.RDFS_Semantics)
    reason_to_fixpoint(native, "rdfs")
    return set(by_owlrl), set(native)


def _assert_same(graph: Graph) -> None:
    by_owlrl, native = _both_ways(graph)
    assert native - by_owlrl == set(), "only the native closure has these"
    assert by_owlrl - native == set(), "only owlrl has these"


@pytest.mark.parametrize(
    "path", SAMPLE_FILES, ids=[str(p.relative_to(SAMPLES)) for p in SAMPLE_FILES]
)
def test_the_closure_matches_owlrl_on_a_sample(path):
    _assert_same(Graph().parse(str(path), format=FORMATS[path.suffix]))


def test_the_closure_matches_owlrl_on_a_generated_tree():
    sys.path.insert(0, str(SAMPLES.parent.parent / "scripts"))
    from bench_quality import synthetic

    _assert_same(synthetic(300).graph)


def test_the_closure_matches_owlrl_on_every_rule():
    g = Graph()
    # Class hierarchy with a cycle, instances, rdfs:Class and rdfs:Datatype.
    g.add((EX.Dog, RDFS.subClassOf, EX.Mammal))
    g.add((EX.Mammal, RDFS.subClassOf, EX.Animal))
    g.add((EX.Animal, RDFS.subClassOf, EX.Mammal))
    g.add((EX.rex, RDF.type, EX.Dog))
    g.add((EX.Shape, RDF.type, RDFS.Class))
    g.add((EX.Age, RDF.type, RDFS.Datatype))
    # Property hierarchy with a cycle, domains and ranges on super-properties.
    g.add((EX.hasPuppy, RDFS.subPropertyOf, EX.hasChild))
    g.add((EX.hasChild, RDFS.subPropertyOf, EX.hasRelative))
    g.add((EX.hasRelative, RDFS.subPropertyOf, EX.hasChild))
    g.add((EX.hasRelative, RDFS.domain, EX.Animal))
    g.add((EX.hasChild, RDFS.range, EX.Animal))
    g.add((EX.rex, EX.hasPuppy, EX.fido))
    g.add((EX.age, RDFS.range, EX.Age))
    g.add((EX.rex, EX.age, Literal("3", datatype=XSD.integer)))  # literal object
    g.add((EX._1, RDF.type, RDFS.ContainerMembershipProperty))
    g.add((EX.p, RDF.type, RDF.Property))
    # A literal as a super-property: owlrl drops what it would derive.
    g.add((EX.odd, RDFS.subPropertyOf, Literal("not a property")))
    g.add((EX.rex, EX.odd, EX.fido))
    # Literals of equal value: owlrl copies triples among them.
    g.add((EX.a, RDFS.label, Literal("abc")))
    g.add((EX.b, RDFS.label, Literal("abc", lang="en")))
    g.add((EX.c, RDFS.comment, Literal("abc", datatype=XSD.string)))
    g.add((EX.d, EX["count"], Literal("1", datatype=XSD.integer)))
    g.add((EX.e, EX["count"], Literal("1.0", datatype=XSD.decimal)))
    g.add((EX.f, EX.flag, Literal("true", datatype=XSD.boolean)))
    # Blank nodes, as restrictions and lists bring them.
    node = BNode()
    g.add((node, RDF.type, OWL.Restriction))
    g.add((EX.Dog, RDFS.subClassOf, node))
    _assert_same(g)


def test_owlrl_quirk_on_equal_values_is_kept():
    """A triple on "abc" is copied to "abc"@en: owlrl compares Python values.
    Kept so the closure stays owlrl's; documented in the rdfs module."""
    g = Graph()
    g.add((EX.a, RDFS.label, Literal("abc")))
    g.add((EX.b, RDFS.label, Literal("abc", lang="en")))
    reason_to_fixpoint(g, "rdfs")
    assert (EX.a, RDFS.label, Literal("abc", lang="en")) in g


def test_reasoning_twice_adds_nothing():
    g = Graph().parse(str(SAMPLES / "prov-o.ttl"), format="turtle")
    assert reason_to_fixpoint(g, "rdfs") > 0
    assert reason_to_fixpoint(g, "rdfs") == 0


def test_no_triple_is_left_with_a_literal_subject():
    g = Graph()
    g.add((EX.age, RDFS.range, EX.Age))
    g.add((EX.rex, EX.age, Literal("3", datatype=XSD.integer)))
    reason_to_fixpoint(g, "rdfs")
    assert not any(isinstance(s, Literal) for s, _, _ in g)


_TRIVIAL = (RDFS.Resource, RDF.Property)


def test_the_lean_closure_keeps_what_the_terms_imply():
    g = Graph().parse(str(SAMPLES / "prov-o.ttl"), format="turtle")
    full, lean = Graph(), Graph()
    for triple in g:
        full.add(triple)
        lean.add(triple)
    reason_to_fixpoint(full, "rdfs")
    reason_to_fixpoint(lean, "rdfs-lean")
    assert set(lean) < set(full)
    added = set(lean) - set(g)
    assert added, "the lean closure still infers"
    assert not any(p == RDF.type and o in _TRIVIAL for _, p, o in added)
    assert not any(
        s == o for s, p, o in added if p in (RDFS.subClassOf, RDFS.subPropertyOf)
    )


def test_the_lean_closure_infers_through_domains_and_hierarchies():
    g = Graph()
    g.add((EX.Dog, RDFS.subClassOf, EX.Mammal))
    g.add((EX.Mammal, RDFS.subClassOf, EX.Animal))
    g.add((EX.hasPuppy, RDFS.subPropertyOf, EX.hasChild))
    g.add((EX.hasChild, RDFS.domain, EX.Dog))
    g.add((EX.rex, EX.hasPuppy, EX.fido))
    reason_to_fixpoint(g, "rdfs-lean")
    assert (EX.Dog, RDFS.subClassOf, EX.Animal) in g
    assert (EX.rex, EX.hasChild, EX.fido) in g
    assert (EX.rex, RDF.type, EX.Animal) in g
    assert (EX.rex, RDF.type, RDFS.Resource) not in g

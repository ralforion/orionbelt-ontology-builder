"""Applying reasoning reaches a fixpoint and leaves only writable RDF."""

from pathlib import Path

import pytest
from rdflib import OWL, RDF, XSD, Literal, Namespace, URIRef

from orionbelt_ontology_builder.ontology_manager import OntologyManager

ERR = Namespace("http://www.daml.org/2002/03/agents/agent-ont#")

PROV_O = (
    Path(__file__).parent.parent
    / "orionbelt_ontology_builder"
    / "samples"
    / "prov-o.ttl"
)


def _prov_o() -> OntologyManager:
    om = OntologyManager()
    om.graph.parse(PROV_O)
    return om


@pytest.mark.parametrize("profile", ["rdfs", "owl-rl", "owl-rl-ext"])
def test_applying_reasoning_twice_adds_nothing(profile):
    om = _prov_o()
    assert om.apply_reasoning(profile) > 0
    count = len(om.graph)
    assert om.apply_reasoning(profile) == 0
    assert len(om.graph) == count


@pytest.mark.parametrize("profile", ["rdfs", "owl-rl", "owl-rl-ext"])
def test_reasoning_leaves_no_literal_subjects(profile):
    om = _prov_o()
    om.apply_reasoning(profile)
    assert not any(isinstance(s, Literal) for s, _, _ in om.graph)


def test_reasoning_reports_each_pass():
    om = _prov_o()
    calls = []
    added = om.apply_reasoning(
        "rdfs", progress=lambda n, so_far: calls.append((n, so_far))
    )
    # RDFS needs a second pass for the terms the first one introduced, and a
    # third to see nothing new.
    assert [n for n, _ in calls] == [1, 2, 3]
    assert calls[0][1] == 0
    assert 0 < calls[1][1] <= calls[2][1] == added


def test_unknown_profile_changes_nothing():
    om = _prov_o()
    count = len(om.graph)
    assert om.apply_reasoning("nope") == 0
    assert len(om.graph) == count


def test_reasoning_leaves_literal_parsing_as_it_was():
    """owlrl's datatype tables are process-wide: no run may change them."""
    rational = Literal("6/2", datatype=OWL.rational)
    assert rational.value is None
    om = _prov_o()
    om.apply_reasoning("owl-rl-ext")
    assert Literal("6/2", datatype=OWL.rational).value is None
    assert Literal("x y", datatype=XSD.NMTOKEN).value is None


@pytest.mark.parametrize("profile", ["owl-rl", "owl-rl-ext"])
def test_an_inconsistency_is_reported_once_and_settles(profile):
    """owlrl writes each error on a fresh blank node; it must not pile up."""
    om = OntologyManager(base_uri="http://test.org/r#")
    a, b, x = (URIRef(f"http://test.org/r#{n}") for n in ("A", "B", "x"))
    om.graph.add((a, OWL.disjointWith, b))
    om.graph.add((x, RDF.type, a))
    om.graph.add((x, RDF.type, b))
    calls = []
    om.apply_reasoning(profile, progress=lambda n, _: calls.append(n))
    assert len(calls) < OntologyManager.REASONING_MAX_PASSES
    errors = list(om.graph.subjects(RDF.type, ERR.ErrorMessage))
    messages = [m for e in errors for m in om.graph.objects(e, ERR.error)]
    assert messages
    assert len(messages) == len(set(messages)) == len(errors)
    assert om.apply_reasoning(profile) == 0

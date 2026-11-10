"""Applying reasoning reaches a fixpoint and leaves only writable RDF, in the
app's process or in a worker."""

from pathlib import Path

import pytest
from rdflib import OWL, RDF, XSD, BNode, Literal, Namespace, URIRef
from rdflib.compare import isomorphic

from orionbelt_ontology_builder import worker_process
from orionbelt_ontology_builder.ontology_manager import OntologyManager, UndoManager
from orionbelt_ontology_builder.reasoning import (
    ClosureChange,
    ReasoningFailed,
    ReasoningTimeout,
)

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


# ---- the closure in a worker process --------------------------------------


def _bnodes(graph) -> set[BNode]:
    return {n for t in graph for n in t if isinstance(n, BNode)}


@pytest.mark.parametrize("profile", ["rdfs", "owl-rl"])
def test_the_worker_infers_what_the_app_process_does(profile):
    here, there = _prov_o(), _prov_o()
    added = here.apply_reasoning(profile)
    assert there.apply_reasoning_in_worker(profile) == added
    assert isomorphic(there.graph, here.graph)


def test_the_worker_keeps_the_ontologys_blank_nodes():
    """A triple inferred about a restriction comes back about the same blank
    node, rather than about a copy of it."""
    om = OntologyManager(base_uri="http://test.org/r#")
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("p", domain="A", range_="B")
    om.add_restriction("A", "p", "someValuesFrom", "B")
    before = _bnodes(om.graph)
    assert before
    assert om.apply_reasoning_in_worker("rdfs") > 0
    assert _bnodes(om.graph) == before  # RDFS makes no blank nodes of its own


def test_the_worker_reports_progress_from_pass_zero():
    om = _prov_o()
    calls = []
    added = om.apply_reasoning_in_worker(
        "rdfs", progress=lambda n, so_far: calls.append((n, so_far))
    )
    passes = sorted(set(calls))
    assert passes[0] == (0, 0)  # while the worker starts and reads the graph
    assert passes[1:] == [(1, 0), (2, passes[2][1]), (3, added)]


def _spy_workers(monkeypatch):
    started = []
    real_start = worker_process.start

    def start(module):
        worker = real_start(module)
        started.append(worker)
        return worker

    monkeypatch.setattr(worker_process, "start", start)
    return started


def test_the_worker_is_stopped_at_the_deadline(monkeypatch):
    started = _spy_workers(monkeypatch)
    om = _prov_o()
    count = len(om.graph)
    with pytest.raises(ReasoningTimeout):
        om.apply_reasoning_in_worker("rdfs", deadline_s=0.05)
    assert len(om.graph) == count
    assert [w.poll() is not None for w in started] == [True]


def test_a_raising_progress_callback_stops_the_worker(monkeypatch):
    """How a Streamlit rerun cancels a run: it raises out of the callback."""

    class Moved(BaseException):
        pass

    def progress(pass_number, _added):
        if pass_number == 1:
            raise Moved

    started = _spy_workers(monkeypatch)
    om = _prov_o()
    count = len(om.graph)
    with pytest.raises(Moved):
        om.apply_reasoning_in_worker("rdfs", progress=progress)
    assert len(om.graph) == count
    assert [w.poll() is not None for w in started] == [True]


def test_a_worker_that_stops_without_a_result_is_reported(monkeypatch):
    real_start = worker_process.start
    monkeypatch.setattr(
        worker_process,
        "start",
        lambda module: real_start("orionbelt_ontology_builder.no_such_worker"),
    )
    om = _prov_o()
    count = len(om.graph)
    with pytest.raises(ReasoningFailed, match="no_such_worker"):
        om.apply_reasoning_in_worker("rdfs")
    assert len(om.graph) == count


def test_an_unknown_profile_starts_no_worker(monkeypatch):
    started = _spy_workers(monkeypatch)
    assert _prov_o().apply_reasoning_in_worker("nope") == 0
    assert started == []


def test_reasoning_in_the_worker_is_one_undo_step():
    om = _prov_o()
    undo = UndoManager(om)
    before = set(om.graph)
    om.apply_reasoning_in_worker("rdfs")
    undo.checkpoint("Apply reasoning")
    assert len(om.graph) > len(before)
    assert undo.undo() == "Initial state"
    assert set(om.graph) == before


def test_inferring_in_the_worker_leaves_the_graph_alone():
    om = _prov_o()
    before = set(om.graph)
    change = om.infer_in_worker("rdfs")
    assert change.added
    assert set(om.graph) == before


def test_applying_a_closure_change_is_all_or_nothing(monkeypatch):
    om = OntologyManager(base_uri="http://test.org/r#")
    a, b, c = (URIRef(f"http://test.org/r#{n}") for n in "ABC")
    om.graph.add((a, RDF.type, OWL.Class))
    before = set(om.graph)
    change = ClosureChange(
        added=[(b, RDF.type, OWL.Class), (c, RDF.type, OWL.Class)],
        removed=[(a, RDF.type, OWL.Class)],
    )
    real_add = om.graph.add
    calls = []

    def add_failing_the_second_time(triple):
        calls.append(triple)
        if len(calls) == 2:
            raise MemoryError
        return real_add(triple)

    monkeypatch.setattr(om.graph, "add", add_failing_the_second_time)
    with pytest.raises(MemoryError):
        om.apply_closure_change(change)
    monkeypatch.undo()
    assert set(om.graph) == before

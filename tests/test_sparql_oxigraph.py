"""SPARQL on a large ontology runs on Oxigraph, in a worker killed at the deadline.

The engine is chosen by size, so most tests lower the threshold rather than
build 20,000 triples. What has to hold: the same answers as rdflib on the
page's examples over every bundled sample, language tags as the ontology writes
them, the queries Oxigraph would answer differently going to rdflib, and the
deadline and row cap still bounding a query on the other side of a pipe.
"""

from collections import Counter
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS

from orionbelt_ontology_builder import sparql, sparql_oxigraph, worker_process
from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.views.sparql import EXAMPLE_QUERIES

SAMPLES = (
    Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "samples"
)
FORMATS = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml"}
SAMPLE_FILES = sorted(p for p in SAMPLES.rglob("*") if p.suffix in FORMATS)

EX = Namespace("http://example.org/")
PREFIXES = "PREFIX ex: <http://example.org/>\n"


@pytest.fixture
def on_oxigraph(monkeypatch):
    """Every query of any size goes to Oxigraph, unless it is one that
    should not."""
    monkeypatch.setattr(sparql, "OXIGRAPH_MIN_TRIPLES", 0)


def _graph(*triples) -> Graph:
    graph = Graph()
    graph.bind("ex", EX)
    for triple in triples:
        graph.add(triple)
    return graph


def _rows(result) -> Counter:
    """The rows as a multiset, blank node labels left out: each engine names
    blank nodes its own way."""
    return Counter(
        tuple("_:" if cell.startswith("_:") else cell for cell in row)
        for row in result.rows
    )


@pytest.mark.parametrize(
    "path", SAMPLE_FILES, ids=[str(p.relative_to(SAMPLES)) for p in SAMPLE_FILES]
)
def test_the_examples_answer_alike_on_every_sample(path, on_oxigraph):
    """Row order can differ: rows that tie on the ORDER BY key, and labels in
    different languages, which SPARQL leaves each engine to order its own way."""
    om = OntologyManager()
    om.load_from_file(str(path), format=FORMATS[path.suffix])
    for name, query in EXAMPLE_QUERIES.items():
        ours = sparql.run_query(om.graph, query, timeout_seconds=60, max_rows=50000)
        by_rdflib = sparql.run_query(
            om.graph, query, timeout_seconds=60, max_rows=50000, engine="rdflib"
        )
        assert ours.engine == "oxigraph", (name, ours.engine_note)
        assert by_rdflib.engine == "rdflib"
        assert ours.columns == by_rdflib.columns, name
        assert _rows(ours) == _rows(by_rdflib), name
        assert not ours.truncated and not ours.timed_out, name


def test_a_large_ontology_runs_on_oxigraph_and_a_small_one_on_rdflib():
    big = _graph(
        *(
            (EX[f"C{i}"], predicate, value)
            for i in range(sparql.OXIGRAPH_MIN_TRIPLES // 2)
            for predicate, value in (
                (RDF.type, OWL.Class),
                (RDFS.label, Literal(f"C{i}")),
            )
        )
    )
    query = PREFIXES + "SELECT (COUNT(*) AS ?n) WHERE { ?c a owl:Class }"
    result = sparql.run_query(big, query)
    assert result.engine == "oxigraph"
    assert result.rows == [[str(sparql.OXIGRAPH_MIN_TRIPLES // 2)]]
    assert result.engine_note == ""

    chosen = sparql.run_query(big, query, engine="rdflib")
    assert chosen.engine == "rdflib"
    assert chosen.engine_note == "", (
        "rdflib was asked for, so there is nothing to explain"
    )
    assert chosen.rows == result.rows

    small = sparql.run_query(_graph((EX.a, RDF.type, OWL.Class)), query)
    assert small.engine == "rdflib"
    assert small.engine_note == ""


def test_oxigraph_can_be_chosen_at_any_size():
    """Chosen, it still hands rdflib the queries it would answer wrongly
    without saying so, and says why under the result."""
    graph = _graph((EX.a, RDFS.comment, Literal("aa bb")))
    query = PREFIXES + "SELECT ?t WHERE { ex:a rdfs:comment ?t FILTER(regex(?t, %s)) }"
    plain = sparql.run_query(graph, query % '"^a+"', engine="oxigraph")
    assert plain.engine == "oxigraph"
    assert plain.rows == [["aa bb"]]
    backreference = sparql.run_query(graph, query % '"(a)\\\\1"', engine="oxigraph")
    assert backreference.engine == "rdflib"
    assert "REGEX" in backreference.engine_note
    assert backreference.rows == [["aa bb"]]


def test_language_tags_come_back_as_written(on_oxigraph):
    graph = _graph(
        (EX.a, RDFS.label, Literal("Colour", lang="en-GB")),
        (EX.a, RDFS.label, Literal("Farbe", lang="de")),
    )
    result = sparql.run_query(
        graph, PREFIXES + "SELECT ?l WHERE { ex:a rdfs:label ?l } ORDER BY ?l"
    )
    assert result.engine == "oxigraph"
    assert sorted(result.rows) == [["Colour@en-GB"], ["Farbe@de"]]


def test_lang_on_mixed_case_tags_goes_to_rdflib(on_oxigraph):
    """Oxigraph lowercases tags, so ``lang(?l) = "en-GB"`` would find nothing
    there, and nothing on the page would say why."""
    graph = _graph((EX.a, RDFS.label, Literal("Colour", lang="en-GB")))
    result = sparql.run_query(
        graph,
        PREFIXES + 'SELECT ?l WHERE { ex:a rdfs:label ?l FILTER(lang(?l) = "en-GB") }',
    )
    assert result.engine == "rdflib"
    assert "en-GB" in result.engine_note
    assert result.rows == [["Colour@en-GB"]]


def test_langmatches_ignores_case_and_stays_on_oxigraph(on_oxigraph):
    graph = _graph((EX.a, RDFS.label, Literal("Colour", lang="en-GB")))
    result = sparql.run_query(
        graph,
        PREFIXES
        + 'SELECT ?l WHERE { ex:a rdfs:label ?l FILTER(langMatches(lang(?l), "en")) }',
    )
    assert result.engine == "oxigraph"
    assert result.rows == [["Colour@en-GB"]]


def test_lang_on_lowercase_tags_stays_on_oxigraph(on_oxigraph):
    graph = _graph((EX.a, RDFS.label, Literal("Farbe", lang="de")))
    result = sparql.run_query(
        graph, PREFIXES + "SELECT (lang(?l) AS ?t) WHERE { ex:a rdfs:label ?l }"
    )
    assert result.engine == "oxigraph"
    assert result.rows == [["de"]]


def test_a_tag_written_in_two_cases_goes_to_rdflib(on_oxigraph):
    graph = _graph(
        (EX.a, RDFS.label, Literal("Colour", lang="en-GB")),
        (EX.b, RDFS.label, Literal("Colour", lang="en-gb")),
    )
    result = sparql.run_query(graph, PREFIXES + "SELECT ?l WHERE { ?s rdfs:label ?l }")
    assert result.engine == "rdflib"
    assert "two cases" in result.engine_note


def test_language_spellings_read_the_object_s_tag_only():
    nt = (
        '<http://e/a> <http://e/p> "x"@en-GB .\n'
        '<http://e/a> <http://e/p> "says \\"y\\"@fr-CA ." .\n'
    )
    assert sparql_oxigraph.language_spellings(nt) == {"en-gb": "en-GB"}


@pytest.mark.parametrize(
    "condition",
    [
        'regex(?t, "(a)\\\\1")',  # a backreference
        'regex(?t, "a(?=a)")',  # a lookahead
        'regex(?t, "a(?<!b)a")',  # a lookbehind
        "regex(?t, ?t)",  # a pattern built at run time
        'replace(?t, "(a)\\\\1", "x") != ?t',  # REPLACE reads a pattern too
    ],
)
def test_a_regex_oxigraph_cannot_read_goes_to_rdflib(on_oxigraph, condition):
    graph = _graph((EX.a, RDFS.comment, Literal("aa bb")))
    result = sparql.run_query(
        graph,
        PREFIXES + f"SELECT ?t WHERE {{ ex:a rdfs:comment ?t FILTER({condition}) }}",
    )
    assert result.engine == "rdflib"
    assert "REGEX" in result.engine_note
    assert result.rows == [["aa bb"]]


def test_a_plain_regex_stays_on_oxigraph(on_oxigraph):
    graph = _graph((EX.a, RDFS.comment, Literal("aa bb")))
    result = sparql.run_query(
        graph,
        PREFIXES
        + 'SELECT ?t WHERE { ex:a rdfs:comment ?t FILTER(regex(?t, "^a+ b", "i")) }',
    )
    assert result.engine == "oxigraph"
    assert result.rows == [["aa bb"]]


def test_a_query_oxigraph_rejects_runs_on_rdflib(on_oxigraph):
    """A relative IRI: rdflib takes it, Oxigraph wants a base to resolve it."""
    graph = _graph((URIRef("rel"), RDFS.label, Literal("x")))
    result = sparql.run_query(graph, "SELECT ?l WHERE { <rel> ?p ?l }")
    assert result.engine == "rdflib"
    assert "could not run" in result.engine_note
    assert result.rows == [["x"]]


def test_the_read_only_rules_hold_before_oxigraph_is_asked(on_oxigraph, monkeypatch):
    monkeypatch.setattr(
        sparql_oxigraph, "run", lambda *a, **k: pytest.fail("Oxigraph was asked")
    )
    graph = _graph((EX.a, RDFS.label, Literal("x")))
    for query in (
        "INSERT DATA { <http://e/a> <http://e/b> <http://e/c> }",
        "SELECT * WHERE { SERVICE <http://e/sparql> { ?s ?p ?o } }",
        "SELECT * FROM <http://e/g> WHERE { ?s ?p ?o }",
    ):
        with pytest.raises(sparql.QueryNotAllowed):
            sparql.run_query(graph, query)


def test_a_runaway_query_is_stopped_at_the_deadline(on_oxigraph, monkeypatch):
    workers = []
    start = worker_process.start

    def recording(module):
        workers.append(start(module))
        return workers[-1]

    monkeypatch.setattr(worker_process, "start", recording)
    graph = _graph(*((EX[f"s{i}"], RDFS.label, Literal(i)) for i in range(2000)))
    result = sparql.run_query(
        graph,
        "SELECT (COUNT(*) AS ?n) WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i }",
        timeout_seconds=1,
    )
    assert result.engine == "oxigraph"
    assert result.timed_out
    assert result.rows == []
    assert result.elapsed < 5
    assert workers and workers[0].poll() is not None, "the worker is gone"


def test_the_row_cap_applies_on_oxigraph(on_oxigraph):
    graph = _graph(*((EX[f"s{i}"], RDFS.label, Literal(i)) for i in range(50)))
    query = PREFIXES + "SELECT ?s WHERE { ?s rdfs:label ?l }"
    capped = sparql.run_query(graph, query, max_rows=5)
    assert capped.engine == "oxigraph"
    assert capped.row_count == 5 and capped.truncated
    exact = sparql.run_query(graph, query, max_rows=50)
    assert exact.row_count == 50 and not exact.truncated
    construct = sparql.run_query(
        graph, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", max_rows=7
    )
    assert construct.row_count == 7 and construct.truncated
    assert len(construct.graph) == 7


def test_a_constructed_graph_matches_rdflib_s(on_oxigraph):
    om = OntologyManager()
    om.load_from_file(str(SAMPLES / "pizza.owl"), format="xml")
    query = (
        "CONSTRUCT { ?c rdfs:subClassOf ?r . ?r ?p ?o } WHERE { "
        "?c rdfs:subClassOf ?r . FILTER(isBlank(?r)) ?r ?p ?o }"
    )
    ours = sparql.run_query(om.graph, query, max_rows=50000)
    by_rdflib = sparql.run_query(om.graph, query, max_rows=50000, engine="rdflib")
    assert ours.engine == "oxigraph"
    assert len(ours.graph) > 0
    assert isomorphic(ours.graph, by_rdflib.graph)
    assert dict(ours.graph.namespaces()) == dict(by_rdflib.graph.namespaces())


def test_select_star_columns_follow_query_order_on_oxigraph(on_oxigraph):
    graph = _graph((EX.a, RDFS.label, Literal("x")))
    result = sparql.run_query(graph, "SELECT * WHERE { ?subject ?predicate ?label }")
    assert result.engine == "oxigraph"
    assert result.columns == ["subject", "predicate", "label"]
    explicit = sparql.run_query(
        graph, "SELECT ?label ?subject WHERE { ?subject ?p ?label }"
    )
    assert explicit.columns == ["label", "subject"]


def test_an_ask_query_runs_on_oxigraph(on_oxigraph):
    graph = _graph((EX.a, RDFS.label, Literal("x")))
    assert sparql.run_query(graph, PREFIXES + "ASK { ex:a ?p ?o }").ask is True
    result = sparql.run_query(graph, PREFIXES + "ASK { ex:b ?p ?o }")
    assert result.engine == "oxigraph"
    assert result.ask is False

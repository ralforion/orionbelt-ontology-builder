"""Tests for the read-only SPARQL console engine."""

import os
import subprocess
import sys
import time

import pytest
from rdflib import Graph, Literal, Namespace, URIRef

from orionbelt_ontology_builder import sparql

EX = Namespace("http://example.org/")


def _cartesian_graph(n=300):
    """A graph small enough to build instantly, big enough that a three-way
    cartesian product over it cannot finish."""
    g = Graph()
    for i in range(n):
        g.add((EX[f"s{i}"], EX.p, Literal(i)))
    return g


# --- read-only enforcement -------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <http://a> <http://b> <http://c> }",
        "DELETE WHERE { ?s ?p ?o }",
        "DROP ALL",
        "CLEAR GRAPH <http://g>",
        "LOAD <http://elsewhere.example/data.ttl>",
    ],
)
def test_updates_are_rejected(populated_om, query):
    with pytest.raises(sparql.QueryNotAllowed):
        sparql.run_query(populated_om.graph, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * WHERE { ?s ?p ?o }",
        "ASK { ?s ?p ?o }",
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "DESCRIBE <http://test.org/ont#Person>",
    ],
)
def test_read_only_forms_are_accepted(populated_om, query):
    result = sparql.run_query(populated_om.graph, query)
    assert result.form in sparql.READ_ONLY_FORMS


def test_update_message_distinguishes_itself_from_a_typo(populated_om):
    with pytest.raises(sparql.QueryNotAllowed, match="read-only"):
        sparql.run_query(populated_om.graph, "DELETE WHERE { ?s ?p ?o }")
    with pytest.raises(sparql.QuerySyntaxError):
        sparql.run_query(populated_om.graph, "SELECT * WHERE { ?s ?p")


def test_empty_query_is_a_syntax_error(populated_om):
    with pytest.raises(sparql.QuerySyntaxError):
        sparql.run_query(populated_om.graph, "   ")


def test_a_query_cannot_mutate_the_ontology(populated_om):
    before = len(populated_om.graph)
    sparql.run_query(populated_om.graph, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert len(populated_om.graph) == before


def test_the_bounded_store_refuses_writes(populated_om):
    store = sparql._DeadlineStore(populated_om.graph.store, time.monotonic() + 60)
    with pytest.raises(sparql.QueryNotAllowed):
        store.add((EX.a, EX.b, EX.c), None)
    with pytest.raises(sparql.QueryNotAllowed):
        store.remove((None, None, None), None)


def test_service_is_rejected(populated_om):
    with pytest.raises(sparql.QueryNotAllowed, match="SERVICE"):
        sparql.run_query(
            populated_om.graph,
            "SELECT * WHERE { SERVICE <http://dbpedia.org/sparql> { ?s ?p ?o } }",
        )


def test_values_only_blowup_is_rejected(populated_om):
    vals = " ".join(str(i) for i in range(400))
    query = (
        f"SELECT * WHERE {{ VALUES ?a {{ {vals} }} VALUES ?b {{ {vals} }} "
        f"VALUES ?c {{ {vals} }} }}"
    )
    with pytest.raises(sparql.QueryNotAllowed, match="VALUES"):
        sparql.run_query(populated_om.graph, query)


def test_small_values_query_still_runs(populated_om):
    result = sparql.run_query(
        populated_om.graph, "SELECT * WHERE { VALUES ?a { 1 2 3 } }"
    )
    assert result.row_count == 3


# --- results ---------------------------------------------------------------


def test_select_returns_columns_and_rows(populated_om):
    result = sparql.run_query(
        populated_om.graph,
        "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }",
    )
    assert result.columns == ["c"]
    # The ontology's namespace is bound to the empty prefix, so its entities
    # render the way Turtle writes them.
    names = {row[0] for row in result.rows}
    assert ":Person" in names


def test_ask_returns_a_boolean(populated_om):
    yes = sparql.run_query(populated_om.graph, "ASK { ?s ?p ?o }")
    no = sparql.run_query(populated_om.graph, "ASK { <http://nope.example/x> ?p ?o }")
    assert yes.ask is True
    assert no.ask is False


def test_construct_returns_a_graph(populated_om):
    result = sparql.run_query(
        populated_om.graph,
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        max_rows=sparql.MAX_ROWS_CEILING,
    )
    assert result.graph is not None
    assert len(result.graph) == len(populated_om.graph)
    assert result.columns == ["subject", "predicate", "object"]


def test_ontology_prefixes_resolve_without_a_prefix_clause(populated_om):
    """The ontology's own bindings are offered to the parser, so a user can
    write ``owl:Class`` without redeclaring it."""
    result = sparql.run_query(populated_om.graph, "SELECT ?c WHERE { ?c a owl:Class }")
    assert result.row_count > 0


def test_running_a_query_does_not_add_prefixes_to_the_ontology(populated_om):
    """rdflib's URI shortening binds generated ``ns1:`` prefixes as a side
    effect; the console must not leave those on the user's ontology."""
    before = set(populated_om.graph.namespaces())
    sparql.run_query(populated_om.graph, "SELECT * WHERE { ?s ?p ?o }")
    assert set(populated_om.graph.namespaces()) == before


def test_language_tagged_literals_keep_their_tag(om):
    om.graph.add((EX.a, EX.label, Literal("Chien", lang="fr")))
    result = sparql.run_query(
        om.graph, "SELECT ?o WHERE { ?s <http://example.org/label> ?o }"
    )
    assert result.rows == [["Chien@fr"]]


def test_format_term_prefers_the_most_specific_namespace():
    prefixes = [("ex", "http://example.org/"), ("exsub", "http://example.org/sub/")]
    prefixes.sort(key=lambda item: len(item[1]), reverse=True)
    assert sparql.format_term(URIRef("http://example.org/sub/A"), prefixes) == "exsub:A"


def test_format_term_keeps_the_colon_for_the_default_prefix():
    assert (
        sparql.format_term(
            URIRef("http://example.org/A"), [("", "http://example.org/")]
        )
        == ":A"
    )


def test_format_term_leaves_an_unshortenable_uri_alone():
    assert (
        sparql.format_term(
            URIRef("http://other.example/A"), [("ex", "http://example.org/")]
        )
        == "http://other.example/A"
    )


# --- the row cap -----------------------------------------------------------


def test_row_cap_truncates_and_says_so(populated_om):
    result = sparql.run_query(
        populated_om.graph, "SELECT * WHERE { ?s ?p ?o }", max_rows=3
    )
    assert result.row_count == 3
    assert result.truncated is True


def test_row_cap_not_flagged_when_everything_fits(populated_om):
    result = sparql.run_query(
        populated_om.graph,
        "SELECT * WHERE { ?s ?p ?o }",
        max_rows=sparql.MAX_ROWS_CEILING,
    )
    assert result.truncated is False
    assert result.row_count == len(populated_om.graph)


def test_row_cap_applies_to_construct(populated_om):
    result = sparql.run_query(
        populated_om.graph, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", max_rows=2
    )
    assert result.truncated is True
    assert result.graph is not None
    assert len(result.graph) == 2


def test_row_cap_is_clamped_to_the_ceiling(populated_om):
    result = sparql.run_query(
        populated_om.graph, "SELECT * WHERE { ?s ?p ?o }", max_rows=10**9
    )
    assert result.truncated is False


# --- the deadline ----------------------------------------------------------


def test_a_query_that_never_yields_a_row_is_still_interrupted():
    """The case a deadline on result iteration cannot catch: ORDER BY consumes
    the whole join before yielding anything, so the interrupt has to come from
    inside the store."""
    graph = _cartesian_graph()
    started = time.monotonic()
    result = sparql.run_query(
        graph,
        "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i } ORDER BY ?c",
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.rows == []
    assert elapsed < 20, f"deadline did not interrupt promptly ({elapsed:.1f}s)"


def test_a_union_query_is_interrupted():
    """The common case, and the one a row cap cannot touch.

    rdflib's ``evalUnion`` is not a generator: it appends both branches into a
    list and returns it, so every query containing a UNION is fully evaluated
    before its first row exists. Only the store deadline can stop one.
    """
    graph = _cartesian_graph()
    started = time.monotonic()
    result = sparql.run_query(
        graph,
        """
        SELECT ?x WHERE {
          { ?x ?p ?o }
          UNION
          { ?a ?b ?c . ?d ?e ?f . ?x ?g ?h }
        }
        """,
        timeout_seconds=1,
    )
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.rows == [], "a UNION yields nothing until it is fully evaluated"
    assert elapsed < 20, f"deadline did not interrupt promptly ({elapsed:.1f}s)"


def test_a_streaming_runaway_is_interrupted(populated_om):
    graph = _cartesian_graph()
    result = sparql.run_query(
        graph, "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i }", timeout_seconds=1
    )
    assert result.timed_out or result.truncated


def test_a_normal_query_is_not_flagged(populated_om):
    result = sparql.run_query(populated_om.graph, "SELECT * WHERE { ?s ?p ?o }")
    assert result.timed_out is False
    assert result.truncated is False
    assert result.elapsed >= 0


def test_the_bounded_store_returns_the_same_rows_as_the_plain_graph(populated_om):
    query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"
    direct = {tuple(str(t) for t in row) for row in populated_om.graph.query(query)}
    viaconsole = sparql.run_query(
        populated_om.graph, query, max_rows=sparql.MAX_ROWS_CEILING
    )
    assert len(viaconsole.rows) == len(direct)


def test_timeout_is_clamped_to_the_ceiling(populated_om):
    result = sparql.run_query(
        populated_om.graph, "SELECT * WHERE { ?s ?p ?o }", timeout_seconds=10**6
    )
    assert result.timed_out is False


# --- csv export ------------------------------------------------------------


def test_rows_to_csv_round_trips():
    csv_text = sparql.rows_to_csv(["a", "b"], [["1", "2"], ["3", "4"]])
    assert csv_text.splitlines()[0] == "a,b"
    assert "3,4" in csv_text


# --- dataset clauses -------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM <http://no-such.example/g> WHERE { ?s ?p ?o }",
        "SELECT * FROM NAMED <http://no-such.example/g> WHERE { ?s ?p ?o }",
        "CONSTRUCT { ?s ?p ?o } FROM <http://no-such.example/g> WHERE { ?s ?p ?o }",
        "ASK FROM <http://no-such.example/g> { ?s ?p ?o }",
        "DESCRIBE ?s FROM <http://no-such.example/g> WHERE { ?s ?p ?o }",
    ],
)
def test_dataset_clauses_are_rejected(populated_om, query):
    """rdflib evaluates these against the graph it is given and ignores the
    clause, so every one of them silently answered from the loaded ontology
    under another graph's name — right-looking rows for a question nobody
    asked. Refused rather than answered wrongly.
    """
    with pytest.raises(sparql.QueryNotAllowed, match="FROM"):
        sparql.run_query(populated_om.graph, query)


def test_a_query_without_a_dataset_clause_is_unaffected(populated_om):
    result = sparql.run_query(populated_om.graph, "SELECT * WHERE { ?s ?p ?o }")
    assert result.row_count == len(populated_om.graph)


# --- column ordering -------------------------------------------------------


def test_select_star_columns_follow_query_order(populated_om):
    result = sparql.run_query(populated_om.graph, "SELECT * WHERE { ?s ?p ?o }")
    assert result.columns == ["s", "p", "o"]


def test_select_star_column_order_is_stable_across_processes():
    """The bug this fixes: rdflib builds SELECT *'s projection from a set, so
    hash randomisation reordered the columns between runs and two exports of
    the same query could disagree. Run in subprocesses because a single
    interpreter has one hash seed for its lifetime.
    """
    script = (
        "from rdflib import Graph, Literal, Namespace;"
        "from orionbelt_ontology_builder import sparql;"
        "EX = Namespace('http://e.org/');"
        "g = Graph();"
        "g.add((EX.a, EX.p, Literal('x')));"
        "print(sparql.run_query(g, 'SELECT * WHERE { ?alpha ?beta ?gamma }').columns)"
    )
    seen = set()
    for seed in ("0", "1", "2", "42"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        seen.add(out.stdout.strip())
    assert len(seen) == 1, f"column order varied by hash seed: {seen}"
    assert seen.pop() == "['alpha', 'beta', 'gamma']"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT ?o ?s WHERE { ?s ?p ?o }", ["o", "s"]),
        ("SELECT ?p ?s WHERE { ?s ?p ?o }", ["p", "s"]),
        (
            "SELECT ?p (COUNT(?s) AS ?n) WHERE { ?s ?p ?o } GROUP BY ?p",
            ["p", "n"],
        ),
    ],
)
def test_an_explicit_projection_keeps_the_users_order(populated_om, query, expected):
    """Only SELECT * may be reordered. The order the user wrote lives solely in
    the projection — the algebra keeps no record of the SELECT clause — so
    ordering an explicit projection against the pattern would rewrite it.
    """
    assert sparql.run_query(populated_om.graph, query).columns == expected


def test_reordering_keeps_each_value_under_its_own_column():
    """Reordering the header without reordering the cells would mislabel every
    row, which is worse than the unstable order it replaces."""
    graph = Graph()
    graph.add((EX.subj, EX.pred, Literal("the object")))
    result = sparql.run_query(graph, "SELECT * WHERE { ?s ?p ?o }")
    row = dict(zip(result.columns, result.rows[0], strict=True))
    assert row["s"].endswith("subj")
    assert row["p"].endswith("pred")
    assert row["o"] == "the object"


def test_ordered_vars_places_unknown_variables_last_by_name():
    """Nothing is dropped, and a variable the walk cannot place still lands in
    a deterministic spot rather than a hash-ordered one."""
    from rdflib import Variable

    algebra = sparql.prepare("SELECT * WHERE { ?s ?p ?o }", {}).query.algebra
    given = [Variable("zeta"), Variable("o"), Variable("alpha"), Variable("s")]
    ordered = sparql.ordered_vars(algebra, given, select_star=True)
    assert [str(v) for v in ordered] == ["s", "o", "alpha", "zeta"]
    assert sorted(str(v) for v in ordered) == sorted(str(v) for v in given)

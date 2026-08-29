"""Read-only SPARQL querying with a wall-clock deadline and a row cap.

The query console hands rdflib a string a user typed, so two things have to be
true before it can be exposed: the query must not be able to modify the
ontology, and it must not be able to hang the app.

**Read-only** is enforced by :func:`prepare`, which accepts only the four query
forms and rejects every update form by name.

**Bounded** is enforced in two layers, because one is not enough:

1. A row cap and a deadline on the result iteration. This catches the common
   runaway — a query that streams far more rows than anyone wants to see.
2. A deadline checked inside :class:`_DeadlineStore`, a read-through proxy in
   front of the real store.

Layer 2 is the one that actually saves the app. rdflib's ``evalBGP`` pulls every
candidate solution through ``ctx.graph.triples(...)`` and recurses per binding,
so a deadline enforced at the store is checked continuously throughout
evaluation — including while an operator above it consumes the whole join before
yielding anything. Layer 1 cannot help there: measured on a 300-triple graph, a
three-way cartesian product under ``ORDER BY`` produced no first row at all after
8 seconds, while the store deadline stopped the same query at 3.05s.

``ORDER BY``/``GROUP BY``/``DISTINCT`` are the obvious cases. The common one is
``UNION``: rdflib's ``evalUnion`` is not a generator, it appends both branches
into a list and returns it, so *every* query containing a ``UNION`` is fully
evaluated before its first row exists. A row cap cannot bound that; only the
deadline can.

The proxy costs nothing to run — the same query with it installed timed at
72.1ms against 72.3ms without, because rdflib's per-triple work dwarfs a
``monotonic()`` call every few hundred triples.

Being in-process is the point. A subprocess would have to fork from a Streamlit
ScriptRunner thread, which is a multi-threaded process, and CPython has
deprecated that since 3.12 ("use of fork() may lead to deadlocks in the child");
the Docker image ships 3.14. The store proxy needs no fork, no signals and no
main thread, so it behaves the same on the server and in the desktop build.

The one blowup this cannot interrupt is a query with no triple patterns at all —
a cross product of large ``VALUES`` blocks never touches the store, so nothing
trips. :func:`prepare` rejects that shape up front rather than leaving a hole.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from math import prod
from typing import Any, cast

from rdflib import BNode, Graph, Literal, URIRef, Variable
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate
from rdflib.plugins.sparql.sparql import Query
from rdflib.query import ResultRow
from rdflib.store import Store
from rdflib.term import Node

#: Wall-clock budget for a single query, in seconds.
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 120.0

#: How many result rows a query may return before the rest is discarded.
DEFAULT_MAX_ROWS = 1000
MAX_ROWS_CEILING = 50000

#: How often the store proxy re-checks the deadline while a single ``triples()``
#: generator is being drained. Small enough that a scan of a large graph is
#: still interrupted promptly, large enough that the check is free.
_DEADLINE_CHECK_EVERY = 512

#: A ``VALUES``-only query is evaluated entirely in memory, so the store
#: deadline never sees it. Reject one whose cross product exceeds this.
_VALUES_PRODUCT_LIMIT = 100_000

#: The query forms that cannot modify the graph. Everything else is an update.
READ_ONLY_FORMS = ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE")


class QueryError(Exception):
    """Base class for a query the console refuses to run."""


class QuerySyntaxError(QueryError):
    """The query text is not valid SPARQL."""


class QueryNotAllowed(QueryError):
    """The query is valid SPARQL but not something this console will run."""


class QueryTimeout(Exception):
    """Raised from inside the store proxy when the deadline passes.

    Not a :class:`QueryError`: it is an internal control-flow signal caught by
    :func:`run_query`, which reports the timeout on the result instead.
    """


class _DeadlineStore(Store):
    """A read-through proxy that trips a deadline from inside ``triples()``.

    Wrapping the *store* rather than the graph means every graph derived from it
    during evaluation — including the ones a ``FROM``/``GRAPH`` clause resolves
    through ``dataset.get_context()`` — is bounded by the same deadline.

    The proxy is read-only on purpose. Nothing in a ``SELECT``/``ASK``/
    ``CONSTRUCT``/``DESCRIBE`` evaluation writes, so a write arriving here means
    something got past :func:`prepare`, and refusing it keeps the user's
    ontology safe by construction rather than by argument.
    """

    def __init__(self, inner: Store, deadline: float) -> None:
        self._inner = inner
        self._deadline = deadline
        super().__init__()
        # Mirror the inner store's capabilities: Graph consults these, and
        # claiming the wrong ones changes how contexts are resolved.
        self.context_aware = inner.context_aware
        self.formula_aware = inner.formula_aware
        self.graph_aware = inner.graph_aware
        self.transaction_aware = inner.transaction_aware

    def _check(self) -> None:
        if time.monotonic() > self._deadline:
            raise QueryTimeout

    def triples(self, triple_pattern, context=None) -> Iterator[Any]:  # type: ignore[override]
        self._check()
        for seen, triple in enumerate(self._inner.triples(triple_pattern, context), 1):
            if seen % _DEADLINE_CHECK_EVERY == 0:
                self._check()
            yield triple

    def __len__(self, context=None) -> int:
        return self._inner.__len__(context)

    def contexts(self, triple=None):
        return self._inner.contexts(triple)

    def namespace(self, prefix):
        return self._inner.namespace(prefix)

    def prefix(self, namespace):
        return self._inner.prefix(namespace)

    def namespaces(self):
        return self._inner.namespaces()

    def bind(self, prefix, namespace, override=True) -> None:
        """Swallow prefix binding rather than forwarding it.

        Constructing a Graph binds rdflib's default prefixes, and forwarding
        those would silently add prefixes to the user's ontology just because
        they ran a query. Reads still see every real binding through
        ``namespaces()``, which is all query evaluation needs.
        """

    def add(self, *args, **kwargs):
        raise QueryNotAllowed("The query console cannot modify the ontology.")

    def remove(self, *args, **kwargs):
        raise QueryNotAllowed("The query console cannot modify the ontology.")


def _walk(node: Any) -> Iterator[Any]:
    """Yield every algebra node under ``node``, itself included."""
    if hasattr(node, "name"):
        yield node
    if isinstance(node, dict):
        values: Any = node.values()
    elif isinstance(node, (list, tuple)):
        values = node
    else:
        return
    for value in values:
        if isinstance(value, (dict, list, tuple)):
            yield from _walk(value)


def _algebra_guard(algebra: Any) -> None:
    """Reject query shapes the deadline cannot police, before running them."""
    names = set()
    values_sizes = []
    for node in _walk(algebra):
        names.add(node.name)
        if node.name == "values":
            values_sizes.append(len(node.get("res") or []))

    # SERVICE makes rdflib open a network connection to a host named in the
    # query. That is a request the app issues on the user's behalf, from the
    # server, to wherever the query says — not something a local ontology
    # editor should offer, and not something the deadline bounds.
    if "ServiceGraphPattern" in names:
        raise QueryNotAllowed(
            "Federated queries (SERVICE) are not supported: this console only "
            "queries the ontology loaded in the app."
        )

    # FROM / FROM NAMED name a dataset to query instead of this one. Nothing
    # here can serve them: the console evaluates against a single wrapper graph
    # over the loaded ontology, so rdflib ignores the clause and answers from
    # the ontology anyway. That is the dangerous outcome — the query looks
    # honoured and the rows look right, so `FROM <somewhere-else>` returns this
    # ontology's data under another graph's name. Refusing is the only reading
    # that cannot mislead.
    if "DatasetClause" in names:
        raise QueryNotAllowed(
            "FROM and FROM NAMED are not supported: this console always queries "
            "the ontology loaded in the app, and the clause would be ignored "
            "rather than honoured. Remove it to query the loaded ontology."
        )

    # No triple pattern means evaluation never reaches the store, so the store
    # deadline never fires. Harmless at small sizes; unstoppable at large ones.
    if "BGP" not in names and prod(values_sizes or [0]) > _VALUES_PRODUCT_LIMIT:
        raise QueryNotAllowed(
            "This query matches no triples and would expand a very large VALUES "
            "cross product, which cannot be interrupted. Add a triple pattern or "
            "use smaller VALUES blocks."
        )


@dataclass(frozen=True)
class PreparedQuery:
    """A parsed, vetted query, plus what the algebra no longer remembers."""

    query: Query
    #: Whether the user wrote ``SELECT *``. Read off the parse tree because the
    #: algebra cannot answer it: an explicit projection and a ``*`` over the
    #: same variables produce an identical ``PV``, differing only in an order
    #: that is meaningful in one case and random in the other.
    select_star: bool


def prepare(query_text: str, init_ns: dict[str, Any] | None = None) -> PreparedQuery:
    """Parse ``query_text``, rejecting anything that is not a read-only query.

    Parsing and translation are done here rather than through ``prepareQuery``
    so the parse tree can be inspected on the way past; ``prepareQuery`` is
    exactly these two calls and discards the tree. Only query forms translate,
    so every update form fails. We re-parse a failure as an update to tell the
    two cases apart: "this console is read-only" and "you have a typo" are
    different problems and deserve different messages.
    """
    if not query_text.strip():
        raise QuerySyntaxError("Enter a query to run.")
    try:
        parsed = parseQuery(query_text)
        query = translateQuery(parsed, initNs=init_ns or {})
    except Exception as exc:
        # Any parse failure is triaged below into "read-only" or "syntax error".
        try:
            parseUpdate(query_text)
        except Exception:  # noqa: BLE001 - not an update either, so it is a syntax error
            raise QuerySyntaxError(str(exc)) from exc
        raise QueryNotAllowed(
            "This console is read-only: it runs SELECT, ASK, CONSTRUCT and "
            "DESCRIBE queries. Updates (INSERT, DELETE, LOAD, CLEAR, DROP) are "
            "not accepted — edit the ontology through the editor pages so the "
            "change is recorded and can be undone."
        ) from exc
    _algebra_guard(query.algebra)
    return PreparedQuery(query=query, select_star=not parsed[1].projection)


def _vars_in_query_order(algebra: Any) -> list[Any]:
    """Variables in the order the query first mentions them.

    Walked off the algebra rather than the query text so comments and string
    literals cannot affect it. ``triples`` (a BGP), ``values`` and the variable
    an ``Extend``/BIND introduces are the three places a variable is first
    bound, and each holds them in the order they were written.
    """
    seen: list[Any] = []

    def note(term: Any) -> None:
        if isinstance(term, Variable) and term not in seen:
            seen.append(term)

    for node in _walk(algebra):
        for triple in node.get("triples") or ():
            for term in triple:
                note(term)
        for binding in node.get("res") or ():
            if isinstance(binding, dict):
                for var in binding:
                    note(var)
        note(node.get("var"))
    return seen


def ordered_vars(algebra: Any, result_vars: Any, select_star: bool) -> list[Any]:
    """The result's variables, in a stable order.

    ``SELECT *`` gets its projection from a *set* in rdflib
    (``PV = list(VS)``), so its column order is whatever hash randomisation
    produced and differs between runs: the same query exported twice can come
    back with its columns rearranged. Those get query order instead.

    An explicit projection is returned untouched. It is already in the order
    the user wrote, and that order is *only* in ``PV`` — the algebra keeps no
    record of the SELECT clause, so reordering it against the pattern would
    turn ``SELECT ?o ?s`` into ``s, o``.

    Anything the walk did not reach sorts by name after everything it did, so
    a variable this cannot place is never dropped and never reintroduces the
    randomness this exists to remove.
    """
    result_vars = list(result_vars or [])
    if not select_star:
        return result_vars
    order = {var: i for i, var in enumerate(_vars_in_query_order(algebra))}
    return sorted(result_vars, key=lambda v: (order.get(v, len(order)), str(v)))


def query_form(query: Query) -> str:
    """The query's form, e.g. ``"SELECT"``. ``""`` when it cannot be read."""
    name = getattr(query.algebra, "name", "") or ""
    # rdflib names these SelectQuery / AskQuery / ConstructQuery / DescribeQuery.
    form = name.removesuffix("Query").upper()
    return form if form in READ_ONLY_FORMS else ""


def format_term(term: Node, prefixes: list[tuple[str, str]]) -> str:
    """Render one result term for a table cell.

    Shortens URIs against ``prefixes`` (longest namespace first, so the most
    specific binding wins). Deliberately does not go through rdflib's
    ``normalizeUri``/``compute_qname``, which *bind* a generated prefix as a
    side effect and would leave ``ns1:`` bindings on the user's ontology.
    """
    if isinstance(term, URIRef):
        text = str(term)
        for prefix, namespace in prefixes:
            if text.startswith(namespace) and len(text) > len(namespace):
                local = text[len(namespace) :]
                if not any(c in local for c in "/#"):
                    # The ontology's own namespace is bound to the empty
                    # prefix, and Turtle writes that as ``:Person`` — keep the
                    # colon so the console reads like the Source page rather
                    # than showing a bare, ambiguous local name.
                    return f"{prefix}:{local}"
        return text
    if isinstance(term, Literal):
        return f"{term}@{term.language}" if term.language else str(term)
    if isinstance(term, BNode):
        return f"_:{term}"
    return "" if term is None else str(term)


def sorted_prefixes(graph: Graph) -> list[tuple[str, str]]:
    """The graph's prefix bindings, longest namespace first."""
    return sorted(
        ((str(p), str(n)) for p, n in graph.namespaces()),
        key=lambda item: len(item[1]),
        reverse=True,
    )


@dataclass
class QueryResult:
    """The outcome of one run. Partial results are still results.

    ``timed_out`` and ``truncated`` are reported rather than raised so a query
    that was cut short still shows the rows it did produce.
    """

    form: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    ask: bool | None = None
    graph: Graph | None = None
    truncated: bool = False
    timed_out: bool = False
    elapsed: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self.rows)


def run_query(
    graph: Graph,
    query_text: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> QueryResult:
    """Run a read-only query against ``graph`` under a deadline and a row cap.

    Raises :class:`QueryError` for a query that is refused outright; a query
    that runs but is cut short comes back with ``timed_out``/``truncated`` set.
    """
    max_rows = max(1, min(int(max_rows), MAX_ROWS_CEILING))
    timeout_seconds = max(
        MIN_TIMEOUT_SECONDS, min(float(timeout_seconds), MAX_TIMEOUT_SECONDS)
    )
    prefixes = sorted_prefixes(graph)
    prepared = prepare(query_text, dict(graph.namespaces()))
    query = prepared.query
    form = query_form(query)

    started = time.monotonic()
    deadline = started + timeout_seconds
    # Same identifier as the source graph: the default store is context-aware,
    # so a wrapper graph with a fresh identifier addresses an empty context and
    # every query silently returns nothing.
    bounded = Graph(
        store=_DeadlineStore(graph.store, deadline), identifier=graph.identifier
    )

    result = QueryResult(form=form)
    try:
        answer = bounded.query(query)
        if form == "ASK":
            result.ask = bool(answer.askAnswer)
        elif form in ("CONSTRUCT", "DESCRIBE"):
            built = Graph()
            for prefix, namespace in graph.namespaces():
                built.bind(prefix, namespace)
            result.columns = ["subject", "predicate", "object"]
            for triple in answer.graph or ():
                if len(result.rows) >= max_rows:
                    result.truncated = True
                    break
                if time.monotonic() > deadline:
                    result.timed_out = True
                    break
                built.add(triple)
                result.rows.append([format_term(t, prefixes) for t in triple])
            result.graph = built
        else:
            # Stable column order: rdflib derives SELECT * from a set, so the
            # order is otherwise randomised per run.
            columns = ordered_vars(query.algebra, answer.vars, prepared.select_star)
            result.columns = [str(v) for v in columns]
            for row in answer:
                if len(result.rows) >= max_rows:
                    result.truncated = True
                    break
                if time.monotonic() > deadline:
                    result.timed_out = True
                    break
                # A SELECT result iterates ResultRow, which the union type on
                # Result.__iter__ (shared with ASK and CONSTRUCT) does not say.
                bindings = cast(ResultRow, row)
                result.rows.append(
                    [format_term(bindings[v], prefixes) for v in columns]
                )
    except QueryTimeout:
        result.timed_out = True
    except QueryError:
        raise
    except Exception as exc:
        # An evaluation failure belongs to the user's query (a bad datatype in a
        # FILTER, say), so it is reported as one rather than as an app crash.
        raise QueryError(str(exc)) from exc
    result.elapsed = time.monotonic() - started
    return result


def rows_to_csv(columns: list[str], rows: list[list[str]]) -> str:
    """Result rows as CSV text, for download."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()

"""Run one SPARQL query on Oxigraph in its own process.

Started by :func:`orionbelt_ontology_builder.sparql_oxigraph.run` as
``python -m orionbelt_ontology_builder.sparql_worker``. On stdin: one line of
JSON with the query, the prefixes and the row limit, then the graph as
N-Triples to the end. On stdout: one JSON line per batch of results, and a
last one when the query is done.

pyoxigraph's ``Store.query`` has no timeout and cannot be cancelled, so the
deadline is the caller killing this process. Results go out in batches as
they are produced, so a query stopped at its deadline still shows what it had
found by then.

Only pyoxigraph is imported, not rdflib or the app, so the process starts in
a few hundredths of a second.
"""

import json
import sys
import time
from typing import Any

import pyoxigraph as ox

_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

#: A batch goes out when it has this many results or is this old, whichever
#: comes first.
_BATCH_SIZE = 200
_BATCH_SECONDS = 0.2


def _term(term: Any) -> list[str] | None:
    """A term as ``["u", iri]``, ``["b", label]`` or
    ``["l", value, language, datatype]``; None for an unbound variable."""
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        return ["u", term.value]
    if isinstance(term, ox.BlankNode):
        return ["b", term.value]
    if isinstance(term, ox.Literal):
        if term.language:
            return ["l", term.value, term.language, ""]
        datatype = term.datatype.value
        return ["l", term.value, "", "" if datatype == _XSD_STRING else datatype]
    return ["t", str(term)]  # an RDF 1.2 triple term, shown as written


def main() -> None:
    out = sys.stdout
    # Whatever a library prints goes to stderr, not into the replies.
    sys.stdout = sys.stderr

    def reply(message: dict[str, Any]) -> None:
        out.write(json.dumps(message) + "\n")
        out.flush()

    stdin = sys.stdin.buffer
    request = json.loads(stdin.readline())
    store = ox.Store()
    store.bulk_load(stdin, format=ox.RdfFormat.N_TRIPLES)
    try:
        answer = store.query(request["query"], prefixes=request["prefixes"])
        if isinstance(answer, ox.QueryBoolean):
            reply({"ask": bool(answer)})
            return
        if isinstance(answer, ox.QuerySolutions):
            names = [variable.value for variable in answer.variables]
            reply({"vars": names})
            key = "rows"
            items: Any = (
                [_term(solution[name]) for name in names] for solution in answer
            )
        else:
            key = "triples"
            items = (
                [_term(t.subject), _term(t.predicate), _term(t.object)] for t in answer
            )
        batch: list[Any] = []
        sent = 0
        flushed = time.monotonic()
        for item in items:
            if sent + len(batch) == request["max_rows"]:
                if batch:
                    reply({key: batch})
                reply({"done": True, "truncated": True})
                return
            batch.append(item)
            if len(batch) >= _BATCH_SIZE or time.monotonic() - flushed > _BATCH_SECONDS:
                reply({key: batch})
                sent += len(batch)
                batch = []
                flushed = time.monotonic()
        if batch:
            reply({key: batch})
        reply({"done": True, "truncated": False})
    except Exception as exc:  # noqa: BLE001 - the app runs the query on rdflib instead
        reply({"refused": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()

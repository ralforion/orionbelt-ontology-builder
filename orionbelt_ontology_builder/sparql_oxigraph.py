"""Run a SPARQL query on Oxigraph, in a worker process killed at the deadline.

rdflib evaluates SPARQL in pure Python; on a 213k-triple ontology the
page's "ancestors at any depth" example took 10.9 s, and Oxigraph answers it
in 0.9 s. But ``Store.query`` cannot be timed out or cancelled, and the
query console promises that no query can hang the app, so the query runs in
:mod:`.sparql_worker` and the process is killed at the deadline.

The worker gets the graph as N-Triples on every run, and parses it in a
fraction of the time rdflib takes to query it: 0.2 s at 213k triples, with
another 0.35 s for the app to write it. It is gone when the query is: no
second copy of the ontology outlives the query, and none can fall out of
step with an edit.

Oxigraph lowercases language tags. The tags as the ontology writes them are
read off the same N-Triples text, so results show ``@en-GB`` rather than
``@en-gb``; :func:`language_spellings` says when that cannot be done.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rdflib import BNode, Literal, URIRef
from rdflib.term import Node

from . import worker_process

#: A language tag at the end of an N-Triples line: the object's, as written.
#: Inside a literal, a line end is written ``\n``, so a match is never there.
_NT_LANGUAGE_TAG = re.compile(r'"@([A-Za-z]+(?:-[A-Za-z0-9]+)*) \.$', re.MULTILINE)

_Triple = tuple[Node, Node, Node]


class Refused(Exception):
    """Oxigraph did not run the query to its end. rdflib should run it."""


@dataclass
class Answer:
    """What Oxigraph answered, in rdflib terms, before any formatting."""

    variables: list[str] = field(default_factory=list)
    rows: list[list[Node | None]] = field(default_factory=list)
    triples: list[_Triple] = field(default_factory=list)
    ask: bool | None = None
    truncated: bool = False
    timed_out: bool = False


def language_spellings(nt: str) -> dict[str, str] | None:
    """Each language tag in the N-Triples text ``nt``, by its lowercase form,
    as written; None when one tag is written two ways (``en-GB`` and
    ``en-gb``), which Oxigraph cannot tell apart."""
    spellings: dict[str, str] = {}
    for tag in set(_NT_LANGUAGE_TAG.findall(nt)):
        if spellings.setdefault(tag.lower(), tag) != tag:
            return None
    return spellings


def run(
    nt: str,
    query: str,
    prefixes: dict[str, str],
    *,
    deadline: float,
    max_rows: int,
    spellings: dict[str, str],
) -> Answer:
    """Run ``query`` over the graph written as ``nt`` until ``deadline`` (a
    ``time.monotonic()`` value), keeping at most ``max_rows`` results.

    A query stopped at the deadline comes back with ``timed_out`` set and
    what it had found by then. Raises :class:`Refused` when Oxigraph rejects
    the query or the worker stops without finishing.
    """
    header = json.dumps({"query": query, "prefixes": prefixes, "max_rows": max_rows})
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    stderr_tail: deque[str] = deque(maxlen=5)
    worker = worker_process.start("orionbelt_ontology_builder.sparql_worker")
    assert worker.stdin and worker.stdout and worker.stderr
    threads = [
        threading.Thread(target=target, args=args, daemon=True)
        for target, args in (
            (worker_process.send, (worker.stdin, header + "\n" + nt)),
            (worker_process.receive, (worker.stdout, events)),
            (stderr_tail.extend, (worker.stderr,)),
        )
    ]
    for thread in threads:
        thread.start()

    answer = Answer()
    bnodes: dict[str, BNode] = {}

    def term(encoded: list[str]) -> Node:
        kind, value = encoded[0], encoded[1]
        if kind == "u":
            return URIRef(value)
        if kind == "b":
            if value not in bnodes:
                bnodes[value] = BNode()
            return bnodes[value]
        if kind == "l":
            language, datatype = encoded[2], encoded[3]
            if language:
                return Literal(value, lang=spellings.get(language, language))
            return Literal(value, datatype=URIRef(datatype) if datatype else None)
        return Literal(value)  # an RDF 1.2 triple term, shown as written

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                answer.timed_out = True
                return answer
            try:
                event = events.get(timeout=remaining)
            except queue.Empty:
                continue
            if event is None:
                worker.wait()
                threads[-1].join(timeout=5)  # the last of stderr, read to its end
                last = stderr_tail[-1].strip() if stderr_tail else "no output"
                raise Refused(f"the query worker stopped ({last})")
            if "refused" in event:
                raise Refused(event["refused"])
            if "ask" in event:
                answer.ask = event["ask"]
                return answer
            if "vars" in event:
                answer.variables = event["vars"]
            elif "rows" in event:
                answer.rows.extend(
                    [None if t is None else term(t) for t in row]
                    for row in event["rows"]
                )
            elif "triples" in event:
                answer.triples.extend(
                    (term(s), term(p), term(o)) for s, p, o in event["triples"]
                )
            elif "done" in event:
                answer.truncated = event["truncated"]
                return answer
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()

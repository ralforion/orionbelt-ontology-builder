"""Run the reasoning closure in a worker process.

owlrl's RDFS closure takes minutes on a 43k-triple ontology, and the closure
repeats passes until nothing new appears (``scripts/bench_large.py`` times it).
Run in the Streamlit process, that froze the app for the whole time with no
way out. In a worker (:mod:`.reasoning_worker`):

* the caller's ``progress`` callback is called a few times a second while it
  waits. Under Streamlit that call is where a script the user has moved on
  from is stopped, and the exception unwinds through here and kills the
  worker, so a Cancel button needs nothing more than to be clickable;
* a deadline kills a closure that runs away;
* the ontology is untouched until the closure is complete: the worker sends
  back the triples it added and removed, and the caller applies them.

The graph travels as N-Triples. Blank nodes keep their labels both ways (see
:class:`_SameLabels`), so a triple inferred about a restriction comes back
about the same blank node, and a blank node the closure creates keeps the
unique label rdflib gave it.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import IO, Any

from rdflib import Graph
from rdflib.term import Node

from . import worker_process

#: How long a closure may run before its worker is stopped.
REASONING_DEADLINE_SECONDS = 600.0

#: How often ``progress`` is called while the worker runs.
_POLL_SECONDS = 0.25

_Triple = tuple[Node, Node, Node]


class ReasoningTimeout(Exception):
    """The closure did not finish within its deadline. Nothing was changed."""


class ReasoningFailed(RuntimeError):
    """The worker stopped without a result. Nothing was changed."""


@dataclass(frozen=True)
class ClosureChange:
    """What a closure did to the graph it was given."""

    added: list[_Triple]
    removed: list[_Triple]


class _SameLabels(dict[str, Any]):
    """A blank node context for rdflib's N-Triples parser that keeps labels.

    The parser asks it for the node a label stands for, and makes a fresh one
    when there is none. Answering with the label itself gives ``BNode(label)``,
    which is equal to the node written under that label: the one in the
    app's graph, on whichever side of the pipe the parse happens.
    """

    def get(self, key, default=None):  # type: ignore[override]
        return key


def to_nt(triples: Iterable[_Triple]) -> str:
    """``triples`` as N-Triples, blank nodes written under their own labels."""
    graph = Graph()
    for triple in triples:
        graph.add(triple)
    return graph.serialize(format="nt")


def from_nt(text: str) -> Graph:
    """Parse N-Triples, reading each blank node label as that same node."""
    graph = Graph()
    graph.parse(data=text, format="nt", bnode_context=_SameLabels())
    return graph


def close_in_worker(
    graph: Graph,
    profile: str,
    *,
    deadline_s: float = REASONING_DEADLINE_SECONDS,
    progress: Callable[[int, int], None] | None = None,
) -> ClosureChange:
    """Reason over a copy of ``graph`` in a worker and return what changed.

    ``progress(pass_number, triples_added_so_far)`` is called every
    :data:`_POLL_SECONDS` while the worker runs, with pass 0 until the worker
    has read the graph. Whatever it raises propagates after the worker is
    killed. Raises :class:`ReasoningTimeout` once ``deadline_s`` has passed,
    and :class:`ReasoningFailed` when the worker stops without a result.
    """
    request = json.dumps({"profile": profile, "data_nt": graph.serialize(format="nt")})
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    stderr_tail: deque[str] = deque(maxlen=5)
    worker = worker_process.start("orionbelt_ontology_builder.reasoning_worker")
    assert worker.stdin and worker.stdout and worker.stderr
    threads = [
        threading.Thread(target=target, args=args, daemon=True)
        for target, args in (
            (_send, (worker.stdin, request)),
            (_receive, (worker.stdout, events)),
            (stderr_tail.extend, (worker.stderr,)),
        )
    ]
    for thread in threads:
        thread.start()
    del request  # freed once the writer is done, not held for the whole run

    deadline = time.monotonic() + deadline_s
    pass_number = added = 0
    try:
        while True:
            if progress is not None:
                progress(pass_number, added)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReasoningTimeout(
                    f"Reasoning did not finish within {deadline_s:g} seconds."
                )
            try:
                event = events.get(timeout=min(_POLL_SECONDS, remaining))
            except queue.Empty:
                continue
            if event is None:
                worker.wait()
                threads[-1].join(timeout=5)  # the last of stderr, read to its end
                last = stderr_tail[-1].strip() if stderr_tail else "no output"
                raise ReasoningFailed(f"the reasoning worker stopped ({last})")
            if "failure" in event:
                raise ReasoningFailed(event["failure"])
            if "pass" in event:
                pass_number, added = event["pass"], event["added"]
                continue
            return ClosureChange(
                added=list(from_nt(event["added_nt"])),
                removed=list(from_nt(event["removed_nt"])),
            )
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()


def _send(stream: IO[str], text: str) -> None:
    """Write the request and close the pipe, so the worker sees its end."""
    try:
        stream.write(text)
        stream.close()
    except OSError:
        pass  # the worker is gone; the reader reports why


def _receive(stream: IO[str], events: queue.Queue[dict[str, Any] | None]) -> None:
    """Queue each JSON line the worker writes, then ``None`` at its end."""
    try:
        for line in stream:
            try:
                events.put(json.loads(line))
            except ValueError:
                continue  # not one of ours
    except OSError:
        pass
    finally:
        events.put(None)

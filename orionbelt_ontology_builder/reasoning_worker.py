"""Run one reasoning closure in its own process.

Started by :func:`orionbelt_ontology_builder.reasoning.close_in_worker` as
``python -m orionbelt_ontology_builder.reasoning_worker``: the request as JSON
on stdin, then one JSON line on stdout before each pass and a last one with
the triples the closure added and removed.
"""

import json
import sys
from typing import Any

from orionbelt_ontology_builder.ontology_manager import reason_to_fixpoint
from orionbelt_ontology_builder.reasoning import from_nt, to_nt


def main() -> None:
    out = sys.stdout
    # Whatever a library prints goes to stderr, not into the replies.
    sys.stdout = sys.stderr

    def reply(message: dict[str, Any]) -> None:
        out.write(json.dumps(message) + "\n")
        out.flush()

    request = json.load(sys.stdin)
    graph = from_nt(request["data_nt"])
    before = set(graph)
    try:
        reason_to_fixpoint(
            graph,
            request["profile"],
            progress=lambda n, added: reply({"pass": n, "added": added}),
        )
    except Exception as exc:  # noqa: BLE001 - reported to the user, not raised
        reply({"failure": f"{type(exc).__name__}: {exc}"})
        return
    after = set(graph)
    reply({"added_nt": to_nt(after - before), "removed_nt": to_nt(before - after)})


if __name__ == "__main__":
    main()

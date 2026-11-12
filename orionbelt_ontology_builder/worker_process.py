"""Start one of the package's worker modules in its own Python process.

The SHACL check (:mod:`.shacl_worker`), the reasoning closure
(:mod:`.reasoning_worker`) and a SPARQL query on Oxigraph
(:mod:`.sparql_worker`) run this way: a plain subprocess rather than
``multiprocessing``, whose ``spawn`` start would re-import the parent's
``__main__``, and under Streamlit that is the app script itself. Killing the
process is the whole of the cleanup when a deadline passes or the user moves
on.
"""

import json
import os
import queue
import subprocess
import sys
from pathlib import Path
from typing import IO, Any


def start(module: str) -> subprocess.Popen[str]:
    """Run ``python -m module`` with text pipes on all three streams.

    The package's own location goes first on the path, so the worker imports
    this copy of it whether or not it is installed (a checkout run with
    ``streamlit run``).
    """
    env = dict(os.environ)
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root, *filter(None, [env.get("PYTHONPATH")])]
    )
    return subprocess.Popen(
        [sys.executable, "-m", module],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )


def send(stream: IO[str], text: str) -> None:
    """Write the request and close the pipe, so the worker sees its end."""
    try:
        stream.write(text)
        stream.close()
    except OSError:
        pass  # the worker is gone; the reader reports why


def receive(stream: IO[str], events: queue.Queue[dict[str, Any] | None]) -> None:
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

"""Run one pySHACL validation in its own process.

Started by :func:`orionbelt_ontology_builder.shacl._in_worker` as
``python -m orionbelt_ontology_builder.shacl_worker``: a request as JSON on
stdin, the result as JSON on stdout. A plain subprocess rather than
``multiprocessing``, whose ``spawn`` start would re-import the parent's
``__main__``, and under Streamlit that is the app script itself.
"""

import json
import sys

from orionbelt_ontology_builder.shacl import _validate_in_worker


def main() -> None:
    request = json.load(sys.stdin)
    result = _validate_in_worker(
        request["data_nt"],
        request["shapes_nt"],
        [(prefix, namespace) for prefix, namespace in request["prefixes"]],
        request["meta"],
    )
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()

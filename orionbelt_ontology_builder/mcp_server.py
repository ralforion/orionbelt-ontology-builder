"""MCP server for the OrionBelt Ontology Builder: ask the ontology, and grow it.

A separate process beside the app, and only a client of the app's HTTP API
(:mod:`.api.rest`): it never loads or edits a graph itself, so whatever an
agent does goes through the same lock and the same undo history as the UI,
and shows up in the open app within a couple of seconds.

Run the app with the API on, then point an MCP client at this server::

    orionbelt-ontology-builder --api
    orionbelt-ontology-builder-mcp                # stdio (Claude Desktop, Claude Code)
    orionbelt-ontology-builder-mcp --http --port 8766   # streamable HTTP

The server finds the API in ``~/.orionbelt_ontology_builder/api.json``, which
the app rewrites on every start, so a restarted app (and its new token) is
picked up without restarting the MCP server. ``ORIONBELT_API_URL`` and
``ORIONBELT_API_TOKEN`` (or ``--api-url`` / ``--api-token``) override it, for
an app in Docker or on another host. ``ORIONBELT_MCP_HTTP``, ``_HOST`` and
``_PORT`` stand for the flags above, and every one of these variables can also
be set in a ``.env`` file (see :mod:`.env_file`).

The tool surface is kept small on purpose: eight tools to ask, three to
change. Every change is one atomic batch and one undo step; ``dry_run``
shows the diff first.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import env_file
from .api.server import DEFAULT_HOST, DEFAULT_PORT, DISCOVERY_NAME
from .api.service import EDIT_OPS
from .ontology_manager import OntologyManager

ENV_URL = "ORIONBELT_API_URL"
ENV_TOKEN = "ORIONBELT_API_TOKEN"
ENV_MCP_HTTP = "ORIONBELT_MCP_HTTP"
ENV_MCP_HOST = "ORIONBELT_MCP_HOST"
ENV_MCP_PORT = "ORIONBELT_MCP_PORT"

#: Set from the command line; otherwise the environment, then the discovery file.
_override: dict[str, str] = {}
#: Extra ``httpx.AsyncClient`` arguments; the tests route calls into the app here.
_client_options: dict[str, Any] = {}


def _discovery_path() -> Path:
    # Not local_store.data_dir(): that creates the directory, and reading
    # where the app wrote must not.
    return Path.home() / ".orionbelt_ontology_builder" / DISCOVERY_NAME


def _endpoint() -> tuple[str, str]:
    url = _override.get("url") or os.environ.get(ENV_URL)
    token = _override.get("token") or os.environ.get(ENV_TOKEN)
    if not (url and token):
        try:
            found = json.loads(_discovery_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found = {}
        url = url or found.get("url")
        token = token or found.get("token")
    if not (url and token):
        raise ToolError(
            "The Ontology Builder API is not running. Start the app with "
            "`orionbelt-ontology-builder --api` (or set ORIONBELT_API_URL and "
            "ORIONBELT_API_TOKEN)."
        )
    return url.rstrip("/"), token


async def _call(
    method: str, path: str, *, params: dict | None = None, body: dict | None = None
) -> Any:
    url, token = _endpoint()
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=180.0, **_client_options) as client:
            resp = await client.request(
                method,
                f"{url}/v1{path}",
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        raise ToolError(
            f"Cannot reach the Ontology Builder API at {url} ({e}). "
            "Is the app running with --api?"
        ) from e
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = {"message": resp.text}
        raise ToolError(json.dumps({"status": resp.status_code, **detail}))
    return resp.json()


def _op_signatures() -> str:
    """One line per edit op, with the engine method's own arguments."""
    lines = []
    for op, method in EDIT_OPS.items():
        params = []
        for p in list(
            inspect.signature(getattr(OntologyManager, method)).parameters.values()
        )[1:]:
            name = "range" if p.name == "range_" else p.name
            params.append(name if p.default is inspect.Parameter.empty else f"{name}?")
        lines.append(f"- {op}({', '.join(params)})")
    return "\n".join(lines)


INSTRUCTIONS = """\
Tools onto the ontology (OWL + SKOS) open in the OrionBelt Ontology Builder.

To answer a question: start with ontology_overview, locate things with
find_entities or list_entities, read them with describe_entity, and use
get_hierarchy, find_paths (how two things are connected) or sparql_query for
the rest. Answer from what the tools return; say when the ontology does not
say something.

To change the ontology: read first, then send all related changes as one
edit_ontology batch (or merge_turtle for a larger piece written as Turtle),
with dry_run=true to check the diff, then again with dry_run=false and the
expected_revision you read. Each applied batch is one undo step the user can
take back in the app; use undo_redo to take back your own mistake. Run
check_ontology after larger changes.
"""

mcp = MCPServer(
    name="orionbelt-ontology-builder",
    title="OrionBelt Ontology Builder",
    instructions=INSTRUCTIONS,
)

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)

Kind = Literal[
    "class",
    "object_property",
    "data_property",
    "individual",
    "concept",
    "concept_scheme",
]


@mcp.tool(annotations=_READ)
async def ontology_overview() -> dict[str, Any]:
    """Metadata, counts, prefixes, top-level classes, concept schemes and the
    current revision of the open ontology. Call this first."""
    return await _call("GET", "/overview")


@mcp.tool(annotations=_READ)
async def find_entities(
    query: str, kind: Kind | None = None, limit: int = 25
) -> dict[str, Any]:
    """Search classes, properties, individuals and SKOS concepts by name,
    label, synonym (altLabel), comment or any annotation. Case-insensitive,
    partial match."""
    return await _call(
        "GET", "/entities", params={"q": query, "kind": kind, "limit": limit}
    )


@mcp.tool(annotations=_READ)
async def list_entities(
    kind: Kind,
    parent: str | None = None,
    scheme: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Page through one kind of entity. parent: direct subclasses of a class
    (kind=class) or members of a class (kind=individual). scheme: concepts of
    one concept scheme."""
    return await _call(
        "GET",
        "/entities",
        params={
            "kind": kind,
            "parent": parent,
            "scheme": scheme,
            "offset": offset,
            "limit": limit,
        },
    )


@mcp.tool(annotations=_READ)
async def describe_entity(ref: str) -> dict[str, Any]:
    """Everything about one entity: kind, labels, comment, parents/children,
    annotations, restrictions, domain/range, members and where it is used.
    ref is a local name, a prefixed name (prov:Agent) or a full URI."""
    return await _call("GET", f"/entities/{quote(ref, safe='')}")


@mcp.tool(annotations=_READ)
async def get_hierarchy(
    kind: Literal["class", "concept"] = "class",
    root: str | None = None,
    scheme: str | None = None,
    depth: int = 3,
) -> dict[str, Any]:
    """The subclass tree (kind=class) or SKOS broader/narrower tree
    (kind=concept), from root or from all top nodes, to depth levels. Each
    node has its name and uri. A node whose children are cut off, by depth
    or by the limit on nodes per answer, carries 'more': the number not
    shown; with the limit reached, truncated is true and 'more_roots' counts
    roots left out. Pass root to see a cut-off part."""
    return await _call(
        "GET",
        "/hierarchy",
        params={"kind": kind, "root": root, "scheme": scheme, "depth": depth},
    )


@mcp.tool(annotations=_READ)
async def find_paths(
    source: str,
    target: str,
    max_paths: int = 3,
    edge_kinds: list[str] | None = None,
) -> dict[str, Any]:
    """How two classes, individuals or concepts are connected in the knowledge
    graph: up to max_paths shortest routes, each a list of hops. edge_kinds
    limits the links walked: subclass, class_relations, object_properties,
    restrictions, individual_types, individual_relations, skos, triples."""
    return await _call(
        "GET",
        "/paths",
        params={
            "source": source,
            "target": target,
            "max_paths": max_paths,
            "edge_kinds": ",".join(edge_kinds) if edge_kinds else None,
        },
    )


@mcp.tool(annotations=_READ)
async def sparql_query(
    query: str, max_rows: int = 200, timeout_seconds: float = 10.0
) -> dict[str, Any]:
    """Run a read-only SPARQL query (SELECT, ASK, CONSTRUCT, DESCRIBE). The
    ontology's prefixes are predeclared. Updates and SERVICE are refused."""
    return await _call(
        "POST",
        "/sparql",
        body={"query": query, "max_rows": max_rows, "timeout_seconds": timeout_seconds},
    )


@mcp.tool(annotations=_READ)
async def check_ontology(
    checks: list[Literal["validate", "skos"]] | None = None, limit: int = 100
) -> dict[str, Any]:
    """Run the app's checks: 'validate' (missing labels, domains/ranges,
    cycles, undeclared references ...) and 'skos' (SKOS integrity)."""
    return await _call(
        "POST", "/check", body={"checks": checks or ["validate"], "limit": limit}
    )


@mcp.tool(annotations=_WRITE)
async def infer(
    profile: Literal["rdfs", "rdfs-lean", "owl-rl", "owl-rl-ext"] = "rdfs",
    apply: bool = False,
    deadline_seconds: float = 60.0,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """What a reasoner infers from the ontology (a sample of the inferred
    triples and their count). With apply=true the inferred triples are added
    as one undo step; leave it false to only look."""
    return await _call(
        "POST",
        "/reason",
        body={
            "profile": profile,
            "apply": apply,
            "deadline_seconds": deadline_seconds,
            "expected_revision": expected_revision,
        },
    )


EDIT_DESCRIPTION = f"""\
Apply a batch of edits atomically, as one undo step; on any error nothing is
changed. Each operation is {{"op": <name>, ...arguments}}. Entities are named
by local name (in the base namespace) or full URI. The entity an update_*,
rename_* or delete_* changes may also be a prefixed name or the local name
of an entity in another namespace; a local name two entities share is
refused, so pass the URI. dry_run=true returns the diff without keeping it. Pass the
revision you read as expected_revision to refuse the batch if the ontology
changed meanwhile. New entities go into the ontology's base namespace unless
you pass namespace.

Operations (? = optional):
{_op_signatures()}

Values:
- restriction_type: {", ".join(OntologyManager.RESTRICTION_TYPES)} (on_class for the qualified ones)
- add_class_relation relation_type: {", ".join(OntologyManager.CLASS_RELATIONS)}
- add_property_relation relation_type: {", ".join(OntologyManager.PROPERTY_RELATIONS)}
- add_individual_relation relation_type: {", ".join(OntologyManager.INDIVIDUAL_RELATIONS)}
- add_concept_relation relation: {", ".join(OntologyManager.SKOS_RELATIONS)}
- assert_property: a property value on an individual; is_object_property=false for a literal
- add_data_property range: an XSD name such as string, integer, decimal, boolean, date, dateTime
"""


@mcp.tool(annotations=_WRITE, description=EDIT_DESCRIPTION)
async def edit_ontology(
    operations: list[dict[str, Any]],
    dry_run: bool = False,
    expected_revision: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    return await _call(
        "POST",
        "/edits",
        body={
            "operations": operations,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
            "label": label,
        },
    )


@mcp.tool(annotations=_WRITE)
async def merge_turtle(
    data: str,
    dry_run: bool = True,
    strategy: Literal["merge", "merge_overwrite"] = "merge",
    format: str = "turtle",
    expected_revision: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Merge RDF (Turtle by default) into the ontology as one undo step: the
    way to add a larger, connected piece of model at once. Declare your
    prefixes. Defaults to dry_run=true, which returns the diff and any
    conflicting values; send again with dry_run=false to apply.
    merge_overwrite lets incoming values replace conflicting ones."""
    return await _call(
        "POST",
        "/merge",
        body={
            "data": data,
            "format": format,
            "strategy": strategy,
            "dry_run": dry_run,
            "expected_revision": expected_revision,
            "label": label,
        },
    )


@mcp.tool(annotations=_WRITE)
async def undo_redo(
    action: Literal["history", "undo", "redo"] = "history",
) -> dict[str, Any]:
    """The app's undo history (action=history), or undo / redo one step. The
    history is shared with the user's own edits in the app."""
    if action == "history":
        return await _call("GET", "/history")
    return await _call("POST", f"/history/{action}")


@mcp.resource(
    "ontology://current.ttl",
    name="current-ontology",
    description="The open ontology, as Turtle.",
    mime_type="text/turtle",
)
async def current_ontology() -> str:
    return (await _call("GET", "/export", params={"format": "turtle"}))["data"]


def run(argv: list[str] | None = None) -> None:
    """Console entry point: ``orionbelt-ontology-builder-mcp``.

    Every flag has an ``ORIONBELT_*`` variable, which can also come from a
    ``.env`` file (see :mod:`.env_file`); a flag wins over both.
    """
    # Read before the parser is built: its defaults come from the variables.
    env_file.load()
    parser = argparse.ArgumentParser(
        prog="orionbelt-ontology-builder-mcp",
        description="MCP server onto a running OrionBelt Ontology Builder.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        default=env_file.flag(ENV_MCP_HTTP),
        help=f"serve streamable HTTP, not stdio (default: ${ENV_MCP_HTTP})",
    )
    parser.add_argument("--host", default=os.environ.get(ENV_MCP_HOST, DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=os.environ.get(ENV_MCP_PORT, DEFAULT_PORT + 1)
    )
    parser.add_argument("--api-url", help=f"default: ${ENV_URL} or the discovery file")
    parser.add_argument(
        "--api-token", help=f"default: ${ENV_TOKEN} or the discovery file"
    )
    args = parser.parse_args(argv)
    # httpx logs every request at INFO; on stdio that is noise in the client's log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.api_url:
        _override["url"] = args.api_url
    if args.api_token:
        _override["token"] = args.api_token
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    run()

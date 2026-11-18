"""The HTTP API: a thin FastAPI layer over :class:`~.service.OntologyService`.

Everything under ``/v1`` needs ``Authorization: Bearer <token>``, except
``/v1/health``. Errors come back as ``{"error", "message", ...}`` with the
status :class:`~.service.ServiceError` names (400, 404, 409, 503).

The request bodies are deliberately loose (``dict`` operations, not one model
per op): the engine method signatures are the schema, and the service checks
every operation's arguments against them before it runs anything.
"""

# No ``from __future__ import annotations``: FastAPI resolves the dependency
# annotations at runtime, and ``auth``'s refers to a local of create_app.
import secrets
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ..ui import APP_VERSION
from .service import KINDS, OntologyService, ServiceError

Kind = Literal[
    "class",
    "object_property",
    "data_property",
    "individual",
    "concept",
    "concept_scheme",
]


class SparqlRequest(BaseModel):
    query: str
    max_rows: int = 200
    timeout_seconds: float = 10.0


class CheckRequest(BaseModel):
    checks: list[Literal["validate", "skos"]] = ["validate"]
    limit: int = 200


class EditRequest(BaseModel):
    operations: list[dict[str, Any]] = Field(min_length=1)
    dry_run: bool = False
    expected_revision: str | None = None
    label: str | None = None


class MergeRequest(BaseModel):
    data: str
    format: str = "turtle"
    strategy: Literal["merge", "merge_overwrite"] = "merge"
    dry_run: bool = True
    expected_revision: str | None = None
    label: str | None = None


class ReasonRequest(BaseModel):
    profile: str = "rdfs"
    apply: bool = False
    deadline_seconds: float = 60.0
    expected_revision: str | None = None


def create_app(service: OntologyService, token: str) -> FastAPI:
    """The API app for ``service``, guarded by ``token``."""
    app = FastAPI(
        title="OrionBelt Ontology Builder API",
        version=APP_VERSION,
        description=(
            "Query and edit the ontology open in the OrionBelt Ontology "
            "Builder. Edits land in the app's undo history."
        ),
    )
    bearer = HTTPBearer(auto_error=False)

    def auth(
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if creds is None or not secrets.compare_digest(creds.credentials, token):
            raise HTTPException(status_code=401, detail="Missing or wrong token.")

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": APP_VERSION}

    guarded = [Depends(auth)]

    @app.get("/v1/overview", dependencies=guarded)
    def overview() -> dict[str, Any]:
        return service.overview()

    @app.get("/v1/entities", dependencies=guarded)
    def entities(
        kind: Kind | None = None,
        q: str | None = None,
        parent: str | None = None,
        scheme: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if q:
            return service.find_entities(q, kind=kind, limit=limit)
        if kind is None:
            raise ServiceError(
                "Pass kind (to list) or q (to search).", kinds=list(KINDS)
            )
        return service.list_entities(
            kind, parent=parent, scheme=scheme, offset=offset, limit=limit
        )

    @app.get("/v1/entities/{ref:path}", dependencies=guarded)
    def entity(ref: str) -> dict[str, Any]:
        return service.describe(ref)

    @app.get("/v1/hierarchy", dependencies=guarded)
    def hierarchy(
        kind: Literal["class", "concept"] = "class",
        root: str | None = None,
        scheme: str | None = None,
        depth: int = 3,
    ) -> dict[str, Any]:
        return service.hierarchy(kind, root=root, scheme=scheme, depth=depth)

    @app.get("/v1/paths", dependencies=guarded)
    def paths(
        source: str, target: str, max_paths: int = 3, edge_kinds: str | None = None
    ) -> dict[str, Any]:
        kinds = [k.strip() for k in edge_kinds.split(",")] if edge_kinds else None
        return service.paths(source, target, max_paths=max_paths, edge_kinds=kinds)

    @app.post("/v1/sparql", dependencies=guarded)
    def sparql(body: SparqlRequest) -> dict[str, Any]:
        return service.sparql(
            body.query, max_rows=body.max_rows, timeout_seconds=body.timeout_seconds
        )

    @app.post("/v1/check", dependencies=guarded)
    def check(body: CheckRequest) -> dict[str, Any]:
        return service.check(list(body.checks), limit=body.limit)

    @app.post("/v1/reason", dependencies=guarded)
    def reason(body: ReasonRequest) -> dict[str, Any]:
        return service.reason(
            body.profile,
            apply=body.apply,
            deadline_seconds=body.deadline_seconds,
            expected_revision=body.expected_revision,
        )

    @app.post("/v1/edits", dependencies=guarded)
    def edits(body: EditRequest) -> dict[str, Any]:
        return service.edit(
            body.operations,
            dry_run=body.dry_run,
            expected_revision=body.expected_revision,
            label=body.label,
        )

    @app.post("/v1/merge", dependencies=guarded)
    def merge(body: MergeRequest) -> dict[str, Any]:
        return service.merge_rdf(
            body.data,
            fmt=body.format,
            strategy=body.strategy,
            dry_run=body.dry_run,
            expected_revision=body.expected_revision,
            label=body.label,
        )

    @app.get("/v1/history", dependencies=guarded)
    def history() -> dict[str, Any]:
        return service.history()

    @app.post("/v1/history/undo", dependencies=guarded)
    def undo() -> dict[str, Any]:
        return service.undo()

    @app.post("/v1/history/redo", dependencies=guarded)
    def redo() -> dict[str, Any]:
        return service.redo()

    @app.get("/v1/export", dependencies=guarded)
    def export(
        format: str = "turtle",
        content: Literal["all", "ontology", "shapes"] = "all",
    ) -> dict[str, Any]:
        return service.export(format, content)

    return app

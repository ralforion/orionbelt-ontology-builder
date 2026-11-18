"""Query and edit operations on the working ontology, for the HTTP API.

Plain Python on purpose: no web framework and no Streamlit here, so the same
operations can be tested on a bare :class:`OntologyManager` and served by any
front (the REST app today). Every method returns JSON-ready dicts and lists.

Two rules hold for every call:

* **One lock.** A call runs while holding the workspace's lock, the same one
  a Streamlit run holds (see :mod:`.bridge`), so the API and the UI never
  edit the graph at the same time. A call that cannot get the lock in time
  fails with :class:`Busy` rather than queueing behind a long UI action.
* **A batch is one undo step, or nothing.** :meth:`OntologyService.edit` and
  :meth:`OntologyService.merge_rdf` apply all their changes or none, and what
  they keep becomes one step in the same undo history the UI uses, so a user
  can take back an agent's edit with the sidebar's Undo button.
"""

from __future__ import annotations

import contextlib
import inspect
import threading
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from rdflib import Graph, Literal, URIRef

from ..ontology_manager import (
    IMPORT_MERGE,
    IMPORT_MERGE_OVERWRITE,
    PATH_EDGE_KINDS,
    PATH_MAX_ROUTES,
    REASONING_PROFILES,
    OntologyManager,
    PathSearchLimitError,
    UndoManager,
)
from ..sparql import QueryError, run_query

#: Most rows of a listing or a search one call returns.
MAX_LIMIT = 500
#: Most triples of a diff or an inference preview shown in full.
DIFF_SAMPLE = 100
#: Most nodes a hierarchy tree holds before it is cut.
MAX_TREE_NODES = 1000
#: Longest an API call waits for a UI run to finish before giving up.
LOCK_TIMEOUT_SECONDS = 15.0
#: Ceiling on a reasoning preview: it holds the lock, so the UI waits too.
MAX_REASONING_SECONDS = 120.0

#: Entity kinds, and the listing each one is read from.
KINDS: dict[str, str] = {
    "class": "get_classes",
    "object_property": "get_object_properties",
    "data_property": "get_data_properties",
    "individual": "get_individuals",
    "concept": "get_concepts",
    "concept_scheme": "get_concept_schemes",
}

#: ``OntologyManager.search`` type labels, as kinds.
_SEARCH_TYPES = {
    "Class": "class",
    "Object Property": "object_property",
    "Data Property": "data_property",
    "Individual": "individual",
    "SKOS Concept": "concept",
    "Concept": "concept",
    "Concept Scheme": "concept_scheme",
}

#: The edit operations a batch may contain, and the engine method each runs.
#: Only these: anything that replaces the whole graph (load, new, a
#: ``replace`` import) stays a UI action.
EDIT_OPS: dict[str, str] = {
    "add_class": "add_class",
    "update_class": "update_class",
    "rename_class": "rename_class",
    "delete_class": "delete_class",
    "add_object_property": "add_object_property",
    "add_data_property": "add_data_property",
    "update_property": "update_property",
    "rename_property": "rename_property",
    "delete_property": "delete_property",
    "add_individual": "add_individual",
    "update_individual": "update_individual",
    "rename_individual": "rename_individual",
    "delete_individual": "delete_individual",
    "assert_property": "add_individual_property",
    "add_restriction": "add_restriction",
    "delete_restriction": "delete_restriction",
    "add_annotation": "add_annotation",
    "delete_annotation": "delete_annotation",
    "add_concept_scheme": "add_concept_scheme",
    "add_concept": "add_concept",
    "update_concept": "update_concept",
    "delete_concept": "delete_concept",
    "add_concept_relation": "add_concept_relation",
    "add_class_relation": "add_class_relation",
    "add_property_relation": "add_property_relation",
    "add_individual_relation": "add_individual_relation",
    "add_custom_relation": "add_custom_relation",
    "set_ontology_metadata": "set_ontology_metadata",
    "add_prefix": "add_prefix",
}

#: Argument names an agent is likely to use, and the engine's own.
_ARG_ALIASES = {"range": "range_", "property": "property_name"}

#: The kinds an update, rename or delete op looks its target up among, by the
#: word after its verb (``delete_class`` changes a class); also a hierarchy's.
_TARGET_KINDS: dict[str, tuple[str, ...]] = {
    "class": ("class",),
    "property": ("object_property", "data_property"),
    "individual": ("individual",),
    "concept": ("concept",),
}


class ServiceError(Exception):
    """A call that cannot be answered, with the HTTP status that says why."""

    status = 400
    code = "bad_request"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


class NotFound(ServiceError):
    status = 404
    code = "not_found"


class Conflict(ServiceError):
    status = 409
    code = "revision_conflict"


class Busy(ServiceError):
    status = 503
    code = "busy"


class Workspace(Protocol):
    """Where the service finds the ontology, and how it takes turns with others."""

    def manager(self) -> OntologyManager: ...

    def undo(self) -> UndoManager | None: ...

    def locked(self, timeout: float) -> contextlib.AbstractContextManager[None]: ...

    def note_write(self, label: str, detail: str = "") -> None:
        """An API change was kept. ``detail`` is a short summary, e.g. the
        triple counts, for whoever shows the change to the user."""
        ...


class LocalWorkspace:
    """A workspace over one manager in this process, for tests and scripts."""

    def __init__(self, manager: OntologyManager | None = None) -> None:
        self._manager = manager or OntologyManager()
        self._undo = UndoManager(self._manager)
        self._lock = threading.RLock()
        self.writes: list[str] = []

    def manager(self) -> OntologyManager:
        return self._manager

    def undo(self) -> UndoManager | None:
        return self._undo

    @contextlib.contextmanager
    def locked(self, timeout: float) -> Iterator[None]:
        if not self._lock.acquire(timeout=timeout):
            raise Busy("The ontology is busy; try again shortly.")
        try:
            yield
        finally:
            self._lock.release()

    def note_write(self, label: str, detail: str = "") -> None:
        self.writes.append(label)


def _default_label(operations: list[dict[str, Any]]) -> str:
    """``API: add_class Employee (+2)``: the first op, what it names, how many more."""
    first = operations[0] if isinstance(operations[0], dict) else {}
    subject = next(
        (
            first[k]
            for k in ("name", "old_name", "class_name", "individual", "subject")
            if isinstance(first.get(k), str)
        ),
        "",
    )
    more = f" (+{len(operations) - 1})" if len(operations) > 1 else ""
    return f"API: {first.get('op', 'edit')} {subject}".rstrip() + more


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _local_name(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _subtrees(
    nodes: list[str], build: Callable[[str], dict[str, Any] | None]
) -> list[dict[str, Any]]:
    """``build`` each node in turn, up to the first that returns None."""
    out = []
    for node in nodes:
        subtree = build(node)
        if subtree is None:
            break
        out.append(subtree)
    return out


class OntologyService:
    """The API's operations on the ontology a :class:`Workspace` holds."""

    def __init__(
        self, workspace: Workspace, lock_timeout: float = LOCK_TIMEOUT_SECONDS
    ) -> None:
        self._ws = workspace
        self._lock_timeout = lock_timeout
        #: Revisions a rollback left behind, each mapped to the one before the
        #: rolled-back changes. The journal's counter moves on a rollback too,
        #: but the graph is as it was, so a dry run followed by the real call
        #: with the same ``expected_revision`` must still go through.
        self._same_as: dict[str, str] = {}

    # -- plumbing ---------------------------------------------------------

    @contextlib.contextmanager
    def _session(self) -> Iterator[OntologyManager]:
        with self._ws.locked(self._lock_timeout):
            yield self._ws.manager()

    @staticmethod
    def _n3(m: OntologyManager, triple: tuple) -> str:
        nm = m.graph.namespace_manager
        return " ".join(term.n3(nm) for term in triple) + " ."

    def _listing(self, m: OntologyManager, kind: str) -> list[dict[str, Any]]:
        if kind not in KINDS:
            raise ServiceError(f"Unknown kind {kind!r}.", allowed=sorted(KINDS))
        return getattr(m, KINDS[kind])()

    def _expand(self, m: OntologyManager, ref: str) -> str:
        """``prefix:name`` as a full URI when the prefix is bound."""
        if ":" in ref and "://" not in ref and not ref.startswith("urn:"):
            prefix, local = ref.split(":", 1)
            ns = dict(m.graph.namespaces()).get(prefix)
            if ns is not None:
                return str(ns) + local
        return ref

    def _matches(self, m: OntologyManager, ref: str) -> list[tuple[str, dict]]:
        """Every entity ``ref`` names: by URI, prefixed name or local name."""
        ref = ref.strip()
        uri = self._expand(m, ref)
        by_uri, by_name = [], []
        for kind in KINDS:
            for rec in self._listing(m, kind):
                if rec.get("uri") == uri:
                    by_uri.append((kind, rec))
                elif rec.get("name") == ref:
                    by_name.append((kind, rec))
        return by_uri or by_name

    def _resolve(self, m: OntologyManager, ref: str) -> tuple[str, dict]:
        found = self._matches(m, ref)
        if not found:
            raise NotFound(
                f"No entity named {ref!r}. Use find_entities to search.",
                ref=ref,
            )
        if len(found) > 1:
            raise ServiceError(
                f"{ref!r} names {len(found)} entities; pass a full URI.",
                candidates=[{"kind": k, "uri": r.get("uri")} for k, r in found],
            )
        return found[0]

    def _canonical(self, token: str) -> str:
        seen = set()
        while token in self._same_as and token not in seen:
            seen.add(token)
            token = self._same_as[token]
        return token

    def _check_revision(self, m: OntologyManager, expected: str | None) -> None:
        current = self._canonical(m.revision_token())
        if expected and self._canonical(expected) != current:
            raise Conflict(
                "The ontology changed since that revision; read it again.",
                expected_revision=expected,
                revision=current,
            )

    # -- reading ----------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        """Metadata, counts, prefixes, top classes and schemes, the revision."""
        with self._session() as m:
            classes = m.get_classes()
            return {
                "revision": self._canonical(m.revision_token()),
                "base_uri": str(m.base_uri),
                "ontology_uri": str(m.ontology_uri),
                "metadata": m.get_ontology_metadata(),
                "imports": m.get_imports(),
                "statistics": m.get_statistics(),
                "prefixes": m.get_prefixes(),
                "top_classes": [c["name"] for c in classes if not c["parents"]][:100],
                "concept_schemes": [s["name"] for s in m.get_concept_schemes()],
            }

    def list_entities(
        self,
        kind: str,
        *,
        parent: str | None = None,
        scheme: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """One kind of entity, a page at a time; optionally under one parent.

        ``parent`` filters classes to the direct subclasses of a class and
        individuals to the members of a class; ``scheme`` filters concepts.
        """
        offset = max(0, int(offset))
        limit = _clamp(limit, 1, MAX_LIMIT)
        with self._session() as m:
            if kind == "concept" and scheme:
                items = m.get_concepts(scheme)
            else:
                items = self._listing(m, kind)
            if parent:
                _, prec = self._resolve(m, parent)
                puri = prec["uri"]
                key = {"class": "parent_uris", "individual": "class_uris"}.get(kind)
                if key is None:
                    raise ServiceError("parent filters classes and individuals only.")
                items = [i for i in items if puri in i.get(key, [])]
            return {
                "kind": kind,
                "total": len(items),
                "offset": offset,
                "items": items[offset : offset + limit],
                "revision": self._canonical(m.revision_token()),
            }

    def find_entities(
        self, query: str, *, kind: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        """Search names, labels, comments and annotations (case-insensitive)."""
        limit = _clamp(limit, 1, MAX_LIMIT)
        with self._session() as m:
            hits = []
            for hit in m.search(query):
                hit_kind = _SEARCH_TYPES.get(hit.get("type", ""), hit.get("type"))
                if kind and hit_kind != kind:
                    continue
                hits.append({**hit, "kind": hit_kind})
            return {"query": query, "total": len(hits), "items": hits[:limit]}

    def describe(self, ref: str) -> dict[str, Any]:
        """Everything the ontology says about one entity, in one answer."""
        with self._session() as m:
            kind, rec = self._resolve(m, ref)
            # By URI, not local name: the engine reads a bare name in the base
            # namespace, so an external Person would get the local one's facts.
            uri = rec["uri"]
            out: dict[str, Any] = {"kind": kind, **rec}
            out["annotations"] = m.get_annotations(uri)
            if kind == "class":
                out["restrictions"] = [
                    r
                    for r in m.get_restrictions()
                    if uri in r.get("applied_to_uris", [])
                ]
                members = [
                    i["name"] for i in m.get_individuals() if uri in i["class_uris"]
                ]
                out["individuals"] = {"total": len(members), "sample": members[:25]}
                props = m.get_object_properties() + m.get_data_properties()
                out["properties_with_domain"] = [
                    p["name"] for p in props if p.get("domain_uri") == uri
                ]
                out["properties_with_range"] = [
                    p["name"]
                    for p in m.get_object_properties()
                    if p.get("range_uri") == uri
                ]
            usages = m.get_resource_usages(uri)
            out["usages"] = {
                direction: {"total": len(rows), "sample": rows[:50]}
                for direction, rows in usages.items()
            }
            out["revision"] = self._canonical(m.revision_token())
            return out

    def hierarchy(
        self,
        kind: str = "class",
        *,
        root: str | None = None,
        scheme: str | None = None,
        depth: int = 3,
    ) -> dict[str, Any]:
        """The subclass (or SKOS broader/narrower) tree, to a depth.

        Built on URIs: a tree keyed by local name merged a Person from
        another namespace with the ontology's own. A root is a node with no
        parent among the listed ones. At most :data:`MAX_TREE_NODES` nodes:
        a node whose children are cut off, by the depth or by that limit,
        counts them in ``more``, and ``more_roots`` counts roots left out.
        """
        depth = _clamp(depth, 1, 20)
        with self._session() as m:
            if kind == "class":
                every = m.get_classes()
                listed, up, down = every, "parent_uris", "child_uris"
            elif kind == "concept":
                every = m.get_concepts()
                listed = m.get_concepts(scheme) if scheme else every
                up, down = "broader_uris", "narrower_uris"
            else:
                raise ServiceError("kind is 'class' or 'concept'.")
            names = {n["uri"]: n["name"] for n in every}
            # Each link from either end: SKOS states broader and narrower
            # separately, and a vocabulary may assert only one of them.
            children: dict[str, set[str]] = {}
            parents: dict[str, set[str]] = {}
            for n in every:
                for child in n.get(down, []):
                    children.setdefault(n["uri"], set()).add(child)
                    parents.setdefault(child, set()).add(n["uri"])
                for parent in n.get(up, []):
                    children.setdefault(parent, set()).add(n["uri"])
                    parents.setdefault(n["uri"], set()).add(parent)
            if root:
                roots = [self._target(m, "hierarchy", root, kind)]
            else:
                inside = {n["uri"] for n in listed}
                roots = [
                    n["uri"]
                    for n in listed
                    if not parents.get(n["uri"], set()) & inside
                ]
            count = 0
            truncated = False

            def name(uri: str) -> str:
                return names.get(uri) or _local_name(uri)

            def tree(
                node: str, level: int, path: frozenset[str]
            ) -> dict[str, Any] | None:
                """The subtree at ``node``, or None once the limit is reached."""
                nonlocal count, truncated
                if count >= MAX_TREE_NODES:
                    truncated = True
                    return None
                count += 1
                entry: dict[str, Any] = {"name": name(node), "uri": node}
                path = path | {node}
                kids = sorted(
                    (k for k in children.get(node, []) if k not in path),
                    key=lambda k: (name(k), k),
                )
                if not kids:
                    return entry
                if level >= depth:
                    entry["more"] = len(kids)
                    return entry
                shown = _subtrees(kids, lambda k: tree(k, level + 1, path))
                entry["children"] = shown
                if len(shown) < len(kids):
                    entry["more"] = len(kids) - len(shown)
                return entry

            ordered = sorted(roots, key=lambda r: (name(r), r))
            shown = _subtrees(ordered, lambda r: tree(r, 1, frozenset()))
            out: dict[str, Any] = {
                "kind": kind,
                "roots": shown,
                "truncated": truncated,
            }
            if len(shown) < len(ordered):
                out["more_roots"] = len(ordered) - len(shown)
            return out

    def paths(
        self,
        source: str,
        target: str,
        *,
        max_paths: int = 3,
        edge_kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        """How two entities are connected: up to ``max_paths`` shortest routes."""
        if edge_kinds:
            unknown = set(edge_kinds) - set(PATH_EDGE_KINDS)
            if unknown:
                raise ServiceError(
                    f"Unknown edge kinds {sorted(unknown)}.",
                    allowed=list(PATH_EDGE_KINDS),
                )
        with self._session() as m:
            ends = []
            for ref in (source, target):
                kind, rec = self._resolve(m, ref)
                if kind not in ("class", "individual", "concept"):
                    raise ServiceError(
                        f"{ref!r} is a {kind}; paths run between classes, "
                        "individuals and concepts."
                    )
                ends.append((kind, rec["name"] if kind == "concept" else rec["uri"]))
            try:
                routes, cut = m.find_paths(
                    ends[0],
                    ends[1],
                    k=_clamp(max_paths, 1, PATH_MAX_ROUTES),
                    kinds=edge_kinds,
                )
            except PathSearchLimitError as e:
                return {"paths": [], "search_limited": True, "message": str(e)}

            def short(node: tuple[str, str]) -> str:
                return _local_name(node[1])

            return {
                "source": ends[0][1],
                "target": ends[1][1],
                "connected": bool(routes),
                "search_limited": bool(cut),
                "paths": [
                    [
                        {
                            "from": short(hop["source"]),
                            "relation": hop["relation"],
                            "to": short(hop["target"]),
                            "forward": hop["forward"],
                        }
                        for hop in route
                    ]
                    for route in routes or []
                ],
            }

    def sparql(
        self, query: str, *, max_rows: int = 200, timeout_seconds: float = 10.0
    ) -> dict[str, Any]:
        """A read-only SPARQL query, under the app's deadline and row cap."""
        with self._session() as m:
            try:
                res = run_query(
                    m.graph,
                    query,
                    timeout_seconds=timeout_seconds,
                    max_rows=max_rows,
                )
            except QueryError as e:
                raise ServiceError(str(e)) from e
            out: dict[str, Any] = {
                "form": res.form,
                "columns": res.columns,
                "rows": res.rows,
                "row_count": res.row_count,
                "truncated": res.truncated,
                "timed_out": res.timed_out,
                "engine": res.engine,
                "elapsed": round(res.elapsed, 3),
            }
            if res.ask is not None:
                out["ask"] = res.ask
            if res.graph is not None:
                out["turtle"] = res.graph.serialize(format="turtle")
            return out

    def check(
        self, checks: list[str] | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Run the app's checks: ``validate`` (OWL/structure) and ``skos``."""
        checks = checks or ["validate"]
        unknown = set(checks) - {"validate", "skos"}
        if unknown:
            raise ServiceError(f"Unknown checks {sorted(unknown)}.")
        limit = _clamp(limit, 1, 5000)
        with self._session() as m:
            out: dict[str, Any] = {}
            for name in checks:
                issues = m.validate() if name == "validate" else m.validate_skos()
                counts: dict[str, int] = {}
                for i in issues:
                    counts[i.get("severity", "")] = (
                        counts.get(i.get("severity", ""), 0) + 1
                    )
                out[name] = {
                    "total": len(issues),
                    "by_severity": counts,
                    "issues": issues[:limit],
                }
            return out

    def export(self, fmt: str = "turtle", content: str = "all") -> dict[str, Any]:
        with self._session() as m:
            try:
                text = m.export_to_string(fmt, content)
            except ValueError as e:
                raise ServiceError(str(e)) from e
            return {
                "format": fmt,
                "revision": self._canonical(m.revision_token()),
                "data": text,
            }

    # -- changing ---------------------------------------------------------

    @contextlib.contextmanager
    def _batch(
        self,
        m: OntologyManager,
        *,
        dry_run: bool,
        label: str,
        result: dict[str, Any],
    ) -> Iterator[None]:
        """Run the body's changes as one undo step, or not at all.

        Fills ``result`` with the net diff, the revisions, and whether the
        changes were kept. Any exception rolls everything back.
        """
        um = self._ws.undo()
        snapshot = None if um is not None else m.take_snapshot()

        def rollback() -> None:
            if um is not None:
                um.discard_pending()
            elif snapshot is not None:
                m.restore_snapshot(snapshot)

        # Canonical like every revision the API reports: the raw token after a
        # dry run differs from the one the dry run reported, so an apply sent
        # with that ``expected_revision`` would show a ``revision_before`` that
        # looks as if the ontology had moved in between when it had not.
        result["revision_before"] = self._canonical(m.revision_token())
        try:
            yield
            # Inside the guard: writing the diff can fail too (a term Turtle
            # cannot write), and the changes must then go as well.
            if um is not None:
                result["diff"] = self._diff(m, um)
        except BaseException:
            rollback()
            self._same_as[m.revision_token()] = result["revision_before"]
            raise
        if dry_run:
            rollback()
            self._same_as[m.revision_token()] = result["revision_before"]
            result["applied"] = False
        else:
            if um is not None:
                um.checkpoint(label)
            diff = result.get("diff")
            detail = (
                f"+{diff['added']} / \u2212{diff['removed']} triples" if diff else ""
            )
            self._ws.note_write(label, detail)
            result["applied"] = True
        result["revision"] = self._canonical(m.revision_token())

    def _diff(self, m: OntologyManager, um: UndoManager) -> dict[str, Any]:
        """The batch's net change, with a sample of each side as Turtle."""
        added, removed = um.pending_triples()
        # rdflib takes any string as an IRI and only objects when writing it,
        # so an IRI with a space would break every later export and autosave.
        # A literal's datatype is an IRI too.
        for triple in added:
            for term in triple:
                iri = term.datatype if isinstance(term, Literal) else term
                if not isinstance(iri, URIRef):
                    continue
                reason = m.invalid_uri_reason(str(iri))
                if reason:
                    raise ServiceError(
                        f"{str(iri)!r} cannot be stored. {reason}",
                        term=str(iri),
                        failed_index=None,
                    )
        return {
            "added": len(added),
            "removed": len(removed),
            "added_sample": [self._n3(m, t) for t in added[:DIFF_SAMPLE]],
            "removed_sample": [self._n3(m, t) for t in removed[:DIFF_SAMPLE]],
        }

    def _target(self, m: OntologyManager, op: str, ref: str, noun: str) -> str:
        """The URI of the one entity of a kind that ``ref`` names.

        For what an update, rename or delete changes, and a hierarchy's root.
        The engine places a bare name in the base namespace, so an entity from
        another namespace, found here by its local name, would be missed and
        the change made to a new resource in the base namespace. The engine
        also takes an unknown name as nothing to do; from an agent that is
        nearly always a typo, so it is refused, as is a name two entities share.
        """
        kinds = _TARGET_KINDS[noun]
        uris = sorted(
            {rec["uri"] for kind, rec in self._matches(m, ref) if kind in kinds}
        )
        if not uris:
            raise NotFound(f"{op}: no {noun} named {ref!r}.", ref=ref)
        if len(uris) > 1:
            raise ServiceError(
                f"{op}: {ref!r} names {len(uris)} entities; pass a full URI "
                "or a prefixed name.",
                candidates=uris,
            )
        return uris[0]

    def _call_op(self, m: OntologyManager, op: dict[str, Any]) -> Any:
        if not isinstance(op, dict) or "op" not in op:
            raise ServiceError("Each operation is an object with an 'op' field.")
        args = {_ARG_ALIASES.get(k, k): v for k, v in op.items() if k != "op"}
        name = op["op"]
        if name not in EDIT_OPS:
            raise ServiceError(f"Unknown op {name!r}.", allowed=sorted(EDIT_OPS))
        method: Callable[..., Any] = getattr(m, EDIT_OPS[name])
        if name == "assert_property":
            args.setdefault("individual", args.pop("subject", None))
        try:
            inspect.signature(method).bind(**args)
        except TypeError as e:
            params = [p for p in inspect.signature(method).parameters if p != "self"]
            raise ServiceError(f"{name}: {e}", parameters=params) from e
        verb, _, noun = name.partition("_")
        if verb in ("update", "rename", "delete") and noun in _TARGET_KINDS:
            key = "old_name" if verb == "rename" else "name"
            uri = self._target(m, name, str(args[key]), noun)
            # Renaming to the same name is the engine's no-op; with the old
            # name as a URI it would find the new one taken.
            if not (verb == "rename" and args[key] == args.get("new_name")):
                args[key] = uri
        value = method(**args)
        if name.startswith("rename_") and value is False:
            raise ServiceError(f"{name}: rename refused (unknown or taken name).")
        if isinstance(value, URIRef):
            return str(value)
        return value if isinstance(value, (str, int, float, bool, type(None))) else None

    def edit(
        self,
        operations: list[dict[str, Any]],
        *,
        dry_run: bool = False,
        expected_revision: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Apply a batch of edit operations atomically.

        Each operation is ``{"op": <name>, **arguments}`` with the arguments
        of the engine method in :data:`EDIT_OPS`. With ``dry_run`` the batch
        runs and is rolled back, so the diff says what it would do. Pass the
        ``revision`` you read as ``expected_revision`` to refuse the batch if
        the ontology changed in between (409).
        """
        if not operations:
            raise ServiceError("No operations given.")
        label = label or _default_label(operations)
        result: dict[str, Any] = {"label": label, "results": []}
        with self._session() as m:
            self._check_revision(m, expected_revision)
            index = -1
            try:
                with self._batch(m, dry_run=dry_run, label=label, result=result):
                    for index, op in enumerate(operations):
                        result["results"].append(
                            {"op": op.get("op"), "result": self._call_op(m, op)}
                        )
            except ServiceError as e:
                e.details.setdefault("failed_index", index)
                e.details["rolled_back"] = True
                raise
            except Exception as e:
                raise ServiceError(
                    f"Operation {index} ({operations[index].get('op')}) failed: {e}",
                    failed_index=index,
                    rolled_back=True,
                ) from e
            return result

    def merge_rdf(
        self,
        data: str,
        *,
        fmt: str = "turtle",
        strategy: str = IMPORT_MERGE,
        dry_run: bool = True,
        expected_revision: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Merge RDF (Turtle by default) into the ontology, as one undo step.

        Defaults to a dry run: the usual way for an agent to model a larger
        piece is to write it as Turtle, look at the diff, then send it again
        with ``dry_run`` off. ``strategy`` is ``merge`` or ``merge_overwrite``
        (incoming values replace conflicting ones); replacing the whole
        ontology is left to the UI.
        """
        if strategy not in (IMPORT_MERGE, IMPORT_MERGE_OVERWRITE):
            raise ServiceError("strategy is 'merge' or 'merge_overwrite'.")
        label = label or "API: merge RDF"
        result: dict[str, Any] = {"label": label}
        with self._session() as m:
            self._check_revision(m, expected_revision)
            try:
                incoming = Graph().parse(data=data, format=fmt)
            except Exception as e:
                raise ServiceError(f"Could not parse the {fmt}: {e}") from e
            result["conflicts"] = m.detect_conflicts(incoming)[:DIFF_SAMPLE]
            with self._batch(m, dry_run=dry_run, label=label, result=result):
                m.merge_from_graph(incoming, strategy=strategy)
            return result

    def reason(
        self,
        profile: str = "rdfs",
        *,
        apply: bool = False,
        deadline_seconds: float = 60.0,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """What reasoning infers; with ``apply``, add it as one undo step."""
        if profile not in REASONING_PROFILES:
            raise ServiceError(
                f"Unknown profile {profile!r}.", allowed=list(REASONING_PROFILES)
            )
        deadline = max(1.0, min(float(deadline_seconds), MAX_REASONING_SECONDS))
        with self._session() as m:
            self._check_revision(m, expected_revision)
            try:
                change = m.infer_in_worker(profile, deadline_s=deadline)
            except Exception as e:
                raise ServiceError(f"Reasoning did not finish: {e}") from e
            out: dict[str, Any] = {
                "profile": profile,
                "inferred": len(change.added),
                "removed": len(change.removed),
                "inferred_sample": [self._n3(m, t) for t in change.added[:DIFF_SAMPLE]],
                "applied": False,
            }
            if apply and (change.added or change.removed):
                label = f"API: reasoning ({profile})"
                with self._batch(m, dry_run=False, label=label, result=out):
                    m.apply_closure_change(change)
                out.pop("diff", None)
            out["revision"] = self._canonical(m.revision_token())
            return out

    # -- history ----------------------------------------------------------

    def history(self) -> dict[str, Any]:
        with self._session() as m:
            um = self._ws.undo()
            return {
                "revision": self._canonical(m.revision_token()),
                "undo": um.undo_labels if um else [],
                "redo": um.redo_labels if um else [],
            }

    def undo(self) -> dict[str, Any]:
        return self._step(redo=False)

    def redo(self) -> dict[str, Any]:
        return self._step(redo=True)

    def _step(self, redo: bool) -> dict[str, Any]:
        with self._session() as m:
            um = self._ws.undo()
            if um is None or not (um.can_redo() if redo else um.can_undo()):
                raise ServiceError(f"Nothing to {'redo' if redo else 'undo'}.")
            # The engine returns the label it lands on; the user wants to
            # know which step was taken back (or put back).
            stepped = (um.redo_labels if redo else um.undo_labels)[-1]
            label = um.redo() if redo else um.undo()
            self._ws.note_write(f"API: {'Redo' if redo else 'Undo'}", stepped)
            return {"label": label, "revision": self._canonical(m.revision_token())}

"""
OntologyManager - Core class for managing OWL ontologies using rdflib.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, ClassVar, cast

import owlrl
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DC, DCTERMS, OWL, RDF, RDFS, SKOS, XSD
from rdflib.term import Node

from .languages import invalid_tag_reason

logger = logging.getLogger(__name__)

#: RDF serialization format for a file, keyed by lower-case extension. Used so a
#: linked working file can be a format other than Turtle (e.g. .owl/.rdf).
RDF_FORMAT_BY_SUFFIX = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".owl": "xml",
    ".rdf": "xml",
    ".xml": "xml",
    ".nt": "nt",
    ".n3": "n3",
    ".jsonld": "json-ld",
    ".json": "json-ld",
}


def rdf_format_for_path(path, default: str = "turtle") -> str:
    """Return the rdflib format for ``path`` based on its extension."""
    return RDF_FORMAT_BY_SUFFIX.get(Path(path).suffix.lower(), default)


_UNSET: Any = object()  # sentinel: "parameter not provided"


def _with_article(noun: str) -> str:
    """'class' -> 'a class', 'individual' -> 'an individual'."""
    return f"{'an' if noun[:1].lower() in 'aeiou' else 'a'} {noun}"


# A triple and a list of (old_triple, new_triple) rename operations.
_Triple = tuple[Node, Node, Node]
_TripleUpdates = list[tuple[_Triple, _Triple]]

# domainIncludes/rangeIncludes from Schema.org and gist
#: SKOS-XL, the W3C extension that makes a label a resource rather than a
#: literal, so statements can be made about the label itself. rdflib has no
#: built-in binding for it. This app authors plain SKOS labels only; SKOS-XL is
#: read so an imported vocabulary is not shown as unlabelled, and reported so
#: the user knows why those labels are not editable here.
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")

_SCHEMA = Namespace("https://schema.org/")
_GIST = Namespace("https://w3id.org/semanticarts/ns/ontology/gist/")
_DOMAIN_INCLUDES = (_SCHEMA.domainIncludes, _GIST.domainIncludes)
_RANGE_INCLUDES = (_SCHEMA.rangeIncludes, _GIST.rangeIncludes)

# Import strategies
IMPORT_REPLACE = "replace"
IMPORT_MERGE = "merge"
IMPORT_MERGE_OVERWRITE = "merge_overwrite"


class OntologyManager:
    """Manages OWL ontology operations including CRUD for classes, properties, individuals, and restrictions."""

    # Common XSD datatypes for data properties
    XSD_DATATYPES: ClassVar[dict[str, URIRef]] = {
        "string": XSD.string,
        "integer": XSD.integer,
        "float": XSD.float,
        "double": XSD.double,
        "boolean": XSD.boolean,
        "date": XSD.date,
        "dateTime": XSD.dateTime,
        "time": XSD.time,
        "decimal": XSD.decimal,
        "anyURI": XSD.anyURI,
        "nonNegativeInteger": XSD.nonNegativeInteger,
        "positiveInteger": XSD.positiveInteger,
    }

    # Restriction types
    RESTRICTION_TYPES: ClassVar[dict[str, URIRef]] = {
        "someValuesFrom": OWL.someValuesFrom,
        "allValuesFrom": OWL.allValuesFrom,
        "hasValue": OWL.hasValue,
        "minCardinality": OWL.minCardinality,
        "maxCardinality": OWL.maxCardinality,
        "exactCardinality": OWL.cardinality,
        "minQualifiedCardinality": OWL.minQualifiedCardinality,
        "maxQualifiedCardinality": OWL.maxQualifiedCardinality,
        "qualifiedCardinality": OWL.qualifiedCardinality,
    }

    def __init__(self, base_uri: str = "http://example.org/ontology#"):
        """Initialize the ontology manager with a base URI."""
        self.graph = Graph()
        self.base_uri = base_uri
        self.namespace = Namespace(base_uri)

        self._bind_standard_prefixes()

        # Prefixes the user explicitly bound via add_prefix (prefix -> namespace).
        # Tracked so the creation picker offers them even when the name collides
        # with one of rdflib's auto-bound defaults (e.g. an explicit 'foaf').
        # Reset on load/restore so it can never go stale against the graph.
        self._user_added_prefixes: dict[str, str] = {}

        # Create ontology declaration
        self.ontology_uri = URIRef(base_uri.rstrip("#").rstrip("/"))
        self.graph.add((self.ontology_uri, RDF.type, OWL.Ontology))

    def set_ontology_metadata(
        self, label=_UNSET, comment=_UNSET, creator=_UNSET, version_iri=_UNSET
    ):
        """Set ontology-level metadata.

        Pass a non-empty string to set a value.
        Pass an empty string or None to clear an existing value.
        Omit the parameter (or don't pass it) to leave the field unchanged.
        """
        _LITERAL_FIELDS = [
            (label, RDFS.label),
            (comment, RDFS.comment),
            (creator, DCTERMS.creator),
        ]
        for value, predicate in _LITERAL_FIELDS:
            if value is _UNSET:
                continue
            if value:
                self.graph.set((self.ontology_uri, predicate, Literal(value)))
            else:
                self.graph.remove((self.ontology_uri, predicate, None))

        if version_iri is not _UNSET:
            if version_iri:
                self.graph.set((self.ontology_uri, OWL.versionIRI, URIRef(version_iri)))
            else:
                self.graph.remove((self.ontology_uri, OWL.versionIRI, None))

    def add_import(self, import_uri: str):
        """Add an owl:imports declaration."""
        self.graph.add((self.ontology_uri, OWL.imports, URIRef(import_uri)))

    def remove_import(self, import_uri: str):
        """Remove an owl:imports declaration."""
        self.graph.remove((self.ontology_uri, OWL.imports, URIRef(import_uri)))

    def get_imports(self) -> list[str]:
        """Get all owl:imports URIs."""
        return [str(o) for o in self.graph.objects(self.ontology_uri, OWL.imports)]

    # Standard prefixes that cannot be removed
    STANDARD_PREFIXES: ClassVar[set[str]] = {
        "owl",
        "rdf",
        "rdfs",
        "xsd",
        "skos",
        # SKOS-XL is a vocabulary this app reads, not one a user mints entities
        # in, so it belongs here beside skos rather than in the creatable list.
        "skosxl",
        "dc",
        "dcterms",
    }

    def get_prefixes(self) -> list[dict[str, str]]:
        """Get namespace prefixes from the graph bindings and loaded declarations."""
        prefixes = []
        seen = set()
        # Include all graph namespace bindings
        for prefix, ns in self.graph.namespaces():
            display = prefix if prefix else "(default)"
            if display not in seen:
                seen.add(display)
                prefixes.append({"prefix": display, "namespace": str(ns)})
        # Include loaded prefixes not yet in graph
        if hasattr(self, "_loaded_prefixes") and self._loaded_prefixes:
            for p in self._loaded_prefixes:
                if p["prefix"] not in seen:
                    seen.add(p["prefix"])
                    prefixes.append(p)
        # Ensure at least the default namespace
        if "(default)" not in seen:
            prefixes.append({"prefix": "(default)", "namespace": self.base_uri})
        prefixes.sort(key=lambda x: "" if x["prefix"] == "(default)" else x["prefix"])
        return prefixes

    def get_all_prefixes(self) -> list[dict[str, str]]:
        """Get all namespace prefix bindings with source classification."""
        prefixes = []
        for prefix, ns in self.graph.namespaces():
            display = prefix if prefix else "(default)"
            if prefix in self.STANDARD_PREFIXES:
                source = "standard"
            elif display == "(default)":
                source = "default"
            else:
                source = "custom"
            prefixes.append(
                {
                    "prefix": display,
                    "namespace": str(ns),
                    "source": source,
                }
            )
        prefixes.sort(key=lambda x: "" if x["prefix"] == "(default)" else x["prefix"])
        return prefixes

    def add_prefix(self, prefix: str, namespace: str) -> str:
        """Bind a custom prefix to a namespace URI in the graph.

        An ``http(s)`` namespace that lacks a trailing delimiter is normalized
        to end with ``#`` so entities created in it get a separator between the
        namespace and the local name. Without it, a namespace like
        ``http://example.org/ontology`` would concatenate with a name into
        ``http://example.org/ontologyDog`` (issue #115). Namespaces that already
        end in a delimiter (``# / : ? = &``) and non-``http`` schemes such as
        ``urn:example:`` are left untouched, since their separator is already
        intentional. Returns the namespace actually bound, so callers can
        surface the normalization.
        """
        namespace = namespace.strip()
        if namespace.startswith(("http://", "https://")) and not namespace.endswith(
            ("#", "/", ":", "?", "=", "&")
        ):
            namespace = namespace + "#"
        self.graph.bind(prefix, Namespace(namespace), override=True)
        self._user_added_prefixes[prefix] = namespace
        return namespace

    def remove_prefix(self, prefix: str):
        """Remove a custom prefix binding. Standard prefixes cannot be removed."""
        if prefix in self.STANDARD_PREFIXES:
            raise ValueError(f"Cannot remove standard prefix '{prefix}'")
        self._user_added_prefixes.pop(prefix, None)
        # rdflib NamespaceManager doesn't support unbinding directly.
        # Rebuild the namespace manager by creating a new graph with the same triples.
        keep = [(p, ns) for p, ns in self.graph.namespaces() if p != prefix]
        new_graph = Graph()
        for s, p_triple, o in self.graph:
            new_graph.add((s, p_triple, o))
        for p, ns in keep:
            new_graph.bind(p, ns, override=True)
        self.graph = new_graph

    def _extract_prefixes_from_ttl(self, data: str) -> list[dict[str, str]]:
        """Extract @prefix declarations from TTL content."""
        import re

        prefixes = []
        # Match @prefix declarations: @prefix name: <uri> .
        pattern = r"@prefix\s+([a-zA-Z0-9_-]*)\s*:\s*<([^>]+)>\s*\."
        for match in re.finditer(pattern, data):
            prefix = match.group(1)
            namespace = match.group(2)
            prefixes.append(
                {"prefix": prefix if prefix else "(default)", "namespace": namespace}
            )
        # Sort by prefix name, with default first
        prefixes.sort(key=lambda x: "" if x["prefix"] == "(default)" else x["prefix"])
        return prefixes

    def _extract_prefixes_from_jsonld(self, data: str) -> list[dict[str, str]]:
        """Extract prefix declarations from JSON-LD @context."""
        import json

        prefixes: list[dict[str, str]] = []
        try:
            doc = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return prefixes
        # JSON-LD can be a dict or a list (expanded form has no @context)
        if isinstance(doc, list):
            return prefixes
        context = doc.get("@context", {})
        if isinstance(context, list):
            # Merge multiple context objects
            merged = {}
            for item in context:
                if isinstance(item, dict):
                    merged.update(item)
            context = merged
        if isinstance(context, dict):
            for key, value in context.items():
                if key.startswith("@"):
                    continue
                if isinstance(value, str) and (
                    value.startswith(("http://", "https://"))
                ):
                    prefixes.append(
                        {
                            "prefix": key if key else "(default)",
                            "namespace": value,
                        }
                    )
        prefixes.sort(key=lambda x: "" if x["prefix"] == "(default)" else x["prefix"])
        return prefixes

    def get_ontology_metadata(self) -> dict[str, str]:
        """Get ontology-level metadata."""
        metadata = {}
        for pred, key in [
            (RDFS.label, "label"),
            (RDFS.comment, "comment"),
            (DCTERMS.creator, "creator"),
            (OWL.versionIRI, "version_iri"),
        ]:
            value = self.graph.value(self.ontology_uri, pred)
            if value:
                metadata[key] = str(value)
        return metadata

    def set_base_uri(self, new_base_uri: str):
        """Update the base URI of the ontology. This will update all local resources."""
        if not new_base_uri:
            return

        # Ensure proper format
        if not new_base_uri.endswith("#") and not new_base_uri.endswith("/"):
            new_base_uri = new_base_uri + "#"

        old_base_uri = self.base_uri
        old_ontology_uri = self.ontology_uri

        # Update internal state
        self.base_uri = new_base_uri
        self.namespace = Namespace(new_base_uri)
        self.ontology_uri = URIRef(new_base_uri.rstrip("#").rstrip("/"))

        # Update the ontology declaration
        # First, collect all triples about the old ontology URI
        old_triples = list(self.graph.triples((old_ontology_uri, None, None)))
        for s, p, o in old_triples:
            self.graph.remove((s, p, o))
            self.graph.add((self.ontology_uri, p, o))

        # Update triples where old ontology URI is object
        old_triples = list(self.graph.triples((None, None, old_ontology_uri)))
        for s, p, o in old_triples:
            self.graph.remove((s, p, o))
            self.graph.add((s, p, self.ontology_uri))

        # Update all resources that used the old namespace
        if old_base_uri != new_base_uri:
            updates = []
            for s, p, o in self.graph:
                new_s, new_o = s, o
                if isinstance(s, URIRef) and str(s).startswith(old_base_uri):
                    local_name = str(s)[len(old_base_uri) :]
                    new_s = URIRef(new_base_uri + local_name)
                if isinstance(o, URIRef) and str(o).startswith(old_base_uri):
                    local_name = str(o)[len(old_base_uri) :]
                    new_o = URIRef(new_base_uri + local_name)
                if new_s != s or new_o != o:
                    updates.append(((s, p, o), (new_s, p, new_o)))

            for old_triple, new_triple in updates:
                self.graph.remove(old_triple)
                self.graph.add(new_triple)

        # Re-bind the default namespace
        self.graph.bind("", self.namespace)

    #: The ``scheme:`` an absolute IRI opens with (RFC 3986). A local name can
    #: never match it: :attr:`_LOCAL_NAME_RE` allows no colon, so "already a
    #: URI" and "a name to place in a namespace" cannot be the same string.
    _IRI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

    def _uri(self, local_name: str, namespace: str | None = None) -> URIRef:
        """Create a URI from a local name.

        A value that is already an absolute URI is returned unchanged.
        Otherwise the local name is placed in ``namespace`` when one is given
        (any bound namespace, e.g. a custom prefix), or in the base namespace
        by default.

        Any scheme counts, not only ``http(s)``: an imported ontology can name
        its resources ``urn:``, ``did:``, ``file:`` or anything else, and
        passing one of those through here used to mint
        ``http://base#urn:example:Account`` instead. The UI hid it, because
        reading the annotations back minted the same wrong subject, but an
        export carried them on a resource nothing declares (review of PR #292).
        """
        if self._IRI_SCHEME_RE.match(local_name):
            return URIRef(local_name)
        if namespace:
            return URIRef(namespace + local_name)
        return self.namespace[local_name]

    # A valid local name is an NCName relaxed to also allow a leading digit:
    # a word character (Unicode letter/digit/underscore) followed by any of
    # word chars, '.' or '-'. This blocks the characters that corrupt a URI or
    # the app — spaces, '/', '#', ':' and stray punctuation — while still
    # allowing Unicode letters, digits, dots and hyphens (e.g. 'my-class.v2').
    _LOCAL_NAME_RE = re.compile(r"^\w[\w.\-]*$", re.UNICODE)
    # A single character allowed anywhere in a local name (used to name the
    # specific offending characters in an error, e.g. a ',' rather than only
    # reporting the first-detected problem).
    _LOCAL_NAME_CHAR_RE = re.compile(r"[\w.\-]", re.UNICODE)

    # Characters that make a full IRI unserializable in Turtle/N3 (mirrors
    # rdflib's own check); whitespace is handled separately via str.isspace().
    _INVALID_URI_CHARS = frozenset('<>"{}|\\^`')

    @classmethod
    def invalid_uri_reason(cls, uri: str) -> str | None:
        """Why ``uri`` cannot be stored as a resource, or None if it can.

        rdflib takes any string as a ``URIRef`` and only objects when asked to
        serialize, so an unusable one is accepted silently and then breaks every
        export of the whole ontology. Callers writing a resource-valued object
        check here first, while there is still something to refuse.
        """
        if uri is None or not uri.strip():
            return "A resource value cannot be empty."
        if any(c.isspace() or c in cls._INVALID_URI_CHARS for c in uri):
            return (
                "A resource value must be a URI: no spaces, and none of the "
                'characters < > " { } | \\ ^ `.'
            )
        return None

    @classmethod
    def invalid_name_reason(cls, name: str) -> str | None:
        """Return a human-readable reason ``name`` is not a valid entity name,
        or ``None`` if it is valid.

        The name is validated verbatim (no stripping), so leading/trailing
        whitespace is rejected — the string is used as-is to build the URI. A
        full ``http(s)`` URI is accepted as an explicit identifier as long as it
        contains no whitespace or characters that break serialization. Otherwise
        the name must be a valid local name (see :attr:`_LOCAL_NAME_RE`).
        """
        if name is None or not name.strip():
            return "Name cannot be empty."
        if name.startswith(("http://", "https://")):
            if any(c.isspace() or c in cls._INVALID_URI_CHARS for c in name):
                return (
                    "A full URI cannot contain spaces or any of the characters "
                    '< > " { } | \\ ^ `.'
                )
            return None
        # Name the specific disallowed characters so a comma (or any other
        # punctuation) is reported, not just the first problem found.
        bad: list[str] = []
        for c in name:
            if not cls._LOCAL_NAME_CHAR_RE.match(c):
                token = "spaces" if c.isspace() else f"'{c}'"
                if token not in bad:
                    bad.append(token)
        if bad:
            return (
                f"Names cannot contain {', '.join(bad)}. Names may contain only "
                "letters, digits, '_', '-' and '.'. Put spaces and punctuation "
                "in the Label field instead, and use a name like 'MyClass' or "
                "'my-class' here."
            )
        if not cls._LOCAL_NAME_RE.match(name):
            return (
                "Names cannot start with '-' or '.'. Use a name like 'MyClass' "
                "or 'my-class' here, and put spaces or punctuation in the Label."
            )
        return None

    def _require_valid_name(self, name: str) -> None:
        """Raise ``ValueError`` if ``name`` is not a valid entity name."""
        reason = self.invalid_name_reason(name)
        if reason:
            raise ValueError(reason)

    def _local_name(self, uri: Node) -> str:
        """Extract local name from a URI."""
        uri_str = str(uri)
        if "#" in uri_str:
            return uri_str.split("#")[-1]
        return uri_str.split("/")[-1]

    def _namespace_of(self, uri: Node) -> str:
        """Return the namespace portion of a URI (everything before the local
        name), e.g. 'http://ex.org/ns#Dog' -> 'http://ex.org/ns#'."""
        uri_str = str(uri)
        local = self._local_name(uri)
        return uri_str[: len(uri_str) - len(local)]

    # Prefixes rdflib auto-binds on a fresh Graph() (foaf, schema, brick, ...).
    # Excluded from the creation picker so it is not flooded with ~30 vocab
    # prefixes the user never chose. Computed from the running rdflib so it
    # stays correct across versions.
    _RDFLIB_DEFAULT_PREFIXES = frozenset(p for p, _ in Graph().namespaces())

    def get_creatable_namespaces(self) -> list[str]:
        """Namespaces offered when creating a new entity, base namespace first.

        Includes the base (default) namespace, every namespace already used by
        an existing entity (so imported namespaces are offered), every namespace
        the user explicitly bound via add_prefix, and any namespace bound under a
        non-default import prefix. Pure-syntax namespaces (owl, rdf, rdfs, xsd)
        and rdflib's auto-bound default prefixes are excluded so the list stays
        relevant. Derived from the live graph plus the (load/restore-reset)
        record of explicit user prefixes, so it reflects the current ontology.
        """
        result = [self.base_uri]
        seen = {self.base_uri}
        syntax_ns = {str(OWL), str(RDF), str(RDFS), str(XSD)}

        # Namespaces the user explicitly bound — offered even when the prefix
        # name matches one of rdflib's auto-bound defaults (e.g. 'foaf').
        extra = set(self._user_added_prefixes.values())
        # Namespaces bound under a prefix an import introduced
        # (i.e. not one of rdflib's auto-bound defaults or our standards).
        for prefix, ns in self.graph.namespaces():
            if (
                prefix
                and prefix not in self._RDFLIB_DEFAULT_PREFIXES
                and prefix not in self.STANDARD_PREFIXES
            ):
                extra.add(str(ns))
        # Namespaces already used by an existing entity.
        for etype in self._ENTITY_TYPES:
            for subject in self.graph.subjects(RDF.type, etype):
                if isinstance(subject, URIRef):
                    extra.add(self._namespace_of(subject))

        for ns_str in sorted(extra):
            if ns_str and ns_str not in seen and ns_str not in syntax_ns:
                seen.add(ns_str)
                result.append(ns_str)
        return result

    # ==================== CLASS OPERATIONS ====================

    def add_class(
        self,
        name: str,
        parent: str | None = None,
        label: str | None = None,
        comment: str | None = None,
        namespace: str | None = None,
    ) -> URIRef:
        """Add a new OWL class.

        ``namespace`` places the class in a specific namespace (any bound
        prefix); when omitted the base namespace is used.
        """
        self._require_valid_name(name)
        self._require_free_name(name, "class", namespace)
        if parent:
            self._require_valid_name(parent)
            # The parent becomes a class by being one (and is declared as one by
            # bulk_add_classes), so a parent owned by another kind of entity is
            # the same collision one link removed.
            self._require_free_name(parent, "class")
        class_uri = self._uri(name, namespace)
        self.graph.add((class_uri, RDF.type, OWL.Class))

        if parent:
            parent_uri = self._uri(parent)
            self.graph.add((class_uri, RDFS.subClassOf, parent_uri))

        if label:
            self.graph.add((class_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((class_uri, RDFS.comment, Literal(comment)))

        return class_uri

    def update_class(
        self,
        name: str,
        new_label: str | None = None,
        new_comment: str | None = None,
        new_parent: str | None = None,
        remove_parent: str | None = None,
    ):
        """Update an existing class."""
        if new_parent:
            self._require_valid_name(new_parent)
        class_uri = self._uri(name)

        if new_label is not None:
            self.graph.remove((class_uri, RDFS.label, None))
            if new_label:
                self.graph.add((class_uri, RDFS.label, Literal(new_label)))

        if new_comment is not None:
            self.graph.remove((class_uri, RDFS.comment, None))
            if new_comment:
                self.graph.add((class_uri, RDFS.comment, Literal(new_comment)))

        if remove_parent:
            self.graph.remove((class_uri, RDFS.subClassOf, self._uri(remove_parent)))

        if new_parent:
            self.graph.add((class_uri, RDFS.subClassOf, self._uri(new_parent)))

    # Entity types that share the local-name space, each with the word the app
    # calls it by; a rename or creation target must not already be any of these,
    # since they would collide on the same URI.
    ENTITY_TYPE_NAMES: ClassVar[dict[URIRef, str]] = {
        OWL.Class: "class",
        OWL.ObjectProperty: "object property",
        OWL.DatatypeProperty: "data property",
        OWL.NamedIndividual: "individual",
        SKOS.Concept: "SKOS concept",
        SKOS.ConceptScheme: "SKOS concept scheme",
    }
    _ENTITY_TYPES = tuple(ENTITY_TYPE_NAMES)

    # The entity kinds each resource type the app talks about covers, so a
    # collision can be told apart from a clash with a different kind. "property"
    # covers both flavours: they are one namespace of property names.
    RESOURCE_TYPE_KINDS: ClassVar[dict[str, frozenset[str]]] = {
        "class": frozenset({"class"}),
        "property": frozenset({"object property", "data property"}),
        "individual": frozenset({"individual"}),
        "concept": frozenset({"SKOS concept"}),
        "scheme": frozenset({"SKOS concept scheme"}),
    }

    def _name_in_use(self, uri: URIRef) -> bool:
        """True if `uri` is already defined as any class, property, individual,
        SKOS concept or scheme. Guards renames against cross-type collisions."""
        return any((uri, RDF.type, t) in self.graph for t in self._ENTITY_TYPES)

    def entity_kinds(self, name: str, namespace: str | None = None) -> list[str]:
        """The kinds of entity the URI ``name`` resolves to is already defined as.

        Empty when the name is free. More than one entry means the URI already
        carries several types (OWL punning), which is legal RDF but is what makes
        one entity show up on two pages of the app.
        """
        uri = self._uri(name, namespace)
        return [
            kind
            for etype, kind in self.ENTITY_TYPE_NAMES.items()
            if (uri, RDF.type, etype) in self.graph
        ]

    def name_conflict_reason(
        self, name: str, resource_type: str, namespace: str | None = None
    ) -> str | None:
        """Why ``name`` cannot be created as ``resource_type``, or None if it can.

        The name is checked against every entity kind, not only its own: classes,
        properties, individuals and SKOS concepts all live in the same URI space,
        so naming a class after an existing individual does not create a second
        entity. It adds ``owl:Class`` to the individual, which the app then lists
        as both, and deleting either one takes the whole thing (issue #279).
        """
        kinds = self.entity_kinds(name, namespace)
        if not kinds:
            return None
        if any(kind in self._kinds_of(resource_type) for kind in kinds):
            return f"{resource_type.capitalize()} '{name}' already exists!"
        return self._cross_kind_message(name, kinds[0], resource_type)

    def _kinds_of(self, resource_type: str) -> frozenset[str]:
        """The entity kinds ``resource_type`` names. An engine kind ("object
        property") stands for itself; the app's wider words are mapped."""
        return self.RESOURCE_TYPE_KINDS.get(resource_type, frozenset({resource_type}))

    def _cross_kind_message(self, name: str, other: str, resource_type: str) -> str:
        return (
            f"'{name}' is already {_with_article(other)} in this ontology. "
            "Classes, properties, individuals and SKOS concepts share one set "
            f"of names, so this would make that {other} "
            f"{_with_article(resource_type)} as well instead of creating a new "
            "one. Choose a different name."
        )

    def cross_kind_conflict(
        self, name: str, resource_type: str, namespace: str | None = None
    ) -> str | None:
        """Why ``name`` cannot be used for a ``resource_type``, when *only* other
        kinds of entity own it. None when the name is free, and None when it
        already is this kind as well: re-adding an existing class is how
        templates and bulk rows top one up, and an ontology that arrived punned
        (PROV-O's EmptyCollection is a class and an individual) must stay usable
        as the kind it is. Neither adds a type the name did not already carry.
        """
        kinds = self.entity_kinds(name, namespace)
        if not kinds or any(kind in self._kinds_of(resource_type) for kind in kinds):
            return None
        return self._cross_kind_message(name, kinds[0], resource_type)

    def _require_free_name(
        self, name: str, resource_type: str, namespace: str | None = None
    ) -> None:
        """Raise ``ValueError`` if another kind of entity owns ``name``.

        Every ``add_*`` runs this, so the guard holds for programmatic callers
        too and not only for the app's create forms (issue #279). Loading and
        merging graphs go around it: an ontology that arrives with a punned name
        (PROV-O has one) is still read as it stands, and validation reports it.
        """
        if reason := self.cross_kind_conflict(name, resource_type, namespace):
            raise ValueError(reason)

    def rename_class(self, old_name: str, new_name: str) -> bool:
        """Rename a class, updating all references.

        The renamed class keeps its current namespace: a new local name is
        placed in the same namespace as ``old_name`` (a full URI passed as
        ``new_name`` still overrides).
        """
        if old_name == new_name:
            return True
        self._require_valid_name(new_name)

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name, self._namespace_of(old_uri))

        # Refuse if the target name is already used by any entity (any type).
        if self._name_in_use(new_uri):
            return False

        # Collect all triples to update
        updates: _TripleUpdates = []

        # Triples where old_uri is subject
        for p, o in self.graph.predicate_objects(old_uri):
            updates.append(((old_uri, p, o), (new_uri, p, o)))

        # Triples where old_uri is object
        for s, p in self.graph.subject_predicates(old_uri):
            updates.append(((s, p, old_uri), (s, p, new_uri)))

        # Apply updates
        for old_triple, new_triple in updates:
            self.graph.remove(old_triple)
            self.graph.add(new_triple)

        return True

    def get_delete_impact(
        self, name: str, resource_type: str = "class"
    ) -> dict[str, Any]:
        """Analyse the impact of deleting a resource before executing it.

        Args:
            name: local name or full URI of the resource
            resource_type: one of the keys of ``RESOURCE_TYPE_KINDS`` — "class",
                "property", "individual", "concept" or "scheme". It selects both
                the impact detail collected and which types count as the
                resource's own, so passing the wrong one reports the resource as
                punned with itself.

        Returns a dict with categorised impact counts and details.
        """
        uri = self._uri(name)
        impact: dict[str, Any] = {
            "resource": name,
            "resource_type": resource_type,
            "direct_triples": 0,
            "subclasses": [],
            "instances": [],
            "domain_of": [],
            "range_of": [],
            "annotations": 0,
            "relations": [],
            "property_assertions": [],
            # Other kinds the same URI is typed as. Deletion removes every
            # triple about it, so a punned name loses both definitions at once
            # and the preview has to say so (issue #279).
            "also_typed_as": [
                kind
                for kind in self.entity_kinds(name)
                if kind not in self._kinds_of(resource_type)
            ],
        }

        if resource_type == "class":
            # Subclasses that reference this class as parent
            for child in self.graph.subjects(RDFS.subClassOf, uri):
                if isinstance(child, URIRef):
                    impact["subclasses"].append(self._local_name(child))

            # Instances typed with this class
            for ind in self.graph.subjects(RDF.type, uri):
                if (
                    isinstance(ind, URIRef)
                    and (ind, RDF.type, OWL.NamedIndividual) in self.graph
                ):
                    impact["instances"].append(self._local_name(ind))

            # Properties that use this class as domain
            for prop in self.graph.subjects(RDFS.domain, uri):
                if isinstance(prop, URIRef):
                    impact["domain_of"].append(self._local_name(prop))

            # Properties that use this class as range
            for prop in self.graph.subjects(RDFS.range, uri):
                if isinstance(prop, URIRef):
                    impact["range_of"].append(self._local_name(prop))

        elif resource_type == "property":
            # Triples where this property is used as predicate
            for s, o in self.graph.subject_objects(uri):
                if isinstance(s, URIRef):
                    impact["property_assertions"].append(
                        f"{self._local_name(s)} -> {self._local_name(o) if isinstance(o, URIRef) else str(o)}"
                    )

        elif resource_type == "individual":
            # Relations referencing this individual as object
            for s, p in self.graph.subject_predicates(uri):
                if isinstance(s, URIRef) and p not in (RDF.type,):
                    impact["relations"].append(
                        f"{self._local_name(s)} {self._local_name(p)}"
                    )

        elif resource_type in ("concept", "scheme"):
            # SKOS links pointing here: broader/narrower/related for a concept,
            # the inScheme of every concept in it for a scheme.
            for s, p in self.graph.subject_predicates(uri):
                if isinstance(s, URIRef) and p not in (RDF.type,):
                    impact["relations"].append(
                        f"{self._local_name(s)} {self._local_name(p)}"
                    )

        # Count direct triples (subject) and referencing triples (object)
        impact["direct_triples"] = len(list(self.graph.predicate_objects(uri)))

        # Count annotations (literal-valued predicates on this resource)
        structural = {
            RDF.type,
            RDFS.subClassOf,
            RDFS.subPropertyOf,
            RDFS.domain,
            RDFS.range,
            OWL.equivalentClass,
            OWL.disjointWith,
            OWL.inverseOf,
        }
        for p, o in self.graph.predicate_objects(uri):
            if p not in structural and isinstance(o, Literal):
                impact["annotations"] += 1

        # Total affected triples. Build the exact set deletion would remove so
        # the preview matches delete_class/delete_property — which also purge the
        # whole restriction blank nodes that reference this resource (a class
        # used as a restriction value contributes only one direct triple, but
        # removing the orphaned restriction takes its other triples too).
        removed = set(self.graph.triples((uri, None, None)))
        removed.update(self.graph.triples((None, None, uri)))
        if resource_type == "property":
            removed.update(self.graph.triples((None, uri, None)))
        for r in self._restrictions_referencing(uri):
            removed.update(self.graph.triples((r, None, None)))
            removed.update(self.graph.triples((None, RDFS.subClassOf, r)))
        impact["total_triples"] = len(removed)

        return impact

    def format_delete_impact(self, impact: dict[str, Any]) -> str:
        """Format an impact dict into a human-readable summary string."""
        parts = []
        rt = impact["resource_type"]
        parts.append(
            f"Deleting {rt} **{impact['resource']}** will remove {impact['total_triples']} triple(s)."
        )

        if impact["also_typed_as"]:
            kinds = ", ".join(_with_article(k) for k in impact["also_typed_as"])
            parts.append(
                f"- **This name is also {kinds}**: it is one resource, so "
                f"deleting the {rt} deletes that too"
            )
        if impact["subclasses"]:
            parts.append(
                f"- {len(impact['subclasses'])} subclass link(s) lost: {', '.join(impact['subclasses'])}"
            )
        if impact["instances"]:
            parts.append(
                f"- {len(impact['instances'])} instance(s) lose their class type: {', '.join(impact['instances'])}"
            )
        if impact["domain_of"]:
            parts.append(
                f"- {len(impact['domain_of'])} property domain reference(s) lost: {', '.join(impact['domain_of'])}"
            )
        if impact["range_of"]:
            parts.append(
                f"- {len(impact['range_of'])} property range reference(s) lost: {', '.join(impact['range_of'])}"
            )
        if impact["annotations"]:
            parts.append(f"- {impact['annotations']} annotation(s) removed")
        if impact["property_assertions"]:
            parts.append(
                f"- {len(impact['property_assertions'])} property assertion(s) removed"
            )
        if impact["relations"]:
            parts.append(f"- {len(impact['relations'])} inbound relation(s) removed")

        return "\n".join(parts)

    def delete_class(self, name: str):
        """Delete a class and all its references."""
        class_uri = self._uri(name)
        # Remove restrictions this class owns or that point at it as a value, so
        # reused-property links (link_classes) don't leave orphan blank nodes.
        self._purge_restrictions_referencing(class_uri)
        # Remove all triples where this class is subject or object
        self.graph.remove((class_uri, None, None))
        self.graph.remove((None, None, class_uri))

    def get_classes(self) -> list[dict[str, Any]]:
        """Get all classes with their details.

        Each entry includes both local-name lists (`parents`, `children`) and
        URI lists (`parent_uris`, `child_uris`). The local-name lists keep
        existing callers working; consumers that need to disambiguate across
        namespaces (e.g. the graph visualizer) should use the URI lists.
        """
        classes = []
        for class_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, BNode):
                continue  # Skip anonymous classes (restrictions)

            class_info: dict[str, Any] = {
                "uri": str(class_uri),
                "name": self._local_name(class_uri),
                "label": str(self.graph.value(class_uri, RDFS.label) or ""),
                "comment": str(self.graph.value(class_uri, RDFS.comment) or ""),
                "parents": [],
                "parent_uris": [],
                "children": [],
                "child_uris": [],
            }

            # Get parent classes
            for parent in self.graph.objects(class_uri, RDFS.subClassOf):
                if isinstance(parent, URIRef):
                    class_info["parents"].append(self._local_name(parent))
                    class_info["parent_uris"].append(str(parent))

            # Get child classes
            for child in self.graph.subjects(RDFS.subClassOf, class_uri):
                if isinstance(child, URIRef):
                    class_info["children"].append(self._local_name(child))
                    class_info["child_uris"].append(str(child))

            classes.append(class_info)

        return sorted(classes, key=lambda x: x["name"])

    def get_class_hierarchy(self) -> dict[str, list[str]]:
        """Get class hierarchy as adjacency list."""
        hierarchy: dict[str, list[str]] = {}
        for class_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, BNode):
                continue
            name = self._local_name(class_uri)
            hierarchy[name] = []
            for child in self.graph.subjects(RDFS.subClassOf, class_uri):
                if isinstance(child, URIRef):
                    hierarchy[name].append(self._local_name(child))
        return hierarchy

    # ==================== BULK OPERATIONS ====================

    @staticmethod
    def parse_bulk_text(
        text: str,
        columns: list[str] | None = None,
        default_columns: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Parse multi-line text into list of dicts.

        Supports:
        - Simple mode: one name per line (returns dicts with 'name' key)
        - CSV mode: delimiter-separated values, with or without a header row

        Delimiter detection: the delimiter is taken from the first line that
        contains one, choosing whichever of ';' / ',' occurs more often on that
        line (ties and no-delimiter default to ','). Deciding from a single line
        by frequency means a lone ';' inside a comma CSV label (or a ',' inside a
        semicolon-delimited value) does not flip the delimiter for the whole
        input. Semicolons are handy when labels themselves contain commas.

        If ``columns`` is provided, each line is split and mapped to those columns.
        Otherwise, if the first line looks like a header (contains 'name'), it is
        used as the columns. If there is no header but a line contains the
        delimiter and ``default_columns`` is provided, the values are mapped
        positionally onto ``default_columns``. Failing all of that, each line is
        treated as a single name.
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return []

        # Determine the delimiter from the first line that contains one. When the
        # column count is known, prefer whichever delimiter splits that line into
        # exactly that many fields; if both do (equal numbers of ',' and ';'),
        # break the tie by whichever appears first, since the leading field (the
        # name) is delimiter-free and its terminator is the real delimiter.
        # Otherwise fall back to whichever separator is more frequent on the
        # line, so a stray ';' in a comma CSV (or ',' in a semicolon CSV) can't
        # flip it.
        expected = (
            len(columns)
            if columns
            else (len(default_columns) if default_columns else None)
        )
        delimiter = ","
        for line in lines:
            if ";" not in line and "," not in line:
                continue
            semi_exact = expected and ";" in line and len(line.split(";")) == expected
            comma_exact = expected and "," in line and len(line.split(",")) == expected
            if semi_exact and comma_exact:
                delimiter = ";" if line.index(";") < line.index(",") else ","
            elif semi_exact:
                delimiter = ";"
            elif comma_exact:
                delimiter = ","
            else:
                delimiter = ";" if line.count(";") > line.count(",") else ","
            break

        # Auto-detect CSV header
        if columns is None and delimiter in lines[0]:
            header = [c.strip().lower() for c in lines[0].split(delimiter)]
            if "name" in header:
                columns = header
                lines = lines[1:]

        # Header-optional: delimiter present in the data but no header row.
        if (
            columns is None
            and default_columns
            and any(delimiter in line for line in lines)
        ):
            columns = default_columns

        if columns:
            result = []
            for line in lines:
                parts = [p.strip() for p in line.split(delimiter)]
                entry = {}
                for i, col in enumerate(columns):
                    entry[col] = parts[i] if i < len(parts) else ""
                if entry.get("name"):
                    result.append(entry)
            return result

        # Simple mode: one name per line
        return [{"name": line} for line in lines]

    def bulk_add_classes(self, entries: list[dict[str, str]]) -> dict[str, Any]:
        """Batch create classes.

        Each entry dict can have: name, label, parent, namespace. Duplicates are
        detected by full URI, so the same local name in a different namespace is
        not treated as existing.

        A referenced parent that is not already a class is declared as a bare
        ``owl:Class`` (issue #106), so the ``rdfs:subClassOf`` target is a real
        class node (visible in Visualization), matching the manual flow of
        creating the parent, creating the child, then setting the parent. This
        is done as a backfill after all rows are processed, keyed by the parent's
        full URI: a parent that another row actually creates (with its own
        label/comment) is left alone, but one whose explicit row is missing,
        skipped, or errors is still declared so no dangling parent remains.

        A row whose class already exists is not dropped outright: if it names a
        parent the class does not yet have, that parent is added as an extra
        ``rdfs:subClassOf`` (multiple inheritance) and the row is reported under
        ``updated`` (issue #157). Two rows with the same name and different
        parents therefore give the class both parents. An existing row with no
        new parent to add stays in ``skipped``; label/comment on an existing
        class are left untouched.

        Returns {created: [], updated: [], errors: [], skipped: []}.
        """
        result: dict[str, Any] = {
            "created": [],
            "updated": [],
            "errors": [],
            "skipped": [],
        }
        existing = {c["uri"] for c in self.get_classes()}
        referenced_parents: set[str] = set()

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            namespace = entry.get("namespace", "").strip() or None
            parent = entry.get("parent", "").strip() or None
            uri = str(self._uri(name, namespace))
            # Both halves of the row are checked before anything is written: a
            # parent owned by another kind of entity would otherwise be linked
            # to (and then declared a class by the backfill), leaving the class
            # listed under an individual (issue #279).
            conflict = self.cross_kind_conflict(name, "class", namespace)
            if not conflict and parent:
                conflict = self.cross_kind_conflict(parent, "class")
            if conflict:
                result["errors"].append({"name": name, "error": conflict})
                continue
            if uri in existing:
                # Existing class: add a newly named parent as an extra
                # subClassOf rather than silently dropping the whole row (#157).
                # A row with no new parent to contribute is still a plain skip.
                if not parent:
                    result["skipped"].append(name)
                    continue
                try:
                    self._require_valid_name(parent)
                except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                    result["errors"].append({"name": name, "error": str(e)})
                    continue
                class_ref = self._uri(name, namespace)
                parent_ref = self._uri(parent)
                if (class_ref, RDFS.subClassOf, parent_ref) in self.graph:
                    result["skipped"].append(name)
                else:
                    self.graph.add((class_ref, RDFS.subClassOf, parent_ref))
                    result["updated"].append(name)
                    referenced_parents.add(str(parent_ref))
                continue
            try:
                self.add_class(
                    name,
                    parent=parent,
                    label=entry.get("label", "").strip() or None,
                    namespace=namespace,
                )
                result["created"].append(name)
                existing.add(uri)
                if parent:
                    referenced_parents.add(str(self._uri(parent)))
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})

        # Backfill: any referenced parent that no successful row declared as a
        # class becomes a bare owl:Class, so the hierarchy has no dangling target.
        # Only parents from rows that got this far are here, so none of them is
        # owned by another kind of entity; add_class refuses one anyway.
        for parent_uri in sorted(referenced_parents - existing):
            try:
                created_uri = self.add_class(parent_uri)
                existing.add(parent_uri)
                result["created"].append(self._local_name(created_uri))
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": parent_uri, "error": str(e)})

        return result

    def bulk_add_properties(
        self, entries: list[dict[str, str]], property_type: str = "object"
    ) -> dict[str, Any]:
        """Batch create properties.

        Each entry dict can have: name, domain, range, label, namespace.
        property_type: "object" or "data". Duplicates are detected by full URI.
        Returns {created: [], errors: [], skipped: []}.
        """
        result: dict[str, Any] = {"created": [], "errors": [], "skipped": []}
        if property_type == "object":
            existing = {p["uri"] for p in self.get_object_properties()}
        else:
            existing = {p["uri"] for p in self.get_data_properties()}

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            namespace = entry.get("namespace", "").strip() or None
            uri = str(self._uri(name, namespace))
            if uri in existing:
                result["skipped"].append(name)
                continue
            # add_object_property/add_data_property refuse a name another kind
            # of entity owns (including the other flavour of property), so a
            # clashing row lands in errors (issue #279).
            try:
                domain = entry.get("domain", "").strip() or None
                range_ = entry.get("range", "").strip() or None
                label = entry.get("label", "").strip() or None
                if property_type == "object":
                    self.add_object_property(
                        name,
                        domain=domain,
                        range_=range_,
                        label=label,
                        namespace=namespace,
                    )
                else:
                    self.add_data_property(
                        name,
                        domain=domain,
                        range_=range_ or "string",
                        label=label,
                        namespace=namespace,
                    )
                result["created"].append(name)
                existing.add(uri)
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})

        return result

    def bulk_add_individuals(self, entries: list[dict[str, str]]) -> dict[str, Any]:
        """Batch create individuals.

        Each entry dict can have: name, class, label, namespace. Duplicates are
        detected by full URI.
        Returns {created: [], errors: [], skipped: []}.
        """
        result: dict[str, Any] = {"created": [], "errors": [], "skipped": []}
        existing = {i["uri"] for i in self.get_individuals()}

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            class_name = entry.get("class", "").strip()
            if not class_name:
                result["errors"].append({"name": name, "error": "Missing class"})
                continue
            namespace = entry.get("namespace", "").strip() or None
            uri = str(self._uri(name, namespace))
            if uri in existing:
                result["skipped"].append(name)
                continue
            # add_individual refuses a name a class, property or concept
            # already owns, so a clashing row lands in errors (issue #279).
            try:
                self.add_individual(
                    name,
                    class_name=class_name,
                    label=entry.get("label", "").strip() or None,
                    namespace=namespace,
                )
                result["created"].append(name)
                existing.add(uri)
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})

        return result

    def bulk_delete_classes(self, names: list[str]) -> dict[str, Any]:
        """Batch delete classes. Returns {deleted: [], errors: []}."""
        result: dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_class(name)
                result["deleted"].append(name)
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_delete_properties(self, names: list[str]) -> dict[str, Any]:
        """Batch delete properties. Returns {deleted: [], errors: []}."""
        result: dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_property(name)
                result["deleted"].append(name)
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_delete_individuals(self, names: list[str]) -> dict[str, Any]:
        """Batch delete individuals. Returns {deleted: [], errors: []}."""
        result: dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_individual(name)
                result["deleted"].append(name)
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_update_annotations(self, updates: list[dict[str, str]]) -> dict[str, Any]:
        """Apply batch annotation changes.

        Each update dict has: resource, predicate, value, lang (optional),
        and action ("add" or "delete"). If action is omitted, defaults to "add".
        Returns {applied: int, errors: []}.
        """
        result: dict[str, Any] = {"applied": 0, "errors": []}

        for update in updates:
            resource = update.get("resource", "").strip()
            predicate = update.get("predicate", "").strip()
            value = update.get("value", "").strip()
            lang = update.get("lang", "").strip() or None
            action = update.get("action", "add").strip().lower()

            if not resource or not predicate:
                result["errors"].append(
                    {
                        "resource": resource,
                        "error": "Missing resource or predicate",
                    }
                )
                continue

            try:
                if action == "delete":
                    self.delete_annotation(
                        resource, predicate, value=value or None, lang=lang
                    )
                else:
                    if not value:
                        result["errors"].append(
                            {
                                "resource": resource,
                                "error": "Missing value for add",
                            }
                        )
                        continue
                    self.add_annotation(resource, predicate, value, lang=lang)
                result["applied"] += 1
            except Exception as e:  # noqa: BLE001 - one bad row must not abort the batch
                result["errors"].append(
                    {
                        "resource": resource,
                        "error": str(e),
                    }
                )

        return result

    # ==================== PROPERTY OPERATIONS ====================

    def add_object_property(
        self,
        name: str,
        domain: str | None = None,
        range_: str | None = None,
        label: str | None = None,
        comment: str | None = None,
        functional: bool = False,
        inverse_functional: bool = False,
        transitive: bool = False,
        symmetric: bool = False,
        asymmetric: bool = False,
        reflexive: bool = False,
        irreflexive: bool = False,
        inverse_of: str | None = None,
        namespace: str | None = None,
    ) -> URIRef:
        """Add a new object property.

        ``namespace`` places the property in a specific namespace (any bound
        prefix); when omitted the base namespace is used.
        """
        self._require_valid_name(name)
        self._require_free_name(name, "object property", namespace)
        for ref in (domain, range_, inverse_of):
            if ref:
                self._require_valid_name(ref)
        prop_uri = self._uri(name, namespace)
        self.graph.add((prop_uri, RDF.type, OWL.ObjectProperty))

        if domain:
            self.graph.add((prop_uri, RDFS.domain, self._uri(domain)))
        if range_:
            self.graph.add((prop_uri, RDFS.range, self._uri(range_)))
        if label:
            self.graph.add((prop_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((prop_uri, RDFS.comment, Literal(comment)))

        # Property characteristics
        if functional:
            self.graph.add((prop_uri, RDF.type, OWL.FunctionalProperty))
        if inverse_functional:
            self.graph.add((prop_uri, RDF.type, OWL.InverseFunctionalProperty))
        if transitive:
            self.graph.add((prop_uri, RDF.type, OWL.TransitiveProperty))
        if symmetric:
            self.graph.add((prop_uri, RDF.type, OWL.SymmetricProperty))
        if asymmetric:
            self.graph.add((prop_uri, RDF.type, OWL.AsymmetricProperty))
        if reflexive:
            self.graph.add((prop_uri, RDF.type, OWL.ReflexiveProperty))
        if irreflexive:
            self.graph.add((prop_uri, RDF.type, OWL.IrreflexiveProperty))
        if inverse_of:
            self.graph.add((prop_uri, OWL.inverseOf, self._uri(inverse_of)))

        return prop_uri

    def add_data_property(
        self,
        name: str,
        domain: str | None = None,
        range_: str = "string",
        label: str | None = None,
        comment: str | None = None,
        functional: bool = False,
        namespace: str | None = None,
    ) -> URIRef:
        """Add a new data property.

        ``namespace`` places the property in a specific namespace (any bound
        prefix); when omitted the base namespace is used.
        """
        self._require_valid_name(name)
        self._require_free_name(name, "data property", namespace)
        if domain:
            self._require_valid_name(domain)
        prop_uri = self._uri(name, namespace)
        self.graph.add((prop_uri, RDF.type, OWL.DatatypeProperty))

        if domain:
            self.graph.add((prop_uri, RDFS.domain, self._uri(domain)))
        if range_:
            datatype = self.XSD_DATATYPES.get(range_, XSD.string)
            self.graph.add((prop_uri, RDFS.range, datatype))
        if label:
            self.graph.add((prop_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((prop_uri, RDFS.comment, Literal(comment)))
        if functional:
            self.graph.add((prop_uri, RDF.type, OWL.FunctionalProperty))

        return prop_uri

    def update_property(
        self,
        name: str,
        new_label: str | None = None,
        new_comment: str | None = None,
        new_domain: str | None = None,
        new_range: str | None = None,
    ):
        """Update an existing property."""
        if new_domain:
            self._require_valid_name(new_domain)
        # new_range may be a datatype (looked up below) or a class URI; only the
        # class case reaches _uri() and needs validating.
        if new_range and new_range not in self.XSD_DATATYPES:
            self._require_valid_name(new_range)
        prop_uri = self._uri(name)

        if new_label is not None:
            self.graph.remove((prop_uri, RDFS.label, None))
            if new_label:
                self.graph.add((prop_uri, RDFS.label, Literal(new_label)))

        if new_comment is not None:
            self.graph.remove((prop_uri, RDFS.comment, None))
            if new_comment:
                self.graph.add((prop_uri, RDFS.comment, Literal(new_comment)))

        if new_domain is not None:
            self.graph.remove((prop_uri, RDFS.domain, None))
            if new_domain:
                self.graph.add((prop_uri, RDFS.domain, self._uri(new_domain)))

        if new_range is not None:
            self.graph.remove((prop_uri, RDFS.range, None))
            if new_range:
                # Check if it's a datatype or class
                if new_range in self.XSD_DATATYPES:
                    self.graph.add(
                        (prop_uri, RDFS.range, self.XSD_DATATYPES[new_range])
                    )
                else:
                    self.graph.add((prop_uri, RDFS.range, self._uri(new_range)))

    def rename_property(self, old_name: str, new_name: str) -> bool:
        """Rename a property, updating all references.

        The renamed property keeps its current namespace (see
        :meth:`rename_class`).
        """
        if old_name == new_name:
            return True
        self._require_valid_name(new_name)

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name, self._namespace_of(old_uri))

        # Refuse if the target name is already used by any entity (any type).
        if self._name_in_use(new_uri):
            return False

        # Collect all triples to update
        updates: _TripleUpdates = []

        # Triples where old_uri is subject
        for p, o in self.graph.predicate_objects(old_uri):
            updates.append(((old_uri, p, o), (new_uri, p, o)))

        # Triples where old_uri is object
        for s, p in self.graph.subject_predicates(old_uri):
            updates.append(((s, p, old_uri), (s, p, new_uri)))

        # Triples where old_uri is predicate (property assertions)
        for s, o in self.graph.subject_objects(old_uri):
            updates.append(((s, old_uri, o), (s, new_uri, o)))

        # Apply updates
        for old_triple, new_triple in updates:
            self.graph.remove(old_triple)
            self.graph.add(new_triple)

        return True

    def _restrictions_referencing(self, node: Node) -> set:
        """Return the ``owl:Restriction`` blank nodes that reference ``node``.

        A restriction is a blank node carrying ``owl:onProperty`` plus a
        constraint (``someValuesFrom``/``allValuesFrom``/``hasValue``/cardinality)
        and is attached to its owning class via ``rdfs:subClassOf``. A node is
        "referenced" when it is the restriction's property/value (the bnode
        points at it) or its owning class (it points at the bnode). Shared by
        :meth:`_purge_restrictions_referencing` and :meth:`get_delete_impact` so
        the cleanup and its preview never drift.
        """
        targets = set()
        # Restrictions that mention `node` as a value: onProperty (property),
        # someValuesFrom/allValuesFrom/hasValue/onClass (a class value).
        for r in self.graph.subjects(None, node):
            if isinstance(r, BNode) and (r, RDF.type, OWL.Restriction) in self.graph:
                targets.add(r)
        # Restrictions owned by `node` (node rdfs:subClassOf [ a owl:Restriction ]).
        for r in self.graph.objects(node, RDFS.subClassOf):
            if isinstance(r, BNode) and (r, RDF.type, OWL.Restriction) in self.graph:
                targets.add(r)
        return targets

    def _purge_restrictions_referencing(self, node: Node) -> None:
        """Remove ``owl:Restriction`` blank nodes that reference ``node``.

        When the property, the owning class, or a class used as the
        restriction's value is deleted, the leftover restriction is malformed or
        orphaned. This removes each such restriction whole, along with any
        ``subClassOf`` links to it, so deletes never leave a dangling restriction
        behind (e.g. the reused property links created by :meth:`link_classes`).
        """
        for r in self._restrictions_referencing(node):
            self.graph.remove((None, RDFS.subClassOf, r))
            self.graph.remove((r, None, None))

    def delete_property(self, name: str):
        """Delete a property and all its references."""
        prop_uri = self._uri(name)
        # Drop reused-property restrictions (link_classes) before the blanket
        # removal, while their onProperty triple still points at this property.
        self._purge_restrictions_referencing(prop_uri)
        self.graph.remove((prop_uri, None, None))
        self.graph.remove((None, None, prop_uri))
        self.graph.remove((None, prop_uri, None))

    def get_object_properties(self) -> list[dict[str, Any]]:
        """Get all object properties with their details."""
        properties = []
        for prop_uri in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            if isinstance(prop_uri, BNode):
                continue

            prop_info: dict[str, Any] = {
                "uri": str(prop_uri),
                "name": self._local_name(prop_uri),
                "label": str(self.graph.value(prop_uri, RDFS.label) or ""),
                "comment": str(self.graph.value(prop_uri, RDFS.comment) or ""),
                "domain": "",
                "domain_uri": "",
                "range": "",
                "range_uri": "",
                "characteristics": [],
            }

            domain = self.graph.value(prop_uri, RDFS.domain)
            if not domain or not isinstance(domain, URIRef):
                for dp in _DOMAIN_INCLUDES:
                    domain = self.graph.value(prop_uri, dp)
                    if domain and isinstance(domain, URIRef):
                        break
            if domain and isinstance(domain, URIRef):
                prop_info["domain"] = self._local_name(domain)
                prop_info["domain_uri"] = str(domain)

            range_ = self.graph.value(prop_uri, RDFS.range)
            if not range_ or not isinstance(range_, URIRef):
                for rp in _RANGE_INCLUDES:
                    range_ = self.graph.value(prop_uri, rp)
                    if range_ and isinstance(range_, URIRef):
                        break
            if range_ and isinstance(range_, URIRef):
                prop_info["range"] = self._local_name(range_)
                prop_info["range_uri"] = str(range_)

            # Check characteristics
            if (prop_uri, RDF.type, OWL.FunctionalProperty) in self.graph:
                prop_info["characteristics"].append("Functional")
            if (prop_uri, RDF.type, OWL.InverseFunctionalProperty) in self.graph:
                prop_info["characteristics"].append("InverseFunctional")
            if (prop_uri, RDF.type, OWL.TransitiveProperty) in self.graph:
                prop_info["characteristics"].append("Transitive")
            if (prop_uri, RDF.type, OWL.SymmetricProperty) in self.graph:
                prop_info["characteristics"].append("Symmetric")
            if (prop_uri, RDF.type, OWL.AsymmetricProperty) in self.graph:
                prop_info["characteristics"].append("Asymmetric")
            if (prop_uri, RDF.type, OWL.ReflexiveProperty) in self.graph:
                prop_info["characteristics"].append("Reflexive")
            if (prop_uri, RDF.type, OWL.IrreflexiveProperty) in self.graph:
                prop_info["characteristics"].append("Irreflexive")

            inverse = self.graph.value(prop_uri, OWL.inverseOf)
            if inverse:
                prop_info["inverse_of"] = self._local_name(inverse)

            properties.append(prop_info)

        return sorted(properties, key=lambda x: x["name"])

    def get_data_properties(self) -> list[dict[str, Any]]:
        """Get all data properties with their details."""
        properties = []
        for prop_uri in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            if isinstance(prop_uri, BNode):
                continue

            prop_info = {
                "uri": str(prop_uri),
                "name": self._local_name(prop_uri),
                "label": str(self.graph.value(prop_uri, RDFS.label) or ""),
                "comment": str(self.graph.value(prop_uri, RDFS.comment) or ""),
                "domain": "",
                "domain_uri": "",
                "range": "",
                "functional": False,
            }

            domain = self.graph.value(prop_uri, RDFS.domain)
            if not domain or not isinstance(domain, URIRef):
                for dp in _DOMAIN_INCLUDES:
                    domain = self.graph.value(prop_uri, dp)
                    if domain and isinstance(domain, URIRef):
                        break
            if domain and isinstance(domain, URIRef):
                prop_info["domain"] = self._local_name(domain)
                prop_info["domain_uri"] = str(domain)

            range_ = self.graph.value(prop_uri, RDFS.range)
            if range_:
                prop_info["range"] = self._local_name(range_)

            prop_info["functional"] = (
                prop_uri,
                RDF.type,
                OWL.FunctionalProperty,
            ) in self.graph

            properties.append(prop_info)

        return sorted(properties, key=lambda x: x["name"])

    # ==================== INDIVIDUAL OPERATIONS ====================

    def add_individual(
        self,
        name: str,
        class_name: str,
        label: str | None = None,
        comment: str | None = None,
        namespace: str | None = None,
    ) -> URIRef:
        """Add a new individual (instance).

        ``namespace`` places the individual in a specific namespace (any bound
        prefix); when omitted the base namespace is used. The class reference is
        resolved independently, so an individual can live in a different
        namespace than its type.
        """
        self._require_valid_name(name)
        self._require_free_name(name, "individual", namespace)
        self._require_valid_name(class_name)
        ind_uri = self._uri(name, namespace)
        class_uri = self._uri(class_name)

        self.graph.add((ind_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((ind_uri, RDF.type, class_uri))

        if label:
            self.graph.add((ind_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((ind_uri, RDFS.comment, Literal(comment)))

        return ind_uri

    def add_individual_property(
        self,
        individual: str,
        property_name: str,
        value: Any,
        is_object_property: bool = True,
    ):
        """Add a property assertion to an individual."""
        ind_uri = self._uri(individual)
        prop_uri = self._uri(property_name)

        if is_object_property:
            value_uri = self._uri(value)
            self.graph.add((ind_uri, prop_uri, value_uri))
        else:
            self.graph.add((ind_uri, prop_uri, Literal(value)))

    def update_individual(
        self,
        name: str,
        new_label: str | None = None,
        new_comment: str | None = None,
        add_class: str | None = None,
        remove_class: str | None = None,
    ):
        """Update an existing individual."""
        if add_class:
            self._require_valid_name(add_class)
        ind_uri = self._uri(name)

        if new_label is not None:
            self.graph.remove((ind_uri, RDFS.label, None))
            if new_label:
                self.graph.add((ind_uri, RDFS.label, Literal(new_label)))

        if new_comment is not None:
            self.graph.remove((ind_uri, RDFS.comment, None))
            if new_comment:
                self.graph.add((ind_uri, RDFS.comment, Literal(new_comment)))

        if add_class:
            self.graph.add((ind_uri, RDF.type, self._uri(add_class)))

        if remove_class:
            self.graph.remove((ind_uri, RDF.type, self._uri(remove_class)))

    def rename_individual(self, old_name: str, new_name: str) -> bool:
        """Rename an individual, updating all references.

        The renamed individual keeps its current namespace (see
        :meth:`rename_class`).
        """
        if old_name == new_name:
            return True
        self._require_valid_name(new_name)

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name, self._namespace_of(old_uri))

        # Refuse if the target name is already used by any entity (any type).
        if self._name_in_use(new_uri):
            return False

        # Collect all triples to update
        updates: _TripleUpdates = []

        # Triples where old_uri is subject
        for p, o in self.graph.predicate_objects(old_uri):
            updates.append(((old_uri, p, o), (new_uri, p, o)))

        # Triples where old_uri is object
        for s, p in self.graph.subject_predicates(old_uri):
            updates.append(((s, p, old_uri), (s, p, new_uri)))

        # Apply updates
        for old_triple, new_triple in updates:
            self.graph.remove(old_triple)
            self.graph.add(new_triple)

        return True

    def delete_individual(self, name: str):
        """Delete an individual and all its references."""
        ind_uri = self._uri(name)
        self.graph.remove((ind_uri, None, None))
        self.graph.remove((None, None, ind_uri))

    def get_individuals(self) -> list[dict[str, Any]]:
        """Get all individuals with their details."""
        individuals = []
        seen = set()

        for ind_uri in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            if isinstance(ind_uri, BNode) or str(ind_uri) in seen:
                continue
            seen.add(str(ind_uri))

            ind_info: dict[str, Any] = {
                "uri": str(ind_uri),
                "name": self._local_name(ind_uri),
                "label": str(self.graph.value(ind_uri, RDFS.label) or ""),
                "comment": str(self.graph.value(ind_uri, RDFS.comment) or ""),
                "classes": [],
                "class_uris": [],
                "properties": [],
            }

            # Get classes — expose both the local name (for display) and the
            # full URI (so consumers like the graph viewer can target the
            # exact class even when local names collide across namespaces).
            for class_uri in self.graph.objects(ind_uri, RDF.type):
                if isinstance(class_uri, URIRef) and class_uri != OWL.NamedIndividual:
                    ind_info["classes"].append(self._local_name(class_uri))
                    ind_info["class_uris"].append(str(class_uri))

            # Get property assertions. ``value`` is the local name for display;
            # ``value_uri`` carries the full URI of an object value (empty for a
            # literal) so callers can resolve the target unambiguously — two
            # individuals in different namespaces can share a local name.
            for pred, obj in self.graph.predicate_objects(ind_uri):
                if pred not in [RDF.type, RDFS.label, RDFS.comment]:
                    prop_name = self._local_name(pred)
                    is_ref = isinstance(obj, URIRef)
                    value = self._local_name(obj) if is_ref else str(obj)
                    ind_info["properties"].append(
                        {
                            "property": prop_name,
                            "value": value,
                            "value_uri": str(obj) if is_ref else "",
                        }
                    )

            individuals.append(ind_info)

        return sorted(individuals, key=lambda x: x["name"])

    # ==================== RESTRICTION OPERATIONS ====================

    @classmethod
    def _cardinality_value(cls, restriction_type: str, value: Any) -> int:
        """Return ``value`` as a cardinality, or raise ``ValueError``.

        Cardinalities are written as ``xsd:nonNegativeInteger``, so a negative
        number would serialize as invalid OWL. The Add form's number input
        blocks that at the widget; checking here covers the edit form's free-text
        value and any other caller (review P2).
        """
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{restriction_type} needs a whole number, got {value!r}"
            ) from None
        if number < 0:
            raise ValueError(f"{restriction_type} cannot be negative, got {number}")
        return number

    def add_restriction(
        self,
        class_name: str,
        property_name: str,
        restriction_type: str,
        value: Any,
        on_class: str | None = None,
    ) -> BNode:
        """Add a restriction to a class.

        Raises ``ValueError`` for a cardinality that is not a whole number of
        zero or more, so no caller can write a value that breaks the
        ``xsd:nonNegativeInteger`` it is stored as.
        """
        class_uri = self._uri(class_name)
        prop_uri = self._uri(property_name)

        # Everything that can be rejected is checked before the first triple is
        # written: raising once the blank node existed left an orphan
        # restriction behind, with no type and no value, that the Restrictions
        # page then listed as an empty row.
        restriction_pred = self.RESTRICTION_TYPES.get(restriction_type)
        if not restriction_pred:
            raise ValueError(f"Unknown restriction type: {restriction_type}")
        if restriction_type in self._CARDINALITY_TYPES:
            cardinality = self._cardinality_value(restriction_type, value)
        elif value is None or not str(value).strip():
            # An empty value would be written as the base namespace itself
            # (owl:someValuesFrom :), a restriction pointing at nothing.
            raise ValueError(f"{restriction_type} needs a value.")

        restriction = BNode()
        self.graph.add((restriction, RDF.type, OWL.Restriction))
        self.graph.add((restriction, OWL.onProperty, prop_uri))

        # Handle different value types
        if restriction_type in ["someValuesFrom", "allValuesFrom"]:
            self.graph.add((restriction, restriction_pred, self._uri(value)))
        elif restriction_type == "hasValue":
            if isinstance(value, str) and not value.startswith("http"):
                self.graph.add((restriction, restriction_pred, Literal(value)))
            else:
                self.graph.add((restriction, restriction_pred, self._uri(value)))
        elif restriction_type in self._CARDINALITY_TYPES:
            self.graph.add(
                (
                    restriction,
                    restriction_pred,
                    Literal(cardinality, datatype=XSD.nonNegativeInteger),
                )
            )
            if on_class:
                self.graph.add((restriction, OWL.onClass, self._uri(on_class)))

        # Add as subclass of the target class
        self.graph.add((class_uri, RDFS.subClassOf, restriction))

        return restriction

    #: ``link_classes`` semantics keyword -> restriction predicate name.
    LINK_SEMANTICS: ClassVar[dict[str, str]] = {
        "all": "allValuesFrom",
        "some": "someValuesFrom",
    }

    def link_classes(
        self,
        source: str,
        property_name: str,
        target: str,
        semantics: str = "all",
    ) -> BNode:
        """Link two classes via an existing property, reusing the property.

        This is the OWL-correct way to use one object property across many class
        pairs (``A``-``P``-``B``, ``C``-``P``-``D``, ...): each pair becomes a
        class restriction on the *source* class rather than another
        ``rdfs:domain``/``rdfs:range`` axiom (stacking those would *intersect*
        the domains, not union them). Thin wrapper over :meth:`add_restriction`.

        ``semantics`` selects the restriction flavour: ``"all"`` (default) writes
        ``source rdfs:subClassOf [ owl:onProperty P ; owl:allValuesFrom target ]``
        ("if source relates via P, the value is a target"); ``"some"`` writes an
        ``owl:someValuesFrom`` existential ("source relates via P to some target").
        """
        restriction_type = self.LINK_SEMANTICS.get(semantics)
        if restriction_type is None:
            raise ValueError(
                f"Unknown link semantics: {semantics!r} "
                f"(expected one of {sorted(self.LINK_SEMANTICS)})"
            )
        return self.add_restriction(source, property_name, restriction_type, target)

    def _iter_restrictions(self):
        """Yield ``(node, row)`` for every restriction in the graph.

        Shared by :meth:`get_restrictions`, :meth:`delete_restriction` and
        :meth:`update_restriction` so all three agree on what a restriction row
        is, and the last two can act on the exact node behind a row (issue #152).
        """
        for restriction in self.graph.subjects(RDF.type, OWL.Restriction):
            prop = self.graph.value(restriction, OWL.onProperty)
            if not prop:
                continue
            yield restriction, self._restriction_row(restriction, prop)

    def _restriction_row(self, restriction: Node, prop: Node) -> dict[str, Any]:
        """Build the display row for one restriction node."""
        rest_info: dict[str, Any] = {
            "property": self._local_name(prop),
            # Full URIs alongside the display-friendly local names so callers
            # can delete a restriction whose property/class live in an
            # external namespace (local names would resolve to the wrong URI).
            "property_uri": str(prop),
            "type": None,
            "value": None,
            "value_uri": None,
            "on_class": None,
            "on_class_uri": None,
            "applied_to": [],
            "applied_to_uris": [],
        }

        # Determine restriction type
        for rtype, pred in self.RESTRICTION_TYPES.items():
            val = self.graph.value(restriction, pred)
            if val is not None:
                rest_info["type"] = rtype
                if isinstance(val, URIRef):
                    rest_info["value"] = self._local_name(val)
                    rest_info["value_uri"] = str(val)
                else:
                    rest_info["value"] = str(val)
                break

        on_class = self.graph.value(restriction, OWL.onClass)
        if on_class:
            rest_info["on_class"] = self._local_name(on_class)
            rest_info["on_class_uri"] = str(on_class)

        # Find classes this restriction applies to
        for cls in self.graph.subjects(RDFS.subClassOf, restriction):
            if isinstance(cls, URIRef):
                rest_info["applied_to"].append(self._local_name(cls))
                rest_info["applied_to_uris"].append(str(cls))

        return rest_info

    def get_restrictions(self, class_name: str | None = None) -> list[dict[str, Any]]:
        """Get restrictions, optionally filtered by class."""
        return [
            row
            for _node, row in self._iter_restrictions()
            if class_name is None or class_name in row["applied_to"]
        ]

    def _restriction_matches(
        self,
        row: dict[str, Any],
        class_name: str,
        property_name: str,
        restriction_type: str,
        value: Any = None,
        on_class: str | None = None,
    ) -> bool:
        """Whether ``row`` is the restriction described by these fields.

        Names are compared as resolved URIs, so a local name matches only what it
        actually resolves to: passing ``Foo`` never touches a restriction on an
        imported ``other:Foo``, which is why callers holding URIs should pass
        them. ``value`` and ``on_class`` only narrow the match when given, and a
        literal value (a cardinality, a hasValue string) is compared as text
        since it has no URI.
        """

        def _same_entity(row_uri, wanted) -> bool:
            return row_uri is not None and str(row_uri) == str(self._uri(str(wanted)))

        if row["type"] != restriction_type:
            return False
        if not _same_entity(row["property_uri"], property_name):
            return False
        if not any(_same_entity(uri, class_name) for uri in row["applied_to_uris"]):
            return False
        if value is not None:
            if row["value_uri"] is not None:
                if not _same_entity(row["value_uri"], value):
                    return False
            elif str(row["value"]) != str(value):
                return False
        return on_class is None or _same_entity(row["on_class_uri"], on_class)

    def _find_restriction(
        self,
        class_name: str,
        property_name: str,
        restriction_type: str,
        value: Any = None,
        on_class: str | None = None,
    ):
        """Return the ``(node, row)`` for one restriction, or ``(None, None)``.

        Passing ``value`` (and ``on_class`` where it applies) is what makes the
        match exact: a class can carry several restrictions on the same property
        with the same type, differing only in value, and without them the first
        one wins — which used to delete the wrong one (issue #152).
        """
        for node, row in self._iter_restrictions():
            if self._restriction_matches(
                row, class_name, property_name, restriction_type, value, on_class
            ):
                return node, row
        return None, None

    def _detach_restriction(self, node: Node, class_name: str) -> None:
        """Unlink a restriction from one class, dropping the node once nothing
        else refers to it (a restriction can be shared by several classes)."""
        self.graph.remove((self._uri(class_name), RDFS.subClassOf, node))
        if not any(self.graph.subjects(RDFS.subClassOf, node)):
            self.graph.remove((node, None, None))

    def delete_restriction(
        self,
        class_name: str,
        property_name: str,
        restriction_type: str,
        value: Any = None,
        on_class: str | None = None,
    ) -> bool:
        """Delete a restriction from a class.

        Give ``value`` (and ``on_class`` for a qualified cardinality) to name
        exactly which one: a class may carry several restrictions on the same
        property and type, and without a value the first is removed, which is
        rarely the one on screen (issue #152). Returns whether one was removed.
        """
        node, row = self._find_restriction(
            class_name, property_name, restriction_type, value, on_class
        )
        if node is None or row is None:
            return False
        self._detach_restriction(node, class_name)
        return True

    # Restriction types whose value is a count rather than a class or literal.
    _CARDINALITY_TYPES = (
        "minCardinality",
        "maxCardinality",
        "exactCardinality",
        "minQualifiedCardinality",
        "maxQualifiedCardinality",
        "qualifiedCardinality",
    )

    @staticmethod
    def _restriction_spec(spec: dict[str, Any], label: str) -> tuple:
        """Pull the three identifying fields out of an update spec.

        Raises rather than letting a missing field resolve to something else:
        a spec without a class would otherwise match by property and type alone,
        which is the ambiguity this whole path exists to remove.
        """
        missing = [
            key
            for key in ("class_name", "property_name", "restriction_type")
            if not spec.get(key)
        ]
        if missing:
            raise ValueError(
                f"The {label} restriction is missing {', '.join(missing)}."
            )
        return (
            str(spec["class_name"]),
            str(spec["property_name"]),
            str(spec["restriction_type"]),
        )

    def update_restriction(self, old: dict[str, Any], new: dict[str, Any]) -> bool:
        """Replace one restriction with an edited one (issue #152).

        Both dicts take ``class_name``, ``property_name``, ``restriction_type``,
        ``value`` and optional ``on_class``; ``old`` should carry the value too,
        or a sibling restriction on the same property may be edited instead. The
        replacement is validated before the original is removed, so a rejected
        edit cannot destroy the restriction it was meant to change. Returns
        False when ``old`` is no longer in the graph.
        """
        old_class, old_property, old_type = self._restriction_spec(old, "old")
        new_class, new_property, new_type = self._restriction_spec(new, "new")

        if new_type not in self.RESTRICTION_TYPES:
            raise ValueError(f"Unknown restriction type: {new_type}")
        # Checked here as well as in add_restriction, so a bad replacement is
        # rejected before the original is detached.
        if new_type in self._CARDINALITY_TYPES:
            self._cardinality_value(new_type, new.get("value"))
        elif new.get("value") is None or not str(new.get("value")).strip():
            raise ValueError(f"{new_type} needs a value.")

        node, _row = self._find_restriction(
            old_class,
            old_property,
            old_type,
            old.get("value"),
            old.get("on_class"),
        )
        if node is None:
            return False

        self._detach_restriction(node, old_class)
        self.add_restriction(
            new_class,
            new_property,
            new_type,
            new.get("value"),
            on_class=new.get("on_class"),
        )
        return True

    # ==================== ANNOTATION OPERATIONS ====================

    # Common annotation predicate local names -> URIs. Shared by add and
    # delete so the two never drift apart (a stale subset on delete is what
    # made skos:example and others impossible to remove).
    _ANNOTATION_PREDICATES: ClassVar[dict[str, URIRef]] = {
        "label": RDFS.label,
        "comment": RDFS.comment,
        "seeAlso": RDFS.seeAlso,
        "isDefinedBy": RDFS.isDefinedBy,
        "prefLabel": SKOS.prefLabel,
        "altLabel": SKOS.altLabel,
        "definition": SKOS.definition,
        "example": SKOS.example,
        "note": SKOS.note,
        "title": DCTERMS.title,
        "description": DCTERMS.description,
        "creator": DCTERMS.creator,
        "contributor": DCTERMS.contributor,
        "date": DCTERMS.date,
        "deprecated": OWL.deprecated,
    }

    def _resolve_predicate_uri(self, predicate: str) -> URIRef:
        """Resolve an annotation predicate to a URI.

        Accepts a full URI, a known local name (label, comment, example, ...),
        a ``prefix:local`` CURIE bound in the graph, or a bare local name
        (falls back to the base namespace).
        """
        predicate = predicate.strip()
        if predicate.startswith(("http://", "https://")):
            return URIRef(predicate)
        mapped = self._ANNOTATION_PREDICATES.get(predicate)
        if mapped is not None:
            return mapped
        if ":" in predicate:
            prefix, _, local = predicate.partition(":")
            for bound_prefix, ns in self.graph.namespaces():
                if bound_prefix == prefix or (
                    prefix == "(default)" and bound_prefix == ""
                ):
                    return URIRef(str(ns) + local)
        return self._uri(predicate)

    def resolve_annotation_predicate(self, predicate: str) -> str:
        """Return the URI an annotation type resolves to, as a string.

        Public form of :meth:`_resolve_predicate_uri`, so callers can recognise
        the same predicate however it was written: a known name, a new local
        name, a ``prefix:local`` CURIE, or a full URI (issue #161).
        """
        return str(self._resolve_predicate_uri(predicate))

    def invalid_annotation_predicate_reason(self, predicate: str) -> str | None:
        """Return a human-readable reason ``predicate`` can't be used as an
        annotation type, or ``None`` if it can.

        Companion to :meth:`invalid_name_reason` for the forms
        :meth:`_resolve_predicate_uri` accepts: a full ``http(s)`` URI, a known
        name (``comment``, ``prefLabel``, ...), a ``prefix:local`` CURIE whose
        prefix is bound here, and a new local name minted in the base namespace.
        An unbound prefix is named explicitly, because resolution would
        otherwise fall through and mint a nonsense base-namespace URI containing
        a colon (issue #161).
        """
        if predicate is None or not predicate.strip():
            return "Annotation type cannot be empty."
        predicate = predicate.strip()
        if predicate.startswith(("http://", "https://")):
            if any(c.isspace() or c in self._INVALID_URI_CHARS for c in predicate):
                return (
                    "A full URI cannot contain spaces or any of the characters "
                    '< > " { } | \\ ^ `.'
                )
            return None
        if predicate in self._ANNOTATION_PREDICATES:
            return None
        if ":" in predicate:
            prefix, _, local = predicate.partition(":")
            bound = {p for p, _ns in self.graph.namespaces()}
            known = ("" in bound) if prefix == "(default)" else (prefix in bound)
            if not known:
                return (
                    f"Prefix '{prefix}' is not bound in this ontology. Add it "
                    "under Namespaces first, or paste the full URI instead."
                )
            if not local:
                return (
                    f"'{predicate}' is missing a name after the prefix, for "
                    "example 'wdt:P31'."
                )
            if not self._LOCAL_NAME_RE.match(local):
                return (
                    f"'{local}' is not a valid name after the prefix. Use "
                    "letters, digits, '_', '-' and '.', for example 'wdt:P31'."
                )
            return None
        if not self._LOCAL_NAME_RE.match(predicate):
            return (
                f"'{predicate}' is not a valid annotation type. Use a name like "
                "'wikidataId', a bound prefix like 'wdt:P31', or a full URI."
            )
        return None

    def _require_valid_annotation_predicate(self, predicate: str) -> None:
        """Raise ``ValueError`` if ``predicate`` is unusable as an annotation type."""
        reason = self.invalid_annotation_predicate_reason(predicate)
        if reason:
            raise ValueError(reason)

    def add_annotation(
        self,
        subject: str,
        predicate: str,
        value: str,
        lang: str | None = None,
        datatype: str | None = None,
        value_is_uri: bool = False,
    ):
        """Add an annotation to any resource.

        A predicate that resolves into this ontology's own namespace is a
        custom annotation type the user just invented (issue #161), so it is
        declared as an ``owl:AnnotationProperty``. That keeps the ontology
        well-formed OWL, so other tools list the annotation instead of seeing an
        undeclared predicate. Vocabulary predicates (``rdfs:label``, ``skos:*``,
        anything under a bound external prefix) are left alone, as is a URI that
        already has a type here.

        Raises ``ValueError`` if the predicate is unusable — an unbound prefix
        above all, which would otherwise be minted as a base-namespace URI
        containing a colon. The check lives here so every caller is covered, not
        only the Annotations page: bulk edits reach this too, and report the
        reason per row. ``delete_annotation`` deliberately stays unchecked, so an
        oddly named predicate already in the graph can still be removed.

        Args:
            subject: The resource name to annotate
            predicate: Either a full URI, a common name (label, comment, etc.), or a local name
            value: The annotation value
            lang: Optional language tag
            datatype: Optional datatype, as the local name of an XSD type or a
                full URI, resolved the same way :meth:`delete_annotation`
                resolves it so an annotation can be removed and re-added without
                changing. Prefer the full URI: a local name that is not an XSD
                type does not resolve back and would mint a relative
                ``^^<Thing>``. Ignored when ``lang`` is given, since RDF
                literals carry a language tag or a datatype, never both, and
                when ``value_is_uri`` is set. Without it an edit that rewrote a
                value would silently drop its ``^^xsd:date`` (issue #223).
            value_is_uri: Write the object as a resource rather than a literal,
                for annotations like ``rdfs:seeAlso`` whose value is an IRI.
        """
        self._require_valid_annotation_predicate(predicate)
        subj_uri = self._uri(subject)
        pred_uri = self._resolve_predicate_uri(predicate)

        # The object is built before anything is written, because building it is
        # what refuses a bad IRI or a language tag rdflib will not take. Declared
        # first, the annotation property below outlived the write it was for: the
        # caller was told the annotation had failed and was left with a new,
        # zero-use annotation type in the ontology — reachable from Bulk Edit,
        # which reports the row and carries on (review of PR #291).
        obj = self._annotation_object(value, lang, datatype, value_is_uri)

        if (
            str(pred_uri).startswith(str(self.namespace))
            and (
                pred_uri,
                RDF.type,
                None,
            )
            not in self.graph
        ):
            self.graph.add((pred_uri, RDF.type, OWL.AnnotationProperty))

        self.graph.add((subj_uri, pred_uri, obj))

    def _annotation_object(
        self,
        value: str,
        lang: str | None,
        datatype: str | None,
        value_is_uri: bool,
    ) -> Node:
        """The object an annotation writes, or ``ValueError`` saying why not.

        Split out of :meth:`add_annotation` so every refusal happens before the
        graph is touched. See that method for what each argument means.
        """
        if value_is_uri:
            # Keep a resource-valued annotation a resource. Writing it back as a
            # literal would leave the original triple in place beside a string
            # copy of the same IRI.
            #
            # Checked before it is stored, because rdflib accepts any string as a
            # URIRef and only refuses at serialization: one bad edit would make
            # the whole ontology unexportable, long after the edit that did it.
            # Raising instead lets the caller's rollback put the original back.
            if reason := self.invalid_uri_reason(value):
                raise ValueError(reason)
            return URIRef(value)
        if lang:
            # Asked before rdflib is handed the tag, so the refusal names what a
            # language tag may look like and what to use for a language no
            # standard names, rather than only that this one is not one.
            if reason := invalid_tag_reason(lang):
                raise ValueError(reason)
            return Literal(value, lang=lang)
        if datatype:
            return Literal(
                value, datatype=self.XSD_DATATYPES.get(datatype, URIRef(datatype))
            )
        return Literal(value)

    #: What a resource says about its place in the ontology rather than about
    #: itself, and so is not an annotation. A class constant because the repair
    #: below has to move exactly what :meth:`get_annotations` reports.
    _STRUCTURAL_PREDICATES: ClassVar[set] = {
        RDF.type,
        RDFS.subClassOf,
        RDFS.subPropertyOf,
        RDFS.domain,
        RDFS.range,
        OWL.equivalentClass,
        OWL.equivalentProperty,
        OWL.disjointWith,
        OWL.inverseOf,
        OWL.propertyChainAxiom,
        OWL.onProperty,
        OWL.someValuesFrom,
        OWL.allValuesFrom,
        OWL.hasValue,
        OWL.minCardinality,
        OWL.maxCardinality,
        OWL.cardinality,
        OWL.unionOf,
        OWL.intersectionOf,
        OWL.complementOf,
        OWL.oneOf,
        OWL.imports,
    }

    def get_annotations(self, subject: str) -> list[dict[str, Any]]:
        """Get all annotations/predicates for a resource (like Protege shows)."""
        subj_uri = self._uri(subject)
        annotations: list[dict[str, Any]] = []

        for pred, obj in self.graph.predicate_objects(subj_uri):
            # Skip structural predicates
            if pred in self._STRUCTURAL_PREDICATES:
                continue
            # Skip blank nodes (restrictions, etc.)
            if isinstance(obj, BNode):
                continue

            pred_uri = str(pred)
            prefix = self._get_prefix_for_uri(pred_uri)
            local_name = self._local_name(pred)
            ann: dict[str, Any] = {
                "predicate": local_name,
                "predicate_uri": pred_uri,
                "predicate_prefixed": f"{prefix}:{local_name}"
                if prefix
                else local_name,
                "value": str(obj),
            }
            if hasattr(obj, "language") and obj.language:
                ann["language"] = obj.language
            if hasattr(obj, "datatype") and obj.datatype:
                # Local name for display, full URI to act on. Two datatypes in
                # different namespaces can share a local name, and one that is
                # not an XSD type does not resolve back from the local name at
                # all — deleting by it removes nothing and re-adding mints a
                # relative ``^^<Thing>`` (issue #223 review).
                ann["datatype"] = self._local_name(obj.datatype)
                ann["datatype_uri"] = str(obj.datatype)
            if isinstance(obj, URIRef):
                # The object is a resource, not a literal. Callers that rewrite
                # an annotation have to know: a literal delete does not match a
                # URIRef, and re-adding one as a literal leaves the original in
                # place next to a string copy of it.
                ann["is_uri"] = True
            annotations.append(ann)

        # Sort by predicate name
        annotations.sort(key=lambda x: x["predicate"])
        return annotations

    def stray_annotation_subject(self, subject: str) -> str | None:
        """The base-namespace namesake holding annotations meant for ``subject``.

        Until this was fixed, the Annotations page addressed the resource it was
        annotating by local name, and a local name resolves into *this*
        ontology's namespace — so annotating an imported class (``gist:Account``)
        wrote to ``:Account``, a subject nothing declares. The page listed those
        annotations, because it read them back the same way, but the editor and
        the row delete aimed at the real URI and quietly did nothing.

        Returns the namesake's URI when it holds something to adopt, else
        ``None``. Only an *undeclared* subject qualifies: a base-namespace
        resource of the same local name that this ontology actually defines is a
        resource in its own right, and its annotations are its own.
        """
        subj_uri = self._uri(subject)
        stray = self.namespace[self._local_name(subj_uri)]
        if stray == subj_uri or (stray, RDF.type, None) in self.graph:
            return None
        return str(stray) if self.get_annotations(str(stray)) else None

    def adopt_stray_annotations(self, subject: str) -> int:
        """Move a namesake's annotations onto ``subject``, returning how many.

        The repair for what :meth:`stray_annotation_subject` finds. The triples
        are moved rather than copied, so the namesake is left with nothing and
        running this again finds nothing to do.
        """
        stray = self.stray_annotation_subject(subject)
        if stray is None:
            return 0
        subj_uri = self._uri(subject)
        stray_uri = URIRef(stray)
        moved = 0
        for pred, obj in list(self.graph.predicate_objects(stray_uri)):
            # Exactly what get_annotations reports, so nothing structural and no
            # blank node (a restriction) is dragged along with it.
            if pred in self._STRUCTURAL_PREDICATES or isinstance(obj, BNode):
                continue
            self.graph.remove((stray_uri, pred, obj))
            self.graph.add((subj_uri, pred, obj))
            moved += 1
        return moved

    def get_used_annotation_predicates(self) -> list[dict[str, str]]:
        """Get all unique annotation predicates used in the ontology."""
        predicates = {}
        for subj, pred, obj in self.graph:
            # Skip structural predicates
            if pred in self._STRUCTURAL_PREDICATES:
                continue
            # Skip blank node objects
            if isinstance(obj, BNode):
                continue
            # Only include predicates with literal values (annotations)
            if isinstance(obj, (Literal, URIRef)):
                pred_uri = str(pred)
                if pred_uri not in predicates:
                    predicates[pred_uri] = {
                        "uri": pred_uri,
                        "local_name": self._local_name(pred),
                        "prefix": self._get_prefix_for_uri(pred_uri),
                    }

        # Sort by local name
        result = sorted(predicates.values(), key=lambda x: x["local_name"].lower())
        return result

    # Vocabularies whose terms are defined elsewhere, as a rename *target*: a
    # custom type can be moved to a URI of the user's own choosing, but not onto
    # a standard vocabulary term, which would give a private meaning to a term
    # every other tool already understands (issue #287).
    _EXTERNAL_ANNOTATION_NAMESPACES: ClassVar[frozenset[str]] = frozenset(
        {str(RDF), str(RDFS), str(OWL), str(XSD), str(SKOS), str(DC), str(DCTERMS)}
    )

    def annotation_property_rename_reason(self, predicate: str) -> str | None:
        """Why the annotation type ``predicate`` cannot be renamed, or ``None``.

        Only a type in this ontology's own namespace can be renamed — the same
        test :meth:`add_annotation` uses to decide that a type is one the user
        invented here. ``rdfs:label``, ``skos:definition`` and the terms of any
        imported vocabulary are defined by that vocabulary, so renaming one here
        would not rename anything: it would fork the vocabulary and leave every
        annotation pointing at a term no other tool knows (issue #287).
        """
        uri = self._resolve_predicate_uri(predicate)
        if not str(uri).startswith(str(self.namespace)):
            return (
                f"'{predicate}' is defined by another vocabulary, not by this "
                "ontology, so renaming it here would fork that vocabulary. Only "
                f"annotation types in this ontology's own namespace "
                f"({self.base_uri}) can be renamed."
            )
        return None

    def get_custom_annotation_properties(self) -> list[dict[str, Any]]:
        """The annotation types this ontology defines itself.

        Everything the Annotations page can show as an annotation type, minus
        the ones belonging to another vocabulary (see
        :meth:`annotation_property_rename_reason`) and minus the predicates that
        are declared as some other kind of entity — an object or data property
        assertion also reads as an annotation here, but it is renamed on the
        Properties page, not this one.

        A type is listed whether it is declared as an ``owl:AnnotationProperty``
        or only used, so one that came in from a loaded file is renameable too.
        Each entry carries ``uri``, ``local_name``, ``prefix``, ``display`` (the
        prefixed form) and ``usage`` (how many annotations use it).
        """
        candidates: dict[str, dict[str, Any]] = {
            p["uri"]: dict(p) for p in self.get_used_annotation_predicates()
        }
        # Declared but unused: the values were deleted and the declaration
        # stayed, so the type is still part of the ontology.
        for pred in self.graph.subjects(RDF.type, OWL.AnnotationProperty):
            if isinstance(pred, URIRef) and str(pred) not in candidates:
                candidates[str(pred)] = {
                    "uri": str(pred),
                    "local_name": self._local_name(pred),
                    "prefix": self._get_prefix_for_uri(str(pred)),
                }

        result: list[dict[str, Any]] = []
        for uri, info in candidates.items():
            if self.annotation_property_rename_reason(uri):
                continue
            pred_uri = URIRef(uri)
            if set(self.graph.objects(pred_uri, RDF.type)) - {OWL.AnnotationProperty}:
                continue
            entry = dict(info)
            entry["display"] = (
                f"{info['prefix']}:{info['local_name']}"
                if info["prefix"]
                else info["local_name"]
            )
            entry["usage"] = sum(1 for _ in self.graph.triples((None, pred_uri, None)))
            result.append(entry)

        result.sort(key=lambda e: e["local_name"].lower())
        return result

    def _resolve_renamed_annotation_uri(self, name: str, namespace: str) -> URIRef:
        """Resolve the new name of an annotation type being renamed.

        Takes the same forms as :meth:`_resolve_predicate_uri` except a bare
        name, which stays in ``namespace`` — the namespace the type already
        lives in, the way the entity renames keep theirs. Mapping it the usual
        way would turn renaming a custom type to 'label' into a silent merge
        into ``rdfs:label``, and minting it in the base namespace would move a
        type out of its own namespace as a side effect of renaming it.
        """
        name = name.strip()
        if name.startswith(("http://", "https://")):
            return URIRef(name)
        if ":" in name:
            return self._resolve_predicate_uri(name)
        return URIRef(namespace + name)

    def _annotation_predicate_in_use(self, uri: URIRef) -> bool:
        """True if ``uri`` already names something in this graph — an entity, an
        annotation type, or any resource carrying triples of its own."""
        return (
            self._name_in_use(uri)
            or (uri, None, None) in self.graph
            or (None, uri, None) in self.graph
        )

    def rename_annotation_property(self, old_name: str, new_name: str) -> bool:
        """Rename a custom annotation type, updating every use of it (#287).

        ``old_name`` may be written any way :meth:`_resolve_predicate_uri`
        accepts — a full URI, a ``prefix:local`` CURIE or a local name. A bare
        ``new_name`` keeps the type in its current namespace (see
        :meth:`_resolve_renamed_annotation_uri`); a CURIE or a full URI moves it
        where it says.

        Every triple that mentions the type moves with it: its declaration and
        any other statement about it, the annotations that use it as their
        predicate, and any reference to it as an object. That is the whole point
        of doing this here rather than by hand — a search-and-replace over the
        Turtle catches the same triples only as long as the file uses one prefix
        for them.

        Returns False when the new name is already taken, so nothing is merged
        into an existing term by accident. Raises ``ValueError`` when the new
        name is unusable, when the type belongs to another vocabulary (see
        :meth:`annotation_property_rename_reason`), or when the new name would
        land on a standard vocabulary term.
        """
        old_uri = self._resolve_predicate_uri(old_name)
        if reason := self.annotation_property_rename_reason(str(old_uri)):
            raise ValueError(reason)
        self._require_valid_annotation_predicate(new_name)

        new_uri = self._resolve_renamed_annotation_uri(
            new_name, self._namespace_of(old_uri)
        )
        if new_uri == old_uri:
            return True
        if self._namespace_of(new_uri) in self._EXTERNAL_ANNOTATION_NAMESPACES:
            raise ValueError(
                f"'{new_name}' is a standard vocabulary term. Renaming a type "
                "onto one would give a private meaning to a term every other "
                "tool already understands."
            )
        if self._annotation_predicate_in_use(new_uri):
            return False

        # Every triple mentioning the type, whichever position it stands in:
        # statements about it (its owl:AnnotationProperty declaration, its
        # label), the annotations that use it as their predicate, and references
        # to it as an object (rdfs:subPropertyOf, seeAlso). Collected as one set
        # and rewritten in all three positions at once, because a triple can
        # mention it more than once — ``ex:tag rdfs:seeAlso ex:tag`` — and moving
        # one position at a time would leave the old URI standing in the other.
        mentions: set[_Triple] = {
            *self.graph.triples((old_uri, None, None)),
            *self.graph.triples((None, old_uri, None)),
            *self.graph.triples((None, None, old_uri)),
        }
        for s, p, o in mentions:
            self.graph.remove((s, p, o))
            self.graph.add(
                (
                    new_uri if s == old_uri else s,
                    new_uri if p == old_uri else p,
                    new_uri if o == old_uri else o,
                )
            )

        return True

    def _get_prefix_for_uri(self, uri: str) -> str:
        """Get the prefix for a URI if bound in the graph."""
        for prefix, namespace in self.graph.namespaces():
            ns_str = str(namespace)
            if uri.startswith(ns_str):
                return prefix if prefix else "(default)"
        return ""

    def delete_annotation(
        self,
        subject: str,
        predicate: str,
        value: str | None = None,
        lang: str | None = None,
        datatype: str | None = None,
        value_is_uri: bool = False,
    ):
        """Delete an annotation from a resource.

        Matches language-tagged and datatype-qualified literals when lang/datatype
        are provided. When they are not provided but a value is given, searches
        for any literal with a matching string value regardless of tag.

        ``datatype`` may be an XSD local name or a full URI; a full one is what
        callers should pass, since a non-XSD local name does not resolve back.
        ``value_is_uri`` says the object is a resource rather than a literal,
        which no literal match can find.
        """
        subj_uri = self._uri(subject)
        pred_uri = self._resolve_predicate_uri(predicate)

        if value is None:
            self.graph.remove((subj_uri, pred_uri, None))
            return

        if value_is_uri:
            # A resource-valued annotation (rdfs:seeAlso, owl:sameAs). The
            # literal branches below cannot match one, so without this the
            # delete silently removes nothing and reports success.
            self.graph.remove((subj_uri, pred_uri, URIRef(value)))
            return

        # Build exact literal if lang or datatype is known
        if lang:
            self.graph.remove((subj_uri, pred_uri, Literal(value, lang=lang)))
            return
        if datatype:
            dt_uri = self.XSD_DATATYPES.get(datatype, URIRef(datatype))
            self.graph.remove((subj_uri, pred_uri, Literal(value, datatype=dt_uri)))
            return

        # Nothing said about the object: remove any whose string value matches,
        # resource or literal alike. Matching only literals here meant a caller
        # that did not know the difference — the bulk editor, whose table has no
        # column for it — deleted nothing and reported success (issue #223
        # review). An exact object kind is still available through
        # ``value_is_uri``.
        to_remove = []
        for obj in self.graph.objects(subj_uri, pred_uri):
            if isinstance(obj, (Literal, URIRef)) and str(obj) == value:
                to_remove.append(obj)
        for obj in to_remove:
            self.graph.remove((subj_uri, pred_uri, obj))

    # ==================== SKOS VOCABULARY OPERATIONS ====================

    SKOS_RELATIONS: ClassVar[dict[str, URIRef]] = {
        "broader": SKOS.broader,
        "narrower": SKOS.narrower,
        "related": SKOS.related,
        "broadMatch": SKOS.broadMatch,
        "narrowMatch": SKOS.narrowMatch,
        "exactMatch": SKOS.exactMatch,
        "closeMatch": SKOS.closeMatch,
        "relatedMatch": SKOS.relatedMatch,
    }

    SKOS_INVERSES: ClassVar[dict[URIRef, URIRef]] = {
        SKOS.broader: SKOS.narrower,
        SKOS.narrower: SKOS.broader,
    }

    SKOS_SYMMETRIC: ClassVar[set[URIRef]] = {
        SKOS.related,
        SKOS.closeMatch,
        SKOS.exactMatch,
        SKOS.relatedMatch,
    }

    #: The three SKOS lexical labels. A concept may carry many of each, and at
    #: most one ``prefLabel`` per language tag (SKOS Reference S14).
    SKOS_LABEL_KINDS: ClassVar[dict[str, URIRef]] = {
        "prefLabel": SKOS.prefLabel,
        "altLabel": SKOS.altLabel,
        "hiddenLabel": SKOS.hiddenLabel,
    }

    #: The SKOS-XL counterpart of each label kind. Reading these is what keeps
    #: an imported AGROVOC or EuroVoc from looking entirely unlabelled.
    SKOS_XL_LABEL_KINDS: ClassVar[dict[str, URIRef]] = {
        "prefLabel": SKOSXL.prefLabel,
        "altLabel": SKOSXL.altLabel,
        "hiddenLabel": SKOSXL.hiddenLabel,
    }

    #: SKOS documentation properties. All are repeatable and language-tagged.
    SKOS_NOTE_KINDS: ClassVar[dict[str, URIRef]] = {
        "definition": SKOS.definition,
        "scopeNote": SKOS.scopeNote,
        "example": SKOS.example,
        "note": SKOS.note,
        "editorialNote": SKOS.editorialNote,
        "historyNote": SKOS.historyNote,
        "changeNote": SKOS.changeNote,
    }

    #: What :meth:`validate_skos` checks, keyed by the ``type`` on each issue.
    #:
    #: The single source of truth for the check list: the page renders its
    #: reference from this, the README documents it from this, and
    #: ``tests/test_skos_validation.py`` fails if the validator emits a check
    #: this does not describe, or describes one it cannot emit.
    #:
    #: ``source`` cites the SKOS Reference by its integrity-condition number
    #: where the condition is stated there, qSKOS where the check comes from
    #: that tool's published quality criteria, and says "practice" where it is
    #: thesaurus convention rather than anything normative. It does not invent
    #: a citation for a check that has none.
    SKOS_CHECKS: ClassVar[dict[str, dict[str, str]]] = {
        # Errors: broken or contradicted by the standard. Always checked.
        "missing_prefLabel": {
            "severity": "error",
            "summary": "The concept has no skos:prefLabel in any language.",
            "source": "Practice",
        },
        "multi_prefLabel_per_lang": {
            "severity": "error",
            "summary": "More than one skos:prefLabel shares a language tag.",
            "source": "SKOS Reference S14",
        },
        "empty_label": {
            "severity": "error",
            "summary": "A label literal is empty or only whitespace.",
            "source": "Practice",
        },
        "self_relation": {
            "severity": "error",
            "summary": "The concept is its own broader, narrower or related.",
            "source": "Practice",
        },
        "dangling_relation": {
            "severity": "error",
            "summary": (
                "A broader, narrower or related link points at something that "
                "is not a Concept here. Mapping properties are exempt: reaching "
                "outside the vocabulary is what they are for."
            ),
            "source": "Practice",
        },
        "relation_clash": {
            "severity": "error",
            "summary": (
                "Two concepts are skos:related and also connected up or down "
                "the hierarchy."
            ),
            "source": "SKOS Reference S27",
        },
        "broader_cycle": {
            "severity": "error",
            "summary": "A chain of skos:broader links returns to its start.",
            # Not a SKOS Reference integrity condition: the standard does not
            # forbid a cycle. It is an error here because a cyclic hierarchy
            # breaks tree rendering and every ancestor query built on it.
            "source": "qSKOS",
        },
        # Conventions: stated practice rather than broken data.
        "missing_lang": {
            "severity": "warning",
            "summary": "A label carries no language tag.",
            "source": "Practice",
        },
        "label_overlap": {
            "severity": "warning",
            "summary": (
                "One concept uses the same text in the same language as two "
                "of prefLabel, altLabel and hiddenLabel."
            ),
            "source": "SKOS Reference S13",
        },
        "duplicate_prefLabel": {
            "severity": "warning",
            "summary": (
                "Two concepts in one scheme share a prefLabel in the same language."
            ),
            "source": "qSKOS",
        },
        "ambiguous_prefLabel": {
            "severity": "warning",
            "summary": (
                "Two concepts anywhere in the vocabulary share a prefLabel in "
                "the same language, without sharing a scheme."
            ),
            "source": "qSKOS",
        },
        "orphan": {
            "severity": "warning",
            "summary": (
                "The concept has no broader, narrower or related concept and is "
                "not a top concept, so nothing reaches it."
            ),
            "source": "qSKOS",
        },
        "top_with_broader": {
            "severity": "warning",
            "summary": (
                "A top concept of a scheme also has a broader concept in that "
                "same scheme. Having one in another scheme is fine."
            ),
            "source": "Practice",
        },
        "hierarchy_redundancy": {
            "severity": "warning",
            "summary": (
                "A direct broader concept is already reachable through another "
                "parent, so the edge says nothing new."
            ),
            "source": "qSKOS",
        },
        "mapping_within_scheme": {
            "severity": "warning",
            "summary": (
                "A mapping property links two concepts of the same scheme; it "
                "is meant for links between vocabularies."
            ),
            "source": "Practice",
        },
        "notation_lang_tagged": {
            "severity": "warning",
            "summary": (
                "A skos:notation carries a language tag. A notation is a code "
                "in a symbol scheme and takes a datatype instead."
            ),
            "source": "SKOS Reference 6.5",
        },
        # Editorial: completeness and shape. Nothing here is wrong as such.
        "no_scheme": {
            "severity": "info",
            "summary": "The concept belongs to no ConceptScheme.",
            "source": "Practice",
        },
        "undocumented": {
            "severity": "info",
            "summary": "The concept has neither a definition nor a scopeNote.",
            "source": "Practice",
        },
        "valueless_association": {
            "severity": "info",
            "summary": (
                "Two concepts are skos:related and already share a parent, "
                "which relates them anyway."
            ),
            "source": "qSKOS",
        },
        "skos_xl_labels": {
            "severity": "info",
            "summary": (
                "The vocabulary uses SKOS-XL labels, which this editor shows "
                "but does not edit."
            ),
            "source": "SKOS-XL",
        },
        "disconnected_components": {
            "severity": "info",
            "summary": (
                "A cluster of concepts has no link to the main body of the vocabulary."
            ),
            "source": "qSKOS",
        },
    }

    #: The subset of :attr:`SKOS_RELATIONS` that links across vocabularies, and
    #: so may point at a URI this graph does not otherwise know about.
    SKOS_MAPPING_RELATIONS: ClassVar[tuple[str, ...]] = (
        "broadMatch",
        "narrowMatch",
        "exactMatch",
        "closeMatch",
        "relatedMatch",
    )

    def _tagged_literals(self, uri: Node, prop: URIRef) -> list[dict[str, str]]:
        """Return ``prop``'s literal objects as ``{"value", "lang"}`` records.

        Sorted untagged-first, then by language tag, so the order a caller sees
        does not depend on the store's iteration order. ``lang`` is ``""`` for
        an untagged literal, never ``None``, so the UI can render it without a
        null check.
        """
        values = [
            {"value": str(o), "lang": o.language or ""}
            for o in self.graph.objects(uri, prop)
            if isinstance(o, Literal)
        ]
        return sorted(values, key=lambda v: (v["lang"] != "", v["lang"], v["value"]))

    def _xl_literals(self, uri: Node, prop: URIRef) -> list[dict[str, str]]:
        """Label literals reached through a SKOS-XL label resource.

        ``concept skosxl:prefLabel [ skosxl:literalForm "Dog"@en ]`` carries the
        same information as ``skos:prefLabel "Dog"@en``, one indirection away.
        A label resource without a ``literalForm`` contributes nothing, which is
        why the value is filtered rather than rendered as an empty string.
        """
        values = []
        for label in self.graph.objects(uri, prop):
            for form in self.graph.objects(label, SKOSXL.literalForm):
                if isinstance(form, Literal):
                    values.append({"value": str(form), "lang": form.language or ""})
        return sorted(values, key=lambda v: (v["lang"] != "", v["lang"], v["value"]))

    @staticmethod
    def _flatten_literal(values: list[dict[str, str]]) -> str:
        """Pick one value out of :meth:`_tagged_literals` output.

        The flat ``prefLabel`` / ``definition`` keys predate language-aware
        editing and are still read by the visualization, the dashboard and the
        hierarchy tree. They stay, as a computed view over the structured list,
        so those callers keep working. Untagged wins, then the first tag
        alphabetically; both are deterministic, which is what those callers
        actually need.
        """
        return values[0]["value"] if values else ""

    def _concept_in_scheme(self, concept: Node, scheme: Node) -> bool:
        """Whether a concept belongs to a scheme, however that was asserted.

        ``skos:topConceptOf`` is a sub-property of ``skos:inScheme``, and it has
        ``skos:hasTopConcept`` as its inverse, so any of the three says the
        concept is in the scheme. An import that carries only the scheme side
        would otherwise have its top concepts counted in no scheme at all.
        """
        return (
            (concept, SKOS.inScheme, scheme) in self.graph
            or (concept, SKOS.topConceptOf, scheme) in self.graph
            or (scheme, SKOS.hasTopConcept, concept) in self.graph
        )

    def add_concept_scheme(
        self, name: str, label: str | None = None, comment: str | None = None
    ) -> URIRef:
        """Add a new SKOS ConceptScheme."""
        self._require_valid_name(name)
        self._require_free_name(name, "SKOS concept scheme")
        scheme_uri = self._uri(name)
        self.graph.add((scheme_uri, RDF.type, SKOS.ConceptScheme))
        if label:
            self.graph.add((scheme_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((scheme_uri, RDFS.comment, Literal(comment)))
        return scheme_uri

    def get_concept_schemes(self) -> list[dict[str, Any]]:
        """Get all SKOS ConceptSchemes."""
        schemes = []
        for uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if isinstance(uri, BNode):
                continue
            name = self._local_name(uri)
            label = str(self.graph.value(uri, RDFS.label) or "")
            comment = str(self.graph.value(uri, RDFS.comment) or "")
            # Count concepts in this scheme
            members = (
                set(self.graph.subjects(SKOS.inScheme, uri))
                | set(self.graph.subjects(SKOS.topConceptOf, uri))
                | set(self.graph.objects(uri, SKOS.hasTopConcept))
            )
            concept_count = len({m for m in members if isinstance(m, URIRef)})
            schemes.append(
                {
                    "name": name,
                    "uri": str(uri),
                    "label": label,
                    "comment": comment,
                    "concept_count": concept_count,
                }
            )
        return sorted(schemes, key=lambda s: s["name"])

    def update_concept_scheme(
        self, name: str, new_label: str = _UNSET, new_comment: str = _UNSET
    ):
        """Update a SKOS ConceptScheme's properties."""
        uri = self._uri(name)
        # Resolve actual URI from graph if _uri doesn't match
        for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if self._local_name(s_uri) == name:
                uri = cast(URIRef, s_uri)
                break

        if new_label is not _UNSET:
            self.graph.remove((uri, RDFS.label, None))
            if new_label:
                self.graph.add((uri, RDFS.label, Literal(new_label)))

        if new_comment is not _UNSET:
            self.graph.remove((uri, RDFS.comment, None))
            if new_comment:
                self.graph.add((uri, RDFS.comment, Literal(new_comment)))

    def rename_concept_scheme(self, old_name: str, new_name: str) -> bool:
        """Rename a SKOS ConceptScheme, updating all references.

        Re-points every triple where the scheme is subject or object (including
        the ``skos:inScheme`` links from its concepts), so no membership is lost.
        """
        if old_name == new_name:
            return True
        self._require_valid_name(new_name)

        # Resolve the actual scheme URI from the graph (mirrors update/delete).
        old_uri = self._uri(old_name)
        for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if self._local_name(s_uri) == old_name:
                old_uri = cast(URIRef, s_uri)
                break

        new_uri = self._uri(new_name, self._namespace_of(old_uri))
        # Refuse if the target name is already used by any entity (any type).
        if self._name_in_use(new_uri):
            return False

        updates: _TripleUpdates = []
        for p, o in self.graph.predicate_objects(old_uri):
            updates.append(((old_uri, p, o), (new_uri, p, o)))
        for s, p in self.graph.subject_predicates(old_uri):
            updates.append(((s, p, old_uri), (s, p, new_uri)))

        for old_triple, new_triple in updates:
            self.graph.remove(old_triple)
            self.graph.add(new_triple)

        return True

    def delete_concept_scheme(self, name: str):
        """Delete a ConceptScheme and remove inScheme references."""
        uri = self._uri(name)
        # Resolve actual URI from graph if _uri doesn't match
        for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if self._local_name(s_uri) == name:
                uri = cast(URIRef, s_uri)
                break
        self.graph.remove((uri, None, None))
        self.graph.remove((None, SKOS.inScheme, uri))
        self.graph.remove((None, None, uri))

    def add_concept(
        self,
        name: str,
        scheme: str | None = None,
        pref_label: str | None = None,
        definition: str | None = None,
        broader: str | None = None,
        lang: str | None = None,
    ) -> URIRef:
        """Add a SKOS Concept with optional scheme/broader links."""
        self._require_valid_name(name)
        self._require_free_name(name, "SKOS concept")
        for ref in (scheme, broader):
            if ref:
                self._require_valid_name(ref)
        concept_uri = self._uri(name)
        # Before anything is written: a broader given at creation time went
        # straight into the graph, so ``add_concept("A", broader="A")`` minted a
        # self-cycle the editing paths refuse.
        if broader:
            self._refuse_broader_cycle(concept_uri, self._uri(broader))
        self.graph.add((concept_uri, RDF.type, SKOS.Concept))

        if scheme:
            scheme_uri = self._uri(scheme)
            self.graph.add((concept_uri, SKOS.inScheme, scheme_uri))

        if pref_label:
            if lang:
                self.graph.add(
                    (concept_uri, SKOS.prefLabel, Literal(pref_label, lang=lang))
                )
            else:
                self.graph.add((concept_uri, SKOS.prefLabel, Literal(pref_label)))

        if definition:
            if lang:
                self.graph.add(
                    (concept_uri, SKOS.definition, Literal(definition, lang=lang))
                )
            else:
                self.graph.add((concept_uri, SKOS.definition, Literal(definition)))

        if broader:
            broader_uri = self._uri(broader)
            self.graph.add((concept_uri, SKOS.broader, broader_uri))
            self.graph.add((broader_uri, SKOS.narrower, concept_uri))

        return concept_uri

    def get_concepts(self, scheme: str | None = None) -> list[dict[str, Any]]:
        """Get SKOS Concepts, optionally filtered by scheme."""
        # Resolve scheme name to URI by looking it up in the graph
        scheme_uri = None
        if scheme:
            for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
                if self._local_name(s_uri) == scheme:
                    scheme_uri = s_uri
                    break
            if not scheme_uri:
                scheme_uri = self._uri(scheme)

        concepts = []
        for uri in self.graph.subjects(RDF.type, SKOS.Concept):
            if isinstance(uri, BNode):
                continue

            # Filter by scheme if specified
            if scheme and scheme_uri and not self._concept_in_scheme(uri, scheme_uri):
                continue

            name = self._local_name(uri)

            labels = {
                kind: self._tagged_literals(uri, prop)
                for kind, prop in self.SKOS_LABEL_KINDS.items()
            }
            notes = {
                kind: self._tagged_literals(uri, prop)
                for kind, prop in self.SKOS_NOTE_KINDS.items()
            }
            # Kept in their own key rather than merged into ``labels``: the
            # editor writes plain SKOS, so a SKOS-XL label offered in the same
            # list would come with a delete button that silently does nothing.
            xl_labels = {
                kind: self._xl_literals(uri, prop)
                for kind, prop in self.SKOS_XL_LABEL_KINDS.items()
            }
            # The flat key falls back to SKOS-XL so the graph, the dashboard and
            # the concept list show a name for an imported vocabulary instead of
            # a bare local name.
            pref_label = self._flatten_literal(
                labels["prefLabel"] or xl_labels["prefLabel"]
            )
            definition = self._flatten_literal(notes["definition"])
            alt_labels = [v["value"] for v in labels["altLabel"]]

            notation = str(self.graph.value(uri, SKOS.notation) or "")
            # Both directions of the pair. ``set_top_concept`` writes both, but
            # a published vocabulary often asserts only the scheme side,
            # ``scheme skos:hasTopConcept concept``, and reading one direction
            # made such a concept look like an orphan belonging to no scheme.
            top_of_uris = sorted(
                {
                    str(o)
                    for o in self.graph.objects(uri, SKOS.topConceptOf)
                    if isinstance(o, URIRef)
                }
                | {
                    str(s)
                    for s in self.graph.subjects(SKOS.hasTopConcept, uri)
                    if isinstance(s, URIRef)
                }
            )
            mappings = {
                rel: sorted(
                    str(o)
                    for o in self.graph.objects(uri, self.SKOS_RELATIONS[rel])
                    if isinstance(o, URIRef)
                )
                for rel in self.SKOS_MAPPING_RELATIONS
            }

            broader_uris = [
                str(o)
                for o in self.graph.objects(uri, SKOS.broader)
                if isinstance(o, URIRef)
            ]
            narrower_uris = [
                str(o)
                for o in self.graph.objects(uri, SKOS.narrower)
                if isinstance(o, URIRef)
            ]
            related_uris = [
                str(o)
                for o in self.graph.objects(uri, SKOS.related)
                if isinstance(o, URIRef)
            ]
            # skos:topConceptOf is a sub-property of skos:inScheme, so heading a
            # scheme is membership of it whether or not inScheme was asserted.
            scheme_uris = sorted(
                {
                    str(o)
                    for o in self.graph.objects(uri, SKOS.inScheme)
                    if isinstance(o, URIRef)
                }
                | set(top_of_uris)
            )

            # Full URIs (``*_uris``) accompany the local-name lists so callers can
            # address a broader/related concept or scheme unambiguously even when
            # local names collide across namespaces (issue #87 part B).
            concepts.append(
                {
                    "name": name,
                    "uri": str(uri),
                    "prefLabel": pref_label,
                    "definition": definition,
                    "altLabels": alt_labels,
                    "broader": [self._local_name(URIRef(u)) for u in broader_uris],
                    "narrower": [self._local_name(URIRef(u)) for u in narrower_uris],
                    "related": [self._local_name(URIRef(u)) for u in related_uris],
                    "schemes": [self._local_name(URIRef(u)) for u in scheme_uris],
                    "broader_uris": broader_uris,
                    "narrower_uris": narrower_uris,
                    "related_uris": related_uris,
                    "scheme_uris": scheme_uris,
                    # Structured, language-aware views. The flat keys above are
                    # computed from these and kept for existing readers.
                    "labels": labels,
                    "xl_labels": xl_labels,
                    "notes": notes,
                    "notation": notation,
                    "top_of_uris": top_of_uris,
                    "top_of": [self._local_name(URIRef(u)) for u in top_of_uris],
                    "mappings": mappings,
                }
            )

        return sorted(concepts, key=lambda c: c["name"])

    def update_concept(
        self,
        name: str,
        new_pref_label: str = _UNSET,
        new_definition: str = _UNSET,
        new_broader: str = _UNSET,
        add_scheme: str | None = None,
        remove_scheme: str | None = None,
    ):
        """Update a SKOS Concept's properties."""
        if new_broader is not _UNSET and new_broader:
            self._require_valid_name(new_broader)
        if add_scheme:
            self._require_valid_name(add_scheme)
        uri = self._uri(name)

        if new_pref_label is not _UNSET:
            self.graph.remove((uri, SKOS.prefLabel, None))
            if new_pref_label:
                self.graph.add((uri, SKOS.prefLabel, Literal(new_pref_label)))

        if new_definition is not _UNSET:
            self.graph.remove((uri, SKOS.definition, None))
            if new_definition:
                self.graph.add((uri, SKOS.definition, Literal(new_definition)))

        if new_broader is not _UNSET:
            # Check before removing the old parent: a refusal must leave the
            # concept's hierarchy exactly as it was, not orphaned.
            if new_broader:
                self._refuse_broader_cycle(uri, self._uri(new_broader))
            # Remove old broader/narrower links
            for old_broader in list(self.graph.objects(uri, SKOS.broader)):
                self.graph.remove((uri, SKOS.broader, old_broader))
                self.graph.remove((old_broader, SKOS.narrower, uri))
            # Add new broader
            if new_broader:
                broader_uri = self._uri(new_broader)
                self.graph.add((uri, SKOS.broader, broader_uri))
                self.graph.add((broader_uri, SKOS.narrower, uri))

        if add_scheme:
            self.graph.add((uri, SKOS.inScheme, self._uri(add_scheme)))

        if remove_scheme:
            self.graph.remove((uri, SKOS.inScheme, self._uri(remove_scheme)))

    def _label_property(self, kind: str) -> URIRef:
        """Resolve a label kind, or say which kinds exist."""
        prop = self.SKOS_LABEL_KINDS.get(kind)
        if prop is None:
            known = ", ".join(self.SKOS_LABEL_KINDS)
            raise ValueError(
                f"Unknown SKOS label kind: {kind} (expected one of {known})"
            )
        return prop

    def _note_property(self, kind: str) -> URIRef:
        """Resolve a documentation-property kind, or say which kinds exist."""
        prop = self.SKOS_NOTE_KINDS.get(kind)
        if prop is None:
            known = ", ".join(self.SKOS_NOTE_KINDS)
            raise ValueError(
                f"Unknown SKOS note kind: {kind} (expected one of {known})"
            )
        return prop

    @staticmethod
    def _literal_text(value: str, what: str) -> str:
        """Reject a blank literal before it reaches the graph."""
        text = (value or "").strip()
        if not text:
            raise ValueError(f"A {what} cannot be empty.")
        return text

    def _checked_lang(self, lang: str | None) -> str | None:
        """Return a usable language tag, or ``None``; raise on a malformed one."""
        tag = (lang or "").strip()
        if not tag:
            return None
        if reason := invalid_tag_reason(tag):
            raise ValueError(reason)
        return tag

    def _broader_ancestors(self, uri: Node) -> set[Node]:
        """Every concept reachable from ``uri`` by following ``skos:broader``.

        Carries a visited set rather than recursing, because an imported
        vocabulary can already contain a cycle and this must terminate on one
        rather than be the thing that discovers it.
        """
        seen: set[Node] = set()
        stack = [uri]
        while stack:
            for parent in self.graph.objects(stack.pop(), SKOS.broader):
                if isinstance(parent, URIRef) and parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen

    def _refuse_broader_cycle(self, child: Node, parent: Node) -> None:
        """Reject a ``child skos:broader parent`` edge that would close a cycle.

        Refusing at write time is worth more than reporting later: the user is
        looking at the form and can pick a different parent. The validation-side
        detector still earns its place, for cycles that arrive through import.
        """
        if child == parent:
            raise ValueError(
                f"'{self._local_name(child)}' cannot be its own broader concept."
            )
        if child in self._broader_ancestors(parent):
            raise ValueError(
                f"'{self._local_name(parent)}' is already a narrower concept of "
                f"'{self._local_name(child)}'; this would create a hierarchy cycle."
            )

    def set_concept_label(
        self, concept: str, kind: str, value: str, lang: str | None = None
    ) -> None:
        """Add a ``prefLabel``/``altLabel``/``hiddenLabel`` to a concept.

        A ``prefLabel`` **replaces** any existing prefLabel carrying the same
        language tag, because SKOS allows at most one per tag (SKOS Reference
        S14). ``altLabel`` and ``hiddenLabel`` are repeatable and are appended.
        Adding the same value and tag twice is a no-op either way, since the
        graph is a set.
        """
        prop = self._label_property(kind)
        text = self._literal_text(value, kind)
        tag = self._checked_lang(lang)
        uri = self._uri(concept)

        if kind == "prefLabel":
            for existing in list(self.graph.objects(uri, prop)):
                if isinstance(existing, Literal) and (existing.language or "") == (
                    tag or ""
                ):
                    self.graph.remove((uri, prop, existing))

        self.graph.add((uri, prop, Literal(text, lang=tag) if tag else Literal(text)))

    def remove_concept_label(
        self, concept: str, kind: str, value: str, lang: str | None = None
    ) -> bool:
        """Remove one label literal. Returns whether anything was removed."""
        prop = self._label_property(kind)
        uri = self._uri(concept)
        target_lang = (lang or "").strip()
        removed = False
        for existing in list(self.graph.objects(uri, prop)):
            if (
                isinstance(existing, Literal)
                and str(existing) == value
                and (existing.language or "") == target_lang
            ):
                self.graph.remove((uri, prop, existing))
                removed = True
        return removed

    def set_concept_note(
        self, concept: str, kind: str, value: str, lang: str | None = None
    ) -> None:
        """Add a documentation property (definition, scopeNote, example, …).

        All SKOS documentation properties are repeatable, so this appends. Use
        :meth:`remove_concept_note` to drop one.
        """
        prop = self._note_property(kind)
        text = self._literal_text(value, kind)
        tag = self._checked_lang(lang)
        uri = self._uri(concept)
        self.graph.add((uri, prop, Literal(text, lang=tag) if tag else Literal(text)))

    def remove_concept_note(
        self, concept: str, kind: str, value: str, lang: str | None = None
    ) -> bool:
        """Remove one documentation literal. Returns whether anything was removed."""
        prop = self._note_property(kind)
        uri = self._uri(concept)
        target_lang = (lang or "").strip()
        removed = False
        for existing in list(self.graph.objects(uri, prop)):
            if (
                isinstance(existing, Literal)
                and str(existing) == value
                and (existing.language or "") == target_lang
            ):
                self.graph.remove((uri, prop, existing))
                removed = True
        return removed

    def set_concept_notation(
        self, concept: str, value: str, datatype: str | None = None
    ) -> None:
        """Set (or clear, with an empty value) a concept's ``skos:notation``.

        A notation carries a datatype, never a language tag: it is a code in a
        symbol scheme, not text in a language (SKOS Reference 6.5.1). Passing a
        language tag here is not possible by construction, which is the point.
        """
        uri = self._uri(concept)
        self.graph.remove((uri, SKOS.notation, None))
        text = (value or "").strip()
        if not text:
            return
        if datatype:
            self.graph.add(
                (uri, SKOS.notation, Literal(text, datatype=URIRef(datatype)))
            )
        else:
            self.graph.add((uri, SKOS.notation, Literal(text)))

    def set_top_concept(self, concept: str, scheme: str, is_top: bool = True) -> None:
        """Assert or retract that a concept is a top concept of a scheme.

        Writes both directions: ``skos:topConceptOf`` on the concept and
        ``skos:hasTopConcept`` on the scheme. They are declared inverses, and
        leaving one behind is the half-edge problem the relation helpers exist
        to avoid.
        """
        concept_uri = self._uri(concept)
        scheme_uri = self._uri(scheme)
        if is_top:
            self.graph.add((concept_uri, SKOS.topConceptOf, scheme_uri))
            self.graph.add((scheme_uri, SKOS.hasTopConcept, concept_uri))
            # A top concept is in its scheme by definition (SKOS Reference S6).
            self.graph.add((concept_uri, SKOS.inScheme, scheme_uri))
        else:
            self.graph.remove((concept_uri, SKOS.topConceptOf, scheme_uri))
            self.graph.remove((scheme_uri, SKOS.hasTopConcept, concept_uri))

    def set_concept_broader(self, concept: str, targets: list[str]) -> None:
        """Replace a concept's ``skos:broader`` edges with ``targets``.

        All or nothing. Removing the old parents first is what lets a concept
        be re-parented under one of its own former descendants, but it means a
        refusal partway through would otherwise leave the concept with no
        parent at all: the edit is rejected *and* the user loses the hierarchy
        they had. On any refusal this restores the exact prior state and
        re-raises.

        The rollback puts the original triples back verbatim rather than
        re-asserting them through :meth:`add_concept_relation`. Those edges
        were never checked by the guard in the first place when they arrived by
        import, so an already-cyclic vocabulary would have its restore refused
        too, losing the edge and reporting the rollback's error instead of the
        real one.
        """
        uri = self._uri(concept)
        want = [self._uri(t) for t in targets]

        def _edges() -> set:
            """This concept's broader triples, with their narrower inverses."""
            return set(self.graph.triples((uri, SKOS.broader, None))) | set(
                self.graph.triples((None, SKOS.narrower, uri))
            )

        before = _edges()
        have = [
            o for o in self.graph.objects(uri, SKOS.broader) if isinstance(o, URIRef)
        ]
        for gone in have:
            if gone not in want:
                self.remove_concept_relation(uri, "broader", gone)

        try:
            for target in want:
                if target not in have:
                    self.add_concept_relation(uri, "broader", target)
        except ValueError:
            for triple in _edges():
                self.graph.remove(triple)
            for triple in before:
                self.graph.add(triple)
            raise

    def add_concept_mapping(self, concept: str, relation: str, target: str) -> None:
        """Link a concept to a resource in another vocabulary.

        Unlike :meth:`add_concept_relation`, ``target`` is an absolute IRI that
        need not exist in this graph — the whole point of a mapping property is
        to reach Wikidata, EuroVoc, AGROVOC or anything else. Only the five
        mapping properties are accepted; the semantic relations stay internal.
        """
        if relation not in self.SKOS_MAPPING_RELATIONS:
            known = ", ".join(self.SKOS_MAPPING_RELATIONS)
            raise ValueError(
                f"Not a SKOS mapping property: {relation} (expected one of {known})"
            )
        target = (target or "").strip()
        if not self._IRI_SCHEME_RE.match(target):
            shown = target or "(empty)"
            raise ValueError(f"A mapping target must be an absolute IRI, got: {shown}")
        # Having a scheme is not enough. rdflib accepts any string as a URIRef
        # and only objects when asked to serialize, so a target with a space in
        # it would be stored happily and then break every export of the whole
        # ontology.
        if reason := self.invalid_uri_reason(target):
            raise ValueError(reason)
        self.add_concept_relation(concept, relation, target)

    def remove_concept_relation(
        self, concept1: str, relation: str, concept2: str
    ) -> bool:
        """Remove a SKOS relation, and the inverse or symmetric triple with it.

        The mirror of :meth:`add_concept_relation`. Removing only the asserted
        direction would leave the auto-added inverse behind as a half-edge,
        which reads as a relation the UI cannot see or delete.
        """
        rel_uri = self.SKOS_RELATIONS.get(relation)
        if not rel_uri:
            raise ValueError(f"Unknown SKOS relation: {relation}")

        c1_uri = self._uri(concept1)
        c2_uri = self._uri(concept2)
        removed = (c1_uri, rel_uri, c2_uri) in self.graph
        self.graph.remove((c1_uri, rel_uri, c2_uri))

        inverse = self.SKOS_INVERSES.get(rel_uri)
        if inverse:
            self.graph.remove((c2_uri, inverse, c1_uri))
        if rel_uri in self.SKOS_SYMMETRIC:
            self.graph.remove((c2_uri, rel_uri, c1_uri))
        return removed

    def rename_concept(self, old_name: str, new_name: str) -> bool:
        """Rename a SKOS concept, updating all references.

        The renamed concept keeps its current namespace (see
        :meth:`rename_class`).
        """
        if old_name == new_name:
            return True
        self._require_valid_name(new_name)

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name, self._namespace_of(old_uri))

        # Refuse if the target name is already used by any entity (any type).
        if self._name_in_use(new_uri):
            return False

        # Collect all triples to update (old_uri as subject and as object)
        updates: _TripleUpdates = []
        for p, o in self.graph.predicate_objects(old_uri):
            updates.append(((old_uri, p, o), (new_uri, p, o)))
        for s, p in self.graph.subject_predicates(old_uri):
            updates.append(((s, p, old_uri), (s, p, new_uri)))

        for old_triple, new_triple in updates:
            self.graph.remove(old_triple)
            self.graph.add(new_triple)

        return True

    def add_concept_relation(self, concept1: str, relation: str, concept2: str):
        """Add a SKOS relation between two concepts.

        Auto-adds inverse for broader/narrower and symmetric for related/matches.
        """
        c1_uri = self._uri(concept1)
        c2_uri = self._uri(concept2)

        rel_uri = self.SKOS_RELATIONS.get(relation)
        if not rel_uri:
            raise ValueError(f"Unknown SKOS relation: {relation}")

        if relation == "broader":
            self._refuse_broader_cycle(c1_uri, c2_uri)
        elif relation == "narrower":
            self._refuse_broader_cycle(c2_uri, c1_uri)
        elif c1_uri == c2_uri:
            raise ValueError(f"A concept cannot be its own '{relation}'.")

        self.graph.add((c1_uri, rel_uri, c2_uri))

        # Auto-add inverse
        inverse = self.SKOS_INVERSES.get(rel_uri)
        if inverse:
            self.graph.add((c2_uri, inverse, c1_uri))

        # Auto-add symmetric
        if rel_uri in self.SKOS_SYMMETRIC:
            self.graph.add((c2_uri, rel_uri, c1_uri))

    def delete_concept(self, name: str):
        """Remove a concept and all its SKOS relations."""
        uri = self._uri(name)

        # Remove inverse narrower/broader pointing to this concept
        for rel, inv in self.SKOS_INVERSES.items():
            for other in self.graph.objects(uri, rel):
                self.graph.remove((other, inv, uri))
            for other in self.graph.subjects(rel, uri):
                self.graph.remove((other, rel, uri))

        # Remove symmetric relations
        for rel in self.SKOS_SYMMETRIC:
            for other in self.graph.objects(uri, rel):
                self.graph.remove((other, rel, uri))

        # Remove all triples with this concept
        self.graph.remove((uri, None, None))
        self.graph.remove((None, None, uri))

    def get_concept_hierarchy(self, scheme: str | None = None) -> dict[str, list[str]]:
        """Return concept hierarchy as {parent: [children]} dict."""
        hierarchy: dict[str, list[str]] = {}
        concepts = self.get_concepts(scheme=scheme)

        for concept in concepts:
            name = concept["name"]
            if name not in hierarchy:
                hierarchy[name] = []
            for child_name in concept["narrower"]:
                hierarchy[name].append(child_name)
                if child_name not in hierarchy:
                    hierarchy[child_name] = []

        return hierarchy

    # SKOS validation is split into one method per family of checks. Each takes
    # the already-fetched concept list so ``get_concepts()`` is walked once, and
    # each returns issue dicts rather than appending to shared state, so a check
    # can be read, tested and switched off on its own.
    #
    # Every index here is keyed by URI, never by local name: two concepts can
    # share a local name across namespaces (issue #87 part B), and a name-keyed
    # map silently merges them.

    @staticmethod
    def _skos_issue(
        severity: str, kind: str, concept: dict[str, Any], message: str
    ) -> dict[str, str]:
        """One issue, carrying the subject's URI as well as its display name.

        ``subject_uri`` is what the UI navigates by; resolving ``subject``
        through the base namespace would land on the wrong concept whenever two
        share a local name.
        """
        return {
            "severity": severity,
            "type": kind,
            "subject": concept["name"],
            "subject_uri": concept["uri"],
            "message": message,
        }

    def _skos_display_names(self, concepts: list[dict[str, Any]]) -> dict[str, str]:
        """URI -> the shortest label that still identifies the concept.

        The local name where it is unique, the full URI where it is not, so a
        message about two concepts sharing a name does not read as one concept.
        """
        counts: dict[str, int] = {}
        for concept in concepts:
            counts[concept["name"]] = counts.get(concept["name"], 0) + 1
        return {
            c["uri"]: (c["name"] if counts[c["name"]] == 1 else c["uri"])
            for c in concepts
        }

    @staticmethod
    def _skos_link_maps(
        concepts: list[dict[str, Any]],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
        """``(parents, children, related)``, each read from both directions.

        SKOS declares broader and narrower inverses of each other, and related
        symmetric, but a published vocabulary usually asserts only one side:
        ``B skos:broader A`` with no matching ``A skos:narrower B``. Our own
        writes materialise both, so reading one direction works on a graph this
        app built and quietly fails on an imported one, which is exactly the
        graph validation exists for. A broader-only import made every parent
        look like an orphan; a narrower-only import hid the hierarchy from the
        checks that walk it.
        """
        known = {c["uri"] for c in concepts}
        parents: dict[str, set[str]] = {uri: set() for uri in known}
        children: dict[str, set[str]] = {uri: set() for uri in known}
        related: dict[str, set[str]] = {uri: set() for uri in known}
        for concept in concepts:
            uri = concept["uri"]
            for target in concept["broader_uris"]:
                if target in known:
                    parents[uri].add(target)
                    children[target].add(uri)
            for target in concept["narrower_uris"]:
                if target in known:
                    children[uri].add(target)
                    parents[target].add(uri)
            for target in concept["related_uris"]:
                if target in known:
                    related[uri].add(target)
                    related[target].add(uri)
        return (
            {uri: sorted(v) for uri, v in parents.items()},
            {uri: sorted(v) for uri, v in children.items()},
            {uri: sorted(v) for uri, v in related.items()},
        )

    @classmethod
    def _skos_parent_map(cls, concepts: list[dict[str, Any]]) -> dict[str, list[str]]:
        """URI -> its broader URIs, from both asserted directions."""
        return cls._skos_link_maps(concepts)[0]

    @staticmethod
    def _skos_ancestors(parents: dict[str, list[str]], start: str) -> set[str]:
        """Every concept above ``start``, cycle-safe.

        A vocabulary that arrived by import may already contain a cycle, so this
        carries a visited set rather than trusting the hierarchy to be acyclic.
        """
        seen: set[str] = set()
        stack = list(parents.get(start, ()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(parents.get(node, ()))
        return seen

    @classmethod
    def _effective_labels(
        cls, concept: dict[str, Any]
    ) -> dict[str, list[dict[str, str]]]:
        """A concept's labels as the SKOS entailment regime sees them.

        A ``skosxl:prefLabel`` whose label resource carries a ``literalForm``
        entails the corresponding ``skos:prefLabel`` (SKOS Reference B.3.4.2),
        so a SKOS-XL label takes part in every integrity condition a plain one
        does: S13 disjointness, S14's one-per-language rule, and the duplicate
        and ambiguous label checks. Suppressing ``missing_prefLabel`` for them
        and stopping there left the rest as false negatives.

        Deduplicated by (value, language), because that entailment means a
        plain label and an XL label carrying the same literal are the same
        statement, not two labels that clash with each other.

        Validation-only. The editor keeps the two apart, since it can write
        plain labels and not SKOS-XL ones.
        """
        merged: dict[str, list[dict[str, str]]] = {}
        for kind in cls.SKOS_LABEL_KINDS:
            seen: set[tuple[str, str]] = set()
            values = []
            for item in [*concept["labels"][kind], *concept["xl_labels"][kind]]:
                key = (item["value"], item["lang"])
                if key not in seen:
                    seen.add(key)
                    values.append(item)
            merged[kind] = values
        return merged

    def _skos_label_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Labels: presence, language tagging, and the SKOS disjointness rules."""
        issues: list[dict[str, str]] = []
        for concept in concepts:
            labels = self._effective_labels(concept)
            name = concept["name"]

            # A SKOS-XL preferred label is a preferred label. Without this the
            # check fires on every concept of a SKOS-XL vocabulary, at the one
            # severity that cannot be switched off, and reports a valid file as
            # broken.
            if not labels["prefLabel"]:
                issues.append(
                    self._skos_issue(
                        "error",
                        "missing_prefLabel",
                        concept,
                        f"Concept '{name}' has no prefLabel",
                    )
                )

            by_lang: dict[str, int] = {}
            for item in labels["prefLabel"]:
                by_lang[item["lang"]] = by_lang.get(item["lang"], 0) + 1
            for lang, count in sorted(by_lang.items()):
                if count > 1:
                    tag = f"@{lang}" if lang else " (untagged)"
                    issues.append(
                        self._skos_issue(
                            "error",
                            "multi_prefLabel_per_lang",
                            concept,
                            f"Concept '{name}' has {count} prefLabels{tag}; SKOS "
                            "allows at most one per language tag "
                            "(SKOS Reference S14)",
                        )
                    )

            for kind in self.SKOS_LABEL_KINDS:
                for item in labels[kind]:
                    if not item["value"].strip():
                        issues.append(
                            self._skos_issue(
                                "error",
                                "empty_label",
                                concept,
                                f"Concept '{name}' has an empty {kind}",
                            )
                        )
                    elif not item["lang"]:
                        issues.append(
                            self._skos_issue(
                                "warning",
                                "missing_lang",
                                concept,
                                f"{kind} '{item['value']}' on '{name}' has no "
                                "language tag",
                            )
                        )
                    # No malformed-tag check here. rdflib refuses a bad tag when
                    # the Literal is constructed, by the API and by the parser
                    # alike, and it refuses exactly what languages.py refuses,
                    # so such a literal cannot reach this graph to be found.

            # S13 makes the three label properties *pairwise* disjoint, so an
            # altLabel matching a hiddenLabel is as much a clash as either
            # matching a prefLabel. Grouping by literal catches all three pairs
            # and reports each clashing literal once rather than once per kind.
            #
            # Keyed by (value, language): a language tag is part of an RDF
            # literal's identity, so "Bank"@en and "Bank"@de are different
            # objects and S13 is not engaged.
            by_literal: dict[tuple[str, str], list[str]] = {}
            for kind in self.SKOS_LABEL_KINDS:
                for item in labels[kind]:
                    if item["value"].strip():
                        by_literal.setdefault((item["value"], item["lang"]), []).append(
                            kind
                        )
            for (value, lang), kinds in by_literal.items():
                clashing = [k for k in self.SKOS_LABEL_KINDS if k in kinds]
                if len(clashing) > 1:
                    tagged = f"'{value}'@{lang}" if lang else f"'{value}'"
                    issues.append(
                        self._skos_issue(
                            "warning",
                            "label_overlap",
                            concept,
                            f"{tagged} on '{name}' is used as "
                            f"{' and '.join(clashing)}; the three label "
                            "properties are pairwise disjoint "
                            "(SKOS Reference S13)",
                        )
                    )

            # Every notation, not ``graph.value``'s arbitrary one: a concept
            # carrying a correct typed notation alongside a language-tagged one
            # would otherwise be reported or not depending on iteration order.
            for notation in self.graph.objects(URIRef(concept["uri"]), SKOS.notation):
                if isinstance(notation, Literal) and notation.language:
                    issues.append(
                        self._skos_issue(
                            "warning",
                            "notation_lang_tagged",
                            concept,
                            f"notation '{notation}' on '{name}' carries a "
                            "language tag; a notation is a code in a symbol "
                            "scheme and takes a datatype instead "
                            "(SKOS Reference 6.5)",
                        )
                    )
        return issues

    def _skos_relation_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Semantic relations: self-links, dangling targets, and S27 clashes."""
        issues: list[dict[str, str]] = []
        shown = self._skos_display_names(concepts)
        parents, _children, related_map = self._skos_link_maps(concepts)
        known = set(shown)

        for concept in concepts:
            uri, name = concept["uri"], concept["name"]

            for kind in ("broader", "narrower", "related"):
                targets = concept[f"{kind}_uris"]
                if uri in targets:
                    issues.append(
                        self._skos_issue(
                            "error",
                            "self_relation",
                            concept,
                            f"Concept '{name}' is its own {kind}",
                        )
                    )
                # Mapping properties are excluded on purpose: pointing outside
                # this graph is the whole point of exactMatch and friends.
                for target in targets:
                    if target not in known:
                        issues.append(
                            self._skos_issue(
                                "error",
                                "dangling_relation",
                                concept,
                                f"{kind} on '{name}' points at {target}, which "
                                "is not a Concept in this vocabulary",
                            )
                        )

            ancestry = self._skos_ancestors(parents, uri)
            for target in related_map[uri]:
                if target not in known or target == uri:
                    continue
                if target in ancestry or uri in self._skos_ancestors(parents, target):
                    issues.append(
                        self._skos_issue(
                            "error",
                            "relation_clash",
                            concept,
                            f"'{name}' is related to '{shown[target]}' and also "
                            "hierarchically connected to it; skos:related is "
                            "disjoint with skos:broaderTransitive "
                            "(SKOS Reference S27)",
                        )
                    )
        return issues

    def _skos_hierarchy_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Shape of the hierarchy: redundant edges and stranded concepts."""
        issues: list[dict[str, str]] = []
        shown = self._skos_display_names(concepts)
        parents, children, related_map = self._skos_link_maps(concepts)

        for concept in concepts:
            uri, name = concept["uri"], concept["name"]

            # A direct parent that is also an ancestor through another parent
            # says nothing the hierarchy does not already say.
            direct = parents.get(uri, [])
            for parent in direct:
                via_others = set()
                for other in direct:
                    if other != parent:
                        via_others |= self._skos_ancestors(parents, other)
                if parent in via_others:
                    issues.append(
                        self._skos_issue(
                            "warning",
                            "hierarchy_redundancy",
                            concept,
                            f"broader '{shown[parent]}' on '{name}' is already "
                            "reachable through another parent (qSKOS: "
                            "hierarchical redundancy)",
                        )
                    )

            if (
                not parents[uri]
                and not children[uri]
                and not related_map[uri]
                and not concept["top_of_uris"]
            ):
                issues.append(
                    self._skos_issue(
                        "warning",
                        "orphan",
                        concept,
                        f"Concept '{name}' has no broader, narrower or related "
                        "concept and is not a top concept (qSKOS: orphan concept)",
                    )
                )

            for scheme_uri in concept["top_of_uris"]:
                if set(parents[uri]) & set(
                    self._skos_concepts_in_scheme(concepts, scheme_uri)
                ):
                    issues.append(
                        self._skos_issue(
                            "warning",
                            "top_with_broader",
                            concept,
                            f"'{name}' is a top concept of "
                            f"'{self._local_name(URIRef(scheme_uri))}' but also "
                            "has a broader concept in that same scheme",
                        )
                    )
        return issues

    @staticmethod
    def _skos_concepts_in_scheme(
        concepts: list[dict[str, Any]], scheme_uri: str
    ) -> set[str]:
        """URIs of the concepts in one scheme, addressed by the scheme's URI."""
        return {c["uri"] for c in concepts if scheme_uri in c["scheme_uris"]}

    def _skos_scheme_issues(
        self, concepts: list[dict[str, Any]], schemes: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Scheme membership, label clashes, and cross-scheme mapping misuse."""
        issues: list[dict[str, str]] = []
        shown = self._skos_display_names(concepts)

        for concept in concepts:
            if not concept["scheme_uris"] and schemes:
                issues.append(
                    self._skos_issue(
                        "info",
                        "no_scheme",
                        concept,
                        f"Concept '{concept['name']}' is not in any ConceptScheme",
                    )
                )

            # A mapping property is for reaching another vocabulary. Between two
            # concepts of the same scheme, a semantic relation is meant instead.
            for relation in self.SKOS_MAPPING_RELATIONS:
                for target in concept["mappings"][relation]:
                    shared = set(concept["scheme_uris"]) & {
                        s
                        for c in concepts
                        if c["uri"] == target
                        for s in c["scheme_uris"]
                    }
                    if shared:
                        issues.append(
                            self._skos_issue(
                                "warning",
                                "mapping_within_scheme",
                                concept,
                                f"{relation} links '{concept['name']}' to "
                                f"'{shown.get(target, target)}' in the same "
                                "scheme; mapping properties are for links "
                                "between vocabularies",
                            )
                        )

        # Duplicate prefLabels within a scheme. Compared per language tag rather
        # than through the flattened compatibility value, and the scheme is
        # addressed by URI: two schemes can share a local name, and resolving by
        # name checks one twice and the other not at all.
        same_scheme_pairs: set[tuple[str, str, str, str]] = set()
        for scheme in schemes:
            seen: dict[tuple[str, str], dict[str, Any]] = {}
            for concept in self.get_concepts(scheme=scheme["uri"]):
                for item in self._effective_labels(concept)["prefLabel"]:
                    key = (item["lang"], item["value"])
                    tagged = (
                        f"'{item['value']}'@{item['lang']}"
                        if item["lang"]
                        else f"'{item['value']}'"
                    )
                    if key in seen:
                        first = seen[key]
                        same_scheme_pairs.add((*key, first["uri"], concept["uri"]))
                        issues.append(
                            self._skos_issue(
                                "warning",
                                "duplicate_prefLabel",
                                concept,
                                f"Duplicate prefLabel {tagged} in scheme "
                                f"'{scheme['name']}' (also on "
                                f"'{shown[first['uri']]}')",
                            )
                        )
                    else:
                        seen[key] = concept

        # The same clash across the whole vocabulary. Pairs already reported
        # above are skipped rather than reported twice: within-scheme and
        # vocabulary-wide duplication are different problems, and a reader who
        # has seen the first does not need the second for the same two concepts.
        vocabulary: dict[tuple[str, str], dict[str, Any]] = {}
        for concept in concepts:
            for item in self._effective_labels(concept)["prefLabel"]:
                key = (item["lang"], item["value"])
                tagged = (
                    f"'{item['value']}'@{item['lang']}"
                    if item["lang"]
                    else f"'{item['value']}'"
                )
                earlier = vocabulary.get(key)
                if earlier is None:
                    vocabulary[key] = concept
                    continue
                if (*key, earlier["uri"], concept["uri"]) in same_scheme_pairs:
                    continue
                issues.append(
                    self._skos_issue(
                        "warning",
                        "ambiguous_prefLabel",
                        concept,
                        f"prefLabel {tagged} is also on '{shown[earlier['uri']]}' "
                        "elsewhere in this vocabulary (qSKOS: ambiguous label)",
                    )
                )
        return issues

    def _skos_editorial_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Completeness and shape, all advisory: nothing here is a SKOS error."""
        issues: list[dict[str, str]] = []
        shown = self._skos_display_names(concepts)
        parents, _children, related_map = self._skos_link_maps(concepts)

        for concept in concepts:
            if not concept["notes"]["definition"] and not concept["notes"]["scopeNote"]:
                issues.append(
                    self._skos_issue(
                        "info",
                        "undocumented",
                        concept,
                        f"Concept '{concept['name']}' has neither a definition "
                        "nor a scopeNote",
                    )
                )

            # Two concepts under the same parent are related by that parent
            # already; saying so again with skos:related adds nothing.
            direct = set(parents.get(concept["uri"], ()))
            for target in related_map[concept["uri"]]:
                if target in shown and direct & set(parents.get(target, ())):
                    issues.append(
                        self._skos_issue(
                            "info",
                            "valueless_association",
                            concept,
                            f"'{concept['name']}' is related to "
                            f"'{shown[target]}' and both share a parent "
                            "(qSKOS: valueless associative relation)",
                        )
                    )

        issues.extend(self._skos_component_issues(concepts))
        issues.extend(self._skos_xl_issues(concepts))
        return issues

    def _skos_xl_issues(self, concepts: list[dict[str, Any]]) -> list[dict[str, str]]:
        """One notice that this vocabulary carries SKOS-XL labels.

        Once for the vocabulary, not once per concept: it is a fact about the
        file rather than a defect in each concept, and AGROVOC would otherwise
        produce forty thousand identical lines. The count is what the user needs
        in order to recognise the situation.
        """
        using = [
            c
            for c in concepts
            if any(c["xl_labels"][kind] for kind in self.SKOS_XL_LABEL_KINDS)
        ]
        if not using:
            return []
        return [
            self._skos_issue(
                "info",
                "skos_xl_labels",
                using[0],
                f"{len(using)} concept{'s' if len(using) != 1 else ''} in this "
                "vocabulary carry SKOS-XL labels. They are shown but not "
                "editable here, which edits plain SKOS labels; editing one "
                "means adding a skos:prefLabel alongside it.",
            )
        ]

    def _skos_component_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Clusters with no connection to the bulk of the vocabulary.

        Reported per stranded cluster rather than once for the vocabulary, so
        each issue names a concept the user can open. The largest cluster is
        taken as the vocabulary proper and is not reported.
        """
        known = {c["uri"]: c for c in concepts}
        adjacency: dict[str, set[str]] = {uri: set() for uri in known}
        for concept in concepts:
            for key in ("broader_uris", "narrower_uris", "related_uris"):
                for target in concept[key]:
                    if target in known:
                        adjacency[concept["uri"]].add(target)
                        adjacency[target].add(concept["uri"])

        seen: set[str] = set()
        components: list[list[str]] = []
        for uri in sorted(known):
            if uri in seen:
                continue
            stack, cluster = [uri], []
            seen.add(uri)
            while stack:
                node = stack.pop()
                cluster.append(node)
                for neighbour in sorted(adjacency[node]):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
            components.append(sorted(cluster))

        if len(components) < 2:
            return []
        components.sort(key=lambda c: (-len(c), c[0]))
        biggest = len(components[0])
        return [
            self._skos_issue(
                "info",
                "disconnected_components",
                known[cluster[0]],
                f"'{known[cluster[0]]['name']}' is in a cluster of "
                f"{len(cluster)} concept{'s' if len(cluster) != 1 else ''} with "
                f"no link to the main body of {biggest} "
                "(qSKOS: disconnected concept cluster)",
            )
            for cluster in components[1:]
        ]

    def _skos_cycles(self, concepts: list[dict[str, Any]]) -> list[list[str]]:
        """Every distinct ``skos:broader`` cycle, as a list of URIs each.

        An iterative three-colour DFS over *all* parents. Iterative because an
        imported vocabulary can be deeper than the recursion limit, over all
        parents because following only the first missed any cycle reachable
        through a second, and canonicalised by member set so a cycle is not
        found once per member.

        Shared by the check and its autofix on purpose: a fixer that rederived
        the cycles its own way could break an edge the check never complained
        about, or leave the one it did.
        """
        cycles: list[list[str]] = []
        parents = self._skos_parent_map(concepts)
        WHITE, GREY, BLACK = 0, 1, 2
        colour = dict.fromkeys(parents, WHITE)
        seen_cycles: set[frozenset] = set()

        for root in sorted(parents):
            if colour[root] != WHITE:
                continue
            colour[root] = GREY
            path = [root]
            stack = [(root, iter(parents[root]))]
            while stack:
                node, remaining = stack[-1]
                descended = False
                for nxt in remaining:
                    if colour.get(nxt) == GREY:
                        # A grey node is on the current path, so we just closed
                        # a loop. Slice the path from it to name the real cycle.
                        cycle = path[path.index(nxt) :]
                        if frozenset(cycle) not in seen_cycles:
                            seen_cycles.add(frozenset(cycle))
                            cycles.append(cycle)
                    elif colour.get(nxt, BLACK) == WHITE:
                        colour[nxt] = GREY
                        path.append(nxt)
                        stack.append((nxt, iter(parents[nxt])))
                        descended = True
                        break
                if not descended:
                    colour[node] = BLACK
                    stack.pop()
                    path.pop()
        return cycles

    def _skos_cycle_issues(
        self, concepts: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """One issue per distinct cycle found by :meth:`_skos_cycles`."""
        shown = self._skos_display_names(concepts)
        by_uri = {c["uri"]: c for c in concepts}
        return [
            self._skos_issue(
                "error",
                "broader_cycle",
                by_uri[cycle[0]],
                "Broader/narrower cycle detected: "
                + " -> ".join(shown[u] for u in [*cycle, cycle[0]]),
            )
            for cycle in self._skos_cycles(concepts)
        ]

    def validate_skos(
        self,
        *,
        check_editorial: bool = True,
        check_conventions: bool = True,
    ) -> list[dict[str, str]]:
        """Validate a SKOS vocabulary against the Reference and common practice.

        Three tiers, so a large imported vocabulary can be checked for real
        errors without drowning in advice:

        - **error** — conditions the SKOS Reference states outright, plus
          structural breakage (a cycle, a relation to something that is not a
          concept). Always checked.
        - **warning** — stated conventions and thesaurus practice. Gated by
          ``check_conventions``.
        - **info** — editorial completeness and vocabulary shape. Gated by
          ``check_editorial``.

        Each issue carries ``severity``, ``type``, ``subject``, ``subject_uri``
        and ``message``. ``type`` is stable, so the UI can group by it and the
        autofixers can target it; ``subject_uri`` is what to navigate by, since
        two concepts may share a local name.
        """
        concepts = self.get_concepts()
        schemes = self.get_concept_schemes()

        issues = self._skos_label_issues(concepts)
        issues += self._skos_relation_issues(concepts)
        issues += self._skos_cycle_issues(concepts)
        issues += self._skos_scheme_issues(concepts, schemes)
        if check_editorial:
            issues += self._skos_editorial_issues(concepts)
        # Hierarchy shape is the most expensive family (an ancestor walk per
        # parent per concept) and every issue in it is advisory, so it is
        # skipped wholesale rather than computed and filtered away.
        if check_conventions:
            issues += self._skos_hierarchy_issues(concepts)
        else:
            issues = [i for i in issues if i["severity"] != "warning"]
        if not check_editorial:
            issues = [i for i in issues if i["severity"] != "info"]

        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(
            issues, key=lambda i: (order[i["severity"]], i["type"], i["subject"])
        )

    #: What :meth:`autofix_skos` can repair, keyed by the check ``type`` it
    #: clears. Deliberately a subset: most checks describe something only the
    #: author can decide (what a concept means, which scheme it belongs to), and
    #: guessing would be worse than reporting.
    SKOS_AUTOFIXES: ClassVar[dict[str, str]] = {
        "missing_lang": "Stamp a language tag on labels that carry none.",
        "self_relation": "Remove the self-referential relation, and its inverse.",
        "dangling_relation": (
            "Remove relations pointing at something that is not a Concept here."
        ),
        "top_with_broader": (
            "Retract topConceptOf where the concept has a broader in that scheme."
        ),
        "label_overlap": "Remove the duplicate of a label held under two kinds.",
        "hierarchy_redundancy": (
            "Remove a broader edge already implied by another parent."
        ),
        "broader_cycle": "Break each hierarchy cycle by removing one edge.",
    }

    def autofix_skos(self, fix_type: str, *, lang: str | None = None) -> int:
        """Repair one class of SKOS issue. Returns how many issues it resolved.

        Counted in issues rather than triples, so the count matches what the
        validation panel offered to fix. The two iterative fixers (cycles and
        redundant edges) can resolve more than one reported issue per removal,
        because one edge may close several cycles, so their count is what they
        removed rather than what was reported.

        One class at a time, never all of them: breaking a cycle and dropping a
        redundant edge both discard something the author may have meant, so the
        choice belongs to them, per issue class, with an undo checkpoint around
        it.

        Each fixer derives its targets from the same views the corresponding
        check reads, rather than re-reading whichever property its author had in
        mind. A fixer that disagreed with its check would either break an edge
        nothing complained about or leave the one that did, and unlike a wrong
        report a wrong repair is written into the user's graph.

        SKOS-XL labels are never touched. This app writes plain SKOS, so
        "repairing" one would mean editing a label resource it cannot author;
        those issues are left for the author to resolve.
        """
        if fix_type not in self.SKOS_AUTOFIXES:
            known = ", ".join(sorted(self.SKOS_AUTOFIXES))
            raise ValueError(f"No autofix for '{fix_type}' (fixable: {known})")
        fixer = getattr(self, f"_autofix_{fix_type}")
        if fix_type == "missing_lang":
            return fixer(lang)
        return fixer()

    def _autofix_missing_lang(self, lang: str | None) -> int:
        """Re-tag untagged labels in ``lang``.

        The tag is asked for rather than guessed: a vocabulary's labels are not
        necessarily in the language of whoever is repairing it, and stamping the
        wrong one is a lie the validator will then report as clean.
        """
        tag = self._checked_lang(lang)
        if not tag:
            raise ValueError("A language tag is required to fix untagged labels.")

        fixed = 0
        for concept in self.get_concepts():
            effective = self._effective_labels(concept)
            taken = {
                (item["value"], item["lang"])
                for kind in self.SKOS_LABEL_KINDS
                for item in effective[kind]
            }
            pref_langs = {
                item["lang"] for item in effective["prefLabel"] if item["lang"]
            }
            for kind in self.SKOS_LABEL_KINDS:
                # Plain labels only: an untagged skosxl:literalForm would have to
                # be edited on the label resource, which this app does not author.
                for item in concept["labels"][kind]:
                    if item["lang"] or not item["value"].strip():
                        continue
                    # Refuse a re-tag that would trade this warning for a worse
                    # problem: a second prefLabel in a language that already has
                    # one breaks S14, and landing on a literal another kind holds
                    # breaks S13. Both are left for the author.
                    if kind == "prefLabel" and tag in pref_langs:
                        continue
                    if (item["value"], tag) in taken:
                        continue
                    # Through the helper, which matches the literal actually in
                    # the graph. Rebuilding one with Literal(value) misses a
                    # typed label such as "Dog"^^xsd:string, so the old literal
                    # survived and a tagged duplicate was added beside it.
                    self.remove_concept_label(concept["uri"], kind, item["value"])
                    self.set_concept_label(concept["uri"], kind, item["value"], tag)
                    taken.add((item["value"], tag))
                    if kind == "prefLabel":
                        pref_langs.add(tag)
                    fixed += 1
        return fixed

    def _autofix_self_relation(self) -> int:
        fixed = 0
        for concept in self.get_concepts():
            uri = concept["uri"]
            for kind in ("broader", "narrower", "related"):
                if uri in concept[f"{kind}_uris"]:
                    # Through the helper, so the auto-added inverse goes too.
                    self.remove_concept_relation(uri, kind, uri)
                    fixed += 1
        return fixed

    def _autofix_dangling_relation(self) -> int:
        concepts = self.get_concepts()
        known = {c["uri"] for c in concepts}
        fixed = 0
        for concept in concepts:
            for kind in ("broader", "narrower", "related"):
                for target in concept[f"{kind}_uris"]:
                    if target not in known:
                        self.remove_concept_relation(concept["uri"], kind, target)
                        fixed += 1
        return fixed

    def _autofix_top_with_broader(self) -> int:
        concepts = self.get_concepts()
        parents, _children, _related = self._skos_link_maps(concepts)
        fixed = 0
        for concept in concepts:
            uri = concept["uri"]
            for scheme_uri in concept["top_of_uris"]:
                in_scheme = self._skos_concepts_in_scheme(concepts, scheme_uri)
                if set(parents[uri]) & in_scheme:
                    # The broader is the assertion with content; being a top
                    # concept is the one contradicted by it.
                    self.set_top_concept(uri, scheme_uri, is_top=False)
                    fixed += 1
        return fixed

    def _autofix_label_overlap(self) -> int:
        """Drop the less specific of two label kinds holding one literal.

        prefLabel is kept over altLabel, and altLabel over hiddenLabel: the
        surviving one is the more visible, so the repair never hides a label
        that was on show. A literal held by a SKOS-XL label is left alone, and
        so is its plain counterpart, because removing either side of that pair
        means guessing which spelling the author meant to keep.
        """
        precedence = list(self.SKOS_LABEL_KINDS)
        fixed = 0
        for concept in self.get_concepts():
            xl_literals = {
                (item["value"], item["lang"])
                for kind in self.SKOS_XL_LABEL_KINDS
                for item in concept["xl_labels"][kind]
            }
            by_literal: dict[tuple[str, str], list[str]] = {}
            for kind in self.SKOS_LABEL_KINDS:
                for item in concept["labels"][kind]:
                    if item["value"].strip():
                        by_literal.setdefault((item["value"], item["lang"]), []).append(
                            kind
                        )
            for (value, tag), kinds in by_literal.items():
                if (value, tag) in xl_literals:
                    continue
                clashing = [k for k in precedence if k in kinds]
                if len(clashing) < 2:
                    continue
                for kind in clashing[1:]:
                    # The helper matches on (text, language) against the literal
                    # in the graph, so a typed label is removed rather than
                    # missed by a rebuilt plain one.
                    self.remove_concept_label(concept["uri"], kind, value, tag)
                # One per clashing literal, matching how the check reports it:
                # a literal held under all three kinds is one issue, not two.
                fixed += 1
        return fixed

    def _autofix_hierarchy_redundancy(self) -> int:
        """Remove a parent already reachable through another parent.

        Recomputed after each removal: two redundant edges can each be implied
        by the other, and removing both would detach the concept from a branch
        it genuinely belongs to.
        """
        fixed = 0
        while True:
            concepts = self.get_concepts()
            parents = self._skos_parent_map(concepts)
            redundant = None
            for concept in concepts:
                uri = concept["uri"]
                direct = parents.get(uri, [])
                for parent in direct:
                    via_others: set[str] = set()
                    for other in direct:
                        if other != parent:
                            via_others |= self._skos_ancestors(parents, other)
                    if parent in via_others:
                        redundant = (uri, parent)
                        break
                if redundant:
                    break
            if not redundant:
                return fixed
            self.remove_concept_relation(redundant[0], "broader", redundant[1])
            fixed += 1

    def _autofix_broader_cycle(self) -> int:
        """Break each cycle by removing the edge that closes it.

        Recomputed after each break, because one edge can close more than one
        cycle and removing it may resolve several at once.
        """
        fixed = 0
        while True:
            cycles = self._skos_cycles(self.get_concepts())
            if not cycles:
                return fixed
            cycle = cycles[0]
            # The closing edge: the last member's broader back to the first.
            self.remove_concept_relation(cycle[-1], "broader", cycle[0])
            fixed += 1

    # ==================== RELATIONS OPERATIONS ====================

    # Class relation types
    CLASS_RELATIONS: ClassVar[dict[str, URIRef]] = {
        "subClassOf": RDFS.subClassOf,
        "equivalentClass": OWL.equivalentClass,
        "disjointWith": OWL.disjointWith,
    }

    # Property relation types
    PROPERTY_RELATIONS: ClassVar[dict[str, URIRef]] = {
        "subPropertyOf": RDFS.subPropertyOf,
        "equivalentProperty": OWL.equivalentProperty,
        "inverseOf": OWL.inverseOf,
        "propertyDisjointWith": OWL.propertyDisjointWith,
    }

    # Individual relation types
    INDIVIDUAL_RELATIONS: ClassVar[dict[str, URIRef]] = {
        "sameAs": OWL.sameAs,
        "differentFrom": OWL.differentFrom,
    }

    def add_class_relation(self, class1: str, relation_type: str, class2: str):
        """Add a relation between two classes."""
        class1_uri = self._uri(class1)
        class2_uri = self._uri(class2)
        relation = self.CLASS_RELATIONS.get(relation_type)
        if relation:
            self.graph.add((class1_uri, relation, class2_uri))

    def remove_class_relation(self, class1: str, relation_type: str, class2: str):
        """Remove a relation between two classes."""
        class1_uri = self._uri(class1)
        class2_uri = self._uri(class2)
        relation = self.CLASS_RELATIONS.get(relation_type)
        if relation:
            self.graph.remove((class1_uri, relation, class2_uri))

    def get_class_relations(
        self, class_name: str | None = None
    ) -> list[dict[str, str]]:
        """Get all class relations, optionally filtered by class.

        Each result dict includes both local names (subject/object) and full
        URIs (subject_uri/object_uri) so callers can disambiguate when local
        names collide across namespaces.
        """
        relations = []
        for rel_name, rel_pred in self.CLASS_RELATIONS.items():
            for subj, obj in self.graph.subject_objects(rel_pred):
                if isinstance(subj, URIRef) and isinstance(obj, URIRef):
                    subj_name = self._local_name(subj)
                    obj_name = self._local_name(obj)
                    if class_name is None or class_name in [subj_name, obj_name]:
                        relations.append(
                            {
                                "subject": subj_name,
                                "subject_uri": str(subj),
                                "relation": rel_name,
                                "object": obj_name,
                                "object_uri": str(obj),
                            }
                        )
        return relations

    def add_property_relation(self, prop1: str, relation_type: str, prop2: str):
        """Add a relation between two properties."""
        prop1_uri = self._uri(prop1)
        prop2_uri = self._uri(prop2)
        relation = self.PROPERTY_RELATIONS.get(relation_type)
        if relation:
            self.graph.add((prop1_uri, relation, prop2_uri))

    def remove_property_relation(self, prop1: str, relation_type: str, prop2: str):
        """Remove a relation between two properties."""
        prop1_uri = self._uri(prop1)
        prop2_uri = self._uri(prop2)
        relation = self.PROPERTY_RELATIONS.get(relation_type)
        if relation:
            self.graph.remove((prop1_uri, relation, prop2_uri))

    def _update_relation(
        self,
        relations: dict[str, Any],
        kind: str,
        old: tuple,
        new: tuple,
    ) -> bool:
        """Replace one relation triple with another (issue #152).

        ``old`` and ``new`` are ``(subject, relation_type, object)`` local names
        or URIs. Both relation types are resolved before anything is written, so
        an unknown type raises instead of deleting the original and failing to
        write the replacement. Returns False when ``old`` isn't asserted, which
        is how a stale row (deleted in another tab, or already edited) is
        reported rather than silently adding a second triple.
        """
        old_subj, old_type, old_obj = old
        new_subj, new_type, new_obj = new
        for relation_type in (old_type, new_type):
            if relation_type not in relations:
                raise ValueError(f"Unknown {kind} relation: {relation_type}")

        old_triple = (
            self._uri(old_subj),
            relations[old_type],
            self._uri(old_obj),
        )
        if old_triple not in self.graph:
            return False

        self.graph.remove(old_triple)
        self.graph.add((self._uri(new_subj), relations[new_type], self._uri(new_obj)))
        return True

    def update_class_relation(self, old: tuple, new: tuple) -> bool:
        """Replace a class relation with an edited one. See :meth:`_update_relation`."""
        return self._update_relation(self.CLASS_RELATIONS, "class", old, new)

    def update_property_relation(self, old: tuple, new: tuple) -> bool:
        """Replace a property relation with an edited one."""
        return self._update_relation(self.PROPERTY_RELATIONS, "property", old, new)

    def update_individual_relation(self, old: tuple, new: tuple) -> bool:
        """Replace an individual relation with an edited one."""
        return self._update_relation(self.INDIVIDUAL_RELATIONS, "individual", old, new)

    def get_property_relations(
        self, prop_name: str | None = None
    ) -> list[dict[str, str]]:
        """Get all property relations, optionally filtered by property.

        Each result dict includes both local names and full URIs.
        """
        relations = []
        for rel_name, rel_pred in self.PROPERTY_RELATIONS.items():
            for subj, obj in self.graph.subject_objects(rel_pred):
                if isinstance(subj, URIRef) and isinstance(obj, URIRef):
                    subj_name = self._local_name(subj)
                    obj_name = self._local_name(obj)
                    if prop_name is None or prop_name in [subj_name, obj_name]:
                        relations.append(
                            {
                                "subject": subj_name,
                                "subject_uri": str(subj),
                                "relation": rel_name,
                                "object": obj_name,
                                "object_uri": str(obj),
                            }
                        )
        return relations

    def add_individual_relation(self, ind1: str, relation_type: str, ind2: str):
        """Add a relation between two individuals (sameAs, differentFrom)."""
        ind1_uri = self._uri(ind1)
        ind2_uri = self._uri(ind2)
        relation = self.INDIVIDUAL_RELATIONS.get(relation_type)
        if relation:
            self.graph.add((ind1_uri, relation, ind2_uri))

    def remove_individual_relation(self, ind1: str, relation_type: str, ind2: str):
        """Remove a relation between two individuals."""
        ind1_uri = self._uri(ind1)
        ind2_uri = self._uri(ind2)
        relation = self.INDIVIDUAL_RELATIONS.get(relation_type)
        if relation:
            self.graph.remove((ind1_uri, relation, ind2_uri))

    def get_individual_relations(
        self, ind_name: str | None = None
    ) -> list[dict[str, str]]:
        """Get all individual relations (sameAs, differentFrom).

        Each result dict includes both local names and full URIs.
        """
        relations = []
        for rel_name, rel_pred in self.INDIVIDUAL_RELATIONS.items():
            for subj, obj in self.graph.subject_objects(rel_pred):
                if isinstance(subj, URIRef) and isinstance(obj, URIRef):
                    subj_name = self._local_name(subj)
                    obj_name = self._local_name(obj)
                    if ind_name is None or ind_name in [subj_name, obj_name]:
                        relations.append(
                            {
                                "subject": subj_name,
                                "subject_uri": str(subj),
                                "relation": rel_name,
                                "object": obj_name,
                                "object_uri": str(obj),
                            }
                        )
        return relations

    # ==================== ADVANCED OWL FEATURES ====================

    def add_property_chain(self, property_name: str, chain_properties: list[str]):
        """Add a property chain axiom (owl:propertyChainAxiom)."""
        prop_uri = self._uri(property_name)
        chain_uris: list[Node] = [self._uri(p) for p in chain_properties]

        # Create RDF list for the chain
        chain_list = BNode()
        Collection(self.graph, chain_list, chain_uris)
        self.graph.add((prop_uri, OWL.propertyChainAxiom, chain_list))

    def get_property_chains(self) -> list[dict[str, Any]]:
        """Get all property chain axioms."""
        chains = []
        for prop, chain_list in self.graph.subject_objects(OWL.propertyChainAxiom):
            if isinstance(prop, URIRef):
                chain = list(Collection(self.graph, chain_list))
                chains.append(
                    {
                        "property": self._local_name(prop),
                        "chain": [
                            self._local_name(p) for p in chain if isinstance(p, URIRef)
                        ],
                    }
                )
        return chains

    def add_class_expression(
        self,
        class_name: str,
        expression_type: str,
        classes: list[str] | None = None,
        individuals: list[str] | None = None,
    ):
        """Add a class expression (unionOf, intersectionOf, complementOf, oneOf)."""
        class_uri = self._uri(class_name)

        if expression_type == "complementOf" and classes:
            # complementOf takes a single class
            self.graph.add((class_uri, OWL.complementOf, self._uri(classes[0])))

        elif expression_type == "oneOf" and individuals:
            # oneOf takes a list of individuals
            ind_uris: list[Node] = [self._uri(i) for i in individuals]
            list_node = BNode()
            Collection(self.graph, list_node, ind_uris)
            self.graph.add((class_uri, OWL.oneOf, list_node))

        elif expression_type in ["unionOf", "intersectionOf"] and classes:
            # unionOf and intersectionOf take a list of classes
            class_uris: list[Node] = [self._uri(c) for c in classes]
            list_node = BNode()
            Collection(self.graph, list_node, class_uris)
            if expression_type == "unionOf":
                self.graph.add((class_uri, OWL.unionOf, list_node))
            else:
                self.graph.add((class_uri, OWL.intersectionOf, list_node))

    def get_class_expressions(
        self, class_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Get class expressions for a class or all classes."""
        expressions = []

        expression_types = [
            (OWL.unionOf, "unionOf"),
            (OWL.intersectionOf, "intersectionOf"),
            (OWL.complementOf, "complementOf"),
            (OWL.oneOf, "oneOf"),
        ]

        for pred, expr_type in expression_types:
            for subj, obj in self.graph.subject_objects(pred):
                if isinstance(subj, URIRef):
                    subj_name = self._local_name(subj)
                    if class_name and subj_name != class_name:
                        continue

                    expr = {"class": subj_name, "type": expr_type, "members": []}

                    if expr_type == "complementOf":
                        if isinstance(obj, URIRef):
                            expr["members"] = [self._local_name(obj)]
                    else:
                        # It's a list
                        try:
                            members = list(Collection(self.graph, obj))
                            expr["members"] = [
                                self._local_name(m)
                                for m in members
                                if isinstance(m, URIRef)
                            ]
                        except Exception:
                            logger.debug(
                                "Skipping malformed RDF list in a %s expression on %s",
                                expr_type,
                                subj_name,
                                exc_info=True,
                            )

                    if expr["members"]:
                        expressions.append(expr)

        return expressions

    def add_all_different(self, individuals: list[str]):
        """Add an owl:AllDifferent declaration for a list of individuals."""
        all_diff = BNode()
        self.graph.add((all_diff, RDF.type, OWL.AllDifferent))

        ind_uris: list[Node] = [self._uri(i) for i in individuals]
        list_node = BNode()
        Collection(self.graph, list_node, ind_uris)
        self.graph.add((all_diff, OWL.distinctMembers, list_node))

    def get_all_different(self) -> list[list[str]]:
        """Get all owl:AllDifferent declarations."""
        all_diffs = []
        for all_diff in self.graph.subjects(RDF.type, OWL.AllDifferent):
            members_list = self.graph.value(all_diff, OWL.distinctMembers)
            if members_list:
                try:
                    members = list(Collection(self.graph, members_list))
                    all_diffs.append(
                        [self._local_name(m) for m in members if isinstance(m, URIRef)]
                    )
                except Exception:
                    logger.debug(
                        "Skipping malformed owl:distinctMembers list", exc_info=True
                    )
        return all_diffs

    def add_has_key(self, class_name: str, properties: list[str]):
        """Add an owl:hasKey axiom to a class."""
        class_uri = self._uri(class_name)
        prop_uris: list[Node] = [self._uri(p) for p in properties]

        list_node = BNode()
        Collection(self.graph, list_node, prop_uris)
        self.graph.add((class_uri, OWL.hasKey, list_node))

    def get_has_keys(self, class_name: str | None = None) -> list[dict[str, Any]]:
        """Get owl:hasKey axioms."""
        keys = []
        for subj, key_list in self.graph.subject_objects(OWL.hasKey):
            if isinstance(subj, URIRef):
                subj_name = self._local_name(subj)
                if class_name and subj_name != class_name:
                    continue
                try:
                    props = list(Collection(self.graph, key_list))
                    keys.append(
                        {
                            "class": subj_name,
                            "properties": [
                                self._local_name(p)
                                for p in props
                                if isinstance(p, URIRef)
                            ],
                        }
                    )
                except Exception:
                    logger.debug("Skipping malformed owl:hasKey list", exc_info=True)
        return keys

    def add_disjoint_union(self, class_name: str, disjoint_classes: list[str]):
        """Add an owl:disjointUnionOf axiom (class is disjoint union of listed classes)."""
        class_uri = self._uri(class_name)
        class_uris: list[Node] = [self._uri(c) for c in disjoint_classes]

        list_node = BNode()
        Collection(self.graph, list_node, class_uris)
        self.graph.add((class_uri, OWL.disjointUnionOf, list_node))

    def get_disjoint_unions(self) -> list[dict[str, Any]]:
        """Get all owl:disjointUnionOf declarations."""
        unions = []
        for subj, union_list in self.graph.subject_objects(OWL.disjointUnionOf):
            if isinstance(subj, URIRef):
                try:
                    members = list(Collection(self.graph, union_list))
                    unions.append(
                        {
                            "class": self._local_name(subj),
                            "members": [
                                self._local_name(m)
                                for m in members
                                if isinstance(m, URIRef)
                            ],
                        }
                    )
                except Exception:
                    logger.debug(
                        "Skipping malformed owl:disjointUnionOf list", exc_info=True
                    )
        return unions

    # ==================== IMPORT/EXPORT OPERATIONS ====================

    def load_from_file(self, file_path: str, format: str = "turtle"):
        """Load ontology from a file."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if format == "turtle":
            self._loaded_prefixes = self._extract_prefixes_from_ttl(content)
        elif format == "json-ld":
            self._loaded_prefixes = self._extract_prefixes_from_jsonld(content)
        else:
            self._loaded_prefixes = []
        self.graph = Graph()
        self.graph.parse(file_path, format=format)
        self._update_namespace_from_graph()

    def save_to_file(self, file_path, format: str | None = None) -> None:
        """Serialize the graph straight to ``file_path``, atomically.

        Streams the serialization to a temp file in the same directory via
        ``Graph.serialize(destination=...)`` and then ``os.replace``s it into
        place, so no giant in-memory string is built and a reader/backup tool
        never sees a half-written file. ``format`` defaults to the file's
        extension (Turtle if unknown).
        """
        fmt = format or rdf_format_for_path(file_path)
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(p.parent), prefix=p.name + ".", suffix=".tmp"
        )
        os.close(fd)
        try:
            self.graph.serialize(destination=tmp, format=fmt)
            os.replace(tmp, str(p))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load_from_string(self, data: str, format: str = "turtle"):
        """Load ontology from a string."""
        if format == "turtle":
            self._loaded_prefixes = self._extract_prefixes_from_ttl(data)
        elif format == "json-ld":
            self._loaded_prefixes = self._extract_prefixes_from_jsonld(data)
        else:
            self._loaded_prefixes = []
        self._user_added_prefixes = {}
        self.graph = Graph()
        self.graph.parse(data=data, format=format)
        self._update_namespace_from_graph()

    def preview_import(self, data: str, format: str = "turtle") -> dict[str, Any]:
        """Parse import data and return a preview without modifying the current graph.

        Returns a dict with:
          - diff: output from compare_graphs
          - incoming_stats: statistics of the parsed graph
          - conflicts: list of detected conflicts (for merge modes)
          - prefix_conflicts: list of prefix/namespace mismatches
        """
        temp = Graph()
        temp.parse(data=data, format=format)

        diff = self.compare_graphs(temp)
        conflicts = self.detect_conflicts(temp)
        prefix_conflicts = self._detect_prefix_conflicts(temp)

        # Compute incoming stats
        incoming_stats = {
            "classes": sum(1 for _ in temp.subjects(RDF.type, OWL.Class)),
            "object_properties": sum(
                1 for _ in temp.subjects(RDF.type, OWL.ObjectProperty)
            ),
            "data_properties": sum(
                1 for _ in temp.subjects(RDF.type, OWL.DatatypeProperty)
            ),
            "individuals": sum(1 for _ in temp.subjects(RDF.type, OWL.NamedIndividual)),
            "total_triples": len(temp),
        }

        # Extract incoming ontology metadata
        incoming_meta = {}
        for ont_uri in temp.subjects(RDF.type, OWL.Ontology):
            label = temp.value(ont_uri, RDFS.label)
            if label:
                incoming_meta["label"] = str(label)
            incoming_meta["uri"] = str(ont_uri)
            break

        return {
            "diff": diff,
            "incoming_stats": incoming_stats,
            "incoming_meta": incoming_meta,
            "conflicts": conflicts,
            "prefix_conflicts": prefix_conflicts,
        }

    def detect_conflicts(self, other_graph: Graph) -> list[dict[str, Any]]:
        """Detect conflicts between current graph and another graph.

        A conflict exists when both graphs have triples with the same subject
        and predicate but different object values, for predicates where multiple
        values are semantically problematic.
        """
        conflict_preds = {
            RDFS.label,
            RDFS.domain,
            RDFS.range,
            RDFS.comment,
            OWL.versionIRI,
            DCTERMS.creator,
        }

        conflicts = []
        for s, p, o in other_graph:
            if not isinstance(s, URIRef) or p not in conflict_preds:
                continue
            current_values = set(self.graph.objects(s, p))
            if not current_values:
                continue
            incoming_value = o
            if incoming_value not in current_values:
                conflicts.append(
                    {
                        "subject": self._local_name(s),
                        "predicate": self._local_name(p),
                        "current_values": [
                            self._local_name(v) if isinstance(v, URIRef) else str(v)
                            for v in current_values
                        ],
                        "incoming_value": (
                            self._local_name(incoming_value)
                            if isinstance(incoming_value, URIRef)
                            else str(incoming_value)
                        ),
                    }
                )

        # Deduplicate (same subject+predicate can appear multiple times)
        seen = set()
        unique = []
        for c in conflicts:
            key = (c["subject"], c["predicate"])
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def merge_from_graph(
        self, other_graph: Graph, strategy: str = IMPORT_MERGE
    ) -> dict[str, Any]:
        """Merge another graph into the current graph using the specified strategy.

        Returns a dict with:
          - triples_before: int
          - triples_after: int
          - triples_added: int
          - triples_removed: int
          - conflicts_resolved: int
        """
        triples_before = len(self.graph)

        if strategy == IMPORT_REPLACE:
            self.graph = Graph()
            for s, p, o in other_graph:
                self.graph.add((s, p, o))
            self._update_namespace_from_graph()
            # Copy namespace bindings
            for prefix, ns in other_graph.namespaces():
                self.graph.bind(prefix, ns, override=False)

        elif strategy == IMPORT_MERGE:
            for s, p, o in other_graph:
                self.graph.add((s, p, o))
            self._reconcile_prefixes_after_merge(other_graph)

        elif strategy == IMPORT_MERGE_OVERWRITE:
            # For conflict predicates: remove current, add incoming
            conflict_preds = {
                RDFS.label,
                RDFS.domain,
                RDFS.range,
                RDFS.comment,
                OWL.versionIRI,
                DCTERMS.creator,
            }
            conflicts_resolved = 0
            for s, p, o in other_graph:
                if isinstance(s, URIRef) and p in conflict_preds:
                    current_values = set(self.graph.objects(s, p))
                    if current_values and o not in current_values:
                        for cv in current_values:
                            self.graph.remove((s, p, cv))
                        conflicts_resolved += 1
                self.graph.add((s, p, o))
            self._reconcile_prefixes_after_merge(other_graph)

            triples_after = len(self.graph)
            return {
                "triples_before": triples_before,
                "triples_after": triples_after,
                "triples_added": max(0, triples_after - triples_before),
                "triples_removed": max(0, triples_before - triples_after),
                "conflicts_resolved": conflicts_resolved,
            }

        triples_after = len(self.graph)
        return {
            "triples_before": triples_before,
            "triples_after": triples_after,
            "triples_added": max(0, triples_after - triples_before),
            "triples_removed": max(0, triples_before - triples_after),
            "conflicts_resolved": 0,
        }

    def merge_from_string(
        self, data: str, format: str = "turtle", strategy: str = IMPORT_MERGE
    ) -> dict[str, Any]:
        """Parse data and merge into current graph."""
        temp = Graph()
        temp.parse(data=data, format=format)
        return self.merge_from_graph(temp, strategy=strategy)

    def _detect_prefix_conflicts(self, other_graph: Graph) -> list[dict[str, str]]:
        """Compare namespace bindings between current and incoming graph."""
        current_ns = {prefix: str(ns) for prefix, ns in self.graph.namespaces()}
        conflicts = []
        for prefix, ns in other_graph.namespaces():
            ns_str = str(ns)
            if prefix in current_ns and current_ns[prefix] != ns_str:
                conflicts.append(
                    {
                        "prefix": prefix,
                        "current_namespace": current_ns[prefix],
                        "incoming_namespace": ns_str,
                    }
                )
        return conflicts

    def _reconcile_prefixes_after_merge(
        self, other_graph: Graph, prefix_resolution: dict[str, str] | None = None
    ):
        """Re-bind prefixes after a merge operation."""
        for prefix, ns in other_graph.namespaces():
            if prefix_resolution and prefix in prefix_resolution:
                self.graph.bind(
                    prefix, Namespace(prefix_resolution[prefix]), override=True
                )
            else:
                # Current bindings take precedence
                self.graph.bind(prefix, ns, override=False)

    def _bind_standard_prefixes(self):
        """Bind the prefixes this app always wants readable in an export.

        Called after every graph replacement, not only at construction: loading
        a file swaps ``self.graph`` for a fresh one, and only the prefixes
        rdflib auto-binds survive that. ``skosxl`` is not one of them, so a
        loaded SKOS-XL vocabulary exported as ``ns1:`` until this ran again.
        """
        self.graph.bind("owl", OWL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("xsd", XSD)
        self.graph.bind("skos", SKOS)
        self.graph.bind("skosxl", SKOSXL)
        self.graph.bind("dc", DC)
        self.graph.bind("dcterms", DCTERMS)
        self.graph.bind("", self.namespace)

    def _update_namespace_from_graph(self):
        """Update namespace based on loaded ontology."""
        found_ontology = False
        # Rebound at the end of this method, once self.namespace is settled.

        # Try to find the ontology URI
        for ont in self.graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(ont, URIRef):
                self.ontology_uri = ont
                uri_str = str(ont)
                self.base_uri = self._detect_base_uri(uri_str)
                self.namespace = Namespace(self.base_uri)
                found_ontology = True
                break

        # Fallback: infer namespace from graph prefixes and resource URIs
        if not found_ontology:
            inferred = self._infer_namespace_from_graph()
            if inferred:
                self.base_uri = inferred
                self.namespace = Namespace(self.base_uri)
                self.ontology_uri = URIRef(self.base_uri.rstrip("#").rstrip("/"))
                self.graph.add((self.ontology_uri, RDF.type, OWL.Ontology))

        # One list, bound from one place. This block used to repeat the set
        # from __init__ and had silently fallen a prefix behind it.
        self._bind_standard_prefixes()

    def _detect_base_uri(self, uri_str: str) -> str:
        """Detect the base URI with separator from an ontology URI string."""
        if uri_str.endswith(("#", "/")):
            return uri_str

        sample_uri = self._find_sample_resource_uri()
        if sample_uri and uri_str in sample_uri:
            remainder = sample_uri[len(uri_str) :]
            if remainder.startswith("/"):
                return uri_str + "/"
            elif remainder.startswith("#"):
                return uri_str + "#"
        return uri_str + "#"

    def _find_sample_resource_uri(self) -> str | None:
        """Find a sample resource URI from classes or properties in the graph."""
        for rdf_type in (
            OWL.Class,
            OWL.ObjectProperty,
            OWL.DatatypeProperty,
            OWL.NamedIndividual,
        ):
            for s in self.graph.subjects(RDF.type, rdf_type):
                if isinstance(s, URIRef):
                    return str(s)
        return None

    def _infer_namespace_from_graph(self) -> str | None:
        """Infer namespace from graph prefixes and resource URIs when no owl:Ontology exists."""
        STANDARD_NAMESPACES = {
            str(OWL),
            str(RDF),
            str(RDFS),
            str(XSD),
            str(SKOS),
            str(DC),
            str(DCTERMS),
        }

        # Try the default prefix first (most likely the ontology namespace)
        for prefix, ns in self.graph.namespaces():
            ns_str = str(ns)
            if prefix == "" and ns_str not in STANDARD_NAMESPACES:
                return ns_str

        # Try to find the most common namespace among typed resources
        from collections import Counter

        ns_counter: Counter = Counter()
        for rdf_type in (
            OWL.Class,
            OWL.ObjectProperty,
            OWL.DatatypeProperty,
            OWL.NamedIndividual,
        ):
            for s in self.graph.subjects(RDF.type, rdf_type):
                if isinstance(s, URIRef):
                    uri_str = str(s)
                    for sep in ("#", "/"):
                        idx = uri_str.rfind(sep)
                        if idx != -1:
                            candidate = uri_str[: idx + 1]
                            if candidate not in STANDARD_NAMESPACES:
                                ns_counter[candidate] += 1
                            break

        if ns_counter:
            return ns_counter.most_common(1)[0][0]

        return None

    def export_to_string(self, format: str = "turtle") -> str:
        """Export ontology to a string."""
        return self.graph.serialize(format=format)

    # ==================== SEARCH ====================

    def search(self, query: str) -> list[dict[str, str]]:
        """Search across resource names, labels, comments and SKOS labels.

        Matches (case-insensitive, partial) against the local name, rdfs:label,
        skos:prefLabel, skos:altLabel and rdfs:comment of every class, property,
        individual and SKOS concept. altLabel matching in particular improves
        discoverability for vocabularies with synonyms.

        Returns a list of dicts with keys: name, uri, type, label, match_field.
        The full URI is included so callers can distinguish duplicate local
        names from different namespaces.
        """
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        results: list[dict[str, str]] = []
        seen: set[str] = set()

        type_map = [
            (OWL.Class, "Class"),
            (OWL.ObjectProperty, "Object Property"),
            (OWL.DatatypeProperty, "Data Property"),
            (OWL.NamedIndividual, "Individual"),
            (SKOS.Concept, "SKOS Concept"),
        ]

        # Lower rank = higher priority when ordering results.
        field_rank = {
            "name": 0,
            "label": 1,
            "prefLabel": 2,
            "altLabel": 3,
            "comment": 4,
        }

        for rdf_type, type_label in type_map:
            for subj in self.graph.subjects(RDF.type, rdf_type):
                if not isinstance(subj, URIRef) or str(subj) in seen:
                    continue
                seen.add(str(subj))
                name = self._local_name(subj)
                label = str(self.graph.value(subj, RDFS.label) or "")
                comment = str(self.graph.value(subj, RDFS.comment) or "")
                pref_label = str(self.graph.value(subj, SKOS.prefLabel) or "")
                alt_labels = [str(o) for o in self.graph.objects(subj, SKOS.altLabel)]

                match_field = None
                if q in name.lower():
                    match_field = "name"
                elif label and q in label.lower():
                    match_field = "label"
                elif pref_label and q in pref_label.lower():
                    match_field = "prefLabel"
                elif any(q in alt.lower() for alt in alt_labels):
                    match_field = "altLabel"
                elif comment and q in comment.lower():
                    match_field = "comment"

                if match_field:
                    results.append(
                        {
                            # Fall back to prefLabel so SKOS concepts (which
                            # rarely carry rdfs:label) still show a label.
                            "name": name,
                            "uri": str(subj),
                            "type": type_label,
                            "label": label or pref_label,
                            "match_field": match_field,
                        }
                    )

        results.sort(
            key=lambda r: (field_rank.get(r["match_field"], 9), r["name"].lower())
        )
        return results

    # ==================== RESOURCE USAGES ====================

    def get_resource_usages(self, name: str) -> dict[str, list[dict[str, str]]]:
        """Find all places a resource is referenced in the graph.

        Returns a dict with:
          - outbound: triples where this resource is the subject (excluding structural type triples)
          - inbound: triples where this resource is the object
          - as_predicate: triples where this resource is used as a predicate
        """
        uri = self._uri(name)

        structural_preds = {
            RDF.type,
            RDFS.subClassOf,
            RDFS.subPropertyOf,
            OWL.equivalentClass,
            OWL.disjointWith,
        }

        outbound: list[dict[str, str]] = []
        for p, o in self.graph.predicate_objects(uri):
            if p in structural_preds:
                continue
            outbound.append(
                {
                    "predicate": self._local_name(p),
                    "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
                    "object_type": "uri" if isinstance(o, URIRef) else "literal",
                }
            )

        inbound: list[dict[str, str]] = []
        for s, p in self.graph.subject_predicates(uri):
            if isinstance(s, BNode):
                continue
            inbound.append(
                {
                    "subject": self._local_name(s) if isinstance(s, URIRef) else str(s),
                    "predicate": self._local_name(p),
                }
            )

        as_predicate: list[dict[str, str]] = []
        for s, o in self.graph.subject_objects(uri):
            as_predicate.append(
                {
                    "subject": self._local_name(s) if isinstance(s, URIRef) else str(s),
                    "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
                }
            )

        return {
            "outbound": outbound,
            "inbound": inbound,
            "as_predicate": as_predicate,
        }

    # ==================== SNAPSHOT & UNDO ====================

    def take_snapshot(self) -> bytes:
        """Capture the current graph state as a compact byte string."""
        return self.graph.serialize(format="nt").encode("utf-8")

    def restore_snapshot(self, snapshot: bytes):
        """Replace the current graph with a previously captured snapshot.

        Snapshots are N-Triples (no prefix bindings), so custom prefixes do not
        survive an undo/redo; reset the explicit-prefix record to match rather
        than leave it pointing at prefixes the restored graph no longer has.
        """
        self._user_added_prefixes = {}
        self.graph = Graph()
        self.graph.parse(data=snapshot.decode("utf-8"), format="nt")
        self._update_namespace_from_graph()

    # ==================== DIFF & COMPARISON ====================

    def compare_graphs(self, other_graph: Graph) -> dict[str, Any]:
        """Compare the current graph against another graph.

        Returns a dict with:
          - added_triples: list of (s, p, o) string tuples present in other but not self
          - removed_triples: list of (s, p, o) string tuples present in self but not other
          - modified_resources: list of dicts grouping changes by subject
          - summary: list of plain-language change descriptions
          - stats: dict with counts (added, removed, modified, unchanged)
        """
        # Compute triple-level diffs using rdflib graph subtraction
        added_set = set(other_graph) - set(self.graph)
        removed_set = set(self.graph) - set(other_graph)

        # Filter out BNode-rooted triples for display (count them separately)
        bnode_added = {t for t in added_set if isinstance(t[0], BNode)}
        bnode_removed = {t for t in removed_set if isinstance(t[0], BNode)}
        named_added = added_set - bnode_added
        named_removed = removed_set - bnode_removed

        # Group changes by subject
        added_by_subj = self._group_triples_by_subject(named_added)
        removed_by_subj = self._group_triples_by_subject(named_removed)

        # Classify each changed subject
        all_subjects = set(added_by_subj.keys()) | set(removed_by_subj.keys())
        modified_resources = []
        counts = {"added": 0, "removed": 0, "modified": 0}

        for subj in sorted(all_subjects):
            change_type = self._classify_resource_change(
                subj, set(added_by_subj.keys()), set(removed_by_subj.keys())
            )
            counts[change_type] = counts.get(change_type, 0) + 1
            modified_resources.append(
                {
                    "name": subj,
                    "change_type": change_type,
                    "added_triples": added_by_subj.get(subj, []),
                    "removed_triples": removed_by_subj.get(subj, []),
                }
            )

        # Build string representations for triple lists
        added_triples = [
            (
                self._local_name(s) if isinstance(s, URIRef) else str(s),
                self._local_name(p),
                self._local_name(o) if isinstance(o, URIRef) else str(o),
            )
            for s, p, o in named_added
        ]
        removed_triples = [
            (
                self._local_name(s) if isinstance(s, URIRef) else str(s),
                self._local_name(p),
                self._local_name(o) if isinstance(o, URIRef) else str(o),
            )
            for s, p, o in named_removed
        ]

        unchanged_count = len(set(self.graph) & set(other_graph))

        diff = {
            "added_triples": sorted(added_triples),
            "removed_triples": sorted(removed_triples),
            "modified_resources": modified_resources,
            "stats": {
                "added": len(named_added),
                "removed": len(named_removed),
                "bnode_added": len(bnode_added),
                "bnode_removed": len(bnode_removed),
                "resources_added": counts["added"],
                "resources_removed": counts["removed"],
                "resources_modified": counts["modified"],
                "unchanged": unchanged_count,
            },
            "summary": [],
        }
        diff["summary"] = self._summarize_changes(diff)
        return diff

    def compare_to_string(self, data: str, format: str = "turtle") -> dict[str, Any]:
        """Parse data into a temporary graph and compare to current state."""
        temp = Graph()
        temp.parse(data=data, format=format)
        return self.compare_graphs(temp)

    def _group_triples_by_subject(self, triples) -> dict[str, list[dict]]:
        """Group a set of triples by subject local name for display."""
        groups: dict[str, list[dict]] = {}
        for s, p, o in triples:
            if isinstance(s, BNode):
                continue
            name = self._local_name(s) if isinstance(s, URIRef) else str(s)
            if name not in groups:
                groups[name] = []
            groups[name].append(
                {
                    "predicate": self._local_name(p),
                    "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
                    "object_type": "uri" if isinstance(o, URIRef) else "literal",
                }
            )
        return groups

    def _classify_resource_change(
        self, subject: str, added_subjects: set[str], removed_subjects: set[str]
    ) -> str:
        """Classify what happened to a resource: 'added', 'removed', or 'modified'."""
        in_added = subject in added_subjects
        in_removed = subject in removed_subjects
        if in_added and not in_removed:
            return "added"
        if in_removed and not in_added:
            return "removed"
        return "modified"

    def _summarize_changes(self, diff: dict[str, Any]) -> list[str]:
        """Generate plain-language summaries for each changed resource."""
        summaries = []

        for res in diff["modified_resources"]:
            name = res["name"]
            change = res["change_type"]

            # Determine the resource type from added or removed triples
            res_type = ""
            all_triples = res["added_triples"] + res["removed_triples"]
            for t in all_triples:
                if t["predicate"] == "type":
                    obj = t["object"]
                    if obj in (
                        "Class",
                        "ObjectProperty",
                        "DatatypeProperty",
                        "NamedIndividual",
                        "Ontology",
                        "AnnotationProperty",
                        "Restriction",
                    ):
                        res_type = obj
                        break

            type_label = {
                "Class": "class",
                "ObjectProperty": "object property",
                "DatatypeProperty": "data property",
                "NamedIndividual": "individual",
                "Ontology": "ontology",
                "AnnotationProperty": "annotation property",
            }.get(res_type, "resource")

            if change == "added":
                label = ""
                for t in res["added_triples"]:
                    if t["predicate"] == "label":
                        label = f' "{t["object"]}"'
                        break
                summaries.append(f"Added {type_label} {name}{label}")
            elif change == "removed":
                summaries.append(f"Removed {type_label} {name}")
            else:
                details = []
                for t in res["added_triples"]:
                    if t["predicate"] != "type":
                        details.append(f"added {t['predicate']} = {t['object']}")
                for t in res["removed_triples"]:
                    if t["predicate"] != "type":
                        details.append(f"removed {t['predicate']} = {t['object']}")
                detail_str = "; ".join(details[:3])
                if len(details) > 3:
                    detail_str += f" (+{len(details) - 3} more)"
                summaries.append(f"Modified {type_label} {name}: {detail_str}")

        # Add BNode summary if any
        stats = diff["stats"]
        bnode_total = stats["bnode_added"] + stats["bnode_removed"]
        if bnode_total > 0:
            summaries.append(
                f"{stats['bnode_added']} anonymous node triples added, "
                f"{stats['bnode_removed']} removed (restrictions/expressions)"
            )

        return summaries

    def format_diff_report(
        self, diff: dict[str, Any], report_format: str = "markdown"
    ) -> str:
        """Format a diff result as a human-readable report."""
        stats = diff["stats"]
        lines = []

        if report_format == "markdown":
            lines.append("# Ontology Change Report\n")
            lines.append("## Summary\n")
            lines.append(
                f"- **Added:** {stats['added']} triples across "
                f"{stats['resources_added']} resources"
            )
            lines.append(
                f"- **Removed:** {stats['removed']} triples across "
                f"{stats['resources_removed']} resources"
            )
            lines.append(f"- **Modified:** {stats['resources_modified']} resources")
            lines.append(f"- **Unchanged:** {stats['unchanged']} triples")
            if stats["bnode_added"] or stats["bnode_removed"]:
                lines.append(
                    f"- **Anonymous nodes:** {stats['bnode_added']} added, "
                    f"{stats['bnode_removed']} removed"
                )
            lines.append("")

            # Group resources by change type
            for change_type, heading in [
                ("added", "Added Resources"),
                ("removed", "Removed Resources"),
                ("modified", "Modified Resources"),
            ]:
                resources = [
                    r
                    for r in diff["modified_resources"]
                    if r["change_type"] == change_type
                ]
                if resources:
                    lines.append(f"## {heading}\n")
                    for res in resources:
                        lines.append(f"### {res['name']}\n")
                        for t in res["added_triples"]:
                            lines.append(f"- + {t['predicate']}: {t['object']}")
                        for t in res["removed_triples"]:
                            lines.append(f"- - {t['predicate']}: {t['object']}")
                        lines.append("")
        else:
            # Plain text format
            lines.append("Ontology Change Report")
            lines.append("=" * 40)
            lines.append(
                f"Added: {stats['added']} triples, "
                f"Removed: {stats['removed']} triples, "
                f"Modified: {stats['resources_modified']} resources"
            )
            lines.append("")
            for line in diff["summary"]:
                lines.append(f"  {line}")

        return "\n".join(lines)

    # ==================== VALIDATION & REASONING ====================

    def validate(self, check_missing_domain_range: bool = True) -> list[dict[str, str]]:
        """Validate the ontology and return issues."""
        issues = []
        # ``pred`` is reused across loops that bind it to both predicate URIRefs
        # and arbitrary graph terms; declare the broader rdflib type up front.
        pred: Node

        # Check for classes without labels
        for class_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, BNode):
                continue
            if not self.graph.value(class_uri, RDFS.label) and not self.graph.value(
                class_uri, SKOS.prefLabel
            ):
                issues.append(
                    {
                        "severity": "warning",
                        "type": "missing_label",
                        "subject": self._local_name(class_uri),
                        "message": f"Class '{self._local_name(class_uri)}' has no label (rdfs:label or skos:prefLabel)",
                    }
                )

        # Check for properties without domain/range
        # Also accept schema:domainIncludes / gist:domainIncludes (and rangeIncludes)
        def _has_domain(uri):
            if self.graph.value(uri, RDFS.domain):
                return True
            return any(self.graph.value(uri, p) for p in _DOMAIN_INCLUDES)

        def _has_range(uri):
            if self.graph.value(uri, RDFS.range):
                return True
            return any(self.graph.value(uri, p) for p in _RANGE_INCLUDES)

        if check_missing_domain_range:
            for prop_uri in self.graph.subjects(RDF.type, OWL.ObjectProperty):
                if isinstance(prop_uri, BNode):
                    continue
                if not _has_domain(prop_uri):
                    issues.append(
                        {
                            "severity": "info",
                            "type": "missing_domain",
                            "subject": self._local_name(prop_uri),
                            "message": f"Object property '{self._local_name(prop_uri)}' has no domain",
                        }
                    )
                if not _has_range(prop_uri):
                    issues.append(
                        {
                            "severity": "info",
                            "type": "missing_range",
                            "subject": self._local_name(prop_uri),
                            "message": f"Object property '{self._local_name(prop_uri)}' has no range",
                        }
                    )

            for prop_uri in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
                if isinstance(prop_uri, BNode):
                    continue
                if not _has_domain(prop_uri):
                    issues.append(
                        {
                            "severity": "info",
                            "type": "missing_domain",
                            "subject": self._local_name(prop_uri),
                            "message": f"Data property '{self._local_name(prop_uri)}' has no domain",
                        }
                    )

        # Check for orphan classes (no parent, no children, not used)
        all_classes = set()
        used_classes = set()

        for class_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, URIRef):
                all_classes.add(str(class_uri))

        # Classes used as domain/range (including domainIncludes/rangeIncludes)
        _all_domain_preds = (RDFS.domain,) + _DOMAIN_INCLUDES
        _all_range_preds = (RDFS.range,) + _RANGE_INCLUDES

        for prop in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            for pred in _all_domain_preds:
                for val in self.graph.objects(prop, pred):
                    if isinstance(val, URIRef):
                        used_classes.add(str(val))
            for pred in _all_range_preds:
                for val in self.graph.objects(prop, pred):
                    if isinstance(val, URIRef):
                        used_classes.add(str(val))

        for prop in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            for pred in _all_domain_preds:
                for val in self.graph.objects(prop, pred):
                    if isinstance(val, URIRef):
                        used_classes.add(str(val))

        # Classes with instances
        for ind in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            for cls in self.graph.objects(ind, RDF.type):
                if isinstance(cls, URIRef):
                    used_classes.add(str(cls))

        # Classes in hierarchy
        for cls in self.graph.subjects(RDFS.subClassOf, None):
            if isinstance(cls, URIRef):
                used_classes.add(str(cls))
        for cls in self.graph.objects(None, RDFS.subClassOf):
            if isinstance(cls, URIRef):
                used_classes.add(str(cls))

        # Classes referenced in restrictions (someValuesFrom, allValuesFrom, etc.)
        for restriction_pred in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue):
            for obj in self.graph.objects(None, restriction_pred):
                if isinstance(obj, URIRef):
                    used_classes.add(str(obj))

        # Classes in class expressions (unionOf, intersectionOf, complementOf)
        for expr_pred in (OWL.equivalentClass, OWL.disjointWith):
            for s in self.graph.subjects(expr_pred, None):
                if isinstance(s, URIRef):
                    used_classes.add(str(s))
            for o in self.graph.objects(None, expr_pred):
                if isinstance(o, URIRef):
                    used_classes.add(str(o))

        # Report orphan classes
        orphan_classes = all_classes - used_classes
        for orphan_uri in orphan_classes:
            name = self._local_name(URIRef(orphan_uri))
            issues.append(
                {
                    "severity": "info",
                    "type": "orphan_class",
                    "subject": name,
                    "message": f"Class '{name}' is not used in any hierarchy, property domain/range, restriction, or instance typing",
                }
            )

        # Check individuals have at least one class
        for ind_uri in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            classes = [
                c
                for c in self.graph.objects(ind_uri, RDF.type)
                if c != OWL.NamedIndividual
            ]
            if not classes:
                issues.append(
                    {
                        "severity": "warning",
                        "type": "untyped_individual",
                        "subject": self._local_name(ind_uri),
                        "message": f"Individual '{self._local_name(ind_uri)}' has no class type",
                    }
                )

        # Check domain/range usage for property assertions on individuals
        def _expand_superclasses(class_uris: set[str]) -> set[str]:
            """Expand a set of class URIs to include all superclasses."""
            expanded = set(class_uris)
            frontier = list(class_uris)
            while frontier:
                cls = frontier.pop()
                for parent in self.graph.objects(URIRef(cls), RDFS.subClassOf):
                    if isinstance(parent, URIRef):
                        parent_str = str(parent)
                        if parent_str not in expanded:
                            expanded.add(parent_str)
                            frontier.append(parent_str)
            return expanded

        for ind_uri in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            if not isinstance(ind_uri, URIRef):
                continue
            ind_name = self._local_name(ind_uri)
            ind_direct_classes = {
                str(c)
                for c in self.graph.objects(ind_uri, RDF.type)
                if isinstance(c, URIRef) and c != OWL.NamedIndividual
            }
            ind_all_classes = _expand_superclasses(ind_direct_classes)

            for pred, obj in self.graph.predicate_objects(ind_uri):
                if pred == RDF.type or isinstance(pred, BNode):
                    continue

                # Check object properties
                if (pred, RDF.type, OWL.ObjectProperty) in self.graph:
                    domain = self.graph.value(pred, RDFS.domain)
                    if (
                        domain
                        and isinstance(domain, URIRef)
                        and str(domain) not in ind_all_classes
                    ):
                        issues.append(
                            {
                                "severity": "warning",
                                "type": "domain_mismatch",
                                "subject": ind_name,
                                "message": f"Individual '{ind_name}' uses property '{self._local_name(pred)}' but is not typed as '{self._local_name(domain)}'",
                            }
                        )

                    range_ = self.graph.value(pred, RDFS.range)
                    if (
                        range_
                        and isinstance(range_, URIRef)
                        and isinstance(obj, URIRef)
                    ):
                        obj_direct = {
                            str(c)
                            for c in self.graph.objects(obj, RDF.type)
                            if isinstance(c, URIRef) and c != OWL.NamedIndividual
                        }
                        obj_all_classes = _expand_superclasses(obj_direct)
                        if str(range_) not in obj_all_classes:
                            issues.append(
                                {
                                    "severity": "warning",
                                    "type": "range_mismatch",
                                    "subject": ind_name,
                                    "message": f"Property '{self._local_name(pred)}' on '{ind_name}' expects range '{self._local_name(range_)}' but '{self._local_name(obj)}' is not typed as such",
                                }
                            )

                # Check data properties
                elif (pred, RDF.type, OWL.DatatypeProperty) in self.graph:
                    domain = self.graph.value(pred, RDFS.domain)
                    if (
                        domain
                        and isinstance(domain, URIRef)
                        and str(domain) not in ind_all_classes
                    ):
                        issues.append(
                            {
                                "severity": "warning",
                                "type": "domain_mismatch",
                                "subject": ind_name,
                                "message": f"Individual '{ind_name}' uses data property '{self._local_name(pred)}' but is not typed as '{self._local_name(domain)}'",
                            }
                        )

        # Names carrying more than one entity type (issue #279). Legal OWL 2
        # punning, but in this app that one resource is listed as, say, both a
        # class and an individual, and deleting either listing deletes the whole
        # resource. The create flows refuse to make this; a loaded ontology can
        # still arrive with it, so say so instead of letting it look like two
        # entities that happen to share a name.
        for subj in set(self.graph.subjects(RDF.type, None)):
            if not isinstance(subj, URIRef):
                continue
            kinds = self.entity_kinds(str(subj))
            if len(kinds) > 1:
                name = self._local_name(subj)
                issues.append(
                    {
                        "severity": "warning",
                        "type": "punned_name",
                        "subject": name,
                        "message": f"'{name}' is defined as {' and '.join(_with_article(k) for k in kinds)} at once: one resource listed in both places, so deleting either listing deletes all of it",
                    }
                )

        # Check for duplicate rdfs:label values across resources
        from collections import defaultdict

        label_to_resources: dict[str, list[str]] = defaultdict(list)
        for subj, label_val in self.graph.subject_objects(RDFS.label):
            if isinstance(subj, URIRef) and isinstance(label_val, Literal):
                label_str = str(label_val)
                name = self._local_name(subj)
                label_to_resources[label_str].append(name)
        for label_str, resources in label_to_resources.items():
            if len(resources) > 1:
                issues.append(
                    {
                        "severity": "warning",
                        "type": "duplicate_label",
                        "subject": ", ".join(sorted(resources)),
                        "message": f"Duplicate label '{label_str}' shared by: {', '.join(sorted(resources))}",
                    }
                )

        # External references: links whose target is defined in another ontology
        # that has not been imported (issue #87 part B). Editing an entity to a
        # custom URI or adding a cross-ontology relation (equivalentClass,
        # sameAs, ...) is intentional and cannot be validated here, so surface
        # each such target as info rather than silently leaving it unresolvable.
        # A target that is a subject in this graph is defined here (or was
        # imported) and is not external. Pure-syntax and core-vocabulary
        # namespaces are always known: SKOS is included so scanning rdf:type
        # does not flag skos:Concept / skos:ConceptScheme (which every SKOS
        # ontology references) as unresolved external links.
        _syntax_ns = (str(OWL), str(RDF), str(RDFS), str(XSD), str(SKOS))
        _link_preds = (
            (
                RDFS.subClassOf,
                OWL.equivalentClass,
                OWL.disjointWith,
                RDFS.subPropertyOf,
                OWL.equivalentProperty,
                OWL.inverseOf,
                OWL.propertyDisjointWith,
                OWL.sameAs,
                OWL.differentFrom,
                RDFS.domain,
                RDFS.range,
                RDF.type,
            )
            + _DOMAIN_INCLUDES
            + _RANGE_INCLUDES
        )
        defined = set(self.graph.subjects())
        external: dict[str, str] = {}
        for pred in _link_preds:
            for _subj, obj in self.graph.subject_objects(pred):
                if not isinstance(obj, URIRef) or obj in defined:
                    continue
                obj_str = str(obj)
                if any(obj_str.startswith(ns) for ns in _syntax_ns):
                    continue
                external.setdefault(obj_str, self._local_name(obj))
        for uri, name in sorted(external.items()):
            issues.append(
                {
                    "severity": "info",
                    "type": "external_reference",
                    "subject": name,
                    "message": f"'{name}' ({uri}) is referenced but not defined in "
                    "this ontology (external link). Import its ontology to "
                    "validate it fully.",
                }
            )

        return issues

    def apply_reasoning(self, profile: str = "rdfs") -> int:
        """Apply reasoning to infer new triples."""
        initial_count = len(self.graph)

        if profile == "rdfs":
            owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(self.graph)
        elif profile == "owl-rl":
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.graph)
        elif profile == "owl-rl-ext":
            owlrl.DeductiveClosure(owlrl.OWLRL_Extension).expand(self.graph)

        return len(self.graph) - initial_count

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, int]:
        """Get ontology statistics."""
        # Count ontology metadata triples (declaration + metadata)
        ontology_meta_count = len(list(self.graph.predicate_objects(self.ontology_uri)))

        stats = {
            "classes": 0,
            "object_properties": 0,
            "data_properties": 0,
            "individuals": 0,
            "restrictions": 0,
            "total_triples": len(self.graph),
            "content_triples": len(self.graph) - ontology_meta_count,
        }

        for _ in self.graph.subjects(RDF.type, OWL.Class):
            stats["classes"] += 1

        for _ in self.graph.subjects(RDF.type, OWL.ObjectProperty):
            stats["object_properties"] += 1

        for _ in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            stats["data_properties"] += 1

        for _ in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            stats["individuals"] += 1

        for _ in self.graph.subjects(RDF.type, OWL.Restriction):
            stats["restrictions"] += 1

        stats["concept_schemes"] = sum(
            1 for _ in self.graph.subjects(RDF.type, SKOS.ConceptScheme)
        )
        stats["concepts"] = sum(1 for _ in self.graph.subjects(RDF.type, SKOS.Concept))

        return stats


class UndoManager:
    """Manages an undo/redo history stack for an OntologyManager instance.

    Usage:
        undo_mgr = UndoManager(ontology_manager, max_history=50)
        undo_mgr.checkpoint("Added class Person")   # before or after a mutation
        undo_mgr.undo()
        undo_mgr.redo()
    """

    def __init__(self, manager: OntologyManager, max_history: int = 50):
        self.manager = manager
        self.max_history = max_history
        self._undo_stack: list[tuple[str, bytes]] = []  # (label, snapshot)
        self._redo_stack: list[tuple[str, bytes]] = []
        # Capture initial state
        self._undo_stack.append(("Initial state", manager.take_snapshot()))

    def checkpoint(self, label: str = "Edit"):
        """Save current state to the undo stack. Call after each mutation."""
        snapshot = self.manager.take_snapshot()
        self._undo_stack.append((label, snapshot))
        if len(self._undo_stack) > self.max_history:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 1

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self) -> str | None:
        """Undo the last change. Returns the label of the restored state, or None."""
        if not self.can_undo():
            return None
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        label, snapshot = self._undo_stack[-1]
        self.manager.restore_snapshot(snapshot)
        return label

    def redo(self) -> str | None:
        """Redo the last undone change. Returns the label, or None."""
        if not self.can_redo():
            return None
        label, snapshot = self._redo_stack.pop()
        self._undo_stack.append((label, snapshot))
        self.manager.restore_snapshot(snapshot)
        return label

    @property
    def undo_labels(self) -> list[str]:
        """Labels in the undo stack (most recent last), excluding the bottom."""
        return [label for label, _ in self._undo_stack[1:]]

    @property
    def redo_labels(self) -> list[str]:
        """Labels in the redo stack (next redo last)."""
        return [label for label, _ in self._redo_stack]

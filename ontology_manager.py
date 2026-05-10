"""
OntologyManager - Core class for managing OWL ontologies using rdflib.
"""

from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, SKOS, DC, DCTERMS
from rdflib.collection import Collection
from typing import Optional, List, Dict, Tuple, Any, Set
import owlrl

_UNSET = object()  # sentinel: "parameter not provided"

# domainIncludes/rangeIncludes from Schema.org and gist
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
    XSD_DATATYPES = {
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
    RESTRICTION_TYPES = {
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

        # Bind common prefixes
        self.graph.bind("owl", OWL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("xsd", XSD)
        self.graph.bind("skos", SKOS)
        self.graph.bind("dc", DC)
        self.graph.bind("dcterms", DCTERMS)
        self.graph.bind("", self.namespace)

        # Create ontology declaration
        self.ontology_uri = URIRef(base_uri.rstrip("#").rstrip("/"))
        self.graph.add((self.ontology_uri, RDF.type, OWL.Ontology))

    def set_ontology_metadata(self, label=_UNSET, comment=_UNSET,
                              creator=_UNSET, version_iri=_UNSET):
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

    def get_imports(self) -> List[str]:
        """Get all owl:imports URIs."""
        return [str(o) for o in self.graph.objects(self.ontology_uri, OWL.imports)]

    # Standard prefixes that cannot be removed
    STANDARD_PREFIXES = {"owl", "rdf", "rdfs", "xsd", "skos", "dc", "dcterms"}

    def get_prefixes(self) -> List[Dict[str, str]]:
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
        if hasattr(self, '_loaded_prefixes') and self._loaded_prefixes:
            for p in self._loaded_prefixes:
                if p["prefix"] not in seen:
                    seen.add(p["prefix"])
                    prefixes.append(p)
        # Ensure at least the default namespace
        if "(default)" not in seen:
            prefixes.append({"prefix": "(default)", "namespace": self.base_uri})
        prefixes.sort(key=lambda x: ("" if x["prefix"] == "(default)" else x["prefix"]))
        return prefixes

    def get_all_prefixes(self) -> List[Dict[str, str]]:
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
            prefixes.append({
                "prefix": display,
                "namespace": str(ns),
                "source": source,
            })
        prefixes.sort(key=lambda x: ("" if x["prefix"] == "(default)" else x["prefix"]))
        return prefixes

    def add_prefix(self, prefix: str, namespace: str):
        """Bind a custom prefix to a namespace URI in the graph."""
        self.graph.bind(prefix, Namespace(namespace), override=True)

    def remove_prefix(self, prefix: str):
        """Remove a custom prefix binding. Standard prefixes cannot be removed."""
        if prefix in self.STANDARD_PREFIXES:
            raise ValueError(f"Cannot remove standard prefix '{prefix}'")
        # rdflib NamespaceManager doesn't support unbinding directly.
        # Rebuild the namespace manager by creating a new graph with the same triples.
        keep = [(p, ns) for p, ns in self.graph.namespaces() if p != prefix]
        new_graph = Graph()
        for s, p_triple, o in self.graph:
            new_graph.add((s, p_triple, o))
        for p, ns in keep:
            new_graph.bind(p, ns, override=True)
        self.graph = new_graph

    def _extract_prefixes_from_ttl(self, data: str) -> List[Dict[str, str]]:
        """Extract @prefix declarations from TTL content."""
        import re
        prefixes = []
        # Match @prefix declarations: @prefix name: <uri> .
        pattern = r'@prefix\s+([a-zA-Z0-9_-]*)\s*:\s*<([^>]+)>\s*\.'
        for match in re.finditer(pattern, data):
            prefix = match.group(1)
            namespace = match.group(2)
            prefixes.append({
                "prefix": prefix if prefix else "(default)",
                "namespace": namespace
            })
        # Sort by prefix name, with default first
        prefixes.sort(key=lambda x: ("" if x["prefix"] == "(default)" else x["prefix"]))
        return prefixes

    def _extract_prefixes_from_jsonld(self, data: str) -> List[Dict[str, str]]:
        """Extract prefix declarations from JSON-LD @context."""
        import json
        prefixes = []
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
                if isinstance(value, str) and (value.startswith("http://") or
                                                value.startswith("https://")):
                    prefixes.append({
                        "prefix": key if key else "(default)",
                        "namespace": value,
                    })
        prefixes.sort(key=lambda x: ("" if x["prefix"] == "(default)" else x["prefix"]))
        return prefixes

    def get_ontology_metadata(self) -> Dict[str, str]:
        """Get ontology-level metadata."""
        metadata = {}
        for pred, key in [(RDFS.label, "label"), (RDFS.comment, "comment"),
                          (DCTERMS.creator, "creator"), (OWL.versionIRI, "version_iri")]:
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
                    local_name = str(s)[len(old_base_uri):]
                    new_s = URIRef(new_base_uri + local_name)
                if isinstance(o, URIRef) and str(o).startswith(old_base_uri):
                    local_name = str(o)[len(old_base_uri):]
                    new_o = URIRef(new_base_uri + local_name)
                if new_s != s or new_o != o:
                    updates.append(((s, p, o), (new_s, p, new_o)))

            for old_triple, new_triple in updates:
                self.graph.remove(old_triple)
                self.graph.add(new_triple)

        # Re-bind the default namespace
        self.graph.bind("", self.namespace)

    def _uri(self, local_name: str) -> URIRef:
        """Create a URI from a local name."""
        if local_name.startswith("http://") or local_name.startswith("https://"):
            return URIRef(local_name)
        return self.namespace[local_name]

    def _local_name(self, uri: URIRef) -> str:
        """Extract local name from a URI."""
        uri_str = str(uri)
        if "#" in uri_str:
            return uri_str.split("#")[-1]
        return uri_str.split("/")[-1]

    # ==================== CLASS OPERATIONS ====================

    def add_class(self, name: str, parent: str = None, label: str = None,
                  comment: str = None) -> URIRef:
        """Add a new OWL class."""
        class_uri = self._uri(name)
        self.graph.add((class_uri, RDF.type, OWL.Class))

        if parent:
            parent_uri = self._uri(parent)
            self.graph.add((class_uri, RDFS.subClassOf, parent_uri))

        if label:
            self.graph.add((class_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((class_uri, RDFS.comment, Literal(comment)))

        return class_uri

    def update_class(self, name: str, new_label: str = None, new_comment: str = None,
                     new_parent: str = None, remove_parent: str = None):
        """Update an existing class."""
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

    def rename_class(self, old_name: str, new_name: str) -> bool:
        """Rename a class, updating all references."""
        if old_name == new_name:
            return True

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name)

        # Check if new name already exists
        if (new_uri, RDF.type, OWL.Class) in self.graph:
            return False

        # Collect all triples to update
        updates = []

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

    def get_delete_impact(self, name: str, resource_type: str = "class") -> Dict[str, Any]:
        """Analyse the impact of deleting a resource before executing it.

        Args:
            name: local name or full URI of the resource
            resource_type: one of "class", "property", "individual"

        Returns a dict with categorised impact counts and details.
        """
        uri = self._uri(name)
        impact: Dict[str, Any] = {
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
        }

        if resource_type == "class":
            # Subclasses that reference this class as parent
            for child in self.graph.subjects(RDFS.subClassOf, uri):
                if isinstance(child, URIRef):
                    impact["subclasses"].append(self._local_name(child))

            # Instances typed with this class
            for ind in self.graph.subjects(RDF.type, uri):
                if isinstance(ind, URIRef) and (ind, RDF.type, OWL.NamedIndividual) in self.graph:
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

        elif resource_type == "concept":
            # SKOS relations referencing this concept
            for s, p in self.graph.subject_predicates(uri):
                if isinstance(s, URIRef) and p not in (RDF.type,):
                    impact["relations"].append(
                        f"{self._local_name(s)} {self._local_name(p)}"
                    )

        # Count direct triples (subject) and referencing triples (object)
        impact["direct_triples"] = len(list(self.graph.predicate_objects(uri)))

        # Count annotations (literal-valued predicates on this resource)
        structural = {RDF.type, RDFS.subClassOf, RDFS.subPropertyOf,
                      RDFS.domain, RDFS.range, OWL.equivalentClass,
                      OWL.disjointWith, OWL.inverseOf}
        for p, o in self.graph.predicate_objects(uri):
            if p not in structural and isinstance(o, Literal):
                impact["annotations"] += 1

        # Total affected triples (as subject + as object + as predicate for properties)
        ref_count = len(list(self.graph.subject_predicates(uri)))
        pred_count = len(list(self.graph.subject_objects(uri))) if resource_type == "property" else 0
        impact["total_triples"] = impact["direct_triples"] + ref_count + pred_count

        return impact

    def format_delete_impact(self, impact: Dict[str, Any]) -> str:
        """Format an impact dict into a human-readable summary string."""
        parts = []
        rt = impact["resource_type"]
        parts.append(f"Deleting {rt} **{impact['resource']}** will remove {impact['total_triples']} triple(s).")

        if impact["subclasses"]:
            parts.append(f"- {len(impact['subclasses'])} subclass link(s) lost: {', '.join(impact['subclasses'])}")
        if impact["instances"]:
            parts.append(f"- {len(impact['instances'])} instance(s) lose their class type: {', '.join(impact['instances'])}")
        if impact["domain_of"]:
            parts.append(f"- {len(impact['domain_of'])} property domain reference(s) lost: {', '.join(impact['domain_of'])}")
        if impact["range_of"]:
            parts.append(f"- {len(impact['range_of'])} property range reference(s) lost: {', '.join(impact['range_of'])}")
        if impact["annotations"]:
            parts.append(f"- {impact['annotations']} annotation(s) removed")
        if impact["property_assertions"]:
            parts.append(f"- {len(impact['property_assertions'])} property assertion(s) removed")
        if impact["relations"]:
            parts.append(f"- {len(impact['relations'])} inbound relation(s) removed")

        return "\n".join(parts)

    def delete_class(self, name: str):
        """Delete a class and all its references."""
        class_uri = self._uri(name)
        # Remove all triples where this class is subject or object
        self.graph.remove((class_uri, None, None))
        self.graph.remove((None, None, class_uri))

    def get_classes(self) -> List[Dict[str, Any]]:
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

            class_info = {
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

    def get_class_hierarchy(self) -> Dict[str, List[str]]:
        """Get class hierarchy as adjacency list."""
        hierarchy = {}
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
    def parse_bulk_text(text: str, columns: List[str] = None) -> List[Dict[str, str]]:
        """Parse multi-line text into list of dicts.

        Supports:
        - Simple mode: one name per line (returns dicts with 'name' key)
        - CSV mode: comma-separated values with column headers

        If columns are provided, each line is split by comma and mapped to columns.
        If columns are not provided but the first line looks like a header
        (contains 'name'), it's used as columns.
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines:
            return []

        # Auto-detect CSV header
        if columns is None and "," in lines[0]:
            header = [c.strip().lower() for c in lines[0].split(",")]
            if "name" in header:
                columns = header
                lines = lines[1:]

        if columns:
            result = []
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                entry = {}
                for i, col in enumerate(columns):
                    entry[col] = parts[i] if i < len(parts) else ""
                if entry.get("name"):
                    result.append(entry)
            return result

        # Simple mode: one name per line
        return [{"name": line} for line in lines]

    def bulk_add_classes(self, entries: List[Dict[str, str]]) -> Dict[str, Any]:
        """Batch create classes.

        Each entry dict can have: name, label, parent.
        Returns {created: [], errors: [], skipped: []}.
        """
        result: Dict[str, Any] = {"created": [], "errors": [], "skipped": []}
        existing = {c["name"] for c in self.get_classes()}

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            if name in existing:
                result["skipped"].append(name)
                continue
            try:
                self.add_class(
                    name,
                    parent=entry.get("parent", "").strip() or None,
                    label=entry.get("label", "").strip() or None,
                )
                result["created"].append(name)
                existing.add(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})

        return result

    def bulk_add_properties(self, entries: List[Dict[str, str]],
                            property_type: str = "object") -> Dict[str, Any]:
        """Batch create properties.

        Each entry dict can have: name, domain, range, label.
        property_type: "object" or "data".
        Returns {created: [], errors: [], skipped: []}.
        """
        result: Dict[str, Any] = {"created": [], "errors": [], "skipped": []}
        if property_type == "object":
            existing = {p["name"] for p in self.get_object_properties()}
        else:
            existing = {p["name"] for p in self.get_data_properties()}

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            if name in existing:
                result["skipped"].append(name)
                continue
            try:
                domain = entry.get("domain", "").strip() or None
                range_ = entry.get("range", "").strip() or None
                label = entry.get("label", "").strip() or None
                if property_type == "object":
                    self.add_object_property(name, domain=domain, range_=range_, label=label)
                else:
                    self.add_data_property(name, domain=domain, range_=range_ or "string", label=label)
                result["created"].append(name)
                existing.add(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})

        return result

    def bulk_add_individuals(self, entries: List[Dict[str, str]]) -> Dict[str, Any]:
        """Batch create individuals.

        Each entry dict can have: name, class, label.
        Returns {created: [], errors: [], skipped: []}.
        """
        result: Dict[str, Any] = {"created": [], "errors": [], "skipped": []}
        existing = {i["name"] for i in self.get_individuals()}

        for entry in entries:
            name = entry.get("name", "").strip()
            if not name:
                result["errors"].append({"name": "", "error": "Empty name"})
                continue
            class_name = entry.get("class", "").strip()
            if not class_name:
                result["errors"].append({"name": name, "error": "Missing class"})
                continue
            if name in existing:
                result["skipped"].append(name)
                continue
            try:
                self.add_individual(
                    name,
                    class_name=class_name,
                    label=entry.get("label", "").strip() or None,
                )
                result["created"].append(name)
                existing.add(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})

        return result

    def bulk_delete_classes(self, names: List[str]) -> Dict[str, Any]:
        """Batch delete classes. Returns {deleted: [], errors: []}."""
        result: Dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_class(name)
                result["deleted"].append(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_delete_properties(self, names: List[str]) -> Dict[str, Any]:
        """Batch delete properties. Returns {deleted: [], errors: []}."""
        result: Dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_property(name)
                result["deleted"].append(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_delete_individuals(self, names: List[str]) -> Dict[str, Any]:
        """Batch delete individuals. Returns {deleted: [], errors: []}."""
        result: Dict[str, Any] = {"deleted": [], "errors": []}
        for name in names:
            try:
                self.delete_individual(name)
                result["deleted"].append(name)
            except Exception as e:
                result["errors"].append({"name": name, "error": str(e)})
        return result

    def bulk_update_annotations(self, updates: List[Dict[str, str]]) -> Dict[str, Any]:
        """Apply batch annotation changes.

        Each update dict has: resource, predicate, value, lang (optional),
        and action ("add" or "delete"). If action is omitted, defaults to "add".
        Returns {applied: int, errors: []}.
        """
        result: Dict[str, Any] = {"applied": 0, "errors": []}

        for update in updates:
            resource = update.get("resource", "").strip()
            predicate = update.get("predicate", "").strip()
            value = update.get("value", "").strip()
            lang = update.get("lang", "").strip() or None
            action = update.get("action", "add").strip().lower()

            if not resource or not predicate:
                result["errors"].append({
                    "resource": resource,
                    "error": "Missing resource or predicate",
                })
                continue

            try:
                if action == "delete":
                    self.delete_annotation(resource, predicate, value=value or None, lang=lang)
                else:
                    if not value:
                        result["errors"].append({
                            "resource": resource,
                            "error": "Missing value for add",
                        })
                        continue
                    self.add_annotation(resource, predicate, value, lang=lang)
                result["applied"] += 1
            except Exception as e:
                result["errors"].append({
                    "resource": resource,
                    "error": str(e),
                })

        return result

    # ==================== PROPERTY OPERATIONS ====================

    def add_object_property(self, name: str, domain: str = None, range_: str = None,
                            label: str = None, comment: str = None,
                            functional: bool = False, inverse_functional: bool = False,
                            transitive: bool = False, symmetric: bool = False,
                            asymmetric: bool = False, reflexive: bool = False,
                            irreflexive: bool = False, inverse_of: str = None) -> URIRef:
        """Add a new object property."""
        prop_uri = self._uri(name)
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

    def add_data_property(self, name: str, domain: str = None, range_: str = "string",
                          label: str = None, comment: str = None,
                          functional: bool = False) -> URIRef:
        """Add a new data property."""
        prop_uri = self._uri(name)
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

    def update_property(self, name: str, new_label: str = None, new_comment: str = None,
                        new_domain: str = None, new_range: str = None):
        """Update an existing property."""
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
                    self.graph.add((prop_uri, RDFS.range, self.XSD_DATATYPES[new_range]))
                else:
                    self.graph.add((prop_uri, RDFS.range, self._uri(new_range)))

    def rename_property(self, old_name: str, new_name: str) -> bool:
        """Rename a property, updating all references."""
        if old_name == new_name:
            return True

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name)

        # Check if new name already exists
        if (new_uri, RDF.type, OWL.ObjectProperty) in self.graph or \
           (new_uri, RDF.type, OWL.DatatypeProperty) in self.graph:
            return False

        # Collect all triples to update
        updates = []

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

    def delete_property(self, name: str):
        """Delete a property and all its references."""
        prop_uri = self._uri(name)
        self.graph.remove((prop_uri, None, None))
        self.graph.remove((None, None, prop_uri))
        self.graph.remove((None, prop_uri, None))

    def get_object_properties(self) -> List[Dict[str, Any]]:
        """Get all object properties with their details."""
        properties = []
        for prop_uri in self.graph.subjects(RDF.type, OWL.ObjectProperty):
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
                "range_uri": "",
                "characteristics": []
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

    def get_data_properties(self) -> List[Dict[str, Any]]:
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
                "functional": False
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

            prop_info["functional"] = (prop_uri, RDF.type, OWL.FunctionalProperty) in self.graph

            properties.append(prop_info)

        return sorted(properties, key=lambda x: x["name"])

    # ==================== INDIVIDUAL OPERATIONS ====================

    def add_individual(self, name: str, class_name: str, label: str = None,
                       comment: str = None) -> URIRef:
        """Add a new individual (instance)."""
        ind_uri = self._uri(name)
        class_uri = self._uri(class_name)

        self.graph.add((ind_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((ind_uri, RDF.type, class_uri))

        if label:
            self.graph.add((ind_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((ind_uri, RDFS.comment, Literal(comment)))

        return ind_uri

    def add_individual_property(self, individual: str, property_name: str, value: Any,
                                is_object_property: bool = True):
        """Add a property assertion to an individual."""
        ind_uri = self._uri(individual)
        prop_uri = self._uri(property_name)

        if is_object_property:
            value_uri = self._uri(value)
            self.graph.add((ind_uri, prop_uri, value_uri))
        else:
            self.graph.add((ind_uri, prop_uri, Literal(value)))

    def update_individual(self, name: str, new_label: str = None, new_comment: str = None,
                          add_class: str = None, remove_class: str = None):
        """Update an existing individual."""
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
        """Rename an individual, updating all references."""
        if old_name == new_name:
            return True

        old_uri = self._uri(old_name)
        new_uri = self._uri(new_name)

        # Check if new name already exists
        if (new_uri, RDF.type, OWL.NamedIndividual) in self.graph:
            return False

        # Collect all triples to update
        updates = []

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

    def get_individuals(self) -> List[Dict[str, Any]]:
        """Get all individuals with their details."""
        individuals = []
        seen = set()

        for ind_uri in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            if isinstance(ind_uri, BNode) or str(ind_uri) in seen:
                continue
            seen.add(str(ind_uri))

            ind_info = {
                "uri": str(ind_uri),
                "name": self._local_name(ind_uri),
                "label": str(self.graph.value(ind_uri, RDFS.label) or ""),
                "comment": str(self.graph.value(ind_uri, RDFS.comment) or ""),
                "classes": [],
                "properties": []
            }

            # Get classes
            for class_uri in self.graph.objects(ind_uri, RDF.type):
                if isinstance(class_uri, URIRef) and class_uri != OWL.NamedIndividual:
                    ind_info["classes"].append(self._local_name(class_uri))

            # Get property assertions
            for pred, obj in self.graph.predicate_objects(ind_uri):
                if pred not in [RDF.type, RDFS.label, RDFS.comment]:
                    prop_name = self._local_name(pred)
                    if isinstance(obj, URIRef):
                        value = self._local_name(obj)
                    else:
                        value = str(obj)
                    ind_info["properties"].append({"property": prop_name, "value": value})

            individuals.append(ind_info)

        return sorted(individuals, key=lambda x: x["name"])

    # ==================== RESTRICTION OPERATIONS ====================

    def add_restriction(self, class_name: str, property_name: str, restriction_type: str,
                        value: Any, on_class: str = None) -> BNode:
        """Add a restriction to a class."""
        class_uri = self._uri(class_name)
        prop_uri = self._uri(property_name)

        restriction = BNode()
        self.graph.add((restriction, RDF.type, OWL.Restriction))
        self.graph.add((restriction, OWL.onProperty, prop_uri))

        restriction_pred = self.RESTRICTION_TYPES.get(restriction_type)
        if not restriction_pred:
            raise ValueError(f"Unknown restriction type: {restriction_type}")

        # Handle different value types
        if restriction_type in ["someValuesFrom", "allValuesFrom"]:
            self.graph.add((restriction, restriction_pred, self._uri(value)))
        elif restriction_type == "hasValue":
            if isinstance(value, str) and not value.startswith("http"):
                self.graph.add((restriction, restriction_pred, Literal(value)))
            else:
                self.graph.add((restriction, restriction_pred, self._uri(value)))
        elif restriction_type in ["minCardinality", "maxCardinality", "exactCardinality"]:
            self.graph.add((restriction, restriction_pred,
                          Literal(int(value), datatype=XSD.nonNegativeInteger)))
        elif restriction_type in ["minQualifiedCardinality", "maxQualifiedCardinality",
                                  "qualifiedCardinality"]:
            self.graph.add((restriction, restriction_pred,
                          Literal(int(value), datatype=XSD.nonNegativeInteger)))
            if on_class:
                self.graph.add((restriction, OWL.onClass, self._uri(on_class)))

        # Add as subclass of the target class
        self.graph.add((class_uri, RDFS.subClassOf, restriction))

        return restriction

    def get_restrictions(self, class_name: str = None) -> List[Dict[str, Any]]:
        """Get restrictions, optionally filtered by class."""
        restrictions = []

        for restriction in self.graph.subjects(RDF.type, OWL.Restriction):
            prop = self.graph.value(restriction, OWL.onProperty)
            if not prop:
                continue

            rest_info = {
                "property": self._local_name(prop),
                "type": None,
                "value": None,
                "on_class": None,
                "applied_to": []
            }

            # Determine restriction type
            for rtype, pred in self.RESTRICTION_TYPES.items():
                val = self.graph.value(restriction, pred)
                if val is not None:
                    rest_info["type"] = rtype
                    if isinstance(val, URIRef):
                        rest_info["value"] = self._local_name(val)
                    else:
                        rest_info["value"] = str(val)
                    break

            on_class = self.graph.value(restriction, OWL.onClass)
            if on_class:
                rest_info["on_class"] = self._local_name(on_class)

            # Find classes this restriction applies to
            for cls in self.graph.subjects(RDFS.subClassOf, restriction):
                if isinstance(cls, URIRef):
                    rest_info["applied_to"].append(self._local_name(cls))

            if class_name is None or class_name in rest_info["applied_to"]:
                restrictions.append(rest_info)

        return restrictions

    def delete_restriction(self, class_name: str, property_name: str, restriction_type: str):
        """Delete a restriction from a class."""
        class_uri = self._uri(class_name)
        prop_uri = self._uri(property_name)

        for restriction in self.graph.subjects(RDF.type, OWL.Restriction):
            if self.graph.value(restriction, OWL.onProperty) == prop_uri:
                # Check if this restriction is on the target class
                if (class_uri, RDFS.subClassOf, restriction) in self.graph:
                    # Check restriction type
                    pred = self.RESTRICTION_TYPES.get(restriction_type)
                    if pred and self.graph.value(restriction, pred) is not None:
                        self.graph.remove((class_uri, RDFS.subClassOf, restriction))
                        self.graph.remove((restriction, None, None))
                        return True
        return False

    # ==================== ANNOTATION OPERATIONS ====================

    def add_annotation(self, subject: str, predicate: str, value: str, lang: str = None):
        """Add an annotation to any resource.

        Args:
            subject: The resource name to annotate
            predicate: Either a full URI, a common name (label, comment, etc.), or a local name
            value: The annotation value
            lang: Optional language tag
        """
        subj_uri = self._uri(subject)

        # Map common annotation names to URIs
        annotation_predicates = {
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

        # Check if predicate is a full URI
        if predicate.startswith("http://") or predicate.startswith("https://"):
            pred_uri = URIRef(predicate)
        else:
            pred_uri = annotation_predicates.get(predicate, self._uri(predicate))

        if lang:
            literal = Literal(value, lang=lang)
        else:
            literal = Literal(value)

        self.graph.add((subj_uri, pred_uri, literal))

    def get_annotations(self, subject: str) -> List[Dict[str, str]]:
        """Get all annotations/predicates for a resource (like Protege shows)."""
        subj_uri = self._uri(subject)
        annotations = []

        # Get all predicates for this subject, excluding rdf:type, rdfs:subClassOf,
        # rdfs:domain, rdfs:range, and other structural predicates
        structural_predicates = {
            RDF.type, RDFS.subClassOf, RDFS.subPropertyOf,
            RDFS.domain, RDFS.range,
            OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith,
            OWL.inverseOf, OWL.propertyChainAxiom,
            OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom,
            OWL.hasValue, OWL.minCardinality, OWL.maxCardinality, OWL.cardinality,
            OWL.unionOf, OWL.intersectionOf, OWL.complementOf, OWL.oneOf,
            OWL.imports
        }

        for pred, obj in self.graph.predicate_objects(subj_uri):
            # Skip structural predicates
            if pred in structural_predicates:
                continue
            # Skip blank nodes (restrictions, etc.)
            if isinstance(obj, BNode):
                continue

            pred_uri = str(pred)
            prefix = self._get_prefix_for_uri(pred_uri)
            local_name = self._local_name(pred)
            ann = {
                "predicate": local_name,
                "predicate_uri": pred_uri,
                "predicate_prefixed": f"{prefix}:{local_name}" if prefix else local_name,
                "value": str(obj)
            }
            if hasattr(obj, 'language') and obj.language:
                ann["language"] = obj.language
            if hasattr(obj, 'datatype') and obj.datatype:
                ann["datatype"] = self._local_name(obj.datatype)
            annotations.append(ann)

        # Sort by predicate name
        annotations.sort(key=lambda x: x["predicate"])
        return annotations

    def get_used_annotation_predicates(self) -> List[Dict[str, str]]:
        """Get all unique annotation predicates used in the ontology."""
        structural_predicates = {
            RDF.type, RDFS.subClassOf, RDFS.subPropertyOf,
            RDFS.domain, RDFS.range,
            OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith,
            OWL.inverseOf, OWL.propertyChainAxiom,
            OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom,
            OWL.hasValue, OWL.minCardinality, OWL.maxCardinality, OWL.cardinality,
            OWL.unionOf, OWL.intersectionOf, OWL.complementOf, OWL.oneOf,
            OWL.imports
        }

        predicates = {}
        for subj, pred, obj in self.graph:
            # Skip structural predicates
            if pred in structural_predicates:
                continue
            # Skip blank node objects
            if isinstance(obj, BNode):
                continue
            # Only include predicates with literal values (annotations)
            if isinstance(obj, Literal) or isinstance(obj, URIRef):
                pred_uri = str(pred)
                if pred_uri not in predicates:
                    predicates[pred_uri] = {
                        "uri": pred_uri,
                        "local_name": self._local_name(pred),
                        "prefix": self._get_prefix_for_uri(pred_uri)
                    }

        # Sort by local name
        result = sorted(predicates.values(), key=lambda x: x["local_name"].lower())
        return result

    def _get_prefix_for_uri(self, uri: str) -> str:
        """Get the prefix for a URI if bound in the graph."""
        for prefix, namespace in self.graph.namespaces():
            ns_str = str(namespace)
            if uri.startswith(ns_str):
                return prefix if prefix else "(default)"
        return ""

    def delete_annotation(self, subject: str, predicate: str, value: str = None,
                          lang: str = None, datatype: str = None):
        """Delete an annotation from a resource.

        Matches language-tagged and datatype-qualified literals when lang/datatype
        are provided. When they are not provided but a value is given, searches
        for any literal with a matching string value regardless of tag.
        """
        subj_uri = self._uri(subject)

        annotation_predicates = {
            "label": RDFS.label, "comment": RDFS.comment,
            "prefLabel": SKOS.prefLabel, "altLabel": SKOS.altLabel,
            "definition": SKOS.definition, "note": SKOS.note,
        }

        pred_uri = annotation_predicates.get(predicate, self._uri(predicate))

        if value is None:
            self.graph.remove((subj_uri, pred_uri, None))
            return

        # Build exact literal if lang or datatype is known
        if lang:
            self.graph.remove((subj_uri, pred_uri, Literal(value, lang=lang)))
            return
        if datatype:
            dt_uri = self.XSD_DATATYPES.get(datatype, URIRef(datatype))
            self.graph.remove((subj_uri, pred_uri, Literal(value, datatype=dt_uri)))
            return

        # No lang/datatype specified: remove any literal whose string value matches
        to_remove = []
        for obj in self.graph.objects(subj_uri, pred_uri):
            if isinstance(obj, Literal) and str(obj) == value:
                to_remove.append(obj)
        for obj in to_remove:
            self.graph.remove((subj_uri, pred_uri, obj))

    # ==================== SKOS VOCABULARY OPERATIONS ====================

    SKOS_RELATIONS = {
        "broader": SKOS.broader, "narrower": SKOS.narrower,
        "related": SKOS.related, "broadMatch": SKOS.broadMatch,
        "narrowMatch": SKOS.narrowMatch, "exactMatch": SKOS.exactMatch,
        "closeMatch": SKOS.closeMatch, "relatedMatch": SKOS.relatedMatch,
    }

    SKOS_INVERSES = {
        SKOS.broader: SKOS.narrower,
        SKOS.narrower: SKOS.broader,
    }

    SKOS_SYMMETRIC = {SKOS.related, SKOS.closeMatch, SKOS.exactMatch, SKOS.relatedMatch}

    def add_concept_scheme(self, name: str, label: str = None,
                           comment: str = None) -> URIRef:
        """Add a new SKOS ConceptScheme."""
        scheme_uri = self._uri(name)
        self.graph.add((scheme_uri, RDF.type, SKOS.ConceptScheme))
        if label:
            self.graph.add((scheme_uri, RDFS.label, Literal(label)))
        if comment:
            self.graph.add((scheme_uri, RDFS.comment, Literal(comment)))
        return scheme_uri

    def get_concept_schemes(self) -> List[Dict[str, Any]]:
        """Get all SKOS ConceptSchemes."""
        schemes = []
        for uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if isinstance(uri, BNode):
                continue
            name = self._local_name(uri)
            label = str(self.graph.value(uri, RDFS.label) or "")
            comment = str(self.graph.value(uri, RDFS.comment) or "")
            # Count concepts in this scheme
            concept_count = sum(
                1 for _ in self.graph.subjects(SKOS.inScheme, uri)
            )
            schemes.append({
                "name": name,
                "uri": str(uri),
                "label": label,
                "comment": comment,
                "concept_count": concept_count,
            })
        return sorted(schemes, key=lambda s: s["name"])

    def update_concept_scheme(self, name: str, new_label: str = _UNSET,
                              new_comment: str = _UNSET):
        """Update a SKOS ConceptScheme's properties."""
        uri = self._uri(name)
        # Resolve actual URI from graph if _uri doesn't match
        for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if self._local_name(s_uri) == name:
                uri = s_uri
                break

        if new_label is not _UNSET:
            self.graph.remove((uri, RDFS.label, None))
            if new_label:
                self.graph.add((uri, RDFS.label, Literal(new_label)))

        if new_comment is not _UNSET:
            self.graph.remove((uri, RDFS.comment, None))
            if new_comment:
                self.graph.add((uri, RDFS.comment, Literal(new_comment)))

    def delete_concept_scheme(self, name: str):
        """Delete a ConceptScheme and remove inScheme references."""
        uri = self._uri(name)
        # Resolve actual URI from graph if _uri doesn't match
        for s_uri in self.graph.subjects(RDF.type, SKOS.ConceptScheme):
            if self._local_name(s_uri) == name:
                uri = s_uri
                break
        self.graph.remove((uri, None, None))
        self.graph.remove((None, SKOS.inScheme, uri))
        self.graph.remove((None, None, uri))

    def add_concept(self, name: str, scheme: str = None,
                    pref_label: str = None, definition: str = None,
                    broader: str = None, lang: str = None) -> URIRef:
        """Add a SKOS Concept with optional scheme/broader links."""
        concept_uri = self._uri(name)
        self.graph.add((concept_uri, RDF.type, SKOS.Concept))

        if scheme:
            scheme_uri = self._uri(scheme)
            self.graph.add((concept_uri, SKOS.inScheme, scheme_uri))

        if pref_label:
            if lang:
                self.graph.add((concept_uri, SKOS.prefLabel, Literal(pref_label, lang=lang)))
            else:
                self.graph.add((concept_uri, SKOS.prefLabel, Literal(pref_label)))

        if definition:
            if lang:
                self.graph.add((concept_uri, SKOS.definition, Literal(definition, lang=lang)))
            else:
                self.graph.add((concept_uri, SKOS.definition, Literal(definition)))

        if broader:
            broader_uri = self._uri(broader)
            self.graph.add((concept_uri, SKOS.broader, broader_uri))
            self.graph.add((broader_uri, SKOS.narrower, concept_uri))

        return concept_uri

    def get_concepts(self, scheme: str = None) -> List[Dict[str, Any]]:
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
            if scheme and scheme_uri:
                if (uri, SKOS.inScheme, scheme_uri) not in self.graph:
                    continue

            name = self._local_name(uri)

            pref_label = str(self.graph.value(uri, SKOS.prefLabel) or "")
            definition = str(self.graph.value(uri, SKOS.definition) or "")

            alt_labels = [str(o) for o in self.graph.objects(uri, SKOS.altLabel)]

            broader_list = [
                self._local_name(o) for o in self.graph.objects(uri, SKOS.broader)
                if isinstance(o, URIRef)
            ]
            narrower_list = [
                self._local_name(o) for o in self.graph.objects(uri, SKOS.narrower)
                if isinstance(o, URIRef)
            ]
            related_list = [
                self._local_name(o) for o in self.graph.objects(uri, SKOS.related)
                if isinstance(o, URIRef)
            ]

            schemes = [
                self._local_name(o) for o in self.graph.objects(uri, SKOS.inScheme)
                if isinstance(o, URIRef)
            ]

            concepts.append({
                "name": name,
                "uri": str(uri),
                "prefLabel": pref_label,
                "definition": definition,
                "altLabels": alt_labels,
                "broader": broader_list,
                "narrower": narrower_list,
                "related": related_list,
                "schemes": schemes,
            })

        return sorted(concepts, key=lambda c: c["name"])

    def update_concept(self, name: str, new_pref_label: str = _UNSET,
                       new_definition: str = _UNSET,
                       new_broader: str = _UNSET,
                       add_scheme: str = None, remove_scheme: str = None):
        """Update a SKOS Concept's properties."""
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

    def add_concept_relation(self, concept1: str, relation: str, concept2: str):
        """Add a SKOS relation between two concepts.

        Auto-adds inverse for broader/narrower and symmetric for related/matches.
        """
        c1_uri = self._uri(concept1)
        c2_uri = self._uri(concept2)

        rel_uri = self.SKOS_RELATIONS.get(relation)
        if not rel_uri:
            raise ValueError(f"Unknown SKOS relation: {relation}")

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

    def get_concept_hierarchy(self, scheme: str = None) -> Dict[str, List[str]]:
        """Return concept hierarchy as {parent: [children]} dict."""
        hierarchy: Dict[str, List[str]] = {}
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

    def validate_skos(self) -> List[Dict[str, str]]:
        """Validate SKOS concepts and schemes.

        Checks:
        - Missing prefLabel
        - Concept not in any scheme
        - Orphan concepts (no broader and not top concept)
        - Duplicate prefLabels within a scheme
        - Broader/narrower cycles
        """
        issues = []

        concepts = self.get_concepts()
        schemes = self.get_concept_schemes()

        for concept in concepts:
            # Missing prefLabel
            if not concept["prefLabel"]:
                issues.append({
                    "severity": "warning",
                    "type": "missing_prefLabel",
                    "subject": concept["name"],
                    "message": f"Concept '{concept['name']}' has no prefLabel",
                })

            # Not in any scheme
            if not concept["schemes"] and schemes:
                issues.append({
                    "severity": "info",
                    "type": "no_scheme",
                    "subject": concept["name"],
                    "message": f"Concept '{concept['name']}' is not in any ConceptScheme",
                })

        # Duplicate prefLabels within schemes
        for scheme in schemes:
            scheme_concepts = self.get_concepts(scheme=scheme["name"])
            labels_seen: Dict[str, str] = {}
            for concept in scheme_concepts:
                lbl = concept["prefLabel"]
                if lbl and lbl in labels_seen:
                    issues.append({
                        "severity": "warning",
                        "type": "duplicate_prefLabel",
                        "subject": concept["name"],
                        "message": f"Duplicate prefLabel '{lbl}' in scheme '{scheme['name']}' (also on '{labels_seen[lbl]}')",
                    })
                elif lbl:
                    labels_seen[lbl] = concept["name"]

        # Broader/narrower cycle detection
        concept_names = {c["name"] for c in concepts}
        for concept in concepts:
            visited: Set[str] = set()
            current = concept["name"]
            chain = [current]
            has_cycle = False
            while True:
                broader_list = []
                for c in concepts:
                    if c["name"] == current:
                        broader_list = c["broader"]
                        break
                if not broader_list:
                    break
                next_name = broader_list[0]
                if next_name in visited:
                    has_cycle = True
                    break
                if next_name not in concept_names:
                    break
                visited.add(current)
                current = next_name
                chain.append(current)

            if has_cycle:
                issues.append({
                    "severity": "error",
                    "type": "broader_cycle",
                    "subject": concept["name"],
                    "message": f"Broader/narrower cycle detected: {' -> '.join(chain)}",
                })

        return issues

    # ==================== RELATIONS OPERATIONS ====================

    # Class relation types
    CLASS_RELATIONS = {
        "subClassOf": RDFS.subClassOf,
        "equivalentClass": OWL.equivalentClass,
        "disjointWith": OWL.disjointWith,
    }

    # Property relation types
    PROPERTY_RELATIONS = {
        "subPropertyOf": RDFS.subPropertyOf,
        "equivalentProperty": OWL.equivalentProperty,
        "inverseOf": OWL.inverseOf,
        "propertyDisjointWith": OWL.propertyDisjointWith,
    }

    # Individual relation types
    INDIVIDUAL_RELATIONS = {
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

    def get_class_relations(self, class_name: str = None) -> List[Dict[str, str]]:
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
                        relations.append({
                            "subject": subj_name,
                            "subject_uri": str(subj),
                            "relation": rel_name,
                            "object": obj_name,
                            "object_uri": str(obj),
                        })
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

    def get_property_relations(self, prop_name: str = None) -> List[Dict[str, str]]:
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
                        relations.append({
                            "subject": subj_name,
                            "subject_uri": str(subj),
                            "relation": rel_name,
                            "object": obj_name,
                            "object_uri": str(obj),
                        })
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

    def get_individual_relations(self, ind_name: str = None) -> List[Dict[str, str]]:
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
                        relations.append({
                            "subject": subj_name,
                            "subject_uri": str(subj),
                            "relation": rel_name,
                            "object": obj_name,
                            "object_uri": str(obj),
                        })
        return relations

    # ==================== ADVANCED OWL FEATURES ====================

    def add_property_chain(self, property_name: str, chain_properties: List[str]):
        """Add a property chain axiom (owl:propertyChainAxiom)."""
        prop_uri = self._uri(property_name)
        chain_uris = [self._uri(p) for p in chain_properties]

        # Create RDF list for the chain
        chain_list = BNode()
        Collection(self.graph, chain_list, chain_uris)
        self.graph.add((prop_uri, OWL.propertyChainAxiom, chain_list))

    def get_property_chains(self) -> List[Dict[str, Any]]:
        """Get all property chain axioms."""
        chains = []
        for prop, chain_list in self.graph.subject_objects(OWL.propertyChainAxiom):
            if isinstance(prop, URIRef):
                chain = list(Collection(self.graph, chain_list))
                chains.append({
                    "property": self._local_name(prop),
                    "chain": [self._local_name(p) for p in chain if isinstance(p, URIRef)]
                })
        return chains

    def add_class_expression(self, class_name: str, expression_type: str,
                            classes: List[str] = None, individuals: List[str] = None):
        """Add a class expression (unionOf, intersectionOf, complementOf, oneOf)."""
        class_uri = self._uri(class_name)

        if expression_type == "complementOf" and classes:
            # complementOf takes a single class
            self.graph.add((class_uri, OWL.complementOf, self._uri(classes[0])))

        elif expression_type == "oneOf" and individuals:
            # oneOf takes a list of individuals
            ind_uris = [self._uri(i) for i in individuals]
            list_node = BNode()
            Collection(self.graph, list_node, ind_uris)
            self.graph.add((class_uri, OWL.oneOf, list_node))

        elif expression_type in ["unionOf", "intersectionOf"] and classes:
            # unionOf and intersectionOf take a list of classes
            class_uris = [self._uri(c) for c in classes]
            list_node = BNode()
            Collection(self.graph, list_node, class_uris)
            if expression_type == "unionOf":
                self.graph.add((class_uri, OWL.unionOf, list_node))
            else:
                self.graph.add((class_uri, OWL.intersectionOf, list_node))

    def get_class_expressions(self, class_name: str = None) -> List[Dict[str, Any]]:
        """Get class expressions for a class or all classes."""
        expressions = []

        expression_types = [
            (OWL.unionOf, "unionOf"),
            (OWL.intersectionOf, "intersectionOf"),
            (OWL.complementOf, "complementOf"),
            (OWL.oneOf, "oneOf")
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
                            expr["members"] = [self._local_name(m) for m in members if isinstance(m, URIRef)]
                        except Exception:
                            pass

                    if expr["members"]:
                        expressions.append(expr)

        return expressions

    def add_all_different(self, individuals: List[str]):
        """Add an owl:AllDifferent declaration for a list of individuals."""
        all_diff = BNode()
        self.graph.add((all_diff, RDF.type, OWL.AllDifferent))

        ind_uris = [self._uri(i) for i in individuals]
        list_node = BNode()
        Collection(self.graph, list_node, ind_uris)
        self.graph.add((all_diff, OWL.distinctMembers, list_node))

    def get_all_different(self) -> List[List[str]]:
        """Get all owl:AllDifferent declarations."""
        all_diffs = []
        for all_diff in self.graph.subjects(RDF.type, OWL.AllDifferent):
            members_list = self.graph.value(all_diff, OWL.distinctMembers)
            if members_list:
                try:
                    members = list(Collection(self.graph, members_list))
                    all_diffs.append([self._local_name(m) for m in members if isinstance(m, URIRef)])
                except Exception:
                    pass
        return all_diffs

    def add_has_key(self, class_name: str, properties: List[str]):
        """Add an owl:hasKey axiom to a class."""
        class_uri = self._uri(class_name)
        prop_uris = [self._uri(p) for p in properties]

        list_node = BNode()
        Collection(self.graph, list_node, prop_uris)
        self.graph.add((class_uri, OWL.hasKey, list_node))

    def get_has_keys(self, class_name: str = None) -> List[Dict[str, Any]]:
        """Get owl:hasKey axioms."""
        keys = []
        for subj, key_list in self.graph.subject_objects(OWL.hasKey):
            if isinstance(subj, URIRef):
                subj_name = self._local_name(subj)
                if class_name and subj_name != class_name:
                    continue
                try:
                    props = list(Collection(self.graph, key_list))
                    keys.append({
                        "class": subj_name,
                        "properties": [self._local_name(p) for p in props if isinstance(p, URIRef)]
                    })
                except Exception:
                    pass
        return keys

    def add_disjoint_union(self, class_name: str, disjoint_classes: List[str]):
        """Add an owl:disjointUnionOf axiom (class is disjoint union of listed classes)."""
        class_uri = self._uri(class_name)
        class_uris = [self._uri(c) for c in disjoint_classes]

        list_node = BNode()
        Collection(self.graph, list_node, class_uris)
        self.graph.add((class_uri, OWL.disjointUnionOf, list_node))

    def get_disjoint_unions(self) -> List[Dict[str, Any]]:
        """Get all owl:disjointUnionOf declarations."""
        unions = []
        for subj, union_list in self.graph.subject_objects(OWL.disjointUnionOf):
            if isinstance(subj, URIRef):
                try:
                    members = list(Collection(self.graph, union_list))
                    unions.append({
                        "class": self._local_name(subj),
                        "members": [self._local_name(m) for m in members if isinstance(m, URIRef)]
                    })
                except Exception:
                    pass
        return unions

    # ==================== IMPORT/EXPORT OPERATIONS ====================

    def load_from_file(self, file_path: str, format: str = "turtle"):
        """Load ontology from a file."""
        with open(file_path, 'r', encoding='utf-8') as f:
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

    def load_from_string(self, data: str, format: str = "turtle"):
        """Load ontology from a string."""
        if format == "turtle":
            self._loaded_prefixes = self._extract_prefixes_from_ttl(data)
        elif format == "json-ld":
            self._loaded_prefixes = self._extract_prefixes_from_jsonld(data)
        else:
            self._loaded_prefixes = []
        self.graph = Graph()
        self.graph.parse(data=data, format=format)
        self._update_namespace_from_graph()

    def preview_import(self, data: str, format: str = "turtle") -> Dict[str, Any]:
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
            "object_properties": sum(1 for _ in temp.subjects(RDF.type, OWL.ObjectProperty)),
            "data_properties": sum(1 for _ in temp.subjects(RDF.type, OWL.DatatypeProperty)),
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

    def detect_conflicts(self, other_graph: Graph) -> List[Dict[str, Any]]:
        """Detect conflicts between current graph and another graph.

        A conflict exists when both graphs have triples with the same subject
        and predicate but different object values, for predicates where multiple
        values are semantically problematic.
        """
        conflict_preds = {
            RDFS.label, RDFS.domain, RDFS.range, RDFS.comment,
            OWL.versionIRI, DCTERMS.creator,
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
                conflicts.append({
                    "subject": self._local_name(s),
                    "predicate": self._local_name(p),
                    "current_values": [
                        self._local_name(v) if isinstance(v, URIRef) else str(v)
                        for v in current_values
                    ],
                    "incoming_value": (
                        self._local_name(incoming_value)
                        if isinstance(incoming_value, URIRef) else str(incoming_value)
                    ),
                })

        # Deduplicate (same subject+predicate can appear multiple times)
        seen = set()
        unique = []
        for c in conflicts:
            key = (c["subject"], c["predicate"])
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def merge_from_graph(self, other_graph: Graph,
                         strategy: str = IMPORT_MERGE) -> Dict[str, Any]:
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
                RDFS.label, RDFS.domain, RDFS.range, RDFS.comment,
                OWL.versionIRI, DCTERMS.creator,
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

    def merge_from_string(self, data: str, format: str = "turtle",
                          strategy: str = IMPORT_MERGE) -> Dict[str, Any]:
        """Parse data and merge into current graph."""
        temp = Graph()
        temp.parse(data=data, format=format)
        return self.merge_from_graph(temp, strategy=strategy)

    def _detect_prefix_conflicts(self, other_graph: Graph) -> List[Dict[str, str]]:
        """Compare namespace bindings between current and incoming graph."""
        current_ns = {prefix: str(ns) for prefix, ns in self.graph.namespaces()}
        conflicts = []
        for prefix, ns in other_graph.namespaces():
            ns_str = str(ns)
            if prefix in current_ns and current_ns[prefix] != ns_str:
                conflicts.append({
                    "prefix": prefix,
                    "current_namespace": current_ns[prefix],
                    "incoming_namespace": ns_str,
                })
        return conflicts

    def _reconcile_prefixes_after_merge(self, other_graph: Graph,
                                         prefix_resolution: Dict[str, str] = None):
        """Re-bind prefixes after a merge operation."""
        for prefix, ns in other_graph.namespaces():
            if prefix_resolution and prefix in prefix_resolution:
                self.graph.bind(prefix, Namespace(prefix_resolution[prefix]),
                                override=True)
            else:
                # Current bindings take precedence
                self.graph.bind(prefix, ns, override=False)

    def _update_namespace_from_graph(self):
        """Update namespace based on loaded ontology."""
        found_ontology = False

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

        # Re-bind prefixes
        self.graph.bind("owl", OWL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)
        self.graph.bind("xsd", XSD)
        self.graph.bind("skos", SKOS)
        self.graph.bind("dc", DC)
        self.graph.bind("dcterms", DCTERMS)

    def _detect_base_uri(self, uri_str: str) -> str:
        """Detect the base URI with separator from an ontology URI string."""
        if uri_str.endswith("#") or uri_str.endswith("/"):
            return uri_str

        sample_uri = self._find_sample_resource_uri()
        if sample_uri and uri_str in sample_uri:
            remainder = sample_uri[len(uri_str):]
            if remainder.startswith("/"):
                return uri_str + "/"
            elif remainder.startswith("#"):
                return uri_str + "#"
        return uri_str + "#"

    def _find_sample_resource_uri(self) -> Optional[str]:
        """Find a sample resource URI from classes or properties in the graph."""
        for rdf_type in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                         OWL.NamedIndividual):
            for s in self.graph.subjects(RDF.type, rdf_type):
                if isinstance(s, URIRef):
                    return str(s)
        return None

    def _infer_namespace_from_graph(self) -> Optional[str]:
        """Infer namespace from graph prefixes and resource URIs when no owl:Ontology exists."""
        STANDARD_NAMESPACES = {
            str(OWL), str(RDF), str(RDFS), str(XSD),
            str(SKOS), str(DC), str(DCTERMS),
        }

        # Try the default prefix first (most likely the ontology namespace)
        for prefix, ns in self.graph.namespaces():
            ns_str = str(ns)
            if prefix == "" and ns_str not in STANDARD_NAMESPACES:
                return ns_str

        # Try to find the most common namespace among typed resources
        from collections import Counter
        ns_counter: Counter = Counter()
        for rdf_type in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                         OWL.NamedIndividual):
            for s in self.graph.subjects(RDF.type, rdf_type):
                if isinstance(s, URIRef):
                    uri_str = str(s)
                    for sep in ("#", "/"):
                        idx = uri_str.rfind(sep)
                        if idx != -1:
                            candidate = uri_str[:idx + 1]
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

    def search(self, query: str) -> List[Dict[str, str]]:
        """Search across all resource names, labels, and comments.

        Returns a list of dicts with keys: name, type, label, match_field.
        Results are case-insensitive partial matches.
        """
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        results: List[Dict[str, str]] = []
        seen: Set[str] = set()

        type_map = [
            (OWL.Class, "Class"),
            (OWL.ObjectProperty, "Object Property"),
            (OWL.DatatypeProperty, "Data Property"),
            (OWL.NamedIndividual, "Individual"),
        ]

        for rdf_type, type_label in type_map:
            for subj in self.graph.subjects(RDF.type, rdf_type):
                if not isinstance(subj, URIRef) or str(subj) in seen:
                    continue
                seen.add(str(subj))
                name = self._local_name(subj)
                label = str(self.graph.value(subj, RDFS.label) or "")
                comment = str(self.graph.value(subj, RDFS.comment) or "")

                match_field = None
                if q in name.lower():
                    match_field = "name"
                elif q in label.lower():
                    match_field = "label"
                elif q in comment.lower():
                    match_field = "comment"

                if match_field:
                    results.append({
                        "name": name,
                        "type": type_label,
                        "label": label,
                        "match_field": match_field,
                    })

        results.sort(key=lambda r: (r["match_field"] != "name", r["name"].lower()))
        return results

    # ==================== RESOURCE USAGES ====================

    def get_resource_usages(self, name: str) -> Dict[str, List[Dict[str, str]]]:
        """Find all places a resource is referenced in the graph.

        Returns a dict with:
          - outbound: triples where this resource is the subject (excluding structural type triples)
          - inbound: triples where this resource is the object
          - as_predicate: triples where this resource is used as a predicate
        """
        uri = self._uri(name)

        structural_preds = {
            RDF.type, RDFS.subClassOf, RDFS.subPropertyOf,
            OWL.equivalentClass, OWL.disjointWith,
        }

        outbound: List[Dict[str, str]] = []
        for p, o in self.graph.predicate_objects(uri):
            if p in structural_preds:
                continue
            outbound.append({
                "predicate": self._local_name(p),
                "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
                "object_type": "uri" if isinstance(o, URIRef) else "literal",
            })

        inbound: List[Dict[str, str]] = []
        for s, p in self.graph.subject_predicates(uri):
            if isinstance(s, BNode):
                continue
            inbound.append({
                "subject": self._local_name(s) if isinstance(s, URIRef) else str(s),
                "predicate": self._local_name(p),
            })

        as_predicate: List[Dict[str, str]] = []
        for s, o in self.graph.subject_objects(uri):
            as_predicate.append({
                "subject": self._local_name(s) if isinstance(s, URIRef) else str(s),
                "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
            })

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
        """Replace the current graph with a previously captured snapshot."""
        self.graph = Graph()
        self.graph.parse(data=snapshot.decode("utf-8"), format="nt")
        self._update_namespace_from_graph()

    # ==================== DIFF & COMPARISON ====================

    def compare_graphs(self, other_graph: Graph) -> Dict[str, Any]:
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
            modified_resources.append({
                "name": subj,
                "change_type": change_type,
                "added_triples": added_by_subj.get(subj, []),
                "removed_triples": removed_by_subj.get(subj, []),
            })

        # Build string representations for triple lists
        added_triples = [
            (self._local_name(s) if isinstance(s, URIRef) else str(s),
             self._local_name(p),
             self._local_name(o) if isinstance(o, URIRef) else str(o))
            for s, p, o in named_added
        ]
        removed_triples = [
            (self._local_name(s) if isinstance(s, URIRef) else str(s),
             self._local_name(p),
             self._local_name(o) if isinstance(o, URIRef) else str(o))
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

    def compare_to_string(self, data: str, format: str = "turtle") -> Dict[str, Any]:
        """Parse data into a temporary graph and compare to current state."""
        temp = Graph()
        temp.parse(data=data, format=format)
        return self.compare_graphs(temp)

    def _group_triples_by_subject(self, triples) -> Dict[str, List[Dict]]:
        """Group a set of triples by subject local name for display."""
        groups: Dict[str, List[Dict]] = {}
        for s, p, o in triples:
            if isinstance(s, BNode):
                continue
            name = self._local_name(s) if isinstance(s, URIRef) else str(s)
            if name not in groups:
                groups[name] = []
            groups[name].append({
                "predicate": self._local_name(p),
                "object": self._local_name(o) if isinstance(o, URIRef) else str(o),
                "object_type": "uri" if isinstance(o, URIRef) else "literal",
            })
        return groups

    def _classify_resource_change(self, subject: str,
                                   added_subjects: Set[str],
                                   removed_subjects: Set[str]) -> str:
        """Classify what happened to a resource: 'added', 'removed', or 'modified'."""
        in_added = subject in added_subjects
        in_removed = subject in removed_subjects
        if in_added and not in_removed:
            return "added"
        if in_removed and not in_added:
            return "removed"
        return "modified"

    def _summarize_changes(self, diff: Dict[str, Any]) -> List[str]:
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
                    if obj in ("Class", "ObjectProperty", "DatatypeProperty",
                               "NamedIndividual", "Ontology", "AnnotationProperty",
                               "Restriction"):
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

    def format_diff_report(self, diff: Dict[str, Any],
                           report_format: str = "markdown") -> str:
        """Format a diff result as a human-readable report."""
        stats = diff["stats"]
        lines = []

        if report_format == "markdown":
            lines.append("# Ontology Change Report\n")
            lines.append("## Summary\n")
            lines.append(f"- **Added:** {stats['added']} triples across "
                         f"{stats['resources_added']} resources")
            lines.append(f"- **Removed:** {stats['removed']} triples across "
                         f"{stats['resources_removed']} resources")
            lines.append(f"- **Modified:** {stats['resources_modified']} resources")
            lines.append(f"- **Unchanged:** {stats['unchanged']} triples")
            if stats["bnode_added"] or stats["bnode_removed"]:
                lines.append(f"- **Anonymous nodes:** {stats['bnode_added']} added, "
                             f"{stats['bnode_removed']} removed")
            lines.append("")

            # Group resources by change type
            for change_type, heading in [("added", "Added Resources"),
                                          ("removed", "Removed Resources"),
                                          ("modified", "Modified Resources")]:
                resources = [r for r in diff["modified_resources"]
                             if r["change_type"] == change_type]
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
            lines.append(f"Added: {stats['added']} triples, "
                         f"Removed: {stats['removed']} triples, "
                         f"Modified: {stats['resources_modified']} resources")
            lines.append("")
            for line in diff["summary"]:
                lines.append(f"  {line}")

        return "\n".join(lines)

    # ==================== VALIDATION & REASONING ====================

    def validate(self, check_missing_domain_range: bool = True) -> List[Dict[str, str]]:
        """Validate the ontology and return issues."""
        issues = []

        # Check for classes without labels
        for class_uri in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, BNode):
                continue
            if not self.graph.value(class_uri, RDFS.label) and not self.graph.value(class_uri, SKOS.prefLabel):
                issues.append({
                    "severity": "warning",
                    "type": "missing_label",
                    "subject": self._local_name(class_uri),
                    "message": f"Class '{self._local_name(class_uri)}' has no label (rdfs:label or skos:prefLabel)"
                })

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
                    issues.append({
                        "severity": "info",
                        "type": "missing_domain",
                        "subject": self._local_name(prop_uri),
                        "message": f"Object property '{self._local_name(prop_uri)}' has no domain"
                    })
                if not _has_range(prop_uri):
                    issues.append({
                        "severity": "info",
                        "type": "missing_range",
                        "subject": self._local_name(prop_uri),
                        "message": f"Object property '{self._local_name(prop_uri)}' has no range"
                    })

            for prop_uri in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
                if isinstance(prop_uri, BNode):
                    continue
                if not _has_domain(prop_uri):
                    issues.append({
                        "severity": "info",
                        "type": "missing_domain",
                        "subject": self._local_name(prop_uri),
                        "message": f"Data property '{self._local_name(prop_uri)}' has no domain"
                    })

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
            issues.append({
                "severity": "info",
                "type": "orphan_class",
                "subject": name,
                "message": f"Class '{name}' is not used in any hierarchy, property domain/range, restriction, or instance typing"
            })

        # Check individuals have at least one class
        for ind_uri in self.graph.subjects(RDF.type, OWL.NamedIndividual):
            classes = [c for c in self.graph.objects(ind_uri, RDF.type)
                      if c != OWL.NamedIndividual]
            if not classes:
                issues.append({
                    "severity": "warning",
                    "type": "untyped_individual",
                    "subject": self._local_name(ind_uri),
                    "message": f"Individual '{self._local_name(ind_uri)}' has no class type"
                })

        # Check domain/range usage for property assertions on individuals
        def _expand_superclasses(class_uris: Set[str]) -> Set[str]:
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
            ind_direct_classes = {str(c) for c in self.graph.objects(ind_uri, RDF.type)
                                  if isinstance(c, URIRef) and c != OWL.NamedIndividual}
            ind_all_classes = _expand_superclasses(ind_direct_classes)

            for pred, obj in self.graph.predicate_objects(ind_uri):
                if pred == RDF.type or isinstance(pred, BNode):
                    continue

                # Check object properties
                if (pred, RDF.type, OWL.ObjectProperty) in self.graph:
                    domain = self.graph.value(pred, RDFS.domain)
                    if domain and isinstance(domain, URIRef) and str(domain) not in ind_all_classes:
                        issues.append({
                            "severity": "warning",
                            "type": "domain_mismatch",
                            "subject": ind_name,
                            "message": f"Individual '{ind_name}' uses property '{self._local_name(pred)}' but is not typed as '{self._local_name(domain)}'"
                        })

                    range_ = self.graph.value(pred, RDFS.range)
                    if range_ and isinstance(range_, URIRef) and isinstance(obj, URIRef):
                        obj_direct = {str(c) for c in self.graph.objects(obj, RDF.type)
                                      if isinstance(c, URIRef) and c != OWL.NamedIndividual}
                        obj_all_classes = _expand_superclasses(obj_direct)
                        if str(range_) not in obj_all_classes:
                            issues.append({
                                "severity": "warning",
                                "type": "range_mismatch",
                                "subject": ind_name,
                                "message": f"Property '{self._local_name(pred)}' on '{ind_name}' expects range '{self._local_name(range_)}' but '{self._local_name(obj)}' is not typed as such"
                            })

                # Check data properties
                elif (pred, RDF.type, OWL.DatatypeProperty) in self.graph:
                    domain = self.graph.value(pred, RDFS.domain)
                    if domain and isinstance(domain, URIRef) and str(domain) not in ind_all_classes:
                        issues.append({
                            "severity": "warning",
                            "type": "domain_mismatch",
                            "subject": ind_name,
                            "message": f"Individual '{ind_name}' uses data property '{self._local_name(pred)}' but is not typed as '{self._local_name(domain)}'"
                        })

        # Check for duplicate rdfs:label values across resources
        from collections import defaultdict
        label_to_resources: Dict[str, List[str]] = defaultdict(list)
        for subj, label_val in self.graph.subject_objects(RDFS.label):
            if isinstance(subj, URIRef) and isinstance(label_val, Literal):
                label_str = str(label_val)
                name = self._local_name(subj)
                label_to_resources[label_str].append(name)
        for label_str, resources in label_to_resources.items():
            if len(resources) > 1:
                issues.append({
                    "severity": "warning",
                    "type": "duplicate_label",
                    "subject": ", ".join(sorted(resources)),
                    "message": f"Duplicate label '{label_str}' shared by: {', '.join(sorted(resources))}"
                })

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

    def get_statistics(self) -> Dict[str, int]:
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
            "content_triples": len(self.graph) - ontology_meta_count
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

        stats["concept_schemes"] = sum(1 for _ in self.graph.subjects(RDF.type, SKOS.ConceptScheme))
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
        self._undo_stack: List[Tuple[str, bytes]] = []  # (label, snapshot)
        self._redo_stack: List[Tuple[str, bytes]] = []
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

    def undo(self) -> Optional[str]:
        """Undo the last change. Returns the label of the restored state, or None."""
        if not self.can_undo():
            return None
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        label, snapshot = self._undo_stack[-1]
        self.manager.restore_snapshot(snapshot)
        return label

    def redo(self) -> Optional[str]:
        """Redo the last undone change. Returns the label, or None."""
        if not self.can_redo():
            return None
        label, snapshot = self._redo_stack.pop()
        self._undo_stack.append((label, snapshot))
        self.manager.restore_snapshot(snapshot)
        return label

    @property
    def undo_labels(self) -> List[str]:
        """Labels in the undo stack (most recent last), excluding the bottom."""
        return [label for label, _ in self._undo_stack[1:]]

    @property
    def redo_labels(self) -> List[str]:
        """Labels in the redo stack (next redo last)."""
        return [label for label, _ in self._redo_stack]

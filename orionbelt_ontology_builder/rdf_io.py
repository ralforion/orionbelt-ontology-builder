"""Parse RDF into an rdflib graph, through Oxigraph where that gives rdflib's result.

rdflib's Turtle and N-Triples parsers are pure Python: a 213k-triple file took
5 s to load, nearly all of it in the parser. Oxigraph parses the same file in a
fraction of a second; turning its terms into rdflib's and filling the working
graph is the rest. The working graph stays rdflib.

The fast path is taken only where its result is exactly rdflib's, so that
loading a file one way or the other never makes a difference (a re-import
would otherwise show every literal as changed):

* **Turtle and N-Triples only.** Oxigraph's RDF/XML parser does not apply XML's
  normalization of attribute values and line ends the way rdflib's does, and
  the other formats are rare in large files.
* **No explicit** ``^^xsd:string``. RDF 1.1 makes ``"a"`` and ``"a"^^xsd:string``
  one term, and Oxigraph reports both alike, but rdflib keeps them apart. A file
  that writes the datatype out is left to rdflib. The check is on the text and
  errs towards rdflib.
* **Language tags keep their case.** Oxigraph lowercases them, rdflib keeps
  them as written (``@en-GB``). The tags as written are read off the text and
  put back; a file that spells one tag two ways is left to rdflib.
* **No base IRI.** A relative IRI makes Oxigraph fail, and rdflib resolves it
  against the same base as before.
* **Anything else Oxigraph rejects or that has no rdflib term** (an RDF 1.2
  triple term, a literal with a base direction) also goes to rdflib, which
  then parses or reports the error as it always did.

Nothing reaches the graph until Oxigraph has parsed and converted the whole
file, so a file that falls back leaves no partial triples behind. Prefixes are
bound the way rdflib's Turtle parser binds them, once the triples are in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pyoxigraph as ox
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD
from rdflib.term import Node

_FAST_FORMATS = {
    "turtle": ox.RdfFormat.TURTLE,
    "ttl": ox.RdfFormat.TURTLE,
    "nt": ox.RdfFormat.N_TRIPLES,
    "nt11": ox.RdfFormat.N_TRIPLES,
    "ntriples": ox.RdfFormat.N_TRIPLES,
}

#: A literal that writes out a datatype named ``string``: ``^^xsd:string`` under
#: any prefix, or the full IRI. Matching other ``…:string`` datatypes too is
#: harmless; such a file only goes to rdflib.
_EXPLICIT_STRING = re.compile(
    r"\^\^\s*(?:<http://www\.w3\.org/2001/XMLSchema#string>|[A-Za-z_][\w.\-]*:string\b|:string\b)"
)

#: A language tag as written, right after the closing quote of a literal.
_LANGUAGE_TAG = re.compile(r"[\"']@([A-Za-z]+(?:-[A-Za-z0-9]+)*)")

_XSD_STRING = str(XSD.string)

_Triple = tuple[Node, Node, Node]


class _LeaveToRdflib(Exception):
    """What Oxigraph parsed has no rdflib term, or no single one."""


def parse_into(
    graph: Graph,
    format: str,
    *,
    data: str | None = None,
    path: str | Path | None = None,
) -> bool:
    """Parse ``data`` or the file at ``path`` into ``graph`` as
    ``graph.parse`` would, through Oxigraph where that gives the same result.

    With both given, ``data`` is the file's text, already read, and ``path``
    is what rdflib parses if it has to (so it resolves against the same base
    as before). Returns whether Oxigraph did the parsing.
    """
    if data is None and path is None:
        raise ValueError("parse_into needs data or a path")
    text = data if data is not None else Path(path).read_text(encoding="utf-8")  # type: ignore[arg-type]
    parsed = _parse_with_oxigraph(text, format)
    if parsed is None:
        if path is not None:
            graph.parse(str(path), format=format)
        else:
            graph.parse(data=text, format=format)
        return False
    triples, prefixes = parsed
    graph.addN((s, p, o, graph) for s, p, o in triples)
    # What rdflib's TurtleParser does once its triples are in.
    for prefix, namespace in prefixes.items():
        graph.bind(prefix, namespace)
    return True


def _parse_with_oxigraph(
    text: str, format: str
) -> tuple[list[_Triple], dict[str, str]] | None:
    """Oxigraph's parse as rdflib triples and the declared prefixes, or None
    when rdflib should parse instead (see the module docstring)."""
    ox_format = _FAST_FORMATS.get(format)
    if ox_format is None or _EXPLICIT_STRING.search(text):
        return None
    spelling = _language_tags_as_written(text)
    if spelling is None:
        return None
    try:
        parser = ox.parse(text, format=ox_format)
        triples = list(_converted(parser, spelling))
        prefixes = dict(parser.prefixes)
    except Exception:  # noqa: BLE001 - any failure hands the text to rdflib, which reports it as before
        return None
    return triples, prefixes


def _language_tags_as_written(text: str) -> dict[str, str] | None:
    """Each language tag in ``text`` by its lowercase form, as written; None
    when one tag is written two ways and rdflib should parse the file.

    A match inside a literal's text can only add a spelling, which then
    conflicts with the real tag's and sends the file to rdflib, so a wrong
    case is never put on a tag.
    """
    spelling: dict[str, str] = {}
    for tag in set(_LANGUAGE_TAG.findall(text)):
        lower = tag.lower()
        if spelling.setdefault(lower, tag) != tag:
            return None
    return spelling


def _converted(quads: Iterable[ox.Quad], spelling: dict[str, str]) -> Iterable[_Triple]:
    """Oxigraph quads as rdflib triples.

    IRIs and datatypes repeat a lot (every class is typed, every label has its
    predicate), so each is made into a ``URIRef`` once. A blank node label
    names one node within the file, as rdflib's parser keeps it.
    """
    named: dict[str, URIRef] = {}
    blank: dict[str, BNode] = {}

    def term(node) -> Node:
        if type(node) is ox.NamedNode:
            value = node.value
            uri = named.get(value)
            if uri is None:
                uri = named[value] = URIRef(value)
            return uri
        if type(node) is ox.BlankNode:
            label = node.value
            bnode = blank.get(label)
            if bnode is None:
                bnode = blank[label] = BNode()
            return bnode
        if type(node) is ox.Literal:
            if getattr(node, "direction", None) is not None:
                raise _LeaveToRdflib("a literal with a base direction")
            if node.language:
                language = node.language
                return Literal(node.value, lang=spelling.get(language, language))
            datatype = node.datatype.value
            if datatype == _XSD_STRING:
                return Literal(node.value)
            dt = named.get(datatype)
            if dt is None:
                dt = named[datatype] = URIRef(datatype)
            return Literal(node.value, datatype=dt)
        raise _LeaveToRdflib(f"a {type(node).__name__}")

    for quad in quads:
        if not isinstance(quad.graph_name, ox.DefaultGraph):
            raise _LeaveToRdflib("a named graph")
        yield term(quad.subject), term(quad.predicate), term(quad.object)

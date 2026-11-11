"""Parse RDF into an rdflib graph, through Oxigraph where that gives rdflib's result.

rdflib's Turtle and N-Triples parsers are pure Python: a 213k-triple file took
3.5 s to load, most of it in the parser. Oxigraph parses the same file in a
fraction of a second; turning its terms into rdflib's and filling the working
graph is the rest. The working graph stays rdflib.

The fast path is taken only where its result is exactly rdflib's, so that
loading a file one way or the other never makes a difference (a re-import
would otherwise show every literal as changed). Where the two parsers part
ways, the file is read for the spellings that are known to be safe, and
anything not recognized as safe goes to rdflib:

* **Turtle and N-Triples only.** Oxigraph's RDF/XML parser normalizes white
  space in literals differently from rdflib's, and the other formats are rare
  in large files.
* **No** ``xsd:string`` **datatype.** RDF 1.1 makes ``"a"`` and
  ``"a"^^xsd:string`` one term, and Oxigraph reports both alike, but rdflib
  keeps them apart. Every ``^^`` must be followed by a datatype read here as
  something else: a full IRI, or a prefixed name whose prefix is declared once.
  A comment or an escape there sends the file to rdflib.
* **Language tags keep their case.** Oxigraph lowercases them, rdflib keeps
  them as written (``@en-GB``). Each tag must be written right after its
  literal, the way rdflib requires, and is put back as written; a tag spelt
  two ways, or one Oxigraph reports that was not found, sends the file to
  rdflib.
* **Relative IRIs resolve alike.** Under ``@base``, rdflib resolves some
  relative IRIs (``<?y>``, ``<g/../h>``) differently from RFC 3986, which
  Oxigraph follows. Each relative IRI is resolved both ways, and one that
  differs, or a second base, sends the file to rdflib. Without a base,
  Oxigraph rejects a relative IRI and rdflib parses. Absolute IRIs are kept
  as written by both.
* **Anything else Oxigraph rejects or that has no rdflib term** (an RDF 1.2
  triple term, a literal with a base direction) also goes to rdflib, which
  then parses or reports the error as it always did.

Numbers written in shorthand (``+1``, ``1E3``) agree: both sides build an
rdflib ``Literal``, which normalizes the lexical form the same way.

Nothing reaches the graph until Oxigraph has parsed and converted the whole
file, so a file that falls back leaves no partial triples behind. Prefixes are
bound the way rdflib's Turtle parser binds them, once the triples are in.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

import pyoxigraph as ox
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD

# What rdflib's Turtle parser resolves every IRI with once it has a base.
from rdflib.plugins.parsers.notation3 import join as rdflib_join
from rdflib.term import Node

_FAST_FORMATS = {
    "turtle": ox.RdfFormat.TURTLE,
    "ttl": ox.RdfFormat.TURTLE,
    "nt": ox.RdfFormat.N_TRIPLES,
    "nt11": ox.RdfFormat.N_TRIPLES,
    "ntriples": ox.RdfFormat.N_TRIPLES,
}

_XSD_STRING = str(XSD.string)

#: Turtle's white space and comments, which may sit between any two tokens.
#: Possessive, so that a comment always runs to the end of its line and a run
#: of ``#`` is read one way only, not split every way it can be.
_SKIP = re.compile(r"(?:[ \t\r\n]++|#[^\r\n]*+)*+")

#: What an IRI between angle brackets may contain, escapes included.
_IRI_CHARS = r"[^<>\"{}|^`\x00-\x20]"

#: A datatype as this module reads it, after ``^^`` and plain white space: a
#: full IRI without escapes, or a prefixed name whose local name is followed
#: by what ends a term (an escape or a colon in it is not read).
_IRI_DATATYPE = r"<[^<>\"{}|^`\\\x00-\x20]*>"
_PREFIXED_NAME = r"([^\s:<>\"'\\^#()\[\],;]*):([\w.\-]*)(?![^ \t\r\n,;)\]#])"
#: A ``^^`` that is not followed by a datatype read here.
_UNREAD_DATATYPE = re.compile(
    r"\^\^(?![ \t\r\n]*(?:" + _IRI_DATATYPE + "|" + _PREFIXED_NAME + "))"
)
#: A datatype IRI that is relative, or is ``xsd:string``.
_RELATIVE_OR_STRING_DATATYPE = re.compile(
    r"\^\^[ \t\r\n]*<(?:(?![A-Za-z][A-Za-z0-9+.\-]*:)|" + re.escape(_XSD_STRING) + ">)"
)
_PREFIXED_DATATYPE = re.compile(r"\^\^[ \t\r\n]*" + _PREFIXED_NAME)

_ABSOLUTE_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")

#: A language tag after the closing quote of its literal. rdflib requires
#: nothing between them; Oxigraph also takes white space or a comment, and
#: lowercases the tag.
_QUOTE = r"[\"']"
_LANGUAGE_TAG = r"@([A-Za-z]+(?:-[A-Za-z0-9]+)*)"

#: ``@base`` or ``BASE`` and its IRI, or text that reads like one.
_BASE = r"(?i:base)"
_BRACKETED_IRI = "<(" + _IRI_CHARS + "*)>"
#: An IRI that is relative, or that hides its scheme behind an escape.
_RELATIVE_IRI = re.compile(r"<((?![A-Za-z][A-Za-z0-9+.\-]*:)" + _IRI_CHARS + "*)>")

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

    With both given, ``data`` is the file's text, already read with its line
    ends kept, and ``path`` is what rdflib parses if it has to (so it resolves
    against the same base as before). Returns whether Oxigraph did the parsing.
    """
    if data is None and path is None:
        raise ValueError("parse_into needs data or a path")
    text = data if data is not None else read_text_as_is(path)  # type: ignore[arg-type]
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


def read_text_as_is(path: str | Path) -> str:
    """A file's text with its line ends as written.

    rdflib parses a file from its bytes, so a CRLF inside a long string stays
    in the literal. Reading in text mode would turn it into LF.
    """
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _parse_with_oxigraph(
    text: str, format: str
) -> tuple[list[_Triple], dict[str, str]] | None:
    """Oxigraph's parse as rdflib triples and the declared prefixes, or None
    when rdflib should parse instead (see the module docstring)."""
    ox_format = _FAST_FORMATS.get(format)
    if ox_format is None:
        return None
    # N-Triples has no base, and Oxigraph rejects a relative IRI in it.
    if ox_format is ox.RdfFormat.TURTLE and not _relative_iris_resolve_alike(text):
        return None
    datatypes = _prefixed_datatypes(text)
    spelling = _language_tags_as_written(text)
    if datatypes is None or spelling is None:
        return None
    try:
        parser = ox.parse(text, format=ox_format)
        triples = list(_converted(parser, spelling))
        prefixes = dict(parser.prefixes)
    except Exception:  # noqa: BLE001 - any failure hands the text to rdflib, which reports it as before
        return None
    for prefix, local in datatypes:
        namespace = prefixes.get(prefix)
        if namespace is None:
            continue  # never declared, so not a datatype: Oxigraph would have failed
        if namespace + local == _XSD_STRING or not _declared_once(text, prefix):
            return None
    return triples, prefixes


def _relative_iris_resolve_alike(text: str) -> bool:
    """Whether every relative IRI in ``text`` resolves to the same IRI in
    rdflib as in Oxigraph.

    rdflib resolves with its own ``join``; Oxigraph is asked by parsing the
    IRIs under the same base. Text in a string or a comment that reads like an
    IRI is resolved too, which can only send a file to rdflib needlessly.
    """
    bases = [iri for _, iri in _next_tokens(text, _BASE, _BRACKETED_IRI)]
    if not bases:
        return True  # Oxigraph rejects a relative IRI without a base
    relative = sorted(set(_RELATIVE_IRI.findall(text)))
    if not relative:
        return True
    if len(bases) > 1:
        return False  # which base each IRI is under is not read here
    (base,) = bases
    if not _ABSOLUTE_IRI.match(base) or "\\" in base + "".join(relative):
        return False
    probe = f"@base <{base}> .\n<urn:s> <urn:p> " + " , ".join(
        f"<{iri}>" for iri in relative
    )
    try:
        by_oxigraph = [
            quad.object.value
            for quad in ox.parse(probe + " .", format=ox.RdfFormat.TURTLE)
        ]
    except Exception:  # noqa: BLE001 - an IRI Oxigraph rejects goes to rdflib
        return False
    try:
        by_rdflib = [rdflib_join(base, iri) for iri in relative]
    except ValueError:
        # A path under a base without one (``urn:x``): rdflib rejects a real
        # IRI like that, and text in a string that reads like one is fine.
        return False
    return by_oxigraph == by_rdflib


def _prefixed_datatypes(text: str) -> set[tuple[str, str]] | None:
    """Read every ``^^`` in ``text``: the datatypes written as prefixed names,
    as (prefix, local name) pairs to check once the prefixes are known, or
    None when a datatype is ``xsd:string``, may be, or is not read here.

    A ``^^`` inside a string or a comment is read too, which can only send a
    file to rdflib that did not need to go.
    """
    if _UNREAD_DATATYPE.search(text) or _RELATIVE_OR_STRING_DATATYPE.search(text):
        return None
    names: set[tuple[str, str]] = set()
    for prefix, local in set(_PREFIXED_DATATYPE.findall(text)):
        local = local.rstrip(".")  # a dot after a local name ends the statement
        if local == "string":
            return None
        names.add((prefix, local))
    return names


def _declared_once(text: str, prefix: str) -> bool:
    """Whether ``prefix`` is declared exactly once, so that the namespace
    Oxigraph ends with is the one every use of it had."""
    name = r"(?<!\S)" + re.escape(prefix) + ":"
    return len(_next_tokens(text, name, "(<)")) == 1


def _language_tags_as_written(text: str) -> dict[str, str] | None:
    """Each language tag in ``text`` by its lowercase form, as written; None
    when one tag is written two ways, or apart from its literal, and rdflib
    should parse the file.

    A match inside a literal's text can only add a spelling, which then
    conflicts with the real tag's and sends the file to rdflib, so a wrong
    case is never put on a tag.
    """
    spelling: dict[str, str] = {}
    for apart, tag in set(_next_tokens(text, _QUOTE, _LANGUAGE_TAG)):
        if apart:
            return None
        lower = tag.lower()
        if spelling.setdefault(lower, tag) != tag:
            return None
    return spelling


def _next_tokens(text: str, anchor: str, token: str) -> list[tuple[bool, str]]:
    """Each match of ``token`` (a pattern with one group) that follows a match
    of ``anchor`` in ``text``, past white space and comments: whether any
    were in between, and the group.

    Tokens on the anchor's line are matched in a single pass. Only for an
    anchor whose line runs on, blank or into a comment, is what follows read
    further, and each stretch of white space and comments is read once.
    """
    found = re.findall(anchor + r"([ \t]*+)(?:" + token + r"|([#\r\n]))", text)
    tokens = [(bool(blank), value) for blank, value, runs_on in found if not runs_on]
    if len(tokens) < len(found):
        after = re.compile(token)
        for start in _starts_past_lines(text, anchor):
            if match := after.match(text, start):
                tokens.append((True, match.group(1)))
    return tokens


def _starts_past_lines(text: str, anchor: str) -> Iterator[int]:
    """For each match of ``anchor`` whose line runs on, blank or into a
    comment, where the next token starts.

    A match that falls inside a comment of the stretch read before it is
    followed by a ``#`` or a line end within that stretch, so what follows it
    starts where the stretch ends, and no stretch is read twice.
    """
    stretch_end = -1
    for match in re.finditer(anchor + r"[ \t]*+(?=[#\r\n])", text):
        start = match.end()
        if start >= stretch_end:
            skipped = _SKIP.match(text, start)
            stretch_end = skipped.end() if skipped else start
        yield stretch_end


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
                written = spelling.get(node.language)
                if written is None:
                    raise _LeaveToRdflib("a language tag not found as written")
                return Literal(node.value, lang=written)
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

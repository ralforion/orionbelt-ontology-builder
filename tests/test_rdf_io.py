"""Parsing through Oxigraph gives exactly rdflib's result, or rdflib parses.

A load must never differ by which parser ran: the same triples (blank nodes
compared by structure) and the same prefix bindings, on every bundled sample,
in Turtle and in N-Triples, and on a file built for the corners where the two
parsers part ways.
"""

from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDFS

from orionbelt_ontology_builder import rdf_io
from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.rdf_io import parse_into

SAMPLES = (
    Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "samples"
)
FORMATS = {".ttl": "turtle", ".owl": "xml", ".rdf": "xml"}
SAMPLE_FILES = sorted(p for p in SAMPLES.rglob("*") if p.suffix in FORMATS)

EDGES = """\
@prefix : <http://ex.org/e#> .
@prefix ex: <http://ex.org/e#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix geo: <http://example.org/geo/> .
@base <http://ex.org/base/> .

:A a owl:Class ; rdfs:label "Ä café"@EN-us, "plain", 'single', \"\"\"long
multi-line "quoted" text\"\"\" , "tab\\there \\u00e9 \\U0001F600"@de .
:B rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; owl:someValuesFrom :A ] .
:C owl:unionOf ( :A :B ) .
:n :int 1 ; :dec 1.50 ; :dbl 1.0e3 ; :neg -0 ; :bool true , false ;
   :lead "007"^^xsd:integer ; :date "2026-11-11"^^xsd:date .
<rel> :p <other#x> .
geo:place :p _:b1 . _:b1 :q _:b1 .
:D :empty "" ; :lang ""@en .
"""


def _both(fmt: str, *, data: str | None = None, path: Path | None = None):
    by_rdflib = Graph()
    if path is not None:
        by_rdflib.parse(str(path), format=fmt)
    else:
        by_rdflib.parse(data=data, format=fmt)
    ours = Graph()
    used = parse_into(ours, fmt, data=data, path=path)
    return by_rdflib, ours, used


def _assert_same(by_rdflib: Graph, ours: Graph) -> None:
    assert isomorphic(by_rdflib, ours)
    assert sorted((p, str(n)) for p, n in by_rdflib.namespaces()) == sorted(
        (p, str(n)) for p, n in ours.namespaces()
    )


@pytest.mark.parametrize(
    "path", SAMPLE_FILES, ids=[str(p.relative_to(SAMPLES)) for p in SAMPLE_FILES]
)
def test_a_sample_parses_alike(path, tmp_path):
    fmt = FORMATS[path.suffix]
    if fmt == "turtle":
        _assert_same(*_both("turtle", path=path)[:2])
    nt = tmp_path / "sample.nt"
    Graph().parse(str(path), format=fmt).serialize(
        str(nt), format="nt", encoding="utf-8"
    )
    _assert_same(*_both("nt", path=nt)[:2])


def test_the_samples_take_the_fast_path_where_they_can(tmp_path):
    """Not only the fallback being exercised: these have no explicit
    ^^xsd:string. gUFO declares a base and has IRI-like text in a comment
    (``<38.8897,-77.0089>``); PROV-O has ``^^xsd:dateTime`` in the text of a
    comment, which in N-Triples names no declared prefix."""
    for name in ("prov-o.ttl", "gufo/gufo.ttl", "skos-showcase.ttl"):
        assert parse_into(Graph(), "turtle", path=SAMPLES / name), name
        nt = tmp_path / "sample.nt"
        Graph().parse(SAMPLES / name, format="turtle").serialize(
            str(nt), format="nt", encoding="utf-8"
        )
        assert parse_into(Graph(), "nt", path=nt), f"{name} as N-Triples"


def test_the_corners_parse_alike_through_oxigraph():
    by_rdflib, ours, used = _both("turtle", data=EDGES)
    assert used
    _assert_same(by_rdflib, ours)


def test_a_language_tag_keeps_the_case_it_was_written_in():
    """Oxigraph lowercases tags; rdflib keeps them, and so must a load."""
    g = Graph()
    assert parse_into(g, "turtle", data='<http://e/a> <http://e/b> "x"@en-GB .')
    (literal,) = g.objects()
    assert literal.language == "en-GB"


def test_a_tag_written_two_ways_goes_to_rdflib():
    data = '<http://e/a> <http://e/b> "x"@en-GB . <http://e/a> <http://e/c> "y"@en-gb .'
    by_rdflib, ours, used = _both("turtle", data=data)
    assert not used
    _assert_same(by_rdflib, ours)


XSD_STRING = URIRef("http://www.w3.org/2001/XMLSchema#string")
XSD_DECL = "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
STRING_TYPED = {
    "prefixed": XSD_DECL + '<http://e/a> <http://e/b> "x"^^xsd:string , "x" .',
    "comment after ^^": XSD_DECL
    + '<http://e/a> <http://e/b> "x"^^ # note\n xsd:string , "x" .',
    "full IRI": '<http://e/a> <http://e/b> "x"^^<http://www.w3.org/2001/XMLSchema#string> .',
    "escaped IRI": '<http://e/a> <http://e/b> "x"^^<http://www.w3.org/2001/XMLSchema#\\u0073tring> .',
    "another prefix": "@prefix t: <http://www.w3.org/2001/XMLSchema#> .\n"
    '<http://e/a> <http://e/b> "x"^^t:string .',
    "empty prefix": "@prefix : <http://www.w3.org/2001/XMLSchema#> .\n"
    '<http://e/a> <http://e/b> "x"^^:string .',
    "split across prefix and name": "@prefix s: <http://www.w3.org/2001/XMLSchema#str> .\n"
    '<http://e/a> <http://e/b> "x"^^s:ing .',
    "escaped local name": "@prefix s: <http://www.w3.org/2001/XMLSchema> .\n"
    '<http://e/a> <http://e/b> "x"^^s:\\#string .',
    "prefix redefined after use": "@prefix s: <http://www.w3.org/2001/XMLSchema#str> .\n"
    '<http://e/a> <http://e/b> "x"^^s:ing .\n@prefix s: <http://e/> .',
    "relative under a base": "@base <http://www.w3.org/2001/XMLSchema> .\n"
    '<http://e/a> <http://e/b> "x"^^<#string> .',
    "N-Triples": '<http://e/a> <http://e/b> "x"^^<http://www.w3.org/2001/XMLSchema#string> .\n',
}


@pytest.mark.parametrize("spelling", STRING_TYPED)
def test_an_xsd_string_datatype_however_written_goes_to_rdflib(spelling):
    """RDF 1.1 makes "a" and "a"^^xsd:string one term and Oxigraph reports
    both alike; rdflib keeps them apart, so these must come out as rdflib's."""
    fmt = "nt" if spelling == "N-Triples" else "turtle"
    by_rdflib, ours, used = _both(fmt, data=STRING_TYPED[spelling])
    assert set(ours) == set(by_rdflib)
    assert any(o.datatype == XSD_STRING for o in ours.objects())
    assert not used


def test_other_datatypes_keep_the_fast_path():
    data = (
        XSD_DECL + "@prefix ex: <http://e/> .\n"
        'ex:a ex:b "1"^^xsd:integer, "x"^^ex:string2, "2026-11-11"^^xsd:date ;'
        ' ex:c "y"^^<http://e/dt> ; ex:d "has ^^xsd:string in its text" .'
    )
    by_rdflib, ours, used = _both("turtle", data=data)
    _assert_same(by_rdflib, ours)
    assert not used  # the text mentions ^^xsd:string, which is read as one
    data = data.replace("has ^^xsd:string in its text", "plain")
    by_rdflib, ours, used = _both("turtle", data=data)
    _assert_same(by_rdflib, ours)
    assert used


def test_numbers_in_shorthand_come_out_as_rdflib_writes_them():
    """rdflib normalizes ``+1`` to ``1`` and ``1E3`` to ``1000.0``; Oxigraph
    reports them as written, and the conversion normalizes them alike."""
    data = "<http://e/a> <http://e/b> +1, .5, 1E3, -.5e-3, 0.0, true, 007 ."
    by_rdflib, ours, used = _both("turtle", data=data)
    assert used
    assert set(ours) == set(by_rdflib)


def test_a_relative_iri_without_a_base_goes_to_rdflib():
    by_rdflib, ours, used = _both("turtle", data="<a> <http://e/b> <c> .")
    assert not used
    _assert_same(by_rdflib, ours)


#: RFC 3986 section 5.4 reference resolution examples, against its base.
RFC_REFERENCES = [
    "g:h", "g", "./g", "g/", "/g", "//g", "?y", "g?y", "#s", "g#s", "g?y#s",
    ";x", "g;x", "g;x?y#s", "", ".", "./", "..", "../", "../g", "../..",
    "../../", "../../g", "../../../g", "../../../../g", "/./g", "/../g", "g.",
    ".g", "g..", "..g", "./../g", "./g/.", "g/./h", "g/../h", "g;x=1/./y",
    "g;x=1/../y", "g?y/./x", "g?y/../x", "g#s/./x", "g#s/../x",
]  # fmt: skip


@pytest.mark.parametrize("reference", RFC_REFERENCES)
def test_a_relative_iri_under_a_base_comes_out_as_rdflib_resolves_it(reference):
    """rdflib's resolution departs from RFC 3986 for some of these (``?y``,
    ``g/../h``), and Oxigraph follows the RFC. Those go to rdflib; the rest
    keep the fast path."""
    data = (
        "@base <http://a/b/c/d;p?q> .\n"
        f"@prefix r: <{reference}> .\n<http://e/s> <http://e/p> <{reference}> ."
    )
    by_rdflib, ours, used = _both("turtle", data=data)
    _assert_same(by_rdflib, ours)
    if reference in ("g", "#s", "../g", "g?y"):
        assert used


def test_two_bases_and_a_relative_iri_go_to_rdflib():
    data = (
        "@base <http://a/x/> .\n<s> <http://e/p> <o> .\n"
        "@base <http://b/y/> .\n<s> <http://e/p> <o> ."
    )
    by_rdflib, ours, used = _both("turtle", data=data)
    assert not used
    _assert_same(by_rdflib, ours)


def test_a_language_tag_set_apart_fails_as_rdflib_fails():
    """Oxigraph takes ``"x" @en-GB`` and lowercases the tag; rdflib rejects
    it. A load must not start accepting it in a different form."""
    for data in (
        '<http://e/a> <http://e/b> "x" @en-GB .',
        '<http://e/a> <http://e/b> "x" # note\n @en-GB .',
    ):
        with pytest.raises(Exception) as by_rdflib:
            Graph().parse(data=data, format="turtle")
        with pytest.raises(type(by_rdflib.value)):
            parse_into(Graph(), "turtle", data=data)


def test_a_crlf_inside_a_long_string_survives_a_load_from_a_file(tmp_path):
    """rdflib parses a file from its bytes and keeps the CRLF; reading the
    file in text mode turned it into LF, so the same content loaded from a
    file and from a string differed, and a re-import showed it as changed."""
    path = tmp_path / "crlf.ttl"
    path.write_bytes(b'@prefix ex: <http://e/> .\r\nex:a ex:b """one\r\ntwo""" .\r\n')
    from_file = OntologyManager()
    from_file.load_from_file(str(path), format="turtle")
    from_string = OntologyManager()
    from_string.load_from_string(path.read_bytes().decode("utf-8"), "turtle")
    by_rdflib = Graph().parse(str(path), format="turtle")
    assert set(from_file.graph) == set(from_string.graph) == set(by_rdflib)
    assert [str(o) for o in from_file.graph.objects()] == ["one\r\ntwo"]
    assert parse_into(Graph(), "turtle", path=path)


def test_rdf_xml_goes_to_rdflib():
    assert not parse_into(Graph(), "xml", path=SAMPLES / "pizza.owl")


def test_a_broken_file_fails_as_rdflib_fails_and_leaves_the_graph_alone():
    g = Graph()
    g.add((URIRef("http://e/kept"), RDFS.label, Literal("kept")))
    with pytest.raises(Exception) as by_rdflib:
        Graph().parse(data="<http://e/a> <http://e/b> .", format="turtle")
    with pytest.raises(type(by_rdflib.value)):
        parse_into(g, "turtle", data="<http://e/a> <http://e/b> .")
    assert len(g) == 1


def test_the_engine_loads_through_it(monkeypatch):
    calls = []
    real = rdf_io._parse_with_oxigraph

    def spying(text, fmt):
        result = real(text, fmt)
        calls.append(result is not None)
        return result

    monkeypatch.setattr(rdf_io, "_parse_with_oxigraph", spying)
    om = OntologyManager()
    om.load_from_file(str(SAMPLES / "prov-o.ttl"), format="turtle")
    reference = OntologyManager()
    monkeypatch.setattr(rdf_io, "_parse_with_oxigraph", lambda text, fmt: None)
    reference.load_from_file(str(SAMPLES / "prov-o.ttl"), format="turtle")
    assert calls == [True]
    _assert_same(reference.graph, om.graph)
    assert om.get_classes() == reference.get_classes()

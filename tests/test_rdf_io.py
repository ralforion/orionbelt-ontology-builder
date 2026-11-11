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
    ^^xsd:string and are Turtle."""
    for name in ("prov-o.ttl", "gufo/gufo.ttl", "skos-showcase.ttl"):
        assert parse_into(Graph(), "turtle", path=SAMPLES / name), name


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


def test_an_explicit_xsd_string_goes_to_rdflib():
    """RDF 1.1 makes "a" and "a"^^xsd:string one term; rdflib does not."""
    data = (
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        '<http://e/a> <http://e/b> "x"^^xsd:string .'
    )
    by_rdflib, ours, used = _both("turtle", data=data)
    assert not used
    assert set(ours) == set(by_rdflib)


def test_a_relative_iri_goes_to_rdflib():
    by_rdflib, ours, used = _both("turtle", data="<a> <http://e/b> <c> .")
    assert not used
    _assert_same(by_rdflib, ours)


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

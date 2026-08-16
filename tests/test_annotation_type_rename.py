"""Renaming a custom annotation type (issue #287).

Doing it by hand means replacing every ``ns1:<name>`` in the Turtle, which only
works while the file uses a single prefix for the type. The engine moves every
triple that mentions it instead, and refuses the two renames that would quietly
destroy meaning: forking a standard vocabulary term, and merging into a name
that is already taken.
"""

import pytest
from rdflib import OWL, RDF, RDFS, Literal, URIRef

from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://test.org/ont#"


@pytest.fixture
def annotated_om(populated_om):
    """Two resources carrying the same custom annotation type."""
    populated_om.add_annotation("Person", "wikidataId", "Q215627")
    populated_om.add_annotation("Organization", "wikidataId", "Q43229")
    return populated_om


# --- the rename itself ------------------------------------------------------


def test_rename_moves_every_annotation(annotated_om):
    assert annotated_om.rename_annotation_property("wikidataId", "wikidataItem")

    for resource, value in (("Person", "Q215627"), ("Organization", "Q43229")):
        anns = annotated_om.get_annotations(resource)
        assert any(
            a["predicate"] == "wikidataItem" and a["value"] == value for a in anns
        ), anns
        assert not any(a["predicate"] == "wikidataId" for a in anns), anns


def test_rename_moves_the_declaration(annotated_om):
    annotated_om.rename_annotation_property("wikidataId", "wikidataItem")
    assert (
        URIRef(NS + "wikidataItem"),
        RDF.type,
        OWL.AnnotationProperty,
    ) in annotated_om.graph
    assert (URIRef(NS + "wikidataId"), None, None) not in annotated_om.graph
    assert (None, URIRef(NS + "wikidataId"), None) not in annotated_om.graph


def test_rename_moves_references_to_the_type(annotated_om):
    """A statement pointing *at* the type follows it, not just its uses."""
    annotated_om.graph.add(
        (URIRef(NS + "otherId"), RDFS.subPropertyOf, URIRef(NS + "wikidataId"))
    )
    annotated_om.rename_annotation_property("wikidataId", "wikidataItem")
    assert (
        URIRef(NS + "otherId"),
        RDFS.subPropertyOf,
        URIRef(NS + "wikidataItem"),
    ) in annotated_om.graph


def test_rename_moves_a_triple_that_mentions_the_type_twice(annotated_om):
    """A triple can name the type in two positions at once. Rewriting one
    position at a time left the old URI standing in the other."""
    old, new = URIRef(NS + "wikidataId"), URIRef(NS + "wikidataItem")
    annotated_om.graph.add((old, RDFS.seeAlso, old))  # subject and object
    annotated_om.graph.add((old, old, Literal("self-annotated")))  # and predicate

    annotated_om.rename_annotation_property("wikidataId", "wikidataItem")

    assert (new, RDFS.seeAlso, new) in annotated_om.graph
    assert (new, new, Literal("self-annotated")) in annotated_om.graph
    assert (old, None, None) not in annotated_om.graph
    assert (None, old, None) not in annotated_om.graph
    assert (None, None, old) not in annotated_om.graph


def test_rename_accepts_the_full_uri_as_the_old_name(annotated_om):
    assert annotated_om.rename_annotation_property(NS + "wikidataId", "wikidataItem")
    assert any(
        a["predicate"] == "wikidataItem" for a in annotated_om.get_annotations("Person")
    )


def test_rename_to_the_same_name_is_a_no_op(annotated_om):
    before = len(annotated_om.graph)
    assert annotated_om.rename_annotation_property("wikidataId", "wikidataId")
    assert len(annotated_om.graph) == before


def test_a_type_from_another_vocabulary_cannot_be_renamed(populated_om):
    """Only this ontology's own types. Renaming a term of an imported (or bound
    external) vocabulary would fork that vocabulary, not rename anything."""
    populated_om.add_prefix("ex", "http://example.org/vocab#")
    populated_om.add_annotation("Person", "ex:ticket", "OB-1")

    with pytest.raises(ValueError, match="another vocabulary"):
        populated_om.rename_annotation_property("ex:ticket", "issueKey")
    assert not any(
        t["local_name"] == "ticket"
        for t in populated_om.get_custom_annotation_properties()
    )


def test_rename_to_a_curie_moves_the_type(populated_om):
    populated_om.add_prefix("ex", "http://example.org/vocab#")
    populated_om.add_annotation("Person", "wikidataId", "Q5")

    assert populated_om.rename_annotation_property("wikidataId", "ex:wikidataId")
    anns = populated_om.get_annotations("Person")
    assert any(
        a["predicate_uri"] == "http://example.org/vocab#wikidataId" for a in anns
    ), anns


def test_a_standard_name_is_not_a_merge_into_that_vocabulary(annotated_om):
    """'label' names a new type here — renaming must never fold a custom type
    into rdfs:label, which would silently relabel every annotated resource."""
    assert annotated_om.rename_annotation_property("wikidataId", "label")
    anns = annotated_om.get_annotations("Person")
    assert any(a["predicate_uri"] == NS + "label" for a in anns), anns
    assert not any(
        a["predicate_uri"] == str(RDFS.label) for a in anns if a["value"] == "Q215627"
    )


# --- what it refuses --------------------------------------------------------


def test_a_standard_type_cannot_be_renamed(populated_om):
    populated_om.add_annotation("Person", "comment", "A human being")
    with pytest.raises(ValueError, match="another vocabulary"):
        populated_om.rename_annotation_property("comment", "remark")
    anns = populated_om.get_annotations("Person")
    assert any(a["predicate"] == "comment" for a in anns), anns


def test_renaming_onto_a_standard_term_is_refused(annotated_om):
    with pytest.raises(ValueError, match="standard vocabulary"):
        annotated_om.rename_annotation_property("wikidataId", "rdfs:label")
    assert any(
        a["predicate"] == "wikidataId" for a in annotated_om.get_annotations("Person")
    )


def test_an_invalid_name_is_refused(annotated_om):
    with pytest.raises(ValueError, match="wikidata id"):
        annotated_om.rename_annotation_property("wikidataId", "wikidata id")


def test_an_unbound_prefix_is_refused(annotated_om):
    with pytest.raises(ValueError, match="wdt"):
        annotated_om.rename_annotation_property("wikidataId", "wdt:P31")


def test_a_taken_name_is_refused(annotated_om):
    """Renaming onto an existing annotation type would merge the two."""
    annotated_om.add_annotation("Person", "ticketId", "OB-1")
    assert annotated_om.rename_annotation_property("wikidataId", "ticketId") is False
    anns = annotated_om.get_annotations("Person")
    assert any(a["predicate"] == "wikidataId" for a in anns), anns
    assert any(a["predicate"] == "ticketId" for a in anns), anns


def test_a_name_used_by_an_entity_is_refused(annotated_om):
    assert (
        annotated_om.rename_annotation_property("wikidataId", "Organization") is False
    )
    assert (
        URIRef(NS + "wikidataId"),
        RDF.type,
        OWL.AnnotationProperty,
    ) in annotated_om.graph


# --- the list the UI offers -------------------------------------------------


def test_custom_types_are_listed_with_their_usage(annotated_om):
    listed = annotated_om.get_custom_annotation_properties()
    entry = next(t for t in listed if t["local_name"] == "wikidataId")
    assert entry["uri"] == NS + "wikidataId"
    assert entry["usage"] == 2
    assert entry["display"].endswith("wikidataId")


def test_standard_types_are_not_listed(annotated_om):
    annotated_om.add_annotation("Person", "comment", "A human being")
    annotated_om.add_annotation("Person", "skos:example", "an example")
    listed = {t["local_name"] for t in annotated_om.get_custom_annotation_properties()}
    assert "comment" not in listed
    assert "example" not in listed


def test_properties_are_not_listed_as_annotation_types(annotated_om):
    """An object/data property assertion reads as an annotation here, but it is
    renamed on the Properties page — listing it would offer two renames with
    different rules for the same thing."""
    annotated_om.add_individual_property("alice", "worksFor", "acme")
    listed = {t["local_name"] for t in annotated_om.get_custom_annotation_properties()}
    assert "worksFor" not in listed


def test_a_declared_but_unused_type_is_still_listed(annotated_om):
    annotated_om.delete_annotation("Person", "wikidataId", "Q215627")
    annotated_om.delete_annotation("Organization", "wikidataId", "Q43229")
    listed = annotated_om.get_custom_annotation_properties()
    entry = next(t for t in listed if t["local_name"] == "wikidataId")
    assert entry["usage"] == 0


def test_an_undeclared_type_from_a_loaded_file_is_listed():
    """A type that arrived without an owl:AnnotationProperty declaration is
    still this ontology's own, and still renameable."""
    ttl = """
    @prefix ns1: <http://acme.example/ont#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    <http://acme.example/ont> a owl:Ontology .
    ns1:Widget a owl:Class ; ns1:partNumber "W-1" .
    """
    om = OntologyManager()
    om.load_from_string(ttl, "turtle")
    listed = {t["local_name"] for t in om.get_custom_annotation_properties()}
    assert "partNumber" in listed
    assert om.rename_annotation_property("http://acme.example/ont#partNumber", "sku")
    anns = om.get_annotations("http://acme.example/ont#Widget")
    assert any(a["predicate"] == "sku" and a["value"] == "W-1" for a in anns), anns


def test_rename_survives_a_round_trip(annotated_om):
    annotated_om.rename_annotation_property("wikidataId", "wikidataItem")
    reloaded = OntologyManager(base_uri=NS)
    reloaded.load_from_string(annotated_om.export_to_string("turtle"), "turtle")
    anns = reloaded.get_annotations("Person")
    assert any(
        a["predicate"] == "wikidataItem" and a["value"] == "Q215627" for a in anns
    ), anns

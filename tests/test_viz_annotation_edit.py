"""Editing an annotation from the Visualization graph (issue #223).

An annotation has no URI of its own, so a graph node can only point back at it
by naming its parts. Two things decide whether that works: the identity has to
survive a rebuild, and rewriting the triple must not lose anything the user did
not touch.
"""

import pytest

from orionbelt_ontology_builder.app import (
    _apply_annotation_edit,
    annotation_ename,
    annotation_matches_ename,
)
from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://ex.org/o#"
DCT = "http://purl.org/dc/terms/"


def _ont():
    ont = OntologyManager(NS)
    ont.add_class("Person")
    return ont


def _ann(ont, predicate):
    return next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate_uri"] == predicate
    )


# --- identity ---------------------------------------------------------------


def test_the_identity_is_content_derived_not_positional():
    """Node ids used to be numbered in iteration order, so adding an annotation
    renamed the ones after it and a click could not be resolved."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "second")
    first = annotation_ename(NS + "Person", _ann(ont, DCT + "source"))

    ont.add_annotation(NS + "Person", DCT + "creator", "aaa-sorts-first")
    assert annotation_ename(NS + "Person", _ann(ont, DCT + "source")) == first


def test_two_values_of_one_predicate_are_told_apart():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "one")
    ont.add_annotation(NS + "Person", DCT + "source", "two")
    names = {
        annotation_ename(NS + "Person", a) for a in ont.get_annotations(NS + "Person")
    }
    assert len(names) == len(ont.get_annotations(NS + "Person"))


def test_the_language_tag_is_part_of_the_identity():
    """Same predicate and same string, different tag: different annotations."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "title", "Bank", lang="en")
    ont.add_annotation(NS + "Person", DCT + "title", "Bank", lang="de")
    anns = [a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "title"]
    assert len({annotation_ename(NS + "Person", a) for a in anns}) == 2


def test_an_annotation_matches_only_its_own_name():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "one")
    ont.add_annotation(NS + "Person", DCT + "source", "two")
    a, b = (a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "source")
    parts = tuple(annotation_ename(NS + "Person", a).split("\x1f"))
    assert annotation_matches_ename(NS + "Person", a, parts)
    assert not annotation_matches_ename(NS + "Person", b, parts)


# --- rewriting --------------------------------------------------------------


def test_editing_the_value_rewrites_the_triple():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "old")
    assert _apply_annotation_edit(
        ont, NS + "Person", _ann(ont, DCT + "source"), DCT + "source", "new", ""
    )
    assert _ann(ont, DCT + "source")["value"] == "new"


def test_an_unchanged_edit_reports_no_change():
    """So the caller does not take an undo checkpoint for a no-op."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "same")
    ann = _ann(ont, DCT + "source")
    assert not _apply_annotation_edit(
        ont, NS + "Person", ann, DCT + "source", "same", ""
    )


def test_a_datatype_survives_an_edit_of_the_value():
    """The engine had no way to re-add a typed literal, so a rewrite used to
    drop ``^^xsd:date`` the user never touched."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "created", "2024-01-01", datatype="date")
    ann = _ann(ont, DCT + "created")
    assert ann["datatype"] == "date"

    assert _apply_annotation_edit(
        ont, NS + "Person", ann, DCT + "created", "2025-02-02", ""
    )
    after = _ann(ont, DCT + "created")
    assert after["value"] == "2025-02-02"
    assert after["datatype"] == "date"


def test_a_language_tag_survives_an_edit_of_the_value():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "title", "Hello", lang="en")
    ann = _ann(ont, DCT + "title")
    assert _apply_annotation_edit(ont, NS + "Person", ann, DCT + "title", "Hallo", "de")
    after = _ann(ont, DCT + "title")
    assert (after["value"], after["language"]) == ("Hallo", "de")


def test_a_rejected_predicate_puts_the_original_back():
    """The rewrite is a delete then an add, so a rejected add must not leave the
    user with neither."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "keepme")
    ann = _ann(ont, DCT + "source")

    assert not _apply_annotation_edit(
        ont, NS + "Person", ann, "nosuchprefix:thing", "changed", ""
    )
    survived = _ann(ont, DCT + "source")
    assert survived["value"] == "keepme"


def test_a_rejected_predicate_does_not_duplicate_the_original():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "keepme")
    ann = _ann(ont, DCT + "source")
    _apply_annotation_edit(ont, NS + "Person", ann, "nosuchprefix:thing", "changed", "")
    assert (
        len(
            [
                a
                for a in ont.get_annotations(NS + "Person")
                if a["predicate"] == "source"
            ]
        )
        == 1
    )


# --- the engine gap this needed ---------------------------------------------


@pytest.mark.parametrize("dt", ["date", "integer", "boolean"])
def test_add_annotation_can_now_write_a_typed_literal(dt):
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "x", "1", datatype=dt)
    assert _ann(ont, DCT + "x")["datatype"] == dt


def test_a_language_tag_wins_over_a_datatype():
    """RDF literals carry one or the other, never both."""
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "y", "v", lang="en", datatype="date")
    ann = _ann(ont, DCT + "y")
    assert ann.get("language") == "en"
    assert not ann.get("datatype")


# --- review follow-ups: what the identity and the rewrite must not lose ------


CUSTOM_DT = "http://types.example/a#Thing"
SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"


def _typed(ont, value, datatype):
    from rdflib import Literal, URIRef

    ont.graph.add(
        (
            ont._uri("Person"),
            URIRef(DCT + "x"),
            Literal(value, datatype=URIRef(datatype)),
        )
    )


def _resource(ont, value):
    from rdflib import URIRef

    ont.graph.add((ont._uri("Person"), URIRef(SEE_ALSO), URIRef(value)))


def test_a_non_xsd_datatype_is_exposed_as_a_full_uri():
    """The display local name does not resolve back, so acting on it is wrong."""
    ont = _ont()
    _typed(ont, "v", CUSTOM_DT)
    ann = _ann(ont, DCT + "x")
    assert ann["datatype"] == "Thing"
    assert ann["datatype_uri"] == CUSTOM_DT


def test_editing_a_custom_datatype_does_not_orphan_the_original():
    """Deleting by the local name matched nothing and re-adding minted a
    relative ``^^<Thing>``, leaving two triples where there was one."""
    ont = _ont()
    _typed(ont, "v", CUSTOM_DT)
    assert _apply_annotation_edit(
        ont, NS + "Person", _ann(ont, DCT + "x"), DCT + "x", "v2", ""
    )
    objs = list(
        ont.graph.objects(ont._uri("Person"), __import__("rdflib").URIRef(DCT + "x"))
    )
    assert len(objs) == 1
    assert str(objs[0]) == "v2"
    assert str(objs[0].datatype) == CUSTOM_DT


def test_a_resource_valued_annotation_is_flagged():
    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )
    assert ann["is_uri"] is True


def test_editing_a_resource_valued_annotation_keeps_it_a_resource():
    """A literal delete never matched the IRI object, and the replacement was
    written as a string, so the original survived beside a copy of itself."""
    from rdflib import URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )
    assert _apply_annotation_edit(
        ont, NS + "Person", ann, SEE_ALSO, "http://docs.example/other", ""
    )
    objs = list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))
    assert [(type(o).__name__, str(o)) for o in objs] == [
        ("URIRef", "http://docs.example/other")
    ]


def test_deleting_a_resource_valued_annotation_actually_removes_it():
    """It used to report success having removed nothing."""
    from rdflib import URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )
    ont.delete_annotation(
        NS + "Person", ann["predicate_uri"], ann["value"], value_is_uri=True
    )
    assert not list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))


def test_a_resource_and_a_literal_spelling_the_same_iri_are_different_annotations():
    """So a click on one cannot resolve to the other."""
    from rdflib import Literal, URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ont.graph.add(
        (ont._uri("Person"), URIRef(SEE_ALSO), Literal("http://docs.example/person"))
    )
    anns = [
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    ]
    assert len({annotation_ename(NS + "Person", a) for a in anns}) == 2


# --- an IRI object has to be storable ---------------------------------------


def test_an_unusable_iri_is_refused_rather_than_stored():
    """rdflib takes any string as a URIRef and only objects at serialization, so
    one bad edit would break every export of the whole ontology, long after the
    edit that caused it."""
    from rdflib import URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )

    assert not _apply_annotation_edit(
        ont, NS + "Person", ann, SEE_ALSO, "not a uri with spaces", ""
    )
    objs = list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))
    assert [str(o) for o in objs] == ["http://docs.example/person"]


def test_the_ontology_still_serializes_after_a_refused_iri_edit():
    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )
    _apply_annotation_edit(ont, NS + "Person", ann, SEE_ALSO, "has spaces", "")
    assert "docs.example/person" in ont.export_to_string("turtle")


@pytest.mark.parametrize(
    "bad", ["has spaces", "angle<brackets>", 'quote"mark', "brace{s}", "", "   "]
)
def test_add_annotation_rejects_an_unserializable_resource_value(bad):
    ont = _ont()
    with pytest.raises(ValueError):
        ont.add_annotation(NS + "Person", SEE_ALSO, bad, value_is_uri=True)


@pytest.mark.parametrize(
    "good", ["http://a.example/x", "urn:isbn:0451450523", "mailto:a@b.example"]
)
def test_a_usable_iri_is_still_accepted(good):
    ont = _ont()
    ont.add_annotation(NS + "Person", SEE_ALSO, good, value_is_uri=True)
    assert ont.export_to_string("turtle")


# --- deleting without knowing the object kind -------------------------------


def test_a_delete_that_does_not_say_the_kind_matches_a_resource_too():
    """The bulk editor's table has no column for it, so it deleted nothing and
    reported success."""
    from rdflib import URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    ont.delete_annotation(NS + "Person", SEE_ALSO, "http://docs.example/person")
    assert not list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))


def test_bulk_delete_removes_a_resource_valued_annotation():
    from rdflib import URIRef

    ont = _ont()
    _resource(ont, "http://docs.example/person")
    result = ont.bulk_update_annotations(
        [
            {
                "resource": "Person",
                "predicate": SEE_ALSO,
                "value": "http://docs.example/person",
                "action": "delete",
            }
        ]
    )
    assert result == {"applied": 1, "errors": []}
    assert not list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))


def test_a_literal_delete_is_unaffected_by_the_widened_match():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "plain")
    ont.delete_annotation(NS + "Person", DCT + "source", "plain")
    assert not [
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "source"
    ]


# --- moving an annotation to another resource (issue #251) -------------------


def _subject_options(ont):
    from orionbelt_ontology_builder.app import annotation_subject_options

    return annotation_subject_options(
        ont.get_classes(),
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
    )


def test_an_annotation_moves_to_another_resource():
    ont = _ont()
    ont.add_class("Org")
    ont.add_annotation(NS + "Person", DCT + "source", "Wikidata Q5")
    ann = _ann(ont, DCT + "source")

    assert _apply_annotation_edit(
        ont,
        NS + "Person",
        ann,
        DCT + "source",
        "Wikidata Q5",
        "",
        new_subject_uri=NS + "Org",
    )
    assert not [
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "source"
    ]
    moved = [a for a in ont.get_annotations(NS + "Org") if a["predicate"] == "source"]
    assert [a["value"] for a in moved] == ["Wikidata Q5"]


def test_a_move_carries_the_datatype():
    """The move is the same delete-then-add, so it must not drop what an edit
    in place already preserves."""
    ont = _ont()
    ont.add_class("Org")
    ont.add_annotation(NS + "Person", DCT + "created", "2024-01-01", datatype="date")
    ann = _ann(ont, DCT + "created")
    assert _apply_annotation_edit(
        ont,
        NS + "Person",
        ann,
        DCT + "created",
        "2024-01-01",
        "",
        new_subject_uri=NS + "Org",
    )
    moved = next(
        a for a in ont.get_annotations(NS + "Org") if a["predicate"] == "created"
    )
    assert moved["datatype"] == "date"


def test_a_move_keeps_a_resource_value_a_resource():
    from rdflib import URIRef

    ont = _ont()
    ont.add_class("Org")
    _resource(ont, "http://docs.example/person")
    ann = next(
        a for a in ont.get_annotations(NS + "Person") if a["predicate"] == "seeAlso"
    )
    assert _apply_annotation_edit(
        ont,
        NS + "Person",
        ann,
        SEE_ALSO,
        "http://docs.example/person",
        "",
        new_subject_uri=NS + "Org",
    )
    objs = list(ont.graph.objects(ont._uri("Org"), URIRef(SEE_ALSO)))
    assert [(type(o).__name__, str(o)) for o in objs] == [
        ("URIRef", "http://docs.example/person")
    ]
    assert not list(ont.graph.objects(ont._uri("Person"), URIRef(SEE_ALSO)))


def test_a_move_to_the_same_resource_is_not_a_change():
    ont = _ont()
    ont.add_annotation(NS + "Person", DCT + "source", "same")
    ann = _ann(ont, DCT + "source")
    assert not _apply_annotation_edit(
        ont,
        NS + "Person",
        ann,
        DCT + "source",
        "same",
        "",
        new_subject_uri=NS + "Person",
    )


def test_a_failed_move_leaves_the_annotation_where_it_was():
    """The add can be rejected after the delete, and the original subject is
    where it has to go back to."""
    ont = _ont()
    ont.add_class("Org")
    ont.add_annotation(NS + "Person", DCT + "source", "keepme")
    ann = _ann(ont, DCT + "source")
    assert not _apply_annotation_edit(
        ont,
        NS + "Person",
        ann,
        "nosuchprefix:thing",
        "keepme",
        "",
        new_subject_uri=NS + "Org",
    )
    assert [
        a["value"]
        for a in ont.get_annotations(NS + "Person")
        if a["predicate"] == "source"
    ] == ["keepme"]
    assert not [
        a for a in ont.get_annotations(NS + "Org") if a["predicate"] == "source"
    ]


def test_the_subject_picker_offers_every_annotatable_kind():
    ont = _ont()
    ont.add_object_property("knows")
    ont.add_data_property("age")
    ont.add_individual("alice", "Person")
    options, lookup = _subject_options(ont)
    assert {lookup[o] for o in options} == {
        NS + "Person",
        NS + "knows",
        NS + "age",
        NS + "alice",
    }


def test_the_picker_says_what_kind_each_resource_is():
    """A property and a class read alike otherwise, and moving an annotation
    onto the wrong one is silent."""
    ont = _ont()
    ont.add_data_property("age")
    options, _ = _subject_options(ont)
    assert {o[o.rindex("[") :] for o in options} == {"[Class]", "[Data Property]"}


def test_the_picker_keys_by_uri_across_namespaces():
    """Two resources sharing a local name are different subjects, and the
    picker has to be able to name both."""
    from rdflib import OWL, RDF, URIRef

    ont = _ont()
    other = URIRef("http://elsewhere.example/o#Person")
    ont.graph.add((other, RDF.type, OWL.Class))
    options, lookup = _subject_options(ont)
    for_person = [o for o in options if o.startswith("Person")]
    assert len(for_person) == 2
    assert len({lookup[o] for o in for_person}) == 2


def test_an_unlisted_subject_is_offered_rather_than_silently_replaced():
    """The picker covers classes, properties and individuals. An annotation on
    anything else would otherwise select the first entry, so saving without
    touching the subject would move the annotation to it."""
    from orionbelt_ontology_builder.app import _uri_option_index

    ont = _ont()
    options, lookup = _subject_options(ont)
    outsider = "http://example.org/ontology#"
    assert outsider not in set(lookup.values())
    # What the editor does when the current subject is not among the options.
    own = f"{outsider} [current]"
    options = [own, *options]
    lookup[own] = outsider
    assert lookup[options[_uri_option_index(options, lookup, outsider)]] == outsider

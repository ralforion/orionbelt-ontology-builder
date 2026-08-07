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

"""Adding individuals and annotations from the graph (issue #221).

Both take their subject from what is selected rather than asking for it again,
so the decision worth pinning is which node yields a usable subject at all, and
that the two pages keep offering the same annotation types.
"""

import pytest

from orionbelt_ontology_builder.app import (
    _uid,
    annotation_predicate_options,
    panel_subject_uri,
)
from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://ex.org/o#"


def _ont():
    ont = OntologyManager(NS)
    ont.add_class("Person")
    ont.add_object_property("knows")
    ont.add_data_property("age")
    ont.add_individual("alice", "Person")
    return ont


def _pools(ont):
    return (
        ont.get_classes(),
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
    )


# --- which selections can be annotated --------------------------------------


@pytest.mark.parametrize(
    ("ntype", "name"),
    [
        ("Class", "Person"),
        ("Object Property", "knows"),
        ("Data Property", "age"),
        ("Individual", "alice"),
    ],
)
def test_an_entity_with_a_uri_yields_a_subject(ntype, name):
    ont = _ont()
    assert panel_subject_uri(ntype, _uid(NS + name), *_pools(ont)) == NS + name


@pytest.mark.parametrize("ntype", ["Class Relation", "Restriction", "Annotation"])
def test_the_kinds_with_no_uri_of_their_own_yield_nothing(ntype):
    """Relations and restrictions are edges, and an annotation is itself a
    triple. None of them is a resource an annotation could hang off."""
    ont = _ont()
    assert panel_subject_uri(ntype, "whatever", *_pools(ont)) is None


def test_nothing_selected_yields_nothing():
    ont = _ont()
    assert panel_subject_uri(None, None, *_pools(ont)) is None


def test_an_entity_that_has_gone_yields_nothing():
    """The selection outlives the graph payload that produced it."""
    ont = _ont()
    assert panel_subject_uri("Class", _uid(NS + "Vanished"), *_pools(ont)) is None


# --- the annotation types both pages offer ----------------------------------


def test_the_standard_types_are_offered():
    options, lookup = annotation_predicate_options(_ont())
    assert "rdfs:seeAlso" in options
    assert "skos:altLabel" in options
    assert all(o in lookup for o in options)


def test_a_type_already_in_the_ontology_is_offered_first():
    """A vocabulary in play stays in play, rather than being buried under the
    standard list."""
    ont = _ont()
    ont.add_annotation(NS + "Person", "http://purl.org/dc/terms/x", "v")
    options, _ = annotation_predicate_options(ont)
    used = [o for o in options if o.endswith(":x") or o == "x"]
    assert used, f"the used predicate is missing from {options[:8]}"


def test_the_lookup_resolves_a_display_back_to_something_addable():
    """What the panel hands to add_annotation has to be usable as a predicate."""
    ont = _ont()
    _, lookup = annotation_predicate_options(ont)
    ont.add_annotation(NS + "Person", lookup["rdfs:seeAlso"], "http://a.example/x")
    assert any(a["predicate"] == "seeAlso" for a in ont.get_annotations(NS + "Person"))


# --- what each add actually writes ------------------------------------------


def test_an_individual_is_typed_by_the_class_it_was_added_from():
    """Added by URI, not by local name: the class may live in another namespace,
    where the name alone would resolve into this ontology's own."""
    ont = _ont()
    ont.add_individual("acme", NS + "Person")
    ind = next(i for i in ont.get_individuals() if i["name"] == "acme")
    assert "Person" in ind["classes"]


def test_an_annotation_lands_on_the_selected_subject():
    ont = _ont()
    subject = panel_subject_uri("Individual", _uid(NS + "alice"), *_pools(ont))
    ont.add_annotation(subject, "http://purl.org/dc/terms/title", "Ms")
    assert [
        a["value"]
        for a in ont.get_annotations(NS + "alice")
        if a["predicate"] == "title"
    ] == ["Ms"]

"""Custom annotation types: a predicate the user invents is usable and declared,
and an unusable one is reported rather than minted into a broken URI (issue #161).
"""

from rdflib import OWL, RDF, URIRef

from orionbelt_ontology_builder.app import (
    annotation_option_for_predicate,
    resolve_annotation_predicate_choice,
)
from orionbelt_ontology_builder.ontology_manager import OntologyManager


def test_custom_predicate_is_stored_and_readable(populated_om):
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    anns = populated_om.get_annotations("Person")
    assert any(a["predicate"] == "wikidataId" and a["value"] == "Q5" for a in anns), (
        anns
    )


def test_custom_predicate_is_declared_as_annotation_property(populated_om):
    """Without a declaration other tools see an undeclared predicate."""
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    pred = URIRef("http://test.org/ont#wikidataId")
    assert (pred, RDF.type, OWL.AnnotationProperty) in populated_om.graph


def test_standard_predicate_is_not_declared_locally(populated_om):
    """rdfs:comment and friends are declared by their own vocabulary."""
    populated_om.add_annotation("Person", "comment", "A human being")
    from rdflib import RDFS

    assert (RDFS.comment, RDF.type, None) not in populated_om.graph


def test_external_prefix_predicate_is_not_declared_locally(populated_om):
    """A bound external vocabulary keeps its own declaration, not ours."""
    populated_om.add_prefix("wdt", "http://www.wikidata.org/prop/direct/")
    populated_om.add_annotation("Person", "wdt:P31", "Q5")
    pred = URIRef("http://www.wikidata.org/prop/direct/P31")
    anns = populated_om.get_annotations("Person")
    assert any(a["value"] == "Q5" for a in anns), anns
    assert (pred, RDF.type, None) not in populated_om.graph


def test_existing_entity_type_is_not_overwritten(populated_om):
    """A name that is already a class must not gain a second type."""
    populated_om.add_annotation("Person", "Organization", "not really an annotation")
    pred = URIRef("http://test.org/ont#Organization")
    types = set(populated_om.graph.objects(pred, RDF.type))
    assert types == {OWL.Class}, types


def test_custom_predicate_roundtrips_through_delete(populated_om):
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    populated_om.delete_annotation("Person", "wikidataId", "Q5")
    anns = populated_om.get_annotations("Person")
    assert not any(a["predicate"] == "wikidataId" for a in anns), anns


def test_custom_predicate_becomes_a_listed_option(populated_om):
    """After first use it shows up alongside the standard predicates."""
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    used = populated_om.get_used_annotation_predicates()
    assert any(p["local_name"] == "wikidataId" for p in used), used


def test_custom_predicate_survives_export(populated_om):
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    ttl = populated_om.export_to_string("turtle")
    reloaded = OntologyManager(base_uri="http://test.org/ont#")
    reloaded.load_from_string(ttl, "turtle")
    anns = reloaded.get_annotations("Person")
    assert any(a["value"] == "Q5" for a in anns), anns


# --- validation -------------------------------------------------------------


def test_valid_predicate_forms_are_accepted(populated_om):
    populated_om.add_prefix("wdt", "http://www.wikidata.org/prop/direct/")
    for predicate in (
        "wikidataId",
        "my-note.v2",
        "comment",
        "wdt:P31",
        "http://example.org/vocab#ticket",
    ):
        assert populated_om.invalid_annotation_predicate_reason(predicate) is None, (
            predicate
        )


def test_unbound_prefix_is_reported_by_name(populated_om):
    reason = populated_om.invalid_annotation_predicate_reason("wdt:P31")
    assert reason and "wdt" in reason and "Namespaces" in reason


def test_empty_predicate_is_reported(populated_om):
    assert populated_om.invalid_annotation_predicate_reason("") is not None
    assert populated_om.invalid_annotation_predicate_reason("   ") is not None
    assert populated_om.invalid_annotation_predicate_reason(None) is not None


def test_bad_name_is_reported(populated_om):
    reason = populated_om.invalid_annotation_predicate_reason("wikidata id")
    assert reason and "wikidata id" in reason


def test_prefix_without_local_name_is_reported(populated_om):
    populated_om.add_prefix("wdt", "http://www.wikidata.org/prop/direct/")
    reason = populated_om.invalid_annotation_predicate_reason("wdt:")
    assert reason and "after the prefix" in reason


def test_uri_with_unserializable_characters_is_reported(populated_om):
    reason = populated_om.invalid_annotation_predicate_reason(
        "http://example.org/a b#x"
    )
    assert reason and "spaces" in reason


# --- the picker's wiring ----------------------------------------------------


def test_listed_choice_resolves_to_its_uri(populated_om):
    lookup = {"rdfs:comment": "comment"}
    predicate, error = resolve_annotation_predicate_choice(
        populated_om, "rdfs:comment", lookup
    )
    assert (predicate, error) == ("comment", None)


def test_typed_choice_is_validated(populated_om):
    predicate, error = resolve_annotation_predicate_choice(
        populated_om, "  wikidataId  ", {}
    )
    assert predicate == "wikidataId"
    assert error is None


def test_typed_choice_with_unbound_prefix_reports_error(populated_om):
    predicate, error = resolve_annotation_predicate_choice(
        populated_om, "wdt:P31", {"rdfs:comment": "comment"}
    )
    assert predicate == "wdt:P31"
    assert error and "wdt" in error


def test_empty_choice_reports_error(populated_om):
    _predicate, error = resolve_annotation_predicate_choice(populated_om, None, {})
    assert error is not None


# --- the guard covers every caller, not just the picker ---------------------


def test_add_annotation_rejects_an_unbound_prefix(populated_om):
    import pytest

    with pytest.raises(ValueError, match="wdt"):
        populated_om.add_annotation("Person", "wdt:P31", "Q5")
    assert not any(a["value"] == "Q5" for a in populated_om.get_annotations("Person"))


def test_bulk_add_reports_an_unbound_prefix_instead_of_minting_a_uri(populated_om):
    """The Bulk Edit tab reaches add_annotation directly, so it must be guarded
    too: an unbound CURIE used to be stored as <base#wdt:P31>."""
    result = populated_om.bulk_update_annotations(
        [{"resource": "Person", "predicate": "wdt:P31", "value": "Q5"}]
    )
    assert result["applied"] == 0
    assert result["errors"] and "wdt" in result["errors"][0]["error"]
    assert not any(
        "wdt:P31" in str(p) for p in populated_om.graph.predicates(None, None)
    )


def test_bulk_add_still_creates_a_valid_custom_type(populated_om):
    result = populated_om.bulk_update_annotations(
        [{"resource": "Person", "predicate": "wikidataId", "value": "Q5"}]
    )
    assert result == {"applied": 1, "errors": []}
    pred = URIRef("http://test.org/ont#wikidataId")
    assert (pred, RDF.type, OWL.AnnotationProperty) in populated_om.graph


def test_bulk_delete_can_still_remove_an_oddly_named_predicate(populated_om):
    """Data minted before the guard has to stay removable."""
    from rdflib import Literal

    bad = URIRef("http://test.org/ont#wdt:P31")
    populated_om.graph.add((URIRef("http://test.org/ont#Person"), bad, Literal("Q5")))

    result = populated_om.bulk_update_annotations(
        [
            {
                "resource": "Person",
                "predicate": "http://test.org/ont#wdt:P31",
                "value": "Q5",
                "action": "delete",
            }
        ]
    )
    assert result["applied"] == 1, result
    assert (URIRef("http://test.org/ont#Person"), bad, None) not in populated_om.graph


# --- re-selecting the type just used ----------------------------------------
#
# After an add, the picker's value is the raw text that was typed while the
# rebuilt options carry the predicate's canonical display, so the just-used type
# has to be found again by the URI it resolves to.


def test_typed_name_finds_its_canonical_option(populated_om):
    populated_om.add_annotation("Person", "wikidataId", "Q5")
    lookup = {
        "rdfs:comment": "comment",
        "test:wikidataId": "http://test.org/ont#wikidataId",
    }
    uri = populated_om.resolve_annotation_predicate("wikidataId")
    assert annotation_option_for_predicate(populated_om, lookup, uri) == (
        "test:wikidataId"
    )


def test_full_uri_and_short_name_find_the_same_option(populated_om):
    lookup = {"skos:example": "example", "rdfs:comment": "comment"}
    uri = populated_om.resolve_annotation_predicate(
        "http://www.w3.org/2004/02/skos/core#example"
    )
    assert annotation_option_for_predicate(populated_om, lookup, uri) == "skos:example"


def test_curie_finds_its_option(populated_om):
    populated_om.add_prefix("wdt", "http://www.wikidata.org/prop/direct/")
    lookup = {"wdt:P31": "http://www.wikidata.org/prop/direct/P31"}
    uri = populated_om.resolve_annotation_predicate("wdt:P31")
    assert annotation_option_for_predicate(populated_om, lookup, uri) == "wdt:P31"


def test_unlisted_predicate_finds_no_option(populated_om):
    lookup = {"rdfs:comment": "comment"}
    uri = populated_om.resolve_annotation_predicate("wikidataId")
    assert annotation_option_for_predicate(populated_om, lookup, uri) is None

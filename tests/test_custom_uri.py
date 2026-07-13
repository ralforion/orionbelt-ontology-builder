"""Tests for custom/arbitrary URI editing and cross-ontology linking to
external URIs (issue #87, part B).

The UI (``_custom_uri_field`` / ``_external_uri_target`` in app.py) only threads
a full URI into the engine's existing rename and relation methods, so these
tests exercise the engine paths those helpers feed.
"""

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontology_manager import OntologyManager

BASE = "http://test.org/ont#"
EXT = "http://other.example/ns#"


def _om():
    return OntologyManager(base_uri=BASE)


# ---- Custom URI rename rewrites every reference position --------------------


def test_rename_class_to_custom_uri_updates_object_position():
    om = _om()
    om.add_class("Animal")
    om.add_class("Dog", parent="Animal")  # Dog subClassOf Animal
    target = EXT + "LivingThing"

    assert om.rename_class("Animal", target) is True

    dog = URIRef(BASE + "Dog")
    assert (dog, RDFS.subClassOf, URIRef(target)) in om.graph
    assert (dog, RDFS.subClassOf, URIRef(BASE + "Animal")) not in om.graph
    assert target in {c["uri"] for c in om.get_classes()}
    assert BASE + "Animal" not in {c["uri"] for c in om.get_classes()}


def test_rename_object_property_to_custom_uri_updates_predicate_position():
    om = _om()
    om.add_class("Person")
    a = om.add_individual("a", "Person")
    b = om.add_individual("b", "Person")
    knows = om.add_object_property("knows")
    om.graph.add((a, knows, b))  # a knows b (property in predicate position)
    target = EXT + "acquaintedWith"

    assert om.rename_property(str(knows), target) is True

    assert (a, URIRef(target), b) in om.graph
    assert (a, knows, b) not in om.graph
    assert target in {p["uri"] for p in om.get_object_properties()}


def test_rename_individual_to_custom_uri_keeps_typing():
    om = _om()
    om.add_class("Person")
    ind = om.add_individual("alice", "Person")
    target = EXT + "Alice"

    assert om.rename_individual(str(ind), target) is True

    assert (URIRef(target), RDF.type, URIRef(BASE + "Person")) in om.graph
    assert target in {i["uri"] for i in om.get_individuals()}


def test_rename_concept_to_custom_uri_updates_broader_link():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Broad", scheme="Scheme")
    om.add_concept("Narrow", scheme="Scheme", broader="Broad")
    target = EXT + "TopConcept"

    assert om.rename_concept("Broad", target) is True

    narrow = URIRef(BASE + "Narrow")
    assert (narrow, SKOS.broader, URIRef(target)) in om.graph
    assert (narrow, SKOS.broader, URIRef(BASE + "Broad")) not in om.graph


def test_rename_concept_scheme_to_custom_uri_updates_inscheme():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Concept", scheme="Scheme")
    target = EXT + "Vocabulary"

    assert om.rename_concept_scheme("Scheme", target) is True

    concept = URIRef(BASE + "Concept")
    assert (concept, SKOS.inScheme, URIRef(target)) in om.graph
    assert (concept, SKOS.inScheme, URIRef(BASE + "Scheme")) not in om.graph


def test_custom_uri_rename_round_trips_through_turtle():
    om = _om()
    om.add_class("Thing")
    target = EXT + "Concept"
    om.rename_class("Thing", target)

    ttl = om.export_to_string(format="turtle")
    om2 = OntologyManager(base_uri=BASE)
    om2.load_from_string(ttl, format="turtle")
    assert target in {c["uri"] for c in om2.get_classes()}


# ---- Custom URI validation --------------------------------------------------


def test_valid_full_uri_accepted():
    assert OntologyManager.invalid_name_reason("http://ex.org/ns#Thing") is None
    assert OntologyManager.invalid_name_reason("https://ex.org/ns/Thing") is None


def test_invalid_custom_uri_rejected():
    # A space makes the IRI unserializable.
    assert OntologyManager.invalid_name_reason("http://ex.org/a b") is not None
    # Angle brackets break Turtle serialization.
    assert OntologyManager.invalid_name_reason("http://ex.org/<x>") is not None


# ---- Cross-ontology linking to an external URI ------------------------------


def test_class_relation_to_external_uri():
    om = _om()
    om.add_class("Organization")
    ext = EXT + "Organization"
    om.add_class_relation(BASE + "Organization", "equivalentClass", ext)

    rels = om.get_class_relations("Organization")
    equ = [r for r in rels if r["relation"] == "equivalentClass"]
    assert any(r["object_uri"] == ext for r in equ)
    assert (URIRef(BASE + "Organization"), OWL.equivalentClass, URIRef(ext)) in om.graph


def test_property_relation_to_external_uri():
    om = _om()
    om.add_object_property("knows")
    ext = EXT + "knows"
    om.add_property_relation(BASE + "knows", "equivalentProperty", ext)

    rels = om.get_property_relations("knows")
    assert any(
        r["relation"] == "equivalentProperty" and r["object_uri"] == ext for r in rels
    )


def test_individual_relation_sameas_external_uri():
    om = _om()
    om.add_class("Person")
    om.add_individual("alice", "Person")
    ext = EXT + "Alice"
    om.add_individual_relation(BASE + "alice", "sameAs", ext)

    rels = om.get_individual_relations("alice")
    assert any(r["relation"] == "sameAs" and r["object_uri"] == ext for r in rels)
    assert (URIRef(BASE + "alice"), OWL.sameAs, URIRef(ext)) in om.graph


def test_external_relation_round_trips_through_turtle():
    om = _om()
    om.add_class("Organization")
    ext = EXT + "Organization"
    om.add_class_relation(BASE + "Organization", "equivalentClass", ext)

    ttl = om.export_to_string(format="turtle")
    om2 = OntologyManager(base_uri=BASE)
    om2.load_from_string(ttl, format="turtle")
    assert (
        URIRef(BASE + "Organization"),
        OWL.equivalentClass,
        URIRef(ext),
    ) in om2.graph


# ---- External-references validation notice ----------------------------------


def _external_issues(om):
    return [i for i in om.validate() if i["type"] == "external_reference"]


def test_validate_flags_external_reference():
    om = _om()
    om.add_class("Organization")
    ext = EXT + "Organization"
    om.add_class_relation(BASE + "Organization", "equivalentClass", ext)

    ext_issues = _external_issues(om)
    assert len(ext_issues) == 1
    assert ext in ext_issues[0]["message"]
    assert ext_issues[0]["severity"] == "info"


def test_validate_no_external_reference_for_internal_link():
    om = _om()
    om.add_class("A")
    om.add_class("B")
    om.add_class_relation(BASE + "A", "equivalentClass", BASE + "B")

    assert _external_issues(om) == []


def test_validate_ignores_standard_namespace_targets():
    om = _om()
    om.add_class("Dog")
    om.graph.add((URIRef(BASE + "Dog"), RDFS.subClassOf, OWL.Thing))

    # owl:Thing is a pure-syntax target, not an external reference.
    assert _external_issues(om) == []


def test_validate_ignores_skos_core_terms():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Concept", scheme="Scheme")

    # skos:Concept / skos:ConceptScheme (rdf:type targets) are core vocabulary,
    # not un-imported external links.
    assert _external_issues(om) == []


# ---- A concept in a non-base namespace is addressed by its URI --------------
# Regression for issue #87 part B: after a concept is moved to a custom
# (non-base) URI, later edit/delete/relation actions must address it by that
# URI. Addressing it by the bare local name resolves through the base namespace
# and silently misses the real concept. The UI now passes concept["uri"].


def _triples(om, s):
    return list(om.graph.triples((s, None, None)))


def test_nonbase_concept_rename_by_uri():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Old", scheme="Scheme")
    assert om.rename_concept("Old", EXT + "New") is True  # move to external ns

    assert om.rename_concept(EXT + "New", EXT + "Newer") is True
    assert (URIRef(EXT + "Newer"), RDF.type, SKOS.Concept) in om.graph
    assert _triples(om, URIRef(EXT + "New")) == []
    # The base namespace was never touched.
    assert _triples(om, URIRef(BASE + "New")) == []


def test_nonbase_concept_update_by_uri():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Old", scheme="Scheme")
    om.rename_concept("Old", EXT + "New")

    om.update_concept(EXT + "New", new_pref_label="Moved label")
    assert (URIRef(EXT + "New"), SKOS.prefLabel, Literal("Moved label")) in om.graph
    # A base-namespace stub must not have been created.
    assert _triples(om, URIRef(BASE + "New")) == []


def test_nonbase_concept_delete_by_uri():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Old", scheme="Scheme")
    om.rename_concept("Old", EXT + "New")

    om.delete_concept(EXT + "New")
    assert _triples(om, URIRef(EXT + "New")) == []
    assert EXT + "New" not in {c["uri"] for c in om.get_concepts()}


def test_nonbase_concept_relation_by_uri():
    om = _om()
    om.add_concept_scheme("Scheme")
    om.add_concept("Old", scheme="Scheme")
    om.add_concept("Other", scheme="Scheme")
    om.rename_concept("Old", EXT + "New")

    om.add_concept_relation(EXT + "New", "related", "Other")
    assert (URIRef(EXT + "New"), SKOS.related, URIRef(BASE + "Other")) in om.graph


def test_nonbase_scheme_rename_by_uri():
    om = _om()
    om.add_concept_scheme("Old")
    om.add_concept("C", scheme="Old")
    assert om.rename_concept_scheme("Old", EXT + "New") is True  # move to external ns

    assert om.rename_concept_scheme(EXT + "New", EXT + "Newer") is True
    assert (URIRef(EXT + "Newer"), RDF.type, SKOS.ConceptScheme) in om.graph
    assert _triples(om, URIRef(EXT + "New")) == []
    # The concept's inScheme link followed the rename.
    assert (URIRef(BASE + "C"), SKOS.inScheme, URIRef(EXT + "Newer")) in om.graph


def test_nonbase_scheme_delete_by_uri():
    om = _om()
    om.add_concept_scheme("Old")
    om.rename_concept_scheme("Old", EXT + "New")

    om.delete_concept_scheme(EXT + "New")
    assert _triples(om, URIRef(EXT + "New")) == []


def test_validate_external_reference_clears_once_defined():
    om = _om()
    om.add_class("Organization")
    ext = EXT + "Organization"
    om.add_class_relation(BASE + "Organization", "equivalentClass", ext)
    assert len(_external_issues(om)) == 1

    # Defining the target here (e.g. after importing its ontology) resolves it.
    om.add_class("Organization", namespace=EXT)
    assert _external_issues(om) == []

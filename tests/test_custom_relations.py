"""Custom relations: direct links between named resources (issue #484).

A custom relation is ``:step1 :nextItem :step2`` with ``:nextItem`` declared as
an ``owl:AnnotationProperty``, which keeps the ontology OWL 2 DL where an object
property between two classes would pun them into individuals. Nothing marks a
triple as one beyond that shape, so a file from elsewhere reads the same way.
"""

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://test.org/ont#"


@pytest.fixture
def om():
    m = OntologyManager(base_uri=NS)
    for name in ("Step1", "Step2", "Step3", "Pnt"):
        m.add_class(name)
    m.add_individual("alice", "Step1")
    m.add_object_property("hasPart")
    m.add_data_property("age")
    return m


def _rels(om):
    return {
        (r["subject"], r["relation"], r["object"]) for r in om.get_custom_relations()
    }


# --- adding and reading back --------------------------------------------------


def test_a_new_relation_is_declared_as_an_annotation_property(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")

    pred = URIRef(NS + "nextItem")
    assert (pred, RDF.type, OWL.AnnotationProperty) in om.graph
    assert (URIRef(NS + "Step1"), pred, URIRef(NS + "Step2")) in om.graph
    assert _rels(om) == {("Step1", "nextItem", "Step2")}


def test_rows_carry_uris_for_every_part(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")

    (row,) = om.get_custom_relations()
    assert row["subject_uri"] == NS + "Step1"
    assert row["relation_uri"] == NS + "nextItem"
    assert row["object_uri"] == NS + "Step2"


def test_any_declared_resource_can_be_on_either_side(om):
    """Classes, individuals and properties alike (the issue's first answer)."""
    om.add_custom_relation("alice", "relatedTo", "Step1")
    om.add_custom_relation("hasPart", "relatedTo", "age")

    assert _rels(om) == {
        ("alice", "relatedTo", "Step1"),
        ("hasPart", "relatedTo", "age"),
    }


def test_filtering_by_name_keeps_relations_touching_it(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")

    assert {r["object"] for r in om.get_custom_relations("Step3")} == {"Step3"}
    assert len(om.get_custom_relations("Step2")) == 2


def test_a_relation_from_a_file_is_read_without_the_app_writing_it(om):
    """Shape is all that marks one, so a hand-written file works the same."""
    pred = URIRef(NS + "follows")
    om.graph.add((pred, RDF.type, OWL.AnnotationProperty))
    om.graph.add((URIRef(NS + "Step2"), pred, URIRef(NS + "Step1")))

    assert _rels(om) == {("Step2", "follows", "Step1")}


# --- what is not a custom relation ---------------------------------------------


def test_an_annotation_with_a_literal_value_is_not_one(om):
    om.add_annotation("Step1", "wikidataId", "Q5")
    assert om.get_custom_relations() == []
    assert om.get_custom_relation_types() == []


def test_a_link_to_an_undeclared_resource_is_not_one(om):
    """``:homepage <http://example.com>`` is an annotation pointing at a web
    page, not a relation between two resources of the ontology."""
    om.add_annotation("Step1", "homepage", "http://example.com/page", value_is_uri=True)
    assert om.get_custom_relations() == []
    assert om.get_custom_relation_types() == []


def test_a_standard_vocabulary_term_is_not_one(om):
    om.graph.add((URIRef(NS + "Step1"), RDFS.seeAlso, URIRef(NS + "Step2")))
    assert om.get_custom_relations() == []


def test_an_object_property_assertion_is_not_one(om):
    om.graph.add((URIRef(NS + "Step1"), URIRef(NS + "hasPart"), URIRef(NS + "Step2")))
    assert om.get_custom_relations() == []


# --- names that are refused -----------------------------------------------------


@pytest.mark.parametrize("name", ["seeAlso", "label", "rdfs:comment"])
def test_a_standard_term_is_refused(om, name):
    assert om.custom_relation_reason(name)
    with pytest.raises(ValueError):
        om.add_custom_relation("Step1", name, "Step2")


def test_a_name_declared_as_something_else_is_refused(om):
    reason = om.custom_relation_reason("hasPart")
    assert reason and "ObjectProperty" in reason
    with pytest.raises(ValueError):
        om.add_custom_relation("Step1", "hasPart", "Step2")


def test_a_property_used_in_restrictions_is_refused(om):
    """It is an object property by use, and being both is not OWL 2 DL."""
    om.add_restriction("Step1", "nextItem", "someValuesFrom", "Step2")
    assert "restriction" in om.custom_relation_reason("nextItem")


def test_an_undeclared_end_is_refused_and_nothing_is_written(om):
    before = len(om.graph)
    with pytest.raises(ValueError, match="not a class, property or individual"):
        om.add_custom_relation("Step1", "nextItem", "http://other.org/X")
    assert len(om.graph) == before


def test_an_invalid_name_is_refused(om):
    assert om.custom_relation_reason("next item")
    assert om.custom_relation_reason("")


# --- types -------------------------------------------------------------------------


def test_types_list_each_relation_once_with_its_usage(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")

    assert om.get_custom_relation_types() == [
        {"uri": NS + "nextItem", "display": "nextItem", "usage": 2}
    ]


def test_a_type_whose_last_link_went_is_still_offered(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.remove_custom_relation(NS + "Step1", NS + "nextItem", NS + "Step2")

    assert om.get_custom_relations() == []
    assert [t["display"] for t in om.get_custom_relation_types()] == ["nextItem"]


def test_a_relation_in_another_namespace_shows_its_prefix(om):
    om.graph.bind("ex", "http://example.org/vocab#")
    om.add_custom_relation("Step1", "http://example.org/vocab#precedes", "Step2")

    (row,) = om.get_custom_relations()
    assert row["relation"] == "ex:precedes"


# --- remove and update ---------------------------------------------------------------


def test_remove_takes_out_just_that_link(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")

    om.remove_custom_relation(NS + "Step1", NS + "nextItem", NS + "Step2")

    assert _rels(om) == {("Step2", "nextItem", "Step3")}


def test_update_rewrites_the_link(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")

    assert om.update_custom_relation(
        (NS + "Step1", NS + "nextItem", NS + "Step2"),
        (NS + "Step1", "precedes", NS + "Step3"),
    )
    assert _rels(om) == {("Step1", "precedes", "Step3")}


def test_update_of_a_link_that_is_gone_reports_it(om):
    assert not om.update_custom_relation(
        (NS + "Step1", NS + "nextItem", NS + "Step2"),
        (NS + "Step1", NS + "nextItem", NS + "Step3"),
    )
    assert om.get_custom_relations() == []


def test_a_refused_update_leaves_the_original(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")

    with pytest.raises(ValueError):
        om.update_custom_relation(
            (NS + "Step1", NS + "nextItem", NS + "Step2"),
            (NS + "Step1", "hasPart", NS + "Step3"),
        )
    assert _rels(om) == {("Step1", "nextItem", "Step2")}


# --- following renames and deletes ---------------------------------------------------


def test_a_renamed_class_keeps_its_links(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.rename_class("Step2", "Second")
    assert _rels(om) == {("Step1", "nextItem", "Second")}


def test_a_deleted_class_takes_its_links_with_it(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.delete_class("Step2")
    assert om.get_custom_relations() == []


def test_a_followed_sequence_is_a_plain_property_path(om):
    """The point of the issue: no restriction nodes to step through."""
    om.add_custom_relation("Pnt", "nextItem", "Step1")
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")

    rows = om.graph.query(
        "PREFIX : <" + NS + "> SELECT ?to WHERE { :Pnt :nextItem+ ?to }"
    )
    assert {str(r[0]) for r in rows} == {NS + "Step1", NS + "Step2", NS + "Step3"}


# --- converting restrictions -----------------------------------------------------------


@pytest.fixture
def chain(om):
    """Steps linked the way the issue's file links them: by restrictions."""
    om.add_restriction("Pnt", "nextItem", "someValuesFrom", "Step1")
    om.add_restriction("Step1", "nextItem", "someValuesFrom", "Step2")
    om.add_restriction("Step2", "nextItem", "someValuesFrom", "Step3")
    return om


def _restrictions(om, prop="nextItem"):
    return [r for r in om.get_restrictions() if r["property"] == prop]


def test_the_convertible_properties_are_listed_with_a_count(chain):
    assert chain.get_convertible_restriction_properties() == [
        {"uri": NS + "nextItem", "display": "nextItem", "count": 3}
    ]


def test_moving_turns_restrictions_into_links_and_removes_them(chain):
    assert chain.convert_restrictions_to_relations(NS + "nextItem") == 3

    assert _rels(chain) == {
        ("Pnt", "nextItem", "Step1"),
        ("Step1", "nextItem", "Step2"),
        ("Step2", "nextItem", "Step3"),
    }
    assert _restrictions(chain) == []
    assert not list(chain.graph.subjects(RDF.type, OWL.Restriction))
    assert chain.custom_relation_reason("nextItem") is None


def test_keeping_the_restrictions_needs_another_name(chain):
    before = len(chain.graph)
    with pytest.raises(ValueError, match="restriction"):
        chain.convert_restrictions_to_relations(NS + "nextItem", keep_restrictions=True)
    assert len(chain.graph) == before


def test_keeping_them_under_another_name_copies(chain):
    assert (
        chain.convert_restrictions_to_relations(
            NS + "nextItem", relation="followedBy", keep_restrictions=True
        )
        == 3
    )
    assert len(_restrictions(chain)) == 3
    assert ("Step1", "followedBy", "Step2") in _rels(chain)


def test_only_some_values_from_with_a_declared_filler_converts(chain):
    """An allValuesFrom says something else, and an undeclared filler would
    make a link no list shows. Both stay, and so the name stays taken."""
    chain.add_restriction("Step3", "nextItem", "allValuesFrom", "Step1")
    chain.add_restriction("Step3", "nextItem", "someValuesFrom", "http://other.org/X")

    assert chain.get_convertible_restriction_properties()[0]["count"] == 3
    with pytest.raises(ValueError, match="restriction"):
        chain.convert_restrictions_to_relations(NS + "nextItem")
    assert (
        chain.convert_restrictions_to_relations(NS + "nextItem", relation="followedBy")
        == 3
    )
    assert {r["type"] for r in _restrictions(chain)} == {
        "allValuesFrom",
        "someValuesFrom",
    }


def test_a_restriction_shared_with_an_undeclared_class_stays_for_it(chain):
    node = next(chain.graph.subjects(OWL.onProperty, URIRef(NS + "nextItem")))
    chain.graph.add((URIRef("http://other.org/Ext"), RDFS.subClassOf, node))

    with pytest.raises(ValueError, match="restriction"):
        chain.convert_restrictions_to_relations(NS + "nextItem")


def test_nothing_to_convert_makes_nothing(om):
    assert om.convert_restrictions_to_relations(NS + "nextItem") == 0
    assert (URIRef(NS + "nextItem"), None, None) not in om.graph


def test_a_literal_valued_restriction_is_not_offered(om):
    om.add_restriction("Step1", "age", "hasValue", Literal(3))
    assert om.get_convertible_restriction_properties() == []


# --- review of PR #493 ---------------------------------------------------------------


def test_relations_sharing_a_local_name_are_told_apart(om):
    """No prefix bound for either, so the bare names would be the same word."""
    om.add_custom_relation("Step1", "http://one.example/next", "Step2")
    om.add_custom_relation("Step1", "http://two.example/next", "Step2")

    displays = {r["relation_uri"]: r["relation"] for r in om.get_custom_relations()}
    assert len(set(displays.values())) == 2
    assert {t["display"] for t in om.get_custom_relation_types()} == set(
        displays.values()
    )


def test_a_unique_name_stays_short(om):
    om.add_custom_relation("Step1", "http://one.example/next", "Step2")
    om.add_custom_relation("Step1", "nextItem", "Step2")
    assert {r["relation"] for r in om.get_custom_relations()} == {"next", "nextItem"}


def _share_with_equivalent_class(om):
    """The Step1 restriction also defines Pnt, through an equivalentClass."""
    node = next(om.graph.subjects(OWL.onProperty, URIRef(NS + "nextItem")))
    om.graph.add((URIRef(NS + "Pnt"), OWL.equivalentClass, node))
    return node


def test_converting_keeps_a_restriction_another_axiom_uses(om):
    om.add_restriction("Step1", "nextItem", "someValuesFrom", "Step2")
    node = _share_with_equivalent_class(om)

    # Moving under the same name would leave the property in use by the
    # restriction that has to stay, so that name is refused...
    with pytest.raises(ValueError, match="restriction"):
        om.convert_restrictions_to_relations(NS + "nextItem")
    # ...and under another one the link is made and the axiom is left whole.
    assert om.convert_restrictions_to_relations(NS + "nextItem", relation="next") == 1
    assert (URIRef(NS + "Step1"), RDFS.subClassOf, node) not in om.graph
    assert om.graph.value(node, OWL.someValuesFrom) == URIRef(NS + "Step2")
    assert om.graph.value(node, OWL.onProperty) == URIRef(NS + "nextItem")


def test_deleting_a_shared_restriction_from_one_class_keeps_it_for_the_other(om):
    """The same helper backs the Restrictions page's delete."""
    om.add_restriction("Step1", "nextItem", "someValuesFrom", "Step2")
    node = _share_with_equivalent_class(om)

    assert om.delete_restriction(
        NS + "Step1", NS + "nextItem", "someValuesFrom", NS + "Step2"
    )
    assert om.graph.value(node, OWL.someValuesFrom) == URIRef(NS + "Step2")


def test_convertible_properties_sharing_a_name_are_told_apart(om):
    om.add_restriction("Step1", "http://one.example/next", "someValuesFrom", "Step2")
    om.add_restriction("Step2", "http://two.example/next", "someValuesFrom", "Step3")

    props = om.get_convertible_restriction_properties()
    assert {p["uri"]: p["display"] for p in props} == {
        "http://one.example/next": "http://one.example/next",
        "http://two.example/next": "http://two.example/next",
    }


# --- and back again (issue #494) -------------------------------------------------------


def _links(om, prop="nextItem"):
    return {
        (r["applied_to"][0], r["value"])
        for r in _restrictions(om, prop)
        if r["type"] == "someValuesFrom"
    }


def test_a_round_trip_gives_back_the_graph_it_started_from(chain):
    """The point of the issue: a conversion is safe to try because it undoes
    exactly, not only through Undo in the same session."""
    from rdflib.compare import isomorphic

    before = Graph()
    for triple in chain.graph:
        before.add(triple)

    chain.convert_restrictions_to_relations(NS + "nextItem")
    assert chain.convert_relations_to_restrictions(NS + "nextItem") == 3

    assert isomorphic(before, chain.graph)


def test_moving_back_turns_links_into_restrictions_and_removes_them(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")

    assert om.convert_relations_to_restrictions(NS + "nextItem") == 2

    assert om.get_custom_relations() == []
    assert _links(om) == {("Step1", "Step2"), ("Step2", "Step3")}
    # No longer an annotation property, so the restrictions keep it OWL 2 DL.
    assert (URIRef(NS + "nextItem"), RDF.type, OWL.AnnotationProperty) not in om.graph


def test_the_relations_with_class_links_are_listed_with_a_count(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("Step2", "nextItem", "Step3")
    om.add_custom_relation("alice", "relatedTo", "Step3")

    assert om.get_relations_convertible_to_restrictions() == [
        {"uri": NS + "nextItem", "display": "nextItem", "count": 2}
    ]


def test_copying_back_needs_another_name(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    before = len(om.graph)

    with pytest.raises(ValueError, match="OWL 2 DL"):
        om.convert_relations_to_restrictions(NS + "nextItem", keep_relations=True)
    assert len(om.graph) == before

    assert (
        om.convert_relations_to_restrictions(
            NS + "nextItem", prop="hasNext", keep_relations=True
        )
        == 1
    )
    assert _rels(om) == {("Step1", "nextItem", "Step2")}
    assert _links(om, "hasNext") == {("Step1", "Step2")}


def test_a_link_from_an_individual_keeps_the_name_taken(om):
    """It has no restriction to become, so it stays, and the relation with it."""
    om.add_custom_relation("Step1", "nextItem", "Step2")
    om.add_custom_relation("alice", "nextItem", "Step3")

    with pytest.raises(ValueError, match="other uses"):
        om.convert_relations_to_restrictions(NS + "nextItem")
    assert om.convert_relations_to_restrictions(NS + "nextItem", prop="hasNext") == 1
    assert _rels(om) == {("alice", "nextItem", "Step3")}
    assert _links(om, "hasNext") == {("Step1", "Step2")}


def test_moving_back_onto_an_object_property(om):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    assert om.convert_relations_to_restrictions(NS + "nextItem", prop="hasPart") == 1
    assert _links(om, "hasPart") == {("Step1", "Step2")}


@pytest.mark.parametrize("prop", ["age", "seeAlso", "next item"])
def test_a_property_a_restriction_cannot_use_is_refused(om, prop):
    om.add_custom_relation("Step1", "nextItem", "Step2")
    with pytest.raises(ValueError):
        om.convert_relations_to_restrictions(NS + "nextItem", prop=prop)
    assert _rels(om) == {("Step1", "nextItem", "Step2")}


def test_a_restriction_already_there_is_not_written_twice(om):
    om.add_restriction("Step1", "hasPart", "someValuesFrom", "Step2")
    om.add_custom_relation("Step1", "nextItem", "Step2")

    om.convert_relations_to_restrictions(NS + "nextItem", prop="hasPart")

    assert len(_restrictions(om, "hasPart")) == 1


def test_nothing_to_convert_back_makes_nothing(om):
    assert om.convert_relations_to_restrictions(NS + "nextItem") == 0


@pytest.mark.parametrize(
    "characteristic",
    [
        "functional",
        "inverse_functional",
        "transitive",
        "symmetric",
        "asymmetric",
        "reflexive",
        "irreflexive",
    ],
)
def test_an_object_property_with_a_characteristic_is_a_target(om, characteristic):
    """Each characteristic is one more rdf:type on the property, and was read
    as a conflicting declaration (Codex review of PR #495)."""
    om.add_object_property("precedes", **{characteristic: True})
    om.add_custom_relation("Step1", "nextItem", "Step2")

    assert om.convert_relations_to_restrictions(NS + "nextItem", prop="precedes") == 1
    assert _links(om, "precedes") == {("Step1", "Step2")}


def test_a_functional_data_property_is_still_refused(om):
    """FunctionalProperty is shared with data properties; the DatatypeProperty
    declaration beside it is what makes it the wrong kind."""
    om.add_data_property("rank", functional=True)
    om.add_custom_relation("Step1", "nextItem", "Step2")

    with pytest.raises(ValueError, match="DatatypeProperty"):
        om.convert_relations_to_restrictions(NS + "nextItem", prop="rank")

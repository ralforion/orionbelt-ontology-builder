"""Tests for property CRUD operations."""


def test_add_object_property(om):
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatesTo", domain="A", range_="B")
    props = om.get_object_properties()
    names = [p["name"] for p in props]
    assert "relatesTo" in names


def test_add_data_property(om):
    om.add_class("A")
    om.add_data_property("hasAge", domain="A", range_="integer")
    props = om.get_data_properties()
    names = [p["name"] for p in props]
    assert "hasAge" in names


def test_delete_property(populated_om):
    populated_om.delete_property("worksFor")
    obj_props = populated_om.get_object_properties()
    names = [p["name"] for p in obj_props]
    assert "worksFor" not in names


def test_rename_property(populated_om):
    result = populated_om.rename_property("worksFor", "employedBy")
    assert result is True
    names = [p["name"] for p in populated_om.get_object_properties()]
    assert "employedBy" in names
    assert "worksFor" not in names


# ---- Reusing one object property across multiple class pairs (issue #58) ----


def _domain_triple_count(om, prop_name):
    """Number of plain rdfs:domain triples on a property (intersection guard)."""
    from rdflib import RDFS

    return len(list(om.graph.objects(om._uri(prop_name), RDFS.domain)))


def test_link_classes_reuses_single_property():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B", "C", "D"):
        om.add_class(c)
    om.add_object_property("relatedTo")  # no domain/range, fully reusable

    om.link_classes("A", "relatedTo", "B")
    om.link_classes("C", "relatedTo", "D")

    # Still exactly one property, no synonyms minted.
    obj_props = om.get_object_properties()
    assert [p["name"] for p in obj_props].count("relatedTo") == 1
    assert om.get_statistics()["object_properties"] == 1

    # Both pairs recorded as restrictions on the source class.
    rests = om.get_restrictions()
    pairs = {
        (r["applied_to"][0], r["property"], r["type"], r["value"])
        for r in rests
        if r["applied_to"]
    }
    assert ("A", "relatedTo", "allValuesFrom", "B") in pairs
    assert ("C", "relatedTo", "allValuesFrom", "D") in pairs


def test_link_classes_default_is_all_values_from():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatedTo")

    om.link_classes("A", "relatedTo", "B")
    assert om.get_restrictions("A")[0]["type"] == "allValuesFrom"


def test_link_classes_some_values_from():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatedTo")

    om.link_classes("A", "relatedTo", "B", semantics="some")
    assert om.get_restrictions("A")[0]["type"] == "someValuesFrom"


def test_link_classes_never_duplicates_rdfs_domain():
    """Regression guard for the OWL intersection trap (issue #58)."""
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B", "C", "D"):
        om.add_class(c)
    om.add_object_property("relatedTo")

    om.link_classes("A", "relatedTo", "B")
    om.link_classes("C", "relatedTo", "D")

    # Reuse must not add any plain rdfs:domain/rdfs:range axioms.
    assert _domain_triple_count(om, "relatedTo") == 0


def test_link_classes_rejects_unknown_semantics():
    import pytest

    from ontology_manager import OntologyManager

    om = OntologyManager()
    om.add_class("A")
    om.add_class("B")
    om.add_object_property("relatedTo")

    with pytest.raises(ValueError):
        om.link_classes("A", "relatedTo", "B", semantics="bogus")


def test_link_classes_round_trips_both_pairs():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B", "C", "D"):
        om.add_class(c)
    om.add_object_property("relatedTo")
    om.link_classes("A", "relatedTo", "B")
    om.link_classes("C", "relatedTo", "D")

    ttl = om.export_to_string(format="turtle")
    reloaded = OntologyManager()
    reloaded.load_from_string(ttl, format="turtle")

    pairs = {
        (r["applied_to"][0], r["value"])
        for r in reloaded.get_restrictions()
        if r["applied_to"]
    }
    assert pairs == {("A", "B"), ("C", "D")}
    assert reloaded.get_statistics()["object_properties"] == 1


def _restriction_bnode_count(om):
    """Number of owl:Restriction nodes left in the graph."""
    from rdflib import OWL, RDF

    return len(list(om.graph.subjects(RDF.type, OWL.Restriction)))


def test_delete_reused_property_removes_its_restrictions():
    """Deleting a reused property must not leave dangling restrictions (#58)."""
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B", "C", "D"):
        om.add_class(c)
    om.add_object_property("relatedTo")
    om.link_classes("A", "relatedTo", "B")
    om.link_classes("C", "relatedTo", "D")
    assert _restriction_bnode_count(om) == 2

    om.delete_property("relatedTo")

    assert _restriction_bnode_count(om) == 0
    assert om.get_restrictions() == []
    # No orphan subClassOf-to-blank-node left on the source classes.
    ttl = om.export_to_string(format="turtle")
    assert "Restriction" not in ttl


def test_delete_source_class_removes_its_reused_link():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B"):
        om.add_class(c)
    om.add_object_property("relatedTo")
    om.link_classes("A", "relatedTo", "B")

    om.delete_class("A")

    assert _restriction_bnode_count(om) == 0
    assert om.get_restrictions() == []


def test_delete_target_class_removes_reused_link():
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B"):
        om.add_class(c)
    om.add_object_property("relatedTo")
    om.link_classes("A", "relatedTo", "B")

    om.delete_class("B")

    # The restriction pointed at B as its value; it is malformed without B, so
    # it must be removed whole rather than left on A.
    assert _restriction_bnode_count(om) == 0
    assert om.get_restrictions() == []


def test_get_restrictions_exposes_uris_and_delete_round_trips_external_ns():
    """Restrictions on external-namespace props/classes delete via their URIs."""
    from ontology_manager import OntologyManager

    om = OntologyManager()
    ttl = """
    @prefix : <http://example.org/o#> .
    @prefix ex: <http://other.example/vocab#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    ex:Foo a owl:Class . ex:Bar a owl:Class .
    ex:relatedTo a owl:ObjectProperty .
    ex:Foo rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:relatedTo ; owl:allValuesFrom ex:Bar ] .
    """
    om.load_from_string(ttl, format="turtle")

    rest = om.get_restrictions()[0]
    assert rest["property_uri"] == "http://other.example/vocab#relatedTo"
    assert rest["applied_to_uris"] == ["http://other.example/vocab#Foo"]
    assert rest["value_uri"] == "http://other.example/vocab#Bar"

    # Deleting by local name would resolve to the wrong (base) namespace and fail.
    assert om.delete_restriction("Foo", "relatedTo", "allValuesFrom") is False
    # Deleting by full URI succeeds.
    assert (
        om.delete_restriction(
            rest["applied_to_uris"][0], rest["property_uri"], "allValuesFrom"
        )
        is True
    )
    assert om.get_restrictions() == []


def _impact_matches_actual(resource, rtype):
    """Build a fresh graph with a reused link, then assert the delete-impact
    preview total equals the triples actually removed by the delete."""
    from ontology_manager import OntologyManager

    om = OntologyManager()
    for c in ("A", "B", "C", "D"):
        om.add_class(c)
    om.add_object_property("relatedTo")
    om.link_classes("A", "relatedTo", "B")
    om.link_classes("C", "relatedTo", "D")

    predicted = om.get_delete_impact(resource, rtype)["total_triples"]
    before = len(om.graph)
    if rtype == "class":
        om.delete_class(resource)
    else:
        om.delete_property(resource)
    actual = before - len(om.graph)
    return predicted, actual


def test_delete_impact_preview_counts_purged_restrictions():
    """The preview must include the restriction triples the purge removes (#58)."""
    # Deleting the reused property removes both restrictions whole.
    predicted, actual = _impact_matches_actual("relatedTo", "property")
    assert predicted == actual
    assert actual > 1  # property decl + the two restrictions, not just one triple

    # Deleting a target class removes the restriction that points at it.
    predicted, actual = _impact_matches_actual("B", "class")
    assert predicted == actual

    # Deleting a source class removes the restriction it owns.
    predicted, actual = _impact_matches_actual("A", "class")
    assert predicted == actual

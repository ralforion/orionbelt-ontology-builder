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

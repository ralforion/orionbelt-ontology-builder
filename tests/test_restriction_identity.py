"""Restrictions are identified by their whole spec, not (class, property, type).

A class can carry several restrictions on the same property with the same type,
differing only in value. Delete used to remove whichever came first, so the row
on screen was rarely the one that went; editing would have rewritten the wrong
one just as silently (issue #152).
"""

import pytest

from orionbelt_ontology_builder.ontology_manager import OntologyManager


@pytest.fixture
def rest_om():
    m = OntologyManager(base_uri="http://test.org/ont#")
    for name in ("Bicycle", "Wheel", "Engine", "Frame", "Car"):
        m.add_class(name)
    m.add_object_property("hasPart")
    m.add_object_property("madeOf")
    m.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Wheel")
    m.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Engine")
    return m


def _rows(om):
    return sorted((r["property"], r["type"], r["value"]) for r in om.get_restrictions())


def test_delete_removes_the_named_one(rest_om):
    assert rest_om.delete_restriction(
        "Bicycle", "hasPart", "someValuesFrom", value="Engine"
    )
    assert _rows(rest_om) == [("hasPart", "someValuesFrom", "Wheel")]


def test_delete_without_a_value_still_removes_one(rest_om):
    """Older callers keep working; they just cannot say which."""
    assert rest_om.delete_restriction("Bicycle", "hasPart", "someValuesFrom")
    assert len(rest_om.get_restrictions()) == 1


def test_delete_reports_a_value_that_is_not_there(rest_om):
    assert not rest_om.delete_restriction(
        "Bicycle", "hasPart", "someValuesFrom", value="Frame"
    )
    assert len(rest_om.get_restrictions()) == 2


def test_update_edits_the_named_one(rest_om):
    assert rest_om.update_restriction(
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Engine",
        },
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Frame",
        },
    )
    assert _rows(rest_om) == [
        ("hasPart", "someValuesFrom", "Frame"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_update_can_change_every_part(rest_om):
    assert rest_om.update_restriction(
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Wheel",
        },
        {
            "class_name": "Car",
            "property_name": "madeOf",
            "restriction_type": "allValuesFrom",
            "value": "Frame",
        },
    )
    rows = {
        (r["applied_to"][0], r["property"], r["type"], r["value"])
        for r in rest_om.get_restrictions()
    }
    assert ("Car", "madeOf", "allValuesFrom", "Frame") in rows
    assert ("Bicycle", "hasPart", "someValuesFrom", "Engine") in rows
    assert len(rows) == 2


def test_update_to_a_cardinality(rest_om):
    assert rest_om.update_restriction(
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Wheel",
        },
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "exactCardinality",
            "value": 2,
        },
    )
    assert ("hasPart", "exactCardinality", "2") in _rows(rest_om)


def test_update_of_a_stale_row_changes_nothing(rest_om):
    assert not rest_om.update_restriction(
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Frame",
        },
        {
            "class_name": "Bicycle",
            "property_name": "hasPart",
            "restriction_type": "someValuesFrom",
            "value": "Wheel",
        },
    )
    assert len(rest_om.get_restrictions()) == 2


def test_a_rejected_edit_keeps_the_original(rest_om):
    """Validation runs before the original is detached."""
    for bad in (
        {"restriction_type": "nonsense", "value": "Wheel"},
        {"restriction_type": "exactCardinality", "value": "two"},
    ):
        with pytest.raises(ValueError):
            rest_om.update_restriction(
                {
                    "class_name": "Bicycle",
                    "property_name": "hasPart",
                    "restriction_type": "someValuesFrom",
                    "value": "Wheel",
                },
                {"class_name": "Bicycle", "property_name": "hasPart", **bad},
            )
    assert _rows(rest_om) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_qualified_cardinality_is_told_apart_by_its_class(rest_om):
    rest_om.add_restriction(
        "Car", "hasPart", "minQualifiedCardinality", 1, on_class="Wheel"
    )
    rest_om.add_restriction(
        "Car", "hasPart", "minQualifiedCardinality", 1, on_class="Engine"
    )
    assert rest_om.delete_restriction(
        "Car", "hasPart", "minQualifiedCardinality", value=1, on_class="Engine"
    )
    remaining = [
        r for r in rest_om.get_restrictions() if r["type"] == "minQualifiedCardinality"
    ]
    assert len(remaining) == 1 and remaining[0]["on_class"] == "Wheel"


def test_a_shared_restriction_is_only_unlinked_from_one_class(rest_om):
    """Two classes can point at one restriction node; deleting for one must not
    strip it from the other."""
    from rdflib import RDFS

    node = next(n for n, row in rest_om._iter_restrictions() if row["value"] == "Wheel")
    rest_om.graph.add((rest_om._uri("Car"), RDFS.subClassOf, node))
    assert sorted(
        r["applied_to"] for r in rest_om.get_restrictions() if r["value"] == "Wheel"
    ) == [["Bicycle", "Car"]]

    assert rest_om.delete_restriction(
        "Bicycle", "hasPart", "someValuesFrom", value="Wheel"
    )
    still_there = [r for r in rest_om.get_restrictions() if r["value"] == "Wheel"]
    assert len(still_there) == 1
    assert still_there[0]["applied_to"] == ["Car"]


def test_local_name_still_does_not_match_an_external_namespace():
    """Matching resolves names to URIs, so a local name cannot delete an
    imported restriction by accident (the guarantee test_properties.py pins)."""
    # The default prefix keeps the base namespace put; without it the loader
    # infers the imported one and "Foo" would legitimately resolve to it.
    ttl = """
    @prefix : <http://test.org/ont#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix other: <http://other.example/vocab#> .
    :Local a owl:Class .
    other:Foo a owl:Class ; rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty other:relatedTo ;
        owl:allValuesFrom other:Bar ] .
    """
    om = OntologyManager(base_uri="http://test.org/ont#")
    om.load_from_string(ttl, format="turtle")
    assert str(om.namespace) == "http://test.org/ont#"

    assert not om.delete_restriction("Foo", "relatedTo", "allValuesFrom", value="Bar")
    assert om.delete_restriction(
        "http://other.example/vocab#Foo",
        "http://other.example/vocab#relatedTo",
        "allValuesFrom",
        value="http://other.example/vocab#Bar",
    )
    assert om.get_restrictions() == []


# --- cardinality values (review P2) -----------------------------------------


def test_a_negative_cardinality_is_rejected_on_add(rest_om):
    """It would serialize as an invalid xsd:nonNegativeInteger."""
    with pytest.raises(ValueError, match="negative"):
        rest_om.add_restriction("Bicycle", "hasPart", "minCardinality", -1)


def test_a_negative_cardinality_is_rejected_on_edit(rest_om):
    with pytest.raises(ValueError, match="negative"):
        rest_om.update_restriction(
            {
                "class_name": "Bicycle",
                "property_name": "hasPart",
                "restriction_type": "someValuesFrom",
                "value": "Wheel",
            },
            {
                "class_name": "Bicycle",
                "property_name": "hasPart",
                "restriction_type": "maxCardinality",
                "value": -3,
            },
        )
    assert _rows(rest_om) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]


def test_zero_is_a_valid_cardinality(rest_om):
    rest_om.add_restriction("Car", "hasPart", "maxCardinality", 0)
    assert ("hasPart", "maxCardinality", "0") in _rows(rest_om)


def test_a_rejected_add_leaves_no_orphan_restriction(rest_om):
    """Raising after the blank node existed left an empty row on the page."""
    before = len(rest_om.get_restrictions())
    for restriction_type, value in (
        ("minCardinality", -1),
        ("minCardinality", "two"),
        ("nonsense", 1),
    ):
        with pytest.raises(ValueError):
            rest_om.add_restriction("Bicycle", "hasPart", restriction_type, value)
    assert len(rest_om.get_restrictions()) == before
    assert all(r["type"] is not None for r in rest_om.get_restrictions())


def test_an_empty_value_is_rejected_on_add(rest_om):
    """owl:someValuesFrom : is a restriction pointing at nothing."""
    for restriction_type in ("someValuesFrom", "allValuesFrom", "hasValue"):
        with pytest.raises(ValueError, match="needs a value"):
            rest_om.add_restriction("Bicycle", "hasPart", restriction_type, "")
        with pytest.raises(ValueError, match="needs a value"):
            rest_om.add_restriction("Bicycle", "hasPart", restriction_type, None)


def test_an_empty_value_is_rejected_on_edit(rest_om):
    with pytest.raises(ValueError, match="needs a value"):
        rest_om.update_restriction(
            {
                "class_name": "Bicycle",
                "property_name": "hasPart",
                "restriction_type": "someValuesFrom",
                "value": "Wheel",
            },
            {
                "class_name": "Bicycle",
                "property_name": "hasPart",
                "restriction_type": "someValuesFrom",
                "value": "   ",
            },
        )
    assert _rows(rest_om) == [
        ("hasPart", "someValuesFrom", "Engine"),
        ("hasPart", "someValuesFrom", "Wheel"),
    ]

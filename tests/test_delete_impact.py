"""Tests for delete impact analysis."""


def test_class_impact_shows_subclasses(populated_om):
    impact = populated_om.get_delete_impact("Person", "class")
    assert "Employee" in impact["subclasses"]


def test_class_impact_shows_instances(populated_om):
    impact = populated_om.get_delete_impact("Employee", "class")
    assert "alice" in impact["instances"]


def test_class_impact_shows_domain_of(populated_om):
    impact = populated_om.get_delete_impact("Person", "class")
    assert "worksFor" in impact["domain_of"]
    assert "hasName" in impact["domain_of"]


def test_class_impact_shows_range_of(populated_om):
    impact = populated_om.get_delete_impact("Organization", "class")
    assert "worksFor" in impact["range_of"]


def test_class_impact_total_triples_positive(populated_om):
    impact = populated_om.get_delete_impact("Person", "class")
    assert impact["total_triples"] > 0


def test_property_impact_shows_assertions(populated_om):
    populated_om.add_individual_property(
        "alice", "worksFor", "acme", is_object_property=True
    )
    impact = populated_om.get_delete_impact("worksFor", "property")
    assert len(impact["property_assertions"]) >= 1


def test_individual_impact_shows_relations(populated_om):
    populated_om.add_individual_property(
        "alice", "worksFor", "acme", is_object_property=True
    )
    impact = populated_om.get_delete_impact("acme", "individual")
    assert len(impact["relations"]) >= 1


def test_format_delete_impact(populated_om):
    impact = populated_om.get_delete_impact("Person", "class")
    text = populated_om.format_delete_impact(impact)
    assert "Person" in text
    assert "triple" in text


def test_scheme_impact_shows_its_concepts_links(skos_om):
    """A scheme is deleted as a "scheme", not a "concept": the resource type
    also decides which types count as its own, so the wrong one made an ordinary
    scheme look punned with itself (issue #279 review)."""
    impact = skos_om.get_delete_impact("MyScheme", "scheme")
    assert impact["also_typed_as"] == []
    assert len(impact["relations"]) >= 1  # the inScheme of each concept in it
    assert "also" not in skos_om.format_delete_impact(impact)


def test_concept_impact_is_unaffected(skos_om):
    impact = skos_om.get_delete_impact("Animal", "concept")
    assert impact["also_typed_as"] == []
    assert len(impact["relations"]) >= 1  # Dog and Cat are broader: Animal


def test_isolated_class_has_minimal_impact(populated_om):
    populated_om.add_class("Isolated")
    impact = populated_om.get_delete_impact("Isolated", "class")
    assert impact["subclasses"] == []
    assert impact["instances"] == []
    assert impact["domain_of"] == []
    assert impact["range_of"] == []

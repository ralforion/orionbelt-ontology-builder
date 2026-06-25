"""Tests for resource usage and backlink view."""


def test_class_inbound_usages(populated_om):
    """Person should appear as domain of worksFor."""
    usages = populated_om.get_resource_usages("Person")
    inbound_preds = [u["predicate"] for u in usages["inbound"]]
    assert "domain" in inbound_preds  # worksFor has domain Person


def test_class_no_outbound_structural(populated_om):
    """Outbound usages should exclude structural predicates like rdf:type."""
    usages = populated_om.get_resource_usages("Person")
    outbound_preds = [u["predicate"] for u in usages["outbound"]]
    assert "type" not in outbound_preds


def test_individual_inbound_after_assertion(populated_om):
    populated_om.add_individual_property(
        "alice", "worksFor", "acme", is_object_property=True
    )
    usages = populated_om.get_resource_usages("acme")
    assert any(
        u["subject"] == "alice" and u["predicate"] == "worksFor"
        for u in usages["inbound"]
    )


def test_property_as_predicate(populated_om):
    populated_om.add_individual_property(
        "alice", "worksFor", "acme", is_object_property=True
    )
    usages = populated_om.get_resource_usages("worksFor")
    assert len(usages["as_predicate"]) >= 1


def test_isolated_class_no_usages(populated_om):
    populated_om.add_class("Isolated")
    usages = populated_om.get_resource_usages("Isolated")
    assert usages["inbound"] == []
    assert usages["outbound"] == []
    assert usages["as_predicate"] == []

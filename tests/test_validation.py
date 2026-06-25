"""Tests for validation logic."""


def test_missing_label_warning(om):
    om.add_class("Unlabeled")
    issues = om.validate()
    assert any(
        i["type"] == "missing_label" and i["subject"] == "Unlabeled" for i in issues
    )


def test_no_warning_when_label_present(om):
    om.add_class("Labeled", label="Labeled")
    issues = om.validate()
    assert not any(
        i["type"] == "missing_label" and i["subject"] == "Labeled" for i in issues
    )


def test_no_warning_when_skos_preflabel_present(om):
    """Classes with skos:prefLabel should not trigger missing label warning (issue #1)."""
    from rdflib import Literal
    from rdflib.namespace import SKOS

    om.add_class("SKOSLabeled")
    class_uri = om.namespace["SKOSLabeled"]
    om.graph.add((class_uri, SKOS.prefLabel, Literal("SKOS Labeled")))
    issues = om.validate()
    assert not any(
        i["type"] == "missing_label" and i["subject"] == "SKOSLabeled" for i in issues
    )


def test_missing_domain_range(om):
    om.add_object_property("orphanProp")
    issues = om.validate()
    assert any(
        i["type"] == "missing_domain" and i["subject"] == "orphanProp" for i in issues
    )
    assert any(
        i["type"] == "missing_range" and i["subject"] == "orphanProp" for i in issues
    )


def test_no_missing_domain_when_domain_includes_present(om):
    """Properties with schema:domainIncludes or gist:domainIncludes should not warn (issue #2)."""
    from ontology_manager import _SCHEMA, _GIST

    om.add_class("Person")
    om.add_object_property("schemaProp")
    om.add_object_property("gistProp")
    prop1 = om.namespace["schemaProp"]
    prop2 = om.namespace["gistProp"]
    om.graph.add((prop1, _SCHEMA.domainIncludes, om.namespace["Person"]))
    om.graph.add((prop2, _GIST.domainIncludes, om.namespace["Person"]))
    issues = om.validate()
    assert not any(
        i["type"] == "missing_domain" and i["subject"] == "schemaProp" for i in issues
    )
    assert not any(
        i["type"] == "missing_domain" and i["subject"] == "gistProp" for i in issues
    )


def test_no_missing_range_when_range_includes_present(om):
    """Properties with schema:rangeIncludes or gist:rangeIncludes should not warn (issue #2)."""
    from ontology_manager import _SCHEMA, _GIST

    om.add_class("Person")
    om.add_object_property("schemaProp", domain="Person")
    om.add_object_property("gistProp", domain="Person")
    prop1 = om.namespace["schemaProp"]
    prop2 = om.namespace["gistProp"]
    om.graph.add((prop1, _SCHEMA.rangeIncludes, om.namespace["Person"]))
    om.graph.add((prop2, _GIST.rangeIncludes, om.namespace["Person"]))
    issues = om.validate()
    assert not any(
        i["type"] == "missing_range" and i["subject"] == "schemaProp" for i in issues
    )
    assert not any(
        i["type"] == "missing_range" and i["subject"] == "gistProp" for i in issues
    )


def test_untyped_individual(om):
    """Individual added as NamedIndividual then class deleted -> untyped."""
    om.add_class("Temp")
    om.add_individual("x", "Temp")
    om.delete_class("Temp")
    issues = om.validate()
    assert any(
        i["type"] == "untyped_individual" and i["subject"] == "x" for i in issues
    )


def test_no_untyped_warning_for_typed_individual(populated_om):
    issues = populated_om.validate()
    assert not any(
        i["type"] == "untyped_individual" and i["subject"] == "alice" for i in issues
    )


def test_orphan_class_detected(om):
    """A class with no hierarchy, domain/range, or instances is orphaned."""
    om.add_class("Isolated", label="Isolated")
    issues = om.validate()
    assert any(
        i["type"] == "orphan_class" and i["subject"] == "Isolated" for i in issues
    )


def test_class_in_hierarchy_not_orphan(om):
    om.add_class("Parent")
    om.add_class("Child", parent="Parent")
    issues = om.validate()
    orphan_names = [i["subject"] for i in issues if i["type"] == "orphan_class"]
    assert "Parent" not in orphan_names
    assert "Child" not in orphan_names


def test_class_as_domain_not_orphan(om):
    om.add_class("MyClass")
    om.add_object_property("myProp", domain="MyClass")
    issues = om.validate()
    orphan_names = [i["subject"] for i in issues if i["type"] == "orphan_class"]
    assert "MyClass" not in orphan_names


def test_class_with_instance_not_orphan(om):
    om.add_class("MyClass")
    om.add_individual("x", "MyClass")
    issues = om.validate()
    orphan_names = [i["subject"] for i in issues if i["type"] == "orphan_class"]
    assert "MyClass" not in orphan_names


def test_duplicate_label_detected(om):
    om.add_class("ClassA", label="Thing")
    om.add_class("ClassB", label="Thing")
    issues = om.validate()
    dup_issues = [i for i in issues if i["type"] == "duplicate_label"]
    assert len(dup_issues) == 1
    assert "ClassA" in dup_issues[0]["subject"]
    assert "ClassB" in dup_issues[0]["subject"]


def test_no_duplicate_label_for_unique_labels(om):
    om.add_class("ClassA", label="Alpha")
    om.add_class("ClassB", label="Beta")
    issues = om.validate()
    assert not any(i["type"] == "duplicate_label" for i in issues)


def test_domain_mismatch_detected(om):
    """Individual using a property without being typed as the declared domain."""
    om.add_class("Person")
    om.add_class("Animal")
    om.add_object_property("worksFor", domain="Person")
    om.add_individual("fido", "Animal")
    om.add_individual_property("fido", "worksFor", "fido", is_object_property=True)
    issues = om.validate()
    assert any(
        i["type"] == "domain_mismatch" and i["subject"] == "fido" for i in issues
    )


def test_range_mismatch_detected(om):
    """Object property used with a value not typed as the declared range."""
    om.add_class("Person")
    om.add_class("Organization")
    om.add_class("Animal")
    om.add_object_property("worksFor", domain="Person", range_="Organization")
    om.add_individual("alice", "Person")
    om.add_individual("fido", "Animal")
    om.add_individual_property("alice", "worksFor", "fido", is_object_property=True)
    issues = om.validate()
    assert any(
        i["type"] == "range_mismatch" and i["subject"] == "alice" for i in issues
    )


def test_no_mismatch_when_types_match(populated_om):
    """Correctly typed assertions should produce no domain/range warnings."""
    populated_om.add_individual_property(
        "alice", "worksFor", "acme", is_object_property=True
    )
    issues = populated_om.validate()
    assert not any(
        i["type"] == "domain_mismatch" and i["subject"] == "alice" for i in issues
    )
    assert not any(
        i["type"] == "range_mismatch" and i["subject"] == "alice" for i in issues
    )

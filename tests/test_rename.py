"""Tests for renaming entity names (URIs) with reference updates (issue #42)."""


def _concept(om, name):
    return next((c for c in om.get_concepts() if c["name"] == name), None)


def test_rename_concept_updates_references(skos_om):
    """Renaming a concept re-points broader/narrower links to the new name."""
    assert skos_om.rename_concept("Animal", "Creature") is True
    names = [c["name"] for c in skos_om.get_concepts()]
    assert "Creature" in names
    assert "Animal" not in names
    # Dog was broader=Animal; it should now point to Creature.
    dog = _concept(skos_om, "Dog")
    assert dog is not None
    assert "Creature" in dog["broader"]


def test_rename_concept_scheme_preserves_membership(skos_om):
    """Renaming a scheme keeps its concepts' inScheme membership."""
    assert skos_om.rename_concept_scheme("MyScheme", "MyVocab") is True
    scheme_names = [s["name"] for s in skos_om.get_concept_schemes()]
    assert "MyVocab" in scheme_names
    assert "MyScheme" not in scheme_names
    members = [c["name"] for c in skos_om.get_concepts(scheme="MyVocab")]
    assert {"Animal", "Dog", "Cat"} <= set(members)


def test_rename_concept_duplicate_returns_false(skos_om):
    assert skos_om.rename_concept("Dog", "Cat") is False
    names = [c["name"] for c in skos_om.get_concepts()]
    assert "Dog" in names


def test_rename_class_blocked_by_individual(populated_om):
    """Cross-type guard: a class cannot be renamed onto an individual's name."""
    assert populated_om.rename_class("Person", "alice") is False
    names = [c["name"] for c in populated_om.get_classes()]
    assert "Person" in names


def test_rename_class_blocked_by_property(populated_om):
    assert populated_om.rename_class("Person", "worksFor") is False


def test_rename_individual_blocked_by_class(populated_om):
    assert populated_om.rename_individual("alice", "Person") is False
    names = [i["name"] for i in populated_om.get_individuals()]
    assert "alice" in names


def test_rename_class_to_free_name_succeeds(populated_om):
    assert populated_om.rename_class("Person", "Human") is True
    names = [c["name"] for c in populated_om.get_classes()]
    assert "Human" in names and "Person" not in names

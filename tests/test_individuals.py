"""Tests for individual CRUD operations."""


def test_add_individual(populated_om):
    populated_om.add_individual("bob", "Person", label="Bob")
    individuals = populated_om.get_individuals()
    names = [i["name"] for i in individuals]
    assert "bob" in names


def test_delete_individual(populated_om):
    populated_om.delete_individual("alice")
    individuals = populated_om.get_individuals()
    names = [i["name"] for i in individuals]
    assert "alice" not in names


def test_rename_individual(populated_om):
    result = populated_om.rename_individual("alice", "alice_smith")
    assert result is True
    names = [i["name"] for i in populated_om.get_individuals()]
    assert "alice_smith" in names
    assert "alice" not in names


def test_property_assertion_exposes_the_target_uri(populated_om):
    """Object values carry ``value_uri`` so callers can resolve them exactly.

    ``value`` is only a local name, which two individuals in different
    namespaces can share — resolving by it draws graph edges to the wrong one
    (PR #202 review).
    """
    populated_om.add_prefix("other", "http://other.example.org/ns#")
    populated_om.add_individual("bob", "Person")
    populated_om.add_individual(
        "bob", "Person", namespace="http://other.example.org/ns#"
    )
    populated_om.add_individual_property("alice", "knows", "bob")

    alice = next(i for i in populated_om.get_individuals() if i["name"] == "alice")
    knows = [p for p in alice["properties"] if p["property"] == "knows"]
    assert len(knows) == 1
    assert knows[0]["value"] == "bob"
    # The base-namespace bob, not the one from the other namespace.
    assert knows[0]["value_uri"] == str(populated_om.namespace["bob"])
    assert "other.example.org" not in knows[0]["value_uri"]


def test_literal_property_assertion_has_no_target_uri(populated_om):
    populated_om.add_individual_property("alice", "age", 42, is_object_property=False)
    alice = next(i for i in populated_om.get_individuals() if i["name"] == "alice")
    age = next(p for p in alice["properties"] if p["property"] == "age")
    assert age["value"] == "42"
    assert age["value_uri"] == ""

"""Tests for global ontology search."""


def test_search_by_name(populated_om):
    results = populated_om.search("Person")
    assert any(r["name"] == "Person" for r in results)


def test_search_by_label(populated_om):
    results = populated_om.search("Alice")
    assert any(r["name"] == "alice" for r in results)


def test_search_case_insensitive(populated_om):
    results = populated_om.search("person")
    assert any(r["name"] == "Person" for r in results)


def test_search_partial_match(populated_om):
    results = populated_om.search("Emp")
    assert any(r["name"] == "Employee" for r in results)


def test_search_returns_type(populated_om):
    results = populated_om.search("worksFor")
    match = next((r for r in results if r["name"] == "worksFor"), None)
    assert match is not None
    assert match["type"] == "Object Property"


def test_search_empty_query(populated_om):
    assert populated_om.search("") == []
    assert populated_om.search("   ") == []


def test_search_no_results(populated_om):
    assert populated_om.search("zzzznotfound") == []


def test_search_finds_individuals(populated_om):
    results = populated_om.search("acme")
    assert any(r["name"] == "acme" and r["type"] == "Individual" for r in results)


def test_search_name_matches_rank_first(populated_om):
    """Name matches should appear before label/comment matches."""
    populated_om.add_class("Alpha", label="Zeta")
    populated_om.add_class("Zeta", label="Alpha")
    results = populated_om.search("Alpha")
    names = [r["name"] for r in results]
    assert names.index("Alpha") < names.index("Zeta")


def test_search_finds_concept_by_pref_label(skos_om):
    results = skos_om.search("Dog")
    assert any(r["name"] == "Dog" and r["type"] == "SKOS Concept" for r in results)


def test_search_finds_concept_by_alt_label(skos_om):
    """altLabel synonyms should be discoverable via search (issue #41)."""
    skos_om.add_annotation("Dog", "altLabel", "Canine")
    results = skos_om.search("Canine")
    match = next((r for r in results if r["name"] == "Dog"), None)
    assert match is not None
    assert match["type"] == "SKOS Concept"
    assert match["match_field"] == "altLabel"


def test_search_alt_label_on_class(populated_om):
    """altLabel matching applies to any resource, not only SKOS concepts."""
    populated_om.add_class("Automobile")
    populated_om.add_annotation("Automobile", "altLabel", "Motorcar")
    results = populated_om.search("Motorcar")
    assert any(r["name"] == "Automobile" for r in results)


def test_search_name_ranks_above_alt_label(populated_om):
    populated_om.add_class("Wolf")
    populated_om.add_annotation("Wolf", "altLabel", "Doggo")
    populated_om.add_class("Doggo")
    results = populated_om.search("Doggo")
    names = [r["name"] for r in results]
    assert names.index("Doggo") < names.index("Wolf")


def test_search_disambiguates_same_name_across_namespaces(monkeypatch):
    """Two entities sharing a local name in different namespaces get a
    namespace tag in the sidebar search, matching the graph/UI (issue #119)."""
    import types

    from ontology_manager import OntologyManager
    from orionbelt_ontology_builder import app

    om = OntologyManager(base_uri="http://example.org/ontology#")
    om.add_class("Dog")  # base namespace
    other_ns = "http://example.org/other-ontology#"
    om.add_prefix("other", other_ns)
    om.add_class("Dog", namespace=other_ns)

    results = [r for r in om.search("Dog") if r["type"] == "Class"]
    assert len(results) == 2
    assert {r["name"] for r in results} == {"Dog"}
    assert len({r["uri"] for r in results}) == 2  # distinct URIs carried through

    # The sidebar builds a per-group collision set and disambiguates via the
    # shared helper; _prefix_for_uri reads the active ontology from session.
    monkeypatch.setattr(
        app, "st", types.SimpleNamespace(session_state={"ontology": om})
    )
    collisions = app._build_name_collision_set(results)
    assert "Dog" in collisions
    displayed = {app._disambiguated_name(r, collisions) for r in results}
    assert len(displayed) == 2  # no two identical entries
    assert "Dog (other)" in displayed

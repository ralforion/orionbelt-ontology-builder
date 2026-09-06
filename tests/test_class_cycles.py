"""validate() reports a subClassOf cycle (issue #413).

Nothing used to mention one. The tree view marks the back-edge it walks into
and `ui.class_descendant_uris` walks with a seen-set, so a loop breaks nothing
and says nothing either: an ontology could carry one with only its own
hierarchy view to show it.

A warning rather than an error, because a cycle is legal OWL. `A ⊑ B` with
`B ⊑ A` says the two classes are equivalent, and a reasoner reads it that way.
It is usually a modelling slip, occasionally deliberate, so the app says so
rather than refusing it.
"""

import pytest

from orionbelt_ontology_builder.ontology_manager import OntologyManager

NS = "http://example.org/ontology#"


@pytest.fixture
def om():
    o = OntologyManager()
    o.add_class("Vehicle")
    o.add_class("Bicycle", parent="Vehicle")
    o.add_class("Tandem", parent="Bicycle")
    return o


def _cycles(o):
    return [i for i in o.validate() if i["type"] == "class_cycle"]


def test_a_plain_hierarchy_reports_nothing(om):
    assert _cycles(om) == []


def test_a_two_class_loop_is_reported(om):
    om.update_class(NS + "Bicycle", new_parent="Tandem")
    found = _cycles(om)

    assert len(found) == 1
    assert found[0]["severity"] == "warning", "a cycle is legal OWL, not an error"
    assert "Bicycle" in found[0]["message"] and "Tandem" in found[0]["message"]


def test_the_message_says_what_a_cycle_means(om):
    """ "Equivalent" is the part that surprises whoever wrote one by accident."""
    om.update_class(NS + "Bicycle", new_parent="Tandem")
    assert "equivalent" in _cycles(om)[0]["message"].lower()


def test_a_longer_loop_is_reported_once_with_its_members(om):
    """Not once per class in it."""
    om.update_class(NS + "Vehicle", new_parent="Tandem")
    found = _cycles(om)

    assert len(found) == 1, [i["message"] for i in found]
    for name in ("Vehicle", "Bicycle", "Tandem"):
        assert name in found[0]["message"]


def test_a_class_that_is_its_own_parent_counts(om):
    om.update_class(NS + "Vehicle", new_parent="Vehicle")
    assert len(_cycles(om)) == 1


def test_two_separate_loops_are_two_issues(om):
    om.update_class(NS + "Bicycle", new_parent="Tandem")
    om.add_class("Left")
    om.add_class("Right", parent="Left")
    om.update_class(NS + "Left", new_parent="Right")

    assert len(_cycles(om)) == 2


# --- naming the classes in the loop -----------------------------------------


def _cross_namespace_loop():
    """``base#A ⊑ other#A`` and back: one local name, two classes."""
    from rdflib import OWL, RDF, RDFS, URIRef

    o = OntologyManager()
    other = "http://other.example/"
    for uri in (o.namespace + "A", other + "A"):
        o.graph.add((URIRef(uri), RDF.type, OWL.Class))
    o.graph.add((URIRef(o.namespace + "A"), RDFS.subClassOf, URIRef(other + "A")))
    o.graph.add((URIRef(other + "A"), RDFS.subClassOf, URIRef(o.namespace + "A")))
    return o, o.namespace + "A", other + "A"


def test_a_cross_namespace_cycle_names_both_classes():
    """The local name alone read "A -> A -> A", which identifies nothing
    (Codex review of PR #416)."""
    o, base_a, other_a = _cross_namespace_loop()
    message = _cycles(o)[0]["message"]

    assert base_a in message and other_a in message, message
    assert "A -> A -> A" not in message


def test_a_cycle_within_one_namespace_still_reads_short(om):
    """The URI is the fallback, not the default: unique names stay names."""
    om.update_class(NS + "Vehicle", new_parent="Bicycle")
    message = _cycles(om)[0]["message"]

    assert "Bicycle -> Vehicle -> Bicycle" in message
    assert "http://" not in message


def test_the_issue_carries_the_uri_to_navigate_by():
    """A name may not be unique; this is what a click has to go on."""
    o, base_a, other_a = _cross_namespace_loop()
    issue = _cycles(o)[0]

    assert issue["subject_uri"] in {base_a, other_a}
    assert issue["subject"] == issue["subject_uri"], "an ambiguous name shows in full"


def test_names_are_disambiguated_against_the_whole_hierarchy(om):
    """Not against the cycle alone: a class outside the loop can share a local
    name with one inside it, and the reader has the ontology in front of them."""
    from rdflib import OWL, RDF, RDFS, URIRef

    other = "http://other.example/"
    om.graph.add((URIRef(other + "Bicycle"), RDF.type, OWL.Class))
    om.graph.add((URIRef(other + "Bicycle"), RDFS.subClassOf, URIRef(NS + "Vehicle")))
    om.update_class(NS + "Vehicle", new_parent="Bicycle")

    message = _cycles(om)[0]["message"]
    assert NS + "Bicycle" in message, message


# --- what must not be mistaken for a cycle ----------------------------------


def test_a_restriction_is_not_a_cycle(om):
    """A restriction is a subClassOf a blank node, and following those would
    report a loop through anonymous classes that says nothing to anyone."""
    om.add_object_property("hasPart")
    om.add_restriction("Bicycle", "hasPart", "someValuesFrom", "Vehicle")
    assert _cycles(om) == []


def test_a_diamond_is_not_a_cycle(om):
    """Two paths to one ancestor is multiple inheritance, not a loop."""
    om.add_class("Machine")
    om.update_class(NS + "Tandem", new_parent="Machine")
    om.update_class(NS + "Machine", new_parent="Vehicle")
    assert _cycles(om) == []


def test_every_bundled_ontology_is_clean():
    """The samples are real vocabularies (FOAF, GoodRelations, Pizza, Wine,
    PROV-O), which is the sharpest available check against false positives."""
    from pathlib import Path

    import orionbelt_ontology_builder as pkg
    from orionbelt_ontology_builder.ui import _rdf_format_for_path

    checked = 0
    for path in sorted((Path(pkg.__file__).parent / "samples").glob("*")):
        if path.suffix.lower() not in {".ttl", ".owl", ".rdf", ".xml", ".nt"}:
            continue
        loaded = OntologyManager()
        loaded.load_from_file(str(path), format=_rdf_format_for_path(path))
        assert _cycles(loaded) == [], f"{path.name}: {_cycles(loaded)}"
        checked += 1
    assert checked >= 5, checked


# --- the walk is shared with the SKOS check ---------------------------------


def test_both_hierarchies_are_walked_by_the_same_code():
    """A second implementation would be a second set of edge cases."""
    import inspect

    src = inspect.getsource(OntologyManager._skos_cycles)
    assert "_cycles_in(" in src

    parents = {"a": ["b"], "b": ["a"], "c": []}
    assert OntologyManager._cycles_in(parents) == [["a", "b"]]

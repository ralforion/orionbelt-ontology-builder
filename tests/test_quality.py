"""Quality rules (orionbelt_ontology_builder.quality): each rule, scoping, samples."""

import re

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS

from ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import (
    RULES,
    QualityConfig,
    RuleSettings,
    analyze,
)

#: Every rule switched on, the off-by-default ones included.
ALL = QualityConfig(rules={rule_id: RuleSettings(enabled=True) for rule_id in RULES})


def _only(*rule_ids, include_imports=False):
    """A configuration running exactly ``rule_ids``."""
    return QualityConfig(
        include_imports=include_imports,
        rules={r: RuleSettings(enabled=r in rule_ids) for r in RULES},
    )


def _om(*names, **parents):
    """An ontology with labelled classes ``names``, and ``child=parent`` edges."""
    om = OntologyManager(base_uri="http://test.org/q#")
    for name in names:
        om.add_class(name, label=name)
    for child, parent in parents.items():
        om.add_class(child, parent=parent, label=child)
    return om


def _sub(om, child, parent):
    om.graph.add((om.namespace[child], RDFS.subClassOf, om.namespace[parent]))


def _names(run, rule_id):
    return sorted(re.split("[#/]", f.resource)[-1] for f in run.by_rule(rule_id))


def _status(run, rule_id):
    status = run.status(rule_id)
    assert status is not None and status.state == "ran", status
    return status


# -- structure ---------------------------------------------------------------


class TestQ019RedundantSubclass:
    def test_edge_implied_through_another_parent(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "B", "C")
        _sub(om, "A", "C")
        run = analyze(om, ALL)
        [finding] = run.by_rule("Q019")
        assert finding.resource.endswith("#A")
        assert "A ⊑ B ⊑ C" in finding.message
        assert finding.evidence["redundant_parent"].endswith("#C")
        assert [u.rsplit("#")[-1] for u in finding.evidence["path"]] == ["A", "B", "C"]
        assert finding.suggestion and "Remove" in finding.suggestion

    def test_two_unrelated_parents_are_not_redundant(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "A", "C")
        assert analyze(om, ALL).by_rule("Q019") == []

    def test_cycle_is_left_to_q006(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "B", "A")
        _sub(om, "A", "C")
        run = analyze(om, ALL)
        assert run.by_rule("Q019") == []
        [cycle] = run.by_rule("Q006")
        assert len(cycle.evidence["cycle"]) == 2
        assert _status(run, "Q006").affected == 2


class TestQ020Islands:
    def _two_parts(self):
        om = _om("Thing1", "Thing2", "Thing3", "Lone1", "Lone2")
        _sub(om, "Thing2", "Thing1")
        _sub(om, "Thing3", "Thing1")
        _sub(om, "Lone2", "Lone1")
        return om

    def test_cut_off_pair_is_reported_and_main_model_is_not(self):
        run = analyze(self._two_parts(), ALL)
        [island] = run.by_rule("Q020")
        assert "Lone1, Lone2" in island.message
        assert len(island.evidence["members"]) == 2
        assert _status(run, "Q020").affected == 2

    def test_object_property_connects_classes(self):
        om = self._two_parts()
        om.add_object_property("rel", domain="Lone1", range_="Thing1")
        assert analyze(om, ALL).by_rule("Q020") == []

    def test_intersection_and_restriction_connect_classes(self):
        """``A ≡ B ⊓ ∃p.C`` ties A to both B and C, however deep it nests."""
        om = _om("A", "B", "C", "D", "E")
        _sub(om, "E", "D")
        g, ns = om.graph, om.namespace
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, ns["p"]))
        g.add((restriction, OWL.someValuesFrom, ns["C"]))
        members = BNode()
        Collection(g, members, [ns["B"], restriction])
        expression = BNode()
        g.add((expression, OWL.intersectionOf, members))
        g.add((ns["A"], OWL.equivalentClass, expression))
        _sub(om, "B", "D")
        assert analyze(om, ALL).by_rule("Q020") == []

    def test_lone_class_is_q007_not_an_island(self):
        om = _om("Thing1", "Thing2", "Alone")
        _sub(om, "Thing2", "Thing1")
        run = analyze(om, ALL)
        assert run.by_rule("Q020") == []
        assert _names(run, "Q007") == ["Alone"]


class TestQ022MultiParent:
    def test_off_by_default(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "A", "C")
        assert analyze(om).status("Q022") is None
        assert _names(analyze(om, ALL), "Q022") == ["A"]

    def test_owl_thing_is_not_a_second_parent(self):
        om = _om("A", "B")
        _sub(om, "A", "B")
        om.graph.add((om.namespace["A"], RDFS.subClassOf, OWL.Thing))
        assert analyze(om, ALL).by_rule("Q022") == []


class TestQ021MissingInverse:
    def _pair(self):
        om = _om("Person", "Company")
        om.add_object_property("worksFor", domain="Person", range_="Company")
        om.add_object_property("employs", domain="Company", range_="Person")
        return om

    def test_opposite_properties_without_inverse(self):
        run = analyze(self._pair(), ALL)
        [finding] = run.by_rule("Q021")
        assert finding.resource_kind == "Object Property"
        assert len(finding.related_resources) == 1
        assert _status(run, "Q021").affected == 2
        assert _status(run, "Q021").checked == 2

    def test_declared_inverse_is_fine(self):
        om = self._pair()
        om.graph.add((om.namespace["employs"], OWL.inverseOf, om.namespace["worksFor"]))
        assert analyze(om, ALL).by_rule("Q021") == []

    def test_self_loops_are_not_paired(self):
        om = _om("Person")
        om.add_object_property("knows", domain="Person", range_="Person")
        om.add_object_property("likes", domain="Person", range_="Person")
        assert analyze(om, ALL).by_rule("Q021") == []


class TestQ023OutsideHierarchy:
    def test_used_class_with_no_hierarchy(self):
        om = _om("Person", "Company", "Employee", Customer="Person")
        om.add_object_property("worksFor", domain="Employee", range_="Company")
        assert _names(analyze(om, ALL), "Q023") == ["Company", "Employee"]
        assert analyze(om).status("Q023") is None

    def test_owl1_intersection_counts_as_hierarchy(self):
        """Wine defines classes as ``RedWine owl:intersectionOf (Wine …)``."""
        om = _om("Wine", "RedWine", "Colour")
        members = BNode()
        Collection(om.graph, members, [om.namespace["Wine"]])
        om.graph.add((om.namespace["RedWine"], OWL.intersectionOf, members))
        om.add_object_property("hasColour", domain="RedWine", range_="Colour")
        assert _names(analyze(om, ALL), "Q023") == ["Colour"]


class TestAdaptersOverValidate:
    def test_q001_missing_label(self):
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("NoLabel")
        run = analyze(om, ALL)
        assert _names(run, "Q001") == ["NoLabel"]
        assert run.by_rule("Q001")[0].resource_kind == "Class"

    def test_q008_is_off_by_default_and_counts_a_property_once(self):
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_object_property("loose")
        assert analyze(om).status("Q008") is None
        run = analyze(om, ALL)
        assert {f.evidence["missing"] for f in run.by_rule("Q008")} == {
            "domain",
            "range",
        }
        assert _status(run, "Q008").affected == 1


# -- scope -------------------------------------------------------------------


class TestScope:
    def _with_merged_vocabulary(self):
        om = _om("Mine", MyChild="Mine")
        other = URIRef("http://other.org/v#Theirs")
        om.graph.add((other, RDF.type, OWL.Class))
        return om, other

    def test_other_namespaces_are_left_out(self):
        om, _ = self._with_merged_vocabulary()
        run = analyze(om, ALL)
        assert run.by_rule("Q001") == []
        assert _status(run, "Q001").checked == 2

    def test_include_imports_brings_them_in(self):
        om, _ = self._with_merged_vocabulary()
        run = analyze(om, _only("Q001", include_imports=True))
        assert _names(run, "Q001") == ["Theirs"]
        assert _status(run, "Q001").checked == 3

    def test_defined_by_counts_as_own(self):
        om, other = self._with_merged_vocabulary()
        om.graph.add((other, RDFS.isDefinedBy, om.ontology_uri))
        assert _names(analyze(om, ALL), "Q001") == ["Theirs"]

    def test_nothing_in_base_namespace_means_everything_is_own(self):
        """gist names its ontology ``…/ontology/gistCore`` and its classes
        ``…/ns/ontology/gist/…``: the whole graph is the ontology then."""
        om = OntologyManager(base_uri="http://test.org/ontology#")
        theirs = URIRef("http://test.org/ns/Theirs")
        om.graph.add((theirs, RDF.type, OWL.Class))
        om.graph.add((theirs, RDFS.comment, Literal("x")))
        assert _names(analyze(om, ALL), "Q001") == ["Theirs"]


# -- bundled samples -----------------------------------------------------------

SAMPLES = {
    "foaf.rdf": "xml",
    "goodrelations.owl": "xml",
    "pizza.owl": "xml",
    "prov-o.ttl": "turtle",
    "wine.owl": "xml",
    "gufo/gufo.ttl": "turtle",
    "gist/gistCore14.1.0.ttl": "turtle",
}


def _sample(name):
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/{name}", format=SAMPLES[name])
    return om


@pytest.mark.parametrize("sample", SAMPLES)
def test_samples_run_every_rule_cleanly(sample):
    run = analyze(_sample(sample), ALL)
    assert {s.rule_id for s in run.rules} == set(RULES)
    assert all(s.state == "ran" for s in run.rules), run.rules
    for finding in run.findings:
        assert finding.resource and finding.message and finding.suggestion


def test_gist_is_not_islands():
    """gist states its hierarchy as equivalentClass intersections; reading only
    subClassOf would break it into dozens of islands."""
    run = analyze(_sample("gist/gistCore14.1.0.ttl"), ALL)
    assert _status(run, "Q020").checked > 50
    assert run.by_rule("Q020") == []


def test_wine_island_is_the_real_one():
    """Vintage and VintageYear really are cut off from the rest of wine."""
    [island] = analyze(_sample("wine.owl"), ALL).by_rule("Q020")
    assert "Vintage, VintageYear" in island.message

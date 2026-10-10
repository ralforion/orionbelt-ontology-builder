"""Model quality checks and the quality score (orionbelt_ontology_builder.quality)."""

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import QUALITY_CHECKS, assess_quality

ALL = [check.key for check in QUALITY_CHECKS]


def _om(*names, **parents):
    """An ontology with labelled classes ``names``, and ``child=parent`` edges."""
    om = OntologyManager(base_uri="http://test.org/q#")
    for name in names:
        om.add_class(name, label=name)
    for child, parent in parents.items():
        om.add_class(child, parent=parent, label=child)
    return om


def _subjects(report, key):
    return [issue["subject"] for issue in report.findings[key]]


def _sub(om, child, parent):
    om.graph.add((om.namespace[child], RDFS.subClassOf, om.namespace[parent]))


# -- structure ---------------------------------------------------------------


class TestRedundantSubclass:
    def test_edge_implied_through_another_parent(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "B", "C")
        _sub(om, "A", "C")
        report = assess_quality(om, ALL)
        assert _subjects(report, "redundant_subclass") == ["A"]
        message = report.findings["redundant_subclass"][0]["message"]
        assert "'A' ⊑ 'C'" in message and "A ⊑ B ⊑ C" in message

    def test_two_unrelated_parents_are_not_redundant(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "A", "C")
        assert assess_quality(om, ALL).findings["redundant_subclass"] == []

    def test_cycle_is_left_to_class_cycle(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "B", "A")
        _sub(om, "A", "C")
        report = assess_quality(om, ALL)
        assert report.findings["redundant_subclass"] == []
        assert report.findings["class_cycle"]
        assert report.per_check["class_cycle"].affected == 2


class TestDisconnectedIsland:
    def test_cut_off_pair_is_reported_and_main_model_is_not(self):
        om = _om("Thing1", "Thing2", "Thing3", "Lone1", "Lone2")
        _sub(om, "Thing2", "Thing1")
        _sub(om, "Thing3", "Thing1")
        _sub(om, "Lone2", "Lone1")
        report = assess_quality(om, ALL)
        islands = report.findings["disconnected_island"]
        assert len(islands) == 1
        assert "Lone1, Lone2" in islands[0]["message"]
        assert report.per_check["disconnected_island"].affected == 2

    def test_object_property_connects_classes(self):
        om = _om("Thing1", "Thing2", "Thing3", "Lone1", "Lone2")
        _sub(om, "Thing2", "Thing1")
        _sub(om, "Thing3", "Thing1")
        _sub(om, "Lone2", "Lone1")
        om.add_object_property("rel", domain="Lone1", range_="Thing1")
        assert assess_quality(om, ALL).findings["disconnected_island"] == []

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
        assert assess_quality(om, ALL).findings["disconnected_island"] == []

    def test_lone_class_is_not_an_island(self):
        om = _om("Thing1", "Thing2", "Alone")
        _sub(om, "Thing2", "Thing1")
        report = assess_quality(om, ALL)
        assert report.findings["disconnected_island"] == []
        assert _subjects(report, "orphan_class") == ["Alone"]


class TestMultiParent:
    def test_off_by_default(self):
        om = _om("A", "B", "C")
        _sub(om, "A", "B")
        _sub(om, "A", "C")
        assert "multi_parent" not in assess_quality(om).findings
        assert _subjects(assess_quality(om, ALL), "multi_parent") == ["A"]

    def test_owl_thing_is_not_a_second_parent(self):
        om = _om("A", "B")
        _sub(om, "A", "B")
        om.graph.add((om.namespace["A"], RDFS.subClassOf, OWL.Thing))
        assert assess_quality(om, ALL).findings["multi_parent"] == []


class TestMissingInverse:
    def test_opposite_properties_without_inverse(self):
        om = _om("Person", "Company")
        om.add_object_property("worksFor", domain="Person", range_="Company")
        om.add_object_property("employs", domain="Company", range_="Person")
        report = assess_quality(om, ALL)
        assert len(report.findings["missing_inverse"]) == 1
        assert report.per_check["missing_inverse"].affected == 2

    def test_declared_inverse_is_fine(self):
        om = _om("Person", "Company")
        om.add_object_property("worksFor", domain="Person", range_="Company")
        om.add_object_property("employs", domain="Company", range_="Person")
        om.graph.add((om.namespace["employs"], OWL.inverseOf, om.namespace["worksFor"]))
        assert assess_quality(om, ALL).findings["missing_inverse"] == []

    def test_self_loops_are_not_paired(self):
        om = _om("Person")
        om.add_object_property("knows", domain="Person", range_="Person")
        om.add_object_property("likes", domain="Person", range_="Person")
        assert assess_quality(om, ALL).findings["missing_inverse"] == []


class TestFlatClass:
    def test_used_class_with_no_hierarchy(self):
        om = _om("Person", "Company", "Employee", "Customer")
        _sub(om, "Customer", "Person")
        om.add_object_property("worksFor", domain="Employee", range_="Company")
        report = assess_quality(om, ALL)
        assert sorted(_subjects(report, "flat_class")) == ["Company", "Employee"]
        assert "flat_class" not in assess_quality(om).findings

    def test_owl1_intersection_counts_as_hierarchy(self):
        """Wine defines classes as ``RedWine owl:intersectionOf (Wine …)``."""
        om = _om("Wine", "RedWine", "Colour")
        members = BNode()
        Collection(om.graph, members, [om.namespace["Wine"]])
        om.graph.add((om.namespace["RedWine"], OWL.intersectionOf, members))
        om.add_object_property("hasColour", domain="RedWine", range_="Colour")
        assert _subjects(assess_quality(om, ALL), "flat_class") == ["Colour"]


class TestReusedChecks:
    def test_missing_label_and_domain_come_from_validate(self):
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("NoLabel")
        om.add_object_property("loose")
        report = assess_quality(om, ALL)
        assert _subjects(report, "missing_label") == ["NoLabel"]
        assert {i["type"] for i in report.findings["missing_domain"]} == {
            "missing_domain",
            "missing_range",
        }
        # One property missing both still counts once.
        assert report.per_check["missing_domain"].affected == 1
        kinds = {i["subject_kind"] for i in report.findings["missing_domain"]}
        assert kinds == {"Object Property"}


# -- scope -------------------------------------------------------------------


class TestScope:
    def _with_merged_vocabulary(self):
        om = _om("Mine", "MyChild")
        _sub(om, "MyChild", "Mine")
        other = URIRef("http://other.org/v#Theirs")
        om.graph.add((other, RDF.type, OWL.Class))
        return om, other

    def test_other_namespaces_are_left_out(self):
        om, _ = self._with_merged_vocabulary()
        report = assess_quality(om, ALL)
        assert report.findings["missing_label"] == []
        assert report.per_check["missing_label"].population == 2

    def test_include_external_brings_them_in(self):
        om, _ = self._with_merged_vocabulary()
        report = assess_quality(om, ALL, include_external=True)
        assert _subjects(report, "missing_label") == ["Theirs"]
        assert report.per_check["missing_label"].population == 3

    def test_defined_by_counts_as_own(self):
        om, other = self._with_merged_vocabulary()
        om.graph.add((other, RDFS.isDefinedBy, om.ontology_uri))
        assert _subjects(assess_quality(om, ALL), "missing_label") == ["Theirs"]

    def test_nothing_in_base_namespace_means_everything_is_own(self):
        """gist names its ontology ``…/ontology/gistCore`` and its classes
        ``…/ns/ontology/gist/…``: the whole graph is the ontology then."""
        om = OntologyManager(base_uri="http://test.org/ontology#")
        theirs = URIRef("http://test.org/ns/Theirs")
        om.graph.add((theirs, RDF.type, OWL.Class))
        assert _subjects(assess_quality(om, ALL), "missing_label") == ["Theirs"]


# -- score -------------------------------------------------------------------


class TestScore:
    def test_empty_ontology_has_no_score(self):
        assert assess_quality(OntologyManager()).score is None

    def test_clean_ontology_scores_100(self):
        om = _om("A", "B")
        _sub(om, "B", "A")
        report = assess_quality(om)
        assert report.issues == []
        assert report.score == 100

    @pytest.mark.parametrize("size", [10, 1000])
    def test_score_does_not_depend_on_size(self, size):
        """One unlabelled class in ten scores the same as a hundred in a thousand."""
        om = OntologyManager(base_uri="http://test.org/q#")
        g, ns = om.graph, om.namespace
        g.add((ns["Root"], RDF.type, OWL.Class))
        g.add((ns["Root"], RDFS.label, Literal("Root")))
        for i in range(size - 1):
            cls = ns[f"C{i}"]
            g.add((cls, RDF.type, OWL.Class))
            g.add((cls, RDFS.subClassOf, ns["Root"]))
            if i >= size // 10:
                g.add((cls, RDFS.label, Literal(f"C{i}")))
        report = assess_quality(om, ["missing_label"])
        assert report.per_check["missing_label"].affected == size // 10
        assert report.score == 90

    def test_disabled_checks_do_not_run_or_count(self):
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("NoLabel")
        report = assess_quality(om, ["class_cycle"])
        assert list(report.findings) == ["class_cycle"]
        assert report.score == 100

    def test_warnings_weigh_more_than_info(self):
        """missing_label (warning, 0.5) and orphan_class (info, 1.0) → 62."""
        om = _om("Labelled", Child="Labelled")
        om.add_class("Bare", parent="Labelled")
        om.add_class("Bare2", parent="Labelled")
        report = assess_quality(om, ["missing_label", "orphan_class"])
        assert report.per_check["missing_label"].score == 0.5
        assert report.per_check["orphan_class"].score == 1.0
        assert report.score == round(100 * (3 * 0.5 + 1 * 1.0) / 4)


def test_manager_memoizes_per_revision():
    om = _om("A")
    first = om.assess_quality()
    assert om.assess_quality() is first
    om.add_class("B")
    assert om.assess_quality() is not first


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


@pytest.mark.parametrize("sample", SAMPLES)
def test_samples_assess_cleanly(sample):
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/{sample}", format=SAMPLES[sample])
    report = assess_quality(om, ALL)
    assert report.score is not None and 0 <= report.score <= 100
    for issue in report.issues:
        assert issue["subject_uri"] and issue["subject_kind"]


def test_gist_is_not_islands():
    """gist states its hierarchy as equivalentClass intersections; reading only
    subClassOf would break it into dozens of islands."""
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/gist/gistCore14.1.0.ttl")
    report = assess_quality(om, ALL)
    assert report.per_check["disconnected_island"].population > 50
    assert report.findings["disconnected_island"] == []


# -- page ----------------------------------------------------------------------


def _quality_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("C", label="C")
        om.add_class("B", parent="C", label="B")
        om.add_class("A", parent="B", label="A")
        # A second parent for A that its first one already implies.
        om.add_class_relation("A", "subClassOf", "C")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
    st.session_state["val_active_tab"] = "Quality"
    app.render_validation()


def test_page_runs_checks_and_opens_a_finding():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Run Quality Checks").click().run()
    assert not at.exception, at.exception
    assert any(m.label == "Quality score" for m in at.metric)
    assert any("already implied by A ⊑ B ⊑ C" in md.value for md in at.markdown)

    next(b for b in at.button if b.label == "Open").click().run()
    assert not at.exception, at.exception
    assert at.session_state["search_navigate_to"] == "Classes"

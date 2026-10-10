"""M2 quality rules: labels, definitions, placeholders, naming, deprecation,
self edges, and the SKOS adapters."""

import re

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import (
    PROFILES,
    RULES,
    QualityConfig,
    RuleSettings,
    analyze,
)

ALL = QualityConfig(rules={rule_id: RuleSettings(enabled=True) for rule_id in RULES})
NS = "http://test.org/q#"


def _om():
    return OntologyManager(base_uri=NS)


def _names(run, rule_id):
    return sorted(re.split("[#/]", f.resource)[-1] for f in run.by_rule(rule_id))


def _concept(om, name, *labels, **links):
    """A SKOS concept with ``(text, lang)`` prefLabels and broader/narrower links."""
    uri = URIRef(NS + name)
    om.graph.add((uri, RDF.type, SKOS.Concept))
    for text, lang in labels:
        om.graph.add((uri, SKOS.prefLabel, Literal(text, lang=lang)))
    for pred, target in links.items():
        om.graph.add((uri, SKOS[pred], URIRef(NS + target)))
    return uri


# -- Q001 / Q002 -------------------------------------------------------------


class TestQ001MissingLabel:
    def test_classes_properties_and_concepts(self):
        om = _om()
        om.add_class("Bare")
        om.add_class("Named", label="Named")
        om.add_object_property("rel")
        _concept(om, "c1")
        _concept(om, "c2", ("Two", "en"))
        run = analyze(om, ALL)
        assert _names(run, "Q001") == ["Bare", "c1", "rel"]
        kinds = {f.resource_kind for f in run.by_rule("Q001")}
        assert kinds == {"Class", "Object Property", "SKOS Concept"}

    def test_blank_label_counts_as_missing(self):
        om = _om()
        om.add_class("Blank")
        om.graph.add((URIRef(NS + "Blank"), RDFS.label, Literal("  ")))
        assert _names(analyze(om, ALL), "Q001") == ["Blank"]


class TestQ002MissingDefinition:
    @pytest.mark.parametrize(
        "pred",
        [
            SKOS.definition,
            RDFS.comment,
            DCTERMS.description,
            URIRef("http://purl.obolibrary.org/obo/IAO_0000115"),
        ],
    )
    def test_any_definition_predicate_counts(self, pred):
        om = _om()
        om.add_class("Defined", label="Defined")
        om.graph.add(
            (URIRef(NS + "Defined"), pred, Literal("A thing that is defined."))
        )
        om.add_class("Undefined", label="Undefined")
        assert _names(analyze(om, ALL), "Q002") == ["Undefined"]

    def test_info_by_default_warning_under_strict_documentation(self):
        om = _om()
        om.add_class("Undefined", label="Undefined")
        assert analyze(om).by_rule("Q002")[0].severity == "info"
        strict = QualityConfig(profile="strict_documentation")
        assert analyze(om, strict).by_rule("Q002")[0].severity == "warning"


# -- Q003 ----------------------------------------------------------------------


class TestQ003DuplicateLabels:
    def test_same_label_same_language_is_reported_once_per_group(self):
        om = _om()
        om.add_class("Car", label="Automobile")
        om.add_class("Auto", label="automobile ")
        om.add_class("Truck", label="Truck")
        run = analyze(om, ALL)
        [finding] = run.by_rule("Q003")
        assert finding.related_resources
        assert set(finding.evidence["resources"]) == {NS + "Auto", NS + "Car"}
        assert run.status("Q003").affected == 2

    def test_different_languages_do_not_clash(self):
        om = _om()
        om.add_class("A", label="Bank")
        om.add_class("B", label="Bank")
        om.graph.remove((URIRef(NS + "A"), RDFS.label, None))
        om.graph.remove((URIRef(NS + "B"), RDFS.label, None))
        om.graph.add((URIRef(NS + "A"), RDFS.label, Literal("Bank", lang="en")))
        om.graph.add((URIRef(NS + "B"), RDFS.label, Literal("Bank", lang="de")))
        assert analyze(om, ALL).by_rule("Q003") == []

    def test_a_class_and_a_property_may_share_a_word(self):
        om = _om()
        om.add_class("Name", label="name")
        om.add_data_property("name_", label="name")
        assert analyze(om, ALL).by_rule("Q003") == []


# -- Q004 ----------------------------------------------------------------------


class TestQ004Placeholders:
    @pytest.mark.parametrize(
        "text",
        ["TODO", "tbd", "FIXME: write this", "-", "...", "", "Lorem ipsum dolor"],
    )
    def test_placeholders_are_found(self, text):
        om = _om()
        om.add_class("C", label="C")
        om.graph.add((URIRef(NS + "C"), RDFS.comment, Literal(text)))
        [finding] = analyze(om, ALL).by_rule("Q004")
        assert finding.evidence["value"] == text

    @pytest.mark.parametrize(
        "text", ["A todo-list item.", "Things to do later.", "A real definition."]
    )
    def test_real_text_is_not_a_placeholder(self, text):
        om = _om()
        om.add_class("C", label="C")
        om.graph.add((URIRef(NS + "C"), RDFS.comment, Literal(text)))
        assert analyze(om, ALL).by_rule("Q004") == []


# -- Q005 ----------------------------------------------------------------------


class TestQ005Naming:
    def _conventions(self, run):
        return sorted(
            (re.split("[#/]", f.resource)[-1], f.evidence["convention"])
            for f in run.by_rule("Q005")
        )

    def test_case_conventions(self):
        om = _om()
        om.graph.add((URIRef(NS + "purchase_order"), RDF.type, OWL.Class))
        om.graph.add((URIRef(NS + "HasPart"), RDF.type, OWL.ObjectProperty))
        om.add_class("PurchaseOrder", label="Purchase order")
        om.add_object_property("hasPart")
        assert self._conventions(analyze(om, ALL)) == [
            ("HasPart", "property_lower_camel"),
            ("purchase_order", "class_upper_camel"),
        ]

    def test_opaque_identifiers_are_left_alone(self):
        om = OntologyManager(base_uri="http://purl.obolibrary.org/obo/")
        om.graph.add(
            (URIRef("http://purl.obolibrary.org/obo/GO_0008150"), RDF.type, OWL.Class)
        )
        assert analyze(om, ALL).by_rule("Q005") == []

    @pytest.mark.parametrize(
        ("name", "flagged"),
        [
            ("Customers", True),
            ("OrderLines", True),
            ("Status", False),
            ("Address", False),
            ("Analysis", False),
            ("Business", False),
            ("Species", False),
        ],
    )
    def test_plural_class_names(self, name, flagged):
        om = _om()
        om.add_class(name)
        conventions = [c for _, c in self._conventions(analyze(om, ALL))]
        assert ("class_plural" in conventions) is flagged

    def test_attribute_like_class_names(self):
        om = _om()
        om.add_class("BirthDate")
        om.add_class("Birth")
        assert self._conventions(analyze(om, ALL)) == [
            ("BirthDate", "class_attribute_like")
        ]

    def test_english_heuristics_skip_non_english_labels(self):
        om = _om()
        om.add_class("Kunden")
        om.graph.add((URIRef(NS + "Kunden"), RDFS.label, Literal("Kunden", lang="de")))
        assert analyze(om, ALL).by_rule("Q005") == []

    def test_off_in_the_skos_profile(self):
        assert PROFILES["skos_vocabulary"]["Q005"].enabled is False


# -- Q009 / Q006 ---------------------------------------------------------------


class TestQ009SelfEdges:
    def test_class_subclass_of_itself_is_q009_not_q006(self):
        om = _om()
        om.add_class("Loop", label="Loop")
        om.graph.add((URIRef(NS + "Loop"), RDFS.subClassOf, URIRef(NS + "Loop")))
        run = analyze(om, ALL)
        assert _names(run, "Q009") == ["Loop"]
        assert run.by_rule("Q006") == []

    def test_concept_its_own_broader(self):
        om = _om()
        _concept(om, "c", ("C", "en"), broader="c")
        run = analyze(om, ALL)
        [finding] = run.by_rule("Q009")
        assert finding.resource_kind == "SKOS Concept"
        assert run.by_rule("Q006") == []

    def test_skos_cycle_is_q006(self):
        om = _om()
        _concept(om, "a", ("A", "en"), broader="b")
        _concept(om, "b", ("B", "en"), broader="a")
        assert _names(analyze(om, ALL), "Q006")


# -- Q010 ----------------------------------------------------------------------


def test_q010_two_preflabels_in_one_language():
    om = _om()
    _concept(om, "c", ("One", "en"), ("Two", "en"), ("Eins", "de"))
    [finding] = analyze(om, ALL).by_rule("Q010")
    assert finding.severity == "error"
    assert finding.resource_kind == "SKOS Concept"


# -- Q016 ----------------------------------------------------------------------


class TestQ016Deprecated:
    def _with_deprecated(self):
        om = _om()
        om.add_class("Old", label="Old")
        om.add_class("New", label="New")
        om.graph.add((URIRef(NS + "Old"), OWL.deprecated, Literal(True)))
        om.graph.add((URIRef(NS + "Old"), DCTERMS.isReplacedBy, URIRef(NS + "New")))
        return om

    def test_subclass_of_a_deprecated_class(self):
        om = self._with_deprecated()
        om.add_class("Child", parent="Old", label="Child")
        [finding] = analyze(om, ALL).by_rule("Q016")
        assert finding.resource == NS + "Child"
        assert finding.evidence["replacement"] == NS + "New"
        assert "'New'" in finding.suggestion

    def test_use_inside_a_restriction_names_the_class(self):
        om = self._with_deprecated()
        om.add_class("User", label="User")
        om.add_object_property("has")
        restriction = BNode()
        om.graph.add((restriction, RDF.type, OWL.Restriction))
        om.graph.add((restriction, OWL.onProperty, URIRef(NS + "has")))
        om.graph.add((restriction, OWL.someValuesFrom, URIRef(NS + "Old")))
        om.graph.add((URIRef(NS + "User"), RDFS.subClassOf, restriction))
        assert _names(analyze(om, ALL), "Q016") == ["User"]

    @pytest.mark.parametrize(
        "pred", [OWL.equivalentClass, OWL.disjointWith, RDFS.seeAlso]
    )
    def test_aliases_disjointness_and_see_also_are_not_uses(self, pred):
        om = self._with_deprecated()
        om.graph.add((URIRef(NS + "New"), pred, URIRef(NS + "Old")))
        assert analyze(om, ALL).by_rule("Q016") == []

    def test_deprecated_resources_using_each_other_are_ignored(self):
        om = self._with_deprecated()
        om.add_class("Older", parent="Old", label="Older")
        om.graph.add(
            (
                URIRef(NS + "Older"),
                OWL.deprecated,
                Literal("true", datatype=XSD.boolean),
            )
        )
        assert analyze(om, ALL).by_rule("Q016") == []


# -- profiles --------------------------------------------------------------------


def test_profiles_only_name_known_rules():
    for name, overrides in PROFILES.items():
        assert set(overrides) <= set(RULES), name
        QualityConfig(profile=name)  # validates


# -- review fixes (PR #505) ------------------------------------------------------

SKOSXL = "http://www.w3.org/2008/05/skos-xl#"


def test_q010_reports_each_language_separately():
    om = _om()
    _concept(om, "c", ("One", "en"), ("Two", "en"), ("Eins", "de"), ("Zwei", "de"))
    findings = analyze(om, ALL).by_rule("Q010")
    assert sorted(f.evidence["lang"] for f in findings) == ["de", "en"]


def test_q006_keeps_distinct_cycles_through_one_concept():
    om = _om()
    _concept(om, "a", ("A", "en"))
    _concept(om, "b", ("B", "en"), broader="a")
    _concept(om, "c", ("C", "en"), broader="a")
    om.graph.add((URIRef(NS + "a"), SKOS.broader, URIRef(NS + "b")))
    om.graph.add((URIRef(NS + "a"), SKOS.broader, URIRef(NS + "c")))
    cycles = {frozenset(f.evidence["cycle"]) for f in analyze(om, ALL).by_rule("Q006")}
    assert cycles == {
        frozenset({NS + "a", NS + "b"}),
        frozenset({NS + "a", NS + "c"}),
    }


def test_a_self_loop_does_not_hide_a_larger_skos_cycle():
    om = _om()
    _concept(om, "a", ("A", "en"), broader="a")
    _concept(om, "b", ("B", "en"), broader="a")
    om.graph.add((URIRef(NS + "a"), SKOS.broader, URIRef(NS + "b")))
    run = analyze(om, ALL)
    assert _names(run, "Q009") == ["a"]
    [cycle] = run.by_rule("Q006")
    assert set(cycle.evidence["cycle"]) == {NS + "a", NS + "b"}


def _xl_label(om, concept, text, lang):
    label = BNode()
    om.graph.add((URIRef(NS + concept), URIRef(SKOSXL + "prefLabel"), label))
    om.graph.add((label, URIRef(SKOSXL + "literalForm"), Literal(text, lang=lang)))


def test_skos_xl_labels_count_as_labels():
    om = _om()
    _concept(om, "c1")
    _concept(om, "c2")
    _xl_label(om, "c1", "Dog", "en")
    _xl_label(om, "c2", "dog", "en")
    run = analyze(om, ALL)
    assert run.by_rule("Q001") == []
    [duplicate] = run.by_rule("Q003")
    assert set(duplicate.evidence["resources"]) == {NS + "c1", NS + "c2"}


def test_q010_counts_skos_xl_labels():
    om = _om()
    _concept(om, "c", ("Dog", "en"))
    _xl_label(om, "c", "Hound", "en")
    assert [f.evidence["lang"] for f in analyze(om, ALL).by_rule("Q010")] == ["en"]


def test_a_cycle_with_an_imported_concept_is_kept():
    """The imported URI sorts first; the cycle still involves an own concept."""
    om = _om()
    theirs = URIRef("http://a-imported.org/v#t")
    om.graph.add((theirs, RDF.type, SKOS.Concept))
    om.graph.add((theirs, SKOS.prefLabel, Literal("T", lang="en")))
    _concept(om, "mine", ("Mine", "en"))
    om.graph.add((theirs, SKOS.broader, URIRef(NS + "mine")))
    om.graph.add((URIRef(NS + "mine"), SKOS.broader, theirs))
    [cycle] = analyze(om, ALL).by_rule("Q006")
    assert cycle.resource == NS + "mine"


class TestQ016ReviewFixes:
    def _with_deprecated(self):
        om = _om()
        om.add_class("Old", label="Old")
        om.graph.add((URIRef(NS + "Old"), OWL.deprecated, Literal(True)))
        return om

    def test_typing_an_individual_with_a_deprecated_class_is_a_use(self):
        om = self._with_deprecated()
        om.graph.add((URIRef(NS + "alice"), RDF.type, URIRef(NS + "Old")))
        [finding] = analyze(om, ALL).by_rule("Q016")
        assert finding.resource == NS + "alice"
        assert finding.resource_kind == "Individual"

    def test_individual_using_a_deprecated_property_opens_as_individual(self):
        om = _om()
        om.add_class("Person", label="Person")
        om.add_data_property("oldName")
        om.graph.add((URIRef(NS + "oldName"), OWL.deprecated, Literal(True)))
        om.add_individual("alice", "Person")
        om.graph.add((URIRef(NS + "alice"), URIRef(NS + "oldName"), Literal("A")))
        [finding] = analyze(om, ALL).by_rule("Q016")
        assert finding.resource_kind == "Individual"

    def test_every_class_sharing_a_restriction_is_reported(self):
        om = self._with_deprecated()
        om.add_class("A", label="A")
        om.add_class("B", label="B")
        om.add_object_property("has")
        restriction = BNode()
        om.graph.add((restriction, RDF.type, OWL.Restriction))
        om.graph.add((restriction, OWL.onProperty, URIRef(NS + "has")))
        om.graph.add((restriction, OWL.someValuesFrom, URIRef(NS + "Old")))
        om.graph.add((URIRef(NS + "A"), RDFS.subClassOf, restriction))
        om.graph.add((URIRef(NS + "B"), RDFS.subClassOf, restriction))
        assert _names(analyze(om, ALL), "Q016") == ["A", "B"]

    def test_a_literal_spelling_the_uri_is_not_a_reference(self):
        om = self._with_deprecated()
        om.add_class("Doc", label="Doc")
        om.graph.add((URIRef(NS + "Doc"), RDFS.comment, Literal(NS + "Old")))
        assert analyze(om, ALL).by_rule("Q016") == []

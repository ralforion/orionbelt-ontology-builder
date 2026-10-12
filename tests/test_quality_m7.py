"""M7: the extended rule catalogue, and suppressions."""

import csv
import io
import json
import re
import time

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import ui
from orionbelt_ontology_builder.quality import (
    PROFILES,
    RULES,
    QualityConfig,
    QualityConfigError,
    RuleSettings,
    Suppression,
    analyze,
    partition,
)
from orionbelt_ontology_builder.quality.exports import findings_csv, findings_json

ALL = QualityConfig(rules={rule_id: RuleSettings(enabled=True) for rule_id in RULES})
NS = "http://test.org/q#"
Q = lambda name: URIRef(NS + name)


def _om():
    return OntologyManager(base_uri=NS)


def _names(run, rule_id):
    return sorted(re.split("[#/]", f.resource)[-1] for f in run.by_rule(rule_id))


def _cls(om, name, label=None, definition=None, parent=None, lang="en"):
    om.graph.add((Q(name), RDF.type, OWL.Class))
    if label is not None:
        om.graph.add((Q(name), RDFS.label, Literal(label, lang=lang)))
    if definition is not None:
        om.graph.add((Q(name), SKOS.definition, Literal(definition, lang=lang)))
    if parent is not None:
        om.graph.add((Q(name), RDFS.subClassOf, Q(parent)))


# -- Q014 similar labels -----------------------------------------------------------


class TestQ014SimilarLabels:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("familyName", "family_name"),
            ("Customer Order", "customer orders"),
            ("Organisation", "Organsiation"),  # two swapped letters
            ("Measurement", "Measurment"),  # one left out
            ("Contractor", "Contrakctor"),  # one put in
        ],
    )
    def test_near_duplicates_are_suggested(self, a, b):
        om = _om()
        _cls(om, "A", a)
        _cls(om, "B", b)
        assert _names(analyze(om, ALL), "Q014") == ["A"]

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("influenced", "influencer"),  # at the end
            ("VegetarianPizza", "VegetarianPizza1"),
            ("height", "weight"),  # at the start
            ("Qualitative value", "Quantitative value"),  # a different word
            ("East Africa", "West Africa"),
            ("hasBeginPoint", "hasEndPoint"),
            ("Cat", "Car"),  # too short to tell
            ("Class 1 of the tree", "Class 2 of the tree"),  # numbered
            ("Release 2 notes", "Release 22 notes"),
        ],
    )
    def test_different_words_are_not(self, a, b):
        om = _om()
        _cls(om, "A", a)
        _cls(om, "B", b)
        assert analyze(om, ALL).by_rule("Q014") == []

    def test_exact_duplicates_are_left_to_q003(self):
        om = _om()
        _cls(om, "A", "Customer")
        _cls(om, "B", "Customer")
        run = analyze(om, ALL)
        assert run.by_rule("Q014") == [] and run.by_rule("Q003")

    def test_kinds_and_languages_are_compared_apart(self):
        om = _om()
        _cls(om, "Order", "Order")
        om.add_object_property("order")
        om.graph.add((Q("order"), RDFS.label, Literal("orders", lang="en")))
        _cls(om, "Bestellung", "Customer order", lang="en")
        _cls(om, "Bestellung2", "Customer orders", lang="de")
        assert analyze(om, ALL).by_rule("Q014") == []

    def test_one_resource_with_two_alike_labels_is_not_a_pair(self):
        om = _om()
        _cls(om, "A", "Colour")
        om.graph.add((Q("A"), RDFS.label, Literal("Colours", lang="en")))
        assert analyze(om, ALL).by_rule("Q014") == []

    def test_the_finding_names_both(self):
        om = _om()
        _cls(om, "A", "familyName")
        _cls(om, "B", "family_name")
        [finding] = analyze(om, ALL).by_rule("Q014")
        assert finding.related_resources == (NS + "B",)
        assert finding.evidence["labels"] == ["familyName", "family_name"]

    def test_stays_fast_on_a_large_vocabulary(self):
        """Compared only with neighbours in length, not all pairs."""
        om = _om()
        for i in range(6000):
            _cls(om, f"C{i}", f"Concept number {i:05d} of the big list")
        began = time.perf_counter()
        run = analyze(om, QualityConfig(rules={"Q014": RuleSettings(enabled=True)}))
        assert run.status("Q014").state == "ran"
        assert time.perf_counter() - began < 10


# -- Q012 acronyms -------------------------------------------------------------------


class TestQ012Acronyms:
    def test_acronym_without_a_definition(self):
        om = _om()
        _cls(om, "Gdpr", "GDPR consent")
        _cls(
            om,
            "Explained",
            "KPI target",
            "A target value of a key performance indicator.",
        )
        _cls(om, "Roman", "Phase II trial")
        _cls(om, "Plain", "Customer")
        run = analyze(om, ALL)
        assert _names(run, "Q012") == ["Gdpr"]
        assert run.by_rule("Q012")[0].evidence["acronyms"] == ["GDPR"]

    def test_plural_acronyms_count(self):
        om = _om()
        _cls(om, "Apis", "Public APIs")
        assert _names(analyze(om, ALL), "Q012") == ["Apis"]

    def test_off_by_default_on_in_strict(self):
        assert not QualityConfig().enabled("Q012")
        assert QualityConfig(profile="strict_documentation").enabled("Q012")


# -- Q013 vague definitions ------------------------------------------------------------


class TestQ013VagueDefinitions:
    def _reasons(self, definition, *, label="Customer", parent=None, lang="en"):
        om = _om()
        if parent:
            _cls(om, parent, parent)
        _cls(om, "Customer", label, definition, parent=parent, lang=lang)
        return [
            r
            for f in analyze(om, ALL).by_rule("Q013")
            if f.resource == NS + "Customer"
            for r in f.evidence["reasons"]
        ]

    def test_a_good_definition_passes(self):
        assert (
            self._reasons(
                "A Person who has bought at least one product from us.",
                parent="Person",
            )
            == []
        )

    def test_too_short(self):
        assert "too short" in self._reasons("A buyer.")

    def test_only_repeats_the_name(self):
        assert "only repeats the name" in self._reasons(
            "This is a customer, the customer."
        )

    def test_only_says_what_it_is_not(self):
        assert "says only what it is not" in self._reasons(
            "Not a supplier, nor an employee of the firm."
        )

    def test_does_not_name_its_superclass(self):
        assert "does not name its superclass" in self._reasons(
            "Someone who has bought at least one product from us.", parent="Person"
        )

    def test_other_languages_are_not_judged(self):
        assert self._reasons("Kurz.", lang="de") == []

    def test_placeholders_are_left_to_q004(self):
        assert self._reasons("TODO") == []


# -- Q017 language tags ------------------------------------------------------------------


def test_q017_untagged_text():
    om = _om()
    om.graph.add((Q("Tagged"), RDF.type, OWL.Class))
    om.graph.add((Q("Tagged"), RDFS.label, Literal("Tagged", lang="en")))
    om.graph.add((Q("Plain"), RDF.type, OWL.Class))
    om.graph.add((Q("Plain"), RDFS.label, Literal("Plain")))
    om.graph.add((Q("Typed"), RDF.type, OWL.Class))
    om.graph.add((Q("Typed"), RDFS.label, Literal("Typed", lang="en")))
    om.graph.add((Q("Typed"), RDFS.comment, Literal("A note.", datatype=XSD.string)))
    run = analyze(om, ALL)
    assert _names(run, "Q017") == ["Plain", "Typed"]
    assert next(f for f in run.by_rule("Q017") if "Typed" in f.resource).evidence[
        "predicates"
    ] == ["comment"]


def test_q017_is_on_for_skos_vocabularies():
    assert not QualityConfig().enabled("Q017")
    assert QualityConfig(profile="skos_vocabulary").enabled("Q017")


# -- Q018 unused properties --------------------------------------------------------------


def test_q018_unused_properties():
    om = _om()
    for name in ("unused", "stated", "restricted", "chained", "inverse", "shaped"):
        om.graph.add((Q(name), RDF.type, OWL.ObjectProperty))
    om.graph.add((Q("x"), Q("stated"), Q("y")))
    restriction = BNode()
    om.graph.add((restriction, RDF.type, OWL.Restriction))
    om.graph.add((restriction, OWL.onProperty, Q("restricted")))
    chain = BNode()
    Collection(om.graph, chain, [Q("chained"), Q("stated")])
    om.graph.add((Q("stated"), OWL.propertyChainAxiom, chain))
    om.graph.add((Q("inverse"), OWL.inverseOf, Q("stated")))
    om.graph.add((BNode(), URIRef("http://www.w3.org/ns/shacl#path"), Q("shaped")))
    assert _names(analyze(om, ALL), "Q018") == ["unused"]


def test_q018_survives_a_cyclic_chain():
    om = _om()
    om.graph.add((Q("p"), RDF.type, OWL.ObjectProperty))
    head = BNode()
    om.graph.add((head, RDF.first, Q("p")))
    om.graph.add((head, RDF.rest, head))
    om.graph.add((Q("q"), OWL.propertyChainAxiom, head))
    run = analyze(om, ALL)
    assert run.status("Q018").state == "ran"


# -- Q011 broader/narrower mirrored ----------------------------------------------------


def test_q011_unmirrored_links():
    om = _om()
    for name in ("top", "mid", "leaf"):
        om.graph.add((Q(name), RDF.type, SKOS.Concept))
    om.graph.add((Q("mid"), SKOS.broader, Q("top")))
    om.graph.add((Q("top"), SKOS.narrower, Q("mid")))
    om.graph.add((Q("leaf"), SKOS.broader, Q("mid")))
    run = analyze(om, ALL)
    [finding] = run.by_rule("Q011")
    assert finding.resource == NS + "leaf"
    assert finding.related_resources == (NS + "mid",)


def test_every_rule_in_a_profile_exists():
    for overrides in PROFILES.values():
        assert set(overrides) <= set(RULES)


# -- suppressions ------------------------------------------------------------------------


def _with_findings():
    om = _om()
    _cls(om, "A", "familyName")
    _cls(om, "B", "family_name")
    om.add_class("NoLabel")
    return om


def test_config_round_trips_suppressions():
    config = QualityConfig().with_suppression(
        Suppression("Q001", NS + "X", "Imported as is.", "ralf", "2026-10-12")
    )
    again = QualityConfig.from_json(config.to_json())
    assert again == config
    # Without suppressions the stored form is as before.
    assert "suppressions" not in QualityConfig().to_dict()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"suppressions": {}}, "expected a list"),
        (
            {
                "suppressions": [
                    {"rule_id": "Q999", "resource": "x", "justification": "y"}
                ]
            },
            "unknown rule ID",
        ),
        (
            {
                "suppressions": [
                    {"rule_id": "Q001", "resource": "x", "justification": " "}
                ]
            },
            "say why",
        ),
        (
            {
                "suppressions": [
                    {"rule_id": "Q001", "resource": "", "justification": "y"}
                ]
            },
            "must not be empty",
        ),
        (
            {
                "suppressions": [
                    {
                        "rule_id": "Q001",
                        "resource": "x",
                        "justification": "y",
                        "note": 1,
                    }
                ]
            },
            "unknown keys",
        ),
    ],
)
def test_invalid_suppressions_are_refused(raw, message):
    with pytest.raises(QualityConfigError, match=message):
        QualityConfig.from_dict(raw)


def test_a_suppressed_finding_is_set_aside_not_lost():
    om = _with_findings()
    config = ALL.with_suppression(Suppression("Q001", NS + "NoLabel", "On purpose."))
    run = analyze(om, config)
    assert "NoLabel" not in _names(run, "Q001")
    [(finding, suppression)] = run.suppressed
    assert finding.resource == NS + "NoLabel"
    assert suppression.justification == "On purpose."
    assert sum(run.counts().values()) == len(run.findings)
    # Suppressing decides what is shown, not what runs.
    assert config.fingerprint == ALL.fingerprint
    # And can be undone on the stored run.
    shown, suppressed = partition(run.all_findings(), ALL)
    assert suppressed == () and len(shown) == len(run.findings) + 1


def test_suppressing_again_replaces_the_reason():
    config = (
        QualityConfig()
        .with_suppression(Suppression("Q001", "x", "First."))
        .with_suppression(Suppression("Q001", "x", "Second."))
    )
    assert [s.justification for s in config.suppressions] == ["Second."]
    assert config.without_suppression("Q001", "x").suppressions == ()


def test_exports_list_suppressed_findings_with_the_reason():
    om = _with_findings()
    run = analyze(
        om, ALL.with_suppression(Suppression("Q001", NS + "NoLabel", "On purpose."))
    )
    document = json.loads(
        findings_json(run.findings, run=run, suppressed=run.suppressed)
    )
    [entry] = document["suppressed"]
    assert entry["resource"] == NS + "NoLabel"
    assert entry["suppression"]["justification"] == "On purpose."
    assert all(
        f["resource"] != NS + "NoLabel" or f["rule_id"] != "Q001"
        for f in document["findings"]
    )
    rows = list(csv.DictReader(io.StringIO(findings_csv(run.findings, run.suppressed))))
    assert len(rows) == len(run.findings) + 1
    assert rows[-1]["suppressed"] == "On purpose."
    assert all(not r["suppressed"] for r in rows[:-1])


# -- page --------------------------------------------------------------------------------


def _quality_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("Labelled", label="Labelled")
        om.add_class("NoLabel")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["_quality_configs_restored"] = True
    st.session_state["val_active_tab"] = "Quality"
    app.render_validation()


def _select(at, rule_title):
    table = next(f.value for f in at.dataframe if "Message" in f.value.columns)
    row = int(table.index[table["Rule"] == rule_title][0])
    key = next(
        k
        for k in at.session_state.filtered_state
        if k.startswith("quality_") and "_table_" in k
    )
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    at.run()


def _stored(at):
    [raw] = at.session_state[ui.QUALITY_CONFIGS_STATE].values()
    return QualityConfig.from_dict(raw)


def test_page_suppresses_a_finding_and_shows_it_again():
    at = AppTest.from_function(_quality_page)
    at.run(timeout=120)
    next(b for b in at.button if b.label == "Run Quality Checks").click().run()
    _select(at, "Missing preferred label")
    suppress = next(b for b in at.button if b.label == "Suppress")
    assert suppress.disabled  # a reason first
    # AppTest does not carry an injected table selection across reruns (the
    # browser does), so the reason goes in with the selection, in one rerun.
    why = next(t for t in at.text_input if t.label == "Why is this fine?")
    at.session_state[why.key] = "Labelled in the imported vocabulary."
    _select(at, "Missing preferred label")
    next(b for b in at.button if b.label == "Suppress").click().run()
    assert not at.exception, at.exception
    [suppression] = _stored(at).suppressions
    assert suppression.justification == "Labelled in the imported vocabulary."
    assert suppression.date
    # Hidden at once, without a new run or a stale warning.
    assert not at.warning
    assert any(e.label == "Suppressed findings (1)" for e in at.expander)
    table = next(f.value for f in at.dataframe if "Message" in f.value.columns)
    assert "Missing preferred label" not in set(table["Rule"])
    # A profile change keeps it.
    next(s for s in at.selectbox if s.label == "Profile").select(
        "strict_documentation"
    ).run()
    assert len(_stored(at).suppressions) == 1
    next(b for b in at.button if b.label == "Show again").click().run()
    assert _stored(at).suppressions == ()
    assert not any(e.label.startswith("Suppressed findings") for e in at.expander)

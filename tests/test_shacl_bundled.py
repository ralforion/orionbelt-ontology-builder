"""Built-in SHACL shapes: valid, safe, and in agreement with the Python rules."""

import pytest
from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import shacl
from orionbelt_ontology_builder.quality import (
    RULES,
    QualityConfig,
    RuleSettings,
    analyze,
)

Q = Namespace("http://test.org/q#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
IAO_DEFINITION = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")

#: Which policy shape stands for which rule, by the shape's label.
POLICY = {
    "Q001": "Missing preferred label (Q001)",
    "Q002": "Missing definition (Q002)",
    "Q010": "More than one prefLabel per language (Q010)",
}

ALL_IN_SCOPE = QualityConfig(
    include_imports=True,
    rules={rule_id: RuleSettings(enabled=True) for rule_id in RULES},
)


@pytest.mark.parametrize("key", list(shacl.BUNDLED_SHAPES))
def test_every_built_in_set_is_valid_safe_shacl(key):
    """Vetted like user shapes: meta-shapes, no SERVICE."""
    shapes = shacl.parse_shapes(shacl._bundled_text(key))
    assert shacl.list_shapes(shapes)


def _xl(om, subject, text, lang):
    label = BNode()
    om.graph.add((subject, SKOSXL.prefLabel, label))
    om.graph.add((label, SKOSXL.literalForm, Literal(text, lang=lang)))


def _fixture():
    """One case for each way the rules and shapes could part company."""
    om = OntologyManager(base_uri=str(Q))
    g = om.graph

    def cls(name, **annotations):
        g.add((Q[name], RDF.type, OWL.Class))
        for pred, value in annotations.items():
            g.add(
                (Q[name], {"label": RDFS.label, "comment": RDFS.comment}[pred], value)
            )

    cls("Labelled", label=Literal("Labelled", lang="en"))
    cls("Unlabelled")
    cls("BlankLabel", label=Literal("   "))
    cls("CommentedOnly", comment=Literal("A thing."))
    cls("BlankComment", comment=Literal(" "), label=Literal("Blank comment"))
    g.add((Q.PrefLabelled, RDF.type, OWL.Class))
    g.add((Q.PrefLabelled, SKOS.prefLabel, Literal("Pref", lang="en")))
    g.add((Q.Defined, RDF.type, OWL.Class))
    g.add((Q.Defined, SKOS.definition, Literal("Defined.")))
    g.add((Q.Described, RDF.type, OWL.Class))
    g.add((Q.Described, DCTERMS.description, Literal("Described.")))
    g.add((Q.IaoDefined, RDF.type, OWL.Class))
    g.add((Q.IaoDefined, IAO_DEFINITION, Literal("Defined the OBO way.")))
    g.add((Q.XlLabelled, RDF.type, OWL.Class))
    _xl(om, Q.XlLabelled, "XL", "en")
    # An anonymous class: neither labelled nor flagged.
    members = BNode()
    Collection(g, members, [Q.Labelled, Q.Unlabelled])
    union = BNode()
    g.add((union, RDF.type, OWL.Class))
    g.add((union, OWL.unionOf, members))
    g.add((Q.op, RDF.type, OWL.ObjectProperty))
    g.add((Q.dp, RDF.type, OWL.DatatypeProperty))
    g.add((Q.dp, RDFS.label, Literal("dp")))

    def concept(name, *labels):
        g.add((Q[name], RDF.type, SKOS.Concept))
        for text, lang in labels:
            g.add((Q[name], SKOS.prefLabel, Literal(text, lang=lang)))

    concept("c_ok", ("One", "en"), ("Eins", "de"))
    concept("c_two_en", ("One", "en"), ("Two", "en"), ("Eins", "de"))
    concept("c_two_untagged", ("One", None), ("Two", None))
    concept("c_none")
    concept("c_xl_only")
    _xl(om, Q.c_xl_only, "XL only", "en")
    concept("c_plain_and_xl_same", ("Same", "en"))
    _xl(om, Q.c_plain_and_xl_same, "Same", "en")
    concept("c_plain_and_xl_differ", ("Plain", "en"))
    _xl(om, Q.c_plain_and_xl_differ, "Other", "en")
    return om


def _by_rule(om):
    run = analyze(om, ALL_IN_SCOPE)
    return {rule: {f.resource for f in run.by_rule(rule)} for rule in POLICY}


def _by_shape(om):
    data, _ = shacl.split_shapes(om.graph)
    run = shacl.run_shacl(data, shacl.load_bundled("policy"), origin="shacl:bundled")
    assert run.error is None, run.error
    return {
        rule: {f.resource for f in run.findings if f.source_shape == label}
        for rule, label in POLICY.items()
    }


def test_policy_shapes_agree_with_the_rules_on_every_case():
    om = _fixture()
    rules, shapes = _by_rule(om), _by_shape(om)
    assert rules == shapes
    # And the fixture really exercises them.
    assert rules["Q001"] >= {str(Q.Unlabelled), str(Q.BlankLabel), str(Q.op)}
    assert str(Q.XlLabelled) not in rules["Q001"]
    assert str(Q.BlankComment) in rules["Q002"]
    assert rules["Q010"] == {
        str(Q.c_two_en),
        str(Q.c_two_untagged),
        str(Q.c_plain_and_xl_differ),
    }


SAMPLES = {
    "pizza.owl": "xml",
    "wine.owl": "xml",
    "foaf.rdf": "xml",
    "gist/gistCore14.1.0.ttl": "turtle",
    "geography-thesaurus.ttl": "turtle",
    "skos-showcase.ttl": "turtle",
}


@pytest.mark.parametrize("sample", SAMPLES)
def test_policy_shapes_agree_with_the_rules_on_the_samples(sample):
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/{sample}", format=SAMPLES[sample])
    assert _by_rule(om) == _by_shape(om)


@pytest.mark.parametrize("key", ["skos", "skos-practice"])
def test_skos_sets_run_on_the_skos_samples(key):
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/skos-showcase.ttl")
    data, _ = shacl.split_shapes(om.graph)
    run = shacl.run_shacl(data, shacl.load_bundled(key), origin="shacl:bundled")
    assert run.error is None and run.conforms is not None


# -- page --------------------------------------------------------------------------


def _page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager, UndoManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("Labelled", label="Labelled")
        om.add_class("Unlabelled")
        st.session_state.ontology = om
        st.session_state.undo_manager = UndoManager(om)
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
    st.session_state["val_active_tab"] = "SHACL"
    app.render_validation()


def test_page_checks_against_a_built_in_set():
    at = AppTest.from_function(_page)
    at.run(timeout=120)
    next(c for c in at.checkbox if c.label == "OrionBelt quality policy").check().run()
    next(b for b in at.button if b.label == "Run SHACL check").click().run()
    assert not at.exception, at.exception
    assert any("(built-in)" in md.value for md in at.markdown)
    messages = [
        m
        for frame in at.dataframe
        if "Message" in frame.value.columns
        for m in frame.value["Message"]
    ]
    assert any("Unlabelled" in m and "no preferred label" in m for m in messages)


def test_page_copies_a_built_in_set_into_the_ontology():
    at = AppTest.from_function(_page)
    at.run(timeout=120)
    before = len(at.session_state["ontology"].graph)
    copy = next(b for b in at.button if b.label == "Copy in")
    copy.click().run()
    assert len(at.session_state["ontology"].graph) > before
    assert shacl.list_shapes(at.session_state["ontology"].graph)
    assert at.session_state["undo_manager"].can_undo()
    next(b for b in at.button if b.label == "Copy in").click().run()
    assert "already in the ontology" in at.session_state["flash_message"]["message"]


# -- review fixes (PR #508) ------------------------------------------------------------


def test_copying_skos_shapes_keeps_the_ontologys_identity():
    """#1: skohub declares skos: an owl:Ontology; copied in, it took over the
    ontology's namespace after an export and a reload."""
    om = OntologyManager(base_uri=str(Q))
    om.add_class("Mine", label="Mine")
    shacl.add_shapes(om.graph, shacl.load_bundled("skos"))
    assert (None, RDF.type, OWL.Ontology) in om.graph
    ontologies = set(om.graph.subjects(RDF.type, OWL.Ontology))
    assert URIRef("http://www.w3.org/2004/02/skos/core#") not in ontologies
    again = OntologyManager()
    again.load_from_string(om.export_to_string(format="xml"), format="xml")
    assert again.base_uri == str(Q)
    # The prefix declarations its SPARQL constraints need did come along.
    data, shapes = shacl.split_shapes(om.graph)
    assert shacl.run_shacl(data, shapes, origin="shacl:ontology").error is None


def test_q010_reports_each_language_from_the_shapes_too():
    """#2: two over-full languages are two findings, from the shape as from the rule."""
    om = OntologyManager(base_uri=str(Q))
    om.graph.add((Q.c, RDF.type, SKOS.Concept))
    for text, lang in (("One", "en"), ("Two", "en"), ("Eins", "de"), ("Zwei", "de")):
        om.graph.add((Q.c, SKOS.prefLabel, Literal(text, lang=lang)))
    data, _ = shacl.split_shapes(om.graph)
    run = shacl.run_shacl(data, shacl.load_bundled("policy"), origin="shacl:bundled")
    q010 = [f for f in run.findings if f.source_shape == POLICY["Q010"]]
    assert len(q010) == 2


def test_q010_counts_literal_labels_on_named_concepts_only():
    """#3: URI-valued labels and blank-node concepts are outside the rule."""
    om = OntologyManager(base_uri=str(Q))
    om.graph.add((Q.c_uri_labels, RDF.type, SKOS.Concept))
    om.graph.add((Q.c_uri_labels, SKOS.prefLabel, Q.a))
    om.graph.add((Q.c_uri_labels, SKOS.prefLabel, Q.b))
    anon = BNode()
    om.graph.add((anon, RDF.type, SKOS.Concept))
    om.graph.add((anon, SKOS.prefLabel, Literal("One", lang="en")))
    om.graph.add((anon, SKOS.prefLabel, Literal("Two", lang="en")))
    assert _by_rule(om)["Q010"] == _by_shape(om)["Q010"] == set()


def test_page_marks_results_stale_when_the_shape_selection_changes():
    """#4."""
    at = AppTest.from_function(_page)
    at.run(timeout=120)
    policy = next(c for c in at.checkbox if c.label == "OrionBelt quality policy")
    policy.check().run()
    next(b for b in at.button if b.label == "Run SHACL check").click().run()
    assert not at.warning
    next(c for c in at.checkbox if c.label == "SKOS integrity").check().run()
    assert any("selection changed" in w.value for w in at.warning)

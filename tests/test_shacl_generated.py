"""Shapes generated from the model (issue #498): each axiom type, both ways."""

import pytest
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import shacl
from orionbelt_ontology_builder.shacl_generate import generate_shapes

Q = Namespace("http://test.org/q#")


def _om():
    return OntologyManager(base_uri=str(Q))


def _restriction(om, cls, prop, pred, value, **extra):
    """``cls ⊑ [prop pred value]``, with ``extra`` (onClass, onDataRange)."""
    r = BNode()
    om.graph.add((r, RDF.type, OWL.Restriction))
    om.graph.add((r, OWL.onProperty, prop))
    om.graph.add((r, pred, value))
    for key, node in extra.items():
        om.graph.add((r, OWL[key], node))
    om.graph.add((cls, RDFS.subClassOf, r))
    return r


def _thing(om, local, *types, **values):
    subject = Q[local]
    om.graph.add((subject, RDF.type, OWL.NamedIndividual))
    for t in types:
        om.graph.add((subject, RDF.type, t))
    for prop, objs in values.items():
        for obj in objs if isinstance(objs, list) else [objs]:
            om.graph.add((subject, Q[prop], obj))
    return subject


def _violations(om):
    data, _ = shacl.split_shapes(om.graph)
    run = shacl.run_shacl(data, generate_shapes(data), origin="shacl:generated")
    assert run.error is None, run.error
    return {f.resource.rsplit("#")[-1] for f in run.findings}, run


def _declare(om, *classes):
    for cls in classes:
        om.graph.add((Q[cls], RDF.type, OWL.Class))


def test_min_cardinality():
    om = _om()
    _declare(om, "Person")
    _restriction(
        om,
        Q.Person,
        Q.name,
        OWL.minCardinality,
        Literal(1, datatype=XSD.nonNegativeInteger),
    )
    _thing(om, "alice", Q.Person)
    _thing(om, "bob", Q.Person, name=Literal("Bob"))
    flagged, run = _violations(om)
    assert flagged == {"alice"}
    assert "at least 1" in run.findings[0].message
    assert "Person ⊑" in run.findings[0].suggestion  # names the axiom


def test_max_and_exact_cardinality():
    om = _om()
    _declare(om, "Person")
    _restriction(om, Q.Person, Q.name, OWL.cardinality, Literal(1))
    _thing(om, "alice", Q.Person)
    _thing(om, "bob", Q.Person, name=Literal("Bob"))
    _thing(om, "carol", Q.Person, name=[Literal("Carol"), Literal("Caro")])
    assert _violations(om)[0] == {"alice", "carol"}


def test_qualified_cardinality():
    om = _om()
    _declare(om, "Car", "Wheel")
    _restriction(
        om, Q.Car, Q.hasPart, OWL.minQualifiedCardinality, Literal(2), onClass=Q.Wheel
    )
    w1, w2 = _thing(om, "w1", Q.Wheel), _thing(om, "w2", Q.Wheel)
    seat = _thing(om, "seat")
    _thing(om, "good", Q.Car, hasPart=[w1, w2])
    _thing(om, "one_wheel", Q.Car, hasPart=[w1, seat])
    assert _violations(om)[0] == {"one_wheel"}


def test_some_values_from():
    om = _om()
    _declare(om, "Pizza", "Topping")
    _restriction(om, Q.Pizza, Q.hasTopping, OWL.someValuesFrom, Q.Topping)
    cheese = _thing(om, "cheese", Q.Topping)
    mystery = _thing(om, "mystery")
    _thing(om, "margherita", Q.Pizza, hasTopping=cheese)
    _thing(om, "plain", Q.Pizza)
    _thing(om, "odd", Q.Pizza, hasTopping=mystery)
    assert _violations(om)[0] == {"plain", "odd"}


def test_all_values_from_class_and_datatype():
    om = _om()
    _declare(om, "Veggie", "VegTopping", "Meat")
    _restriction(om, Q.Veggie, Q.hasTopping, OWL.allValuesFrom, Q.VegTopping)
    _restriction(om, Q.Veggie, Q.calories, OWL.allValuesFrom, XSD.integer)
    tomato = _thing(om, "tomato", Q.VegTopping)
    ham = _thing(om, "ham", Q.Meat)
    _thing(om, "good", Q.Veggie, hasTopping=tomato, calories=Literal(800))
    _thing(om, "hammy", Q.Veggie, hasTopping=ham)
    _thing(om, "wordy", Q.Veggie, calories=Literal("lots"))
    assert _violations(om)[0] == {"hammy", "wordy"}


def test_has_value():
    om = _om()
    _declare(om, "ItalianWine")
    _restriction(om, Q.ItalianWine, Q.origin, OWL.hasValue, Q.Italy)
    _thing(om, "chianti", Q.ItalianWine, origin=Q.Italy)
    _thing(om, "unknown", Q.ItalianWine)
    assert _violations(om)[0] == {"unknown"}


def test_functional_property():
    om = _om()
    om.graph.add((Q.mother, RDF.type, OWL.ObjectProperty))
    om.graph.add((Q.mother, RDF.type, OWL.FunctionalProperty))
    _thing(om, "ann", mother=Q.m1)
    _thing(om, "ben", mother=[Q.m1, Q.m2])
    assert _violations(om)[0] == {"ben"}


def test_ranges_class_and_datatype():
    om = _om()
    _declare(om, "Company")
    om.graph.add((Q.worksFor, RDF.type, OWL.ObjectProperty))
    om.graph.add((Q.worksFor, RDFS.range, Q.Company))
    om.graph.add((Q.born, RDF.type, OWL.DatatypeProperty))
    om.graph.add((Q.born, RDFS.range, XSD.date))
    acme = _thing(om, "acme", Q.Company)
    _thing(om, "ann", worksFor=acme, born=Literal("1990-01-01", datatype=XSD.date))
    _thing(om, "ben", worksFor=Q.somewhere)
    _thing(om, "cy", born=Literal("yesterday"))
    assert _violations(om)[0] == {"ben", "cy"}


def test_restrictions_inside_an_equivalence_intersection():
    """gist's style: A ≡ B ⊓ ∃p.C makes ∃p.C necessary for A."""
    om = _om()
    _declare(om, "A", "B", "C")
    r = BNode()
    om.graph.add((r, RDF.type, OWL.Restriction))
    om.graph.add((r, OWL.onProperty, Q.p))
    om.graph.add((r, OWL.someValuesFrom, Q.C))
    members = BNode()
    Collection(om.graph, members, [Q.B, r])
    expr = BNode()
    om.graph.add((expr, OWL.intersectionOf, members))
    om.graph.add((Q.A, OWL.equivalentClass, expr))
    c = _thing(om, "c", Q.C)
    _thing(om, "good", Q.A, p=c)
    _thing(om, "bad", Q.A)
    assert _violations(om)[0] == {"bad"}


def test_an_inverse_property_becomes_an_inverse_path():
    om = _om()
    _declare(om, "Child", "Parent")
    inverse = BNode()
    om.graph.add((inverse, OWL.inverseOf, Q.hasChild))
    _restriction(om, Q.Child, inverse, OWL.someValuesFrom, Q.Parent)
    kid = _thing(om, "kid", Q.Child)
    _thing(om, "orphan", Q.Child)
    _thing(om, "mum", Q.Parent, hasChild=kid)
    assert _violations(om)[0] == {"orphan"}


def test_what_cannot_be_expressed_faithfully_is_left_out():
    """A union filler, owl:Thing and a malformed count produce no constraint."""
    om = _om()
    _declare(om, "X", "Y", "Z")
    members = BNode()
    Collection(om.graph, members, [Q.Y, Q.Z])
    union = BNode()
    om.graph.add((union, OWL.unionOf, members))
    _restriction(om, Q.X, Q.p, OWL.someValuesFrom, union)
    _restriction(om, Q.X, Q.q, OWL.allValuesFrom, OWL.Thing)
    _restriction(om, Q.X, Q.r, OWL.minCardinality, Literal("many"))
    _thing(om, "x", Q.X)
    shapes = generate_shapes(om.graph)
    assert not list(shapes.subjects(shacl.SH.property, None))
    assert _violations(om)[0] == set()


SAMPLES = {
    "pizza.owl": "xml",
    "wine.owl": "xml",
    "foaf.rdf": "xml",
    "goodrelations.owl": "xml",
    "prov-o.ttl": "turtle",
    "gufo/gufo.ttl": "turtle",
    "gist/gistCore14.1.0.ttl": "turtle",
}


@pytest.mark.parametrize("sample", SAMPLES)
def test_generated_shapes_are_valid_shacl_for_every_sample(sample):
    import sources

    om = OntologyManager()
    om.load_from_file(f"{sources.PKG}/samples/{sample}", format=SAMPLES[sample])
    generated = generate_shapes(shacl.split_shapes(om.graph)[0])
    shacl.parse_shapes(generated.serialize(format="turtle"))
    data, _ = shacl.split_shapes(om.graph)
    assert shacl.run_shacl(data, generated, origin="shacl:generated").error is None


def test_generation_does_not_touch_the_model():
    om = _om()
    _declare(om, "Person")
    _restriction(om, Q.Person, Q.name, OWL.minCardinality, Literal(1))
    before = set(om.graph)
    generate_shapes(om.graph)
    assert set(om.graph) == before
    assert isinstance(generate_shapes(Graph()), Graph)


# -- page ------------------------------------------------------------------------------


def _page():
    import streamlit as st
    from rdflib import BNode, Literal
    from rdflib.namespace import OWL, RDF, RDFS

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("Person", label="Person")
        om.add_data_property("name", domain="Person")
        r = BNode()
        om.graph.add((r, RDF.type, OWL.Restriction))
        om.graph.add((r, OWL.onProperty, om.namespace["name"]))
        om.graph.add((r, OWL.minCardinality, Literal(1)))
        om.graph.add((om.namespace["Person"], RDFS.subClassOf, r))
        om.add_individual("alice", "Person")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
    st.session_state["val_active_tab"] = "SHACL"
    app.render_validation()


def test_page_checks_individuals_against_the_model_without_storing_shapes():
    at = AppTest.from_function(_page)
    at.run(timeout=120)
    before = len(at.session_state["ontology"].graph)
    next(c for c in at.checkbox if c.label == "Generated from the model").check().run()
    next(b for b in at.button if b.label == "Run SHACL check").click().run()
    assert not at.exception, at.exception
    assert any("Generated from the model" in md.value for md in at.markdown)
    messages = [
        m
        for frame in at.dataframe
        if "Message" in frame.value.columns
        for m in frame.value["Message"]
    ]
    assert any("alice" in m and "at least 1" in m for m in messages)
    assert len(at.session_state["ontology"].graph) == before


def test_page_shows_the_generated_shapes():
    at = AppTest.from_function(_page)
    at.run(timeout=120)
    next(t for t in at.toggle if t.label == "Show the generated shapes").set_value(
        True
    ).run()
    assert any("sh:minCount" in c.value for c in at.code)

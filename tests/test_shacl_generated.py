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


# -- review fixes (PR #509) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "value", "ok"),
    [
        (XSD.integer, Literal("3", datatype=XSD.int), True),
        (XSD.integer, Literal("3", datatype=XSD.nonNegativeInteger), True),
        (XSD.decimal, Literal("3", datatype=XSD.byte), True),
        (XSD.integer, Literal("3.5", datatype=XSD.decimal), False),
        (XSD.string, Literal("x", datatype=XSD.token), True),
        (OWL.real, Literal("2.5", datatype=XSD.decimal), True),
        (OWL.real, Literal("2", datatype=XSD.integer), True),
        (OWL.rational, Literal("2", datatype=XSD.long), True),
        (OWL.real, Literal("x"), False),
        (RDFS.Literal, Literal("anything", lang="en"), True),
    ],
)
def test_datatypes_accept_their_whole_value_space(declared, value, ok):
    """#1, #5: a range, allValuesFrom, someValuesFrom and a qualified count all
    accept values of a derived datatype."""
    om = _om()
    _declare(om, "Thing")
    om.graph.add((Q.v, RDF.type, OWL.DatatypeProperty))
    om.graph.add((Q.v, RDFS.range, declared))
    _restriction(om, Q.Thing, Q.v, OWL.allValuesFrom, declared)
    _restriction(om, Q.Thing, Q.v, OWL.someValuesFrom, declared)
    _restriction(
        om, Q.Thing, Q.v, OWL.minQualifiedCardinality, Literal(1), onDataRange=declared
    )
    _thing(om, "t", Q.Thing, v=value)
    assert (_violations(om)[0] == set()) is ok


def test_a_custom_datatype_is_left_out_rather_than_misread():
    om = _om()
    om.graph.add((Q.Celsius, RDF.type, RDFS.Datatype))
    om.graph.add((Q.temp, RDFS.range, Q.Celsius))
    _thing(om, "today", temp=Literal("21", datatype=XSD.decimal))
    assert _violations(om)[0] == set()


def test_a_range_on_an_untyped_property_is_checked():
    """#2: FOAF declares ranges on properties it types only as rdf:Property."""
    om = _om()
    _declare(om, "Document")
    om.graph.add((Q.topicOf, RDFS.range, Q.Document))
    _thing(om, "page", topicOf=Literal("not a document"))
    assert _violations(om)[0] == {"page"}


def _intersection(om, *members):
    head = BNode()
    Collection(om.graph, head, list(members))
    node = BNode()
    om.graph.add((node, OWL.intersectionOf, head))
    return node


def _some(om, prop, cls):
    r = BNode()
    om.graph.add((r, RDF.type, OWL.Restriction))
    om.graph.add((r, OWL.onProperty, prop))
    om.graph.add((r, OWL.someValuesFrom, cls))
    return r


@pytest.mark.parametrize("style", ["subclass", "own", "nested", "reversed"])
def test_necessary_restrictions_in_every_intersection_style(style):
    """#3, #4: A ⊑ (B ⊓ ∃p.C), A owl:intersectionOf (…), nested intersections,
    and R owl:equivalentClass A all make ∃p.C necessary for A."""
    om = _om()
    _declare(om, "A", "B", "C")
    some = _some(om, Q.p, Q.C)
    if style == "subclass":
        om.graph.add((Q.A, RDFS.subClassOf, _intersection(om, Q.B, some)))
    elif style == "own":
        head = BNode()
        Collection(om.graph, head, [Q.B, some])
        om.graph.add((Q.A, OWL.intersectionOf, head))
    elif style == "nested":
        inner = _intersection(om, Q.B, some)
        om.graph.add((Q.A, OWL.equivalentClass, _intersection(om, Q.B, inner)))
    else:
        om.graph.add((some, OWL.equivalentClass, Q.A))
    c = _thing(om, "c", Q.C)
    _thing(om, "good", Q.A, p=c)
    _thing(om, "bad", Q.A)
    assert _violations(om)[0] == {"bad"}


# -- review fixes, second round (PR #509) ----------------------------------------------


def _range_check(declared, value):
    om = _om()
    om.graph.add((Q.v, RDFS.range, declared))
    _thing(om, "t", v=value)
    return _violations(om)[0] == set()


@pytest.mark.parametrize(
    ("declared", "value", "ok"),
    [
        (XSD.integer, Literal("3.0", datatype=XSD.decimal), True),
        (XSD.integer, Literal("3.5", datatype=XSD.decimal), False),
        (XSD.nonNegativeInteger, Literal("3", datatype=XSD.int), True),
        (XSD.nonNegativeInteger, Literal("-3", datatype=XSD.int), False),
        (XSD.positiveInteger, Literal("0", datatype=XSD.integer), False),
        (XSD.byte, Literal("127", datatype=XSD.integer), True),
        (XSD.byte, Literal("128", datatype=XSD.integer), False),
        (XSD.unsignedShort, Literal("65535", datatype=XSD.long), True),
        (XSD.decimal, Literal("2.5", datatype=XSD.decimal), True),
        (XSD.decimal, Literal("2.5", datatype=XSD.double), False),
    ],
)
def test_numeric_values_are_checked_by_value_not_datatype(declared, value, ok):
    """#1: value-space membership, across numeric datatypes."""
    assert _range_check(declared, value) is ok


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (Literal("1/3", datatype=OWL.rational), True),
        (Literal("-2/4", datatype=OWL.rational), True),
        (Literal("1/0", datatype=OWL.rational), False),
        (Literal("one third", datatype=OWL.rational), False),
        (Literal("not a real", datatype=OWL.real), False),
        (Literal("2.5", datatype=XSD.decimal), True),
    ],
)
def test_owl_numeric_literals_are_validated(value, ok):
    """#3: owl:rational has a syntax to check; owl:real has no literals of its own."""
    assert _range_check(OWL.real, value) is ok


def test_a_named_restriction_is_still_a_restriction():
    """#2: Person ⊑ ex:NameRequired, where ex:NameRequired is a restriction."""
    om = _om()
    _declare(om, "Person")
    om.graph.add((Q.NameRequired, RDF.type, OWL.Restriction))
    om.graph.add((Q.NameRequired, OWL.onProperty, Q.name))
    om.graph.add((Q.NameRequired, OWL.minCardinality, Literal(1)))
    om.graph.add((Q.Person, RDFS.subClassOf, Q.NameRequired))
    _thing(om, "alice", Q.Person)
    _thing(om, "bob", Q.Person, name=Literal("Bob"))
    assert _violations(om)[0] == {"alice"}


def test_rdfs_resource_is_no_constraint():
    """#4: everything is an rdfs:Resource, literals included."""
    assert _range_check(RDFS.Resource, Literal("plain"))

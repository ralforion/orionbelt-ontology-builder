"""General SHACL: shapes in the ontology, shapes added to it, checks against them."""

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from streamlit.testing.v1 import AppTest

from ontology_manager import OntologyManager, UndoManager
from orionbelt_ontology_builder import shacl
from orionbelt_ontology_builder.shacl import SH, ShapesError

Q = Namespace("http://test.org/q#")

PERSON_SHAPE = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix q: <http://test.org/q#> .
q:PersonShape a sh:NodeShape ;
    sh:targetClass q:Person ;
    sh:property [
        sh:path q:name ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:message "A person needs exactly one name." ;
        sh:description "Every person is known by one name."
    ] .
"""


def _people():
    om = OntologyManager(base_uri=str(Q))
    om.add_class("Person", label="Person")
    om.add_data_property("name", domain="Person")
    om.add_individual("alice", "Person")
    om.add_individual("bob", "Person")
    om.graph.add((Q.bob, Q.name, Literal("Bob")))
    return om


def _check(om, origin="shacl:ontology", **kwargs):
    data, shapes = shacl.split_shapes(om.graph)
    return shacl.run_shacl(data, shapes, origin=origin, **kwargs)


# -- parsing and vetting -----------------------------------------------------------


class TestParseShapes:
    def test_valid_shapes(self):
        shapes = shacl.parse_shapes(PERSON_SHAPE)
        [info] = shacl.list_shapes(shapes)
        assert info.name.endswith("PersonShape")
        assert info.targets == ("targetClass q:Person",)
        assert info.constraints >= 3

    def test_unparsable_text(self):
        with pytest.raises(ShapesError, match="do not parse"):
            shacl.parse_shapes("this is not turtle")

    def test_no_shapes(self):
        with pytest.raises(ShapesError, match="No shapes found"):
            shacl.parse_shapes("<http://x/a> <http://x/b> <http://x/c> .")

    def test_invalid_shacl_is_refused_with_the_report(self):
        bad = (
            "@prefix sh: <http://www.w3.org/ns/shacl#> . "
            '<http://x/S> a sh:NodeShape ; sh:targetNode <http://x/a> ; sh:minCount "many" .'
        )
        with pytest.raises(ShapesError, match="not valid SHACL") as exc:
            shacl.parse_shapes(bad)
        assert "minCount" in str(exc.value)

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT $this WHERE { SERVICE <http://evil.example/sparql> { ?s ?p ?o } }",
            "SELECT $this WHERE { service silent ?endpoint { ?s ?p ?o } }",
        ],
    )
    def test_federated_sparql_is_refused(self, query):
        text = (
            "@prefix sh: <http://www.w3.org/ns/shacl#> . "
            "<http://x/S> a sh:NodeShape ; sh:targetNode <http://x/a> ; "
            f'sh:sparql [ sh:select "{query}" ] .'
        )
        with pytest.raises(ShapesError, match="SERVICE"):
            shacl.parse_shapes(text)

    def test_vetting_does_not_change_the_shapes(self):
        """The meta-shapes check mixes RDFS triples into the graph it gets;
        none of them may end up in what is added to the ontology."""
        parsed = Graph().parse(data=PERSON_SHAPE, format="turtle")
        assert len(shacl.parse_shapes(PERSON_SHAPE)) == len(parsed)


# -- storing shapes in the ontology --------------------------------------------------


class TestStoredShapes:
    def test_add_then_remove_restores_the_graph(self):
        om = _people()
        before = set(om.graph)
        added = shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        assert added == len(Graph().parse(data=PERSON_SHAPE, format="turtle"))
        [info] = shacl.list_shapes(om.graph)
        assert shacl.remove_shape(om.graph, info.node) == added
        assert set(om.graph) == before

    def test_adding_is_one_undo_step(self):
        om = _people()
        undo = UndoManager(om)
        before = len(om.graph)
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        undo.checkpoint("Add SHACL shapes")
        undo.undo()
        assert len(om.graph) == before
        undo.redo()
        assert shacl.list_shapes(om.graph)

    def test_shapes_survive_save_and_load(self):
        om = _people()
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        again = OntologyManager()
        again.load_from_string(om.export_to_string())
        [info] = shacl.list_shapes(again.graph)
        assert info.node == Q.PersonShape

    def test_removing_keeps_structure_another_shape_shares(self):
        om = _people()
        text = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix q: <http://test.org/q#> .
        q:A a sh:NodeShape ; sh:targetClass q:Person ; sh:property q:NameRule .
        q:B a sh:NodeShape ; sh:targetNode q:alice ; sh:property q:NameRule .
        q:NameRule a sh:PropertyShape ; sh:path q:name ; sh:in ( "Alice" "Bob" ) .
        """
        shacl.add_shapes(om.graph, shacl.parse_shapes(text))
        shacl.remove_shape(om.graph, Q.A)
        names = {s.name for s in shacl.list_shapes(om.graph)}
        assert ":A" not in names and ":B" in names
        # NameRule's sh:in list is intact for B.
        assert (Q.NameRule, SH["in"], None) in om.graph

    def test_a_class_that_is_also_a_shape_stays_a_class(self):
        om = _people()
        om.graph.add((Q.Person, RDF.type, SH.NodeShape))
        om.graph.add((Q.Person, SH.closed, Literal(False)))
        data, shapes = shacl.split_shapes(om.graph)
        assert (Q.Person, RDF.type, OWL.Class) in data
        assert (Q.Person, RDFS.label, Literal("Person")) in data
        assert (Q.Person, RDF.type, OWL.Class) in shapes  # its implicit target
        assert (Q.Person, RDF.type, SH.NodeShape) not in data
        shacl.remove_shape(om.graph, Q.Person)
        assert (Q.Person, RDF.type, OWL.Class) in om.graph
        assert (Q.Person, RDF.type, SH.NodeShape) not in om.graph


# -- running checks ------------------------------------------------------------------


class TestRun:
    def test_violation_names_the_focus_node_and_shape(self):
        om = _people()
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        run = _check(om, name=lambda uri: uri.rsplit("#")[-1])
        assert run.conforms is False and run.error is None
        [finding] = run.findings
        assert finding.resource == str(Q.alice)
        assert finding.severity == "error"
        assert finding.rule_id == "Q015"
        assert finding.origin == "shacl:ontology"
        assert "exactly one name" in finding.message
        # In the ontology's own prefix, not a second one the shapes declared.
        assert finding.source_shape == ":PersonShape › :name"
        assert finding.suggestion == "Every person is known by one name."
        assert finding.evidence["path"] == ":name"

    @pytest.mark.parametrize(
        ("severity", "expected"), [("sh:Warning", "warning"), ("sh:Info", "info")]
    )
    def test_severity_mapping(self, severity, expected):
        om = _people()
        shapes = shacl.parse_shapes(
            PERSON_SHAPE.replace(
                "sh:minCount 1 ;", f"sh:minCount 1 ; sh:severity {severity} ;"
            )
        )
        shacl.add_shapes(om.graph, shapes)
        assert [f.severity for f in _check(om).findings] == [expected]

    def test_conforming_data(self):
        om = _people()
        om.graph.add((Q.alice, Q.name, Literal("Alice")))
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        run = _check(om)
        assert run.conforms is True and run.findings == []

    def test_shapes_are_not_checked_as_data(self):
        """A shape targeting every node shape would flag the shapes
        themselves if they were part of the data."""
        om = _people()
        text = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <http://x/LabelledShapes> a sh:NodeShape ; sh:targetClass sh:NodeShape ;
            sh:property [ sh:path rdfs:label ; sh:minCount 1 ] .
        """
        shacl.add_shapes(om.graph, shacl.parse_shapes(text))
        assert _check(om).conforms is True

    def test_the_deadline_stops_a_run(self):
        om = _people()
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        run = _check(om, deadline_s=0.0)
        assert run.conforms is None
        assert "did not finish" in run.error

    def test_no_shapes_conforms_trivially(self):
        run = _check(_people())
        assert run.conforms is True and run.shapes_checked == 0

    def test_the_user_graph_is_not_touched(self):
        om = _people()
        shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
        before = set(om.graph)
        _check(om)
        assert set(om.graph) == before


# -- export ----------------------------------------------------------------------------


def test_export_ontology_shapes_or_both():
    om = _people()
    shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))
    every = Graph().parse(data=om.export_to_string(), format="turtle")
    ontology = Graph().parse(
        data=om.export_to_string(content="ontology"), format="turtle"
    )
    shapes = Graph().parse(data=om.export_to_string(content="shapes"), format="turtle")
    assert shacl.shape_nodes(every) and shacl.shape_nodes(shapes)
    assert not shacl.shape_nodes(ontology)
    assert (Q.alice, RDF.type, Q.Person) in ontology
    assert (Q.alice, RDF.type, Q.Person) not in shapes
    with pytest.raises(ValueError):
        om.export_to_string(content="nonsense")


# -- page --------------------------------------------------------------------------------


def _shacl_page():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager, UndoManager

    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/q#")
        om.add_class("Person", label="Person")
        om.add_data_property("name", domain="Person")
        om.add_individual("alice", "Person")
        st.session_state.ontology = om
        st.session_state.undo_manager = UndoManager(om)
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
    st.session_state["val_active_tab"] = "SHACL"
    app.render_validation()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_page_adds_shapes_checks_and_opens_a_finding():
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    assert not at.exception, at.exception
    assert _button(at, "Run SHACL check").disabled
    _button(at, "Check shapes").click().run()
    assert any("Paste or upload" in w.value for w in at.warning)

    at.text_area[0].set_value(PERSON_SHAPE).run()
    _button(at, "Check shapes").click().run()
    assert any("Valid SHACL" in s.value for s in at.success)
    _button(at, "Add to ontology").click().run()
    assert not at.exception, at.exception
    assert shacl.list_shapes(at.session_state["ontology"].graph)
    assert at.session_state["undo_manager"].can_undo()

    _button(at, "Run SHACL check").click().run()
    assert not at.exception, at.exception
    assert any("exactly one name" in md.value for md in at.markdown)
    _button(at, "Open").click().run()
    assert at.session_state["search_navigate_to"] == "Individuals"


def test_page_shows_why_shapes_were_refused():
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    at.text_area[0].set_value("not turtle at all").run()
    _button(at, "Check shapes").click().run()
    assert any("do not parse" in e.value for e in at.error)
    assert not [b for b in at.button if b.label == "Add to ontology"]


def test_one_off_shapes_are_checked_but_not_saved():
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    before = len(at.session_state["ontology"].graph)
    at.text_area[0].set_value(PERSON_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Use for one check").click().run()
    _button(at, "Run SHACL check").click().run()
    assert any("exactly one name" in md.value for md in at.markdown)
    assert len(at.session_state["ontology"].graph) == before


def test_page_marks_a_check_stale_after_an_edit():
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    at.text_area[0].set_value(PERSON_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Add to ontology").click().run()
    _button(at, "Run SHACL check").click().run()
    at.session_state["ontology"].graph.add((Q.alice, Q.name, Literal("Alice")))
    at.run()
    assert any("changed since this check" in w.value for w in at.warning)


def test_unknown_uri_reference_is_fine():
    """A focus node with no page (a blank node) has no Open button."""
    om = _people()
    text = """
    @prefix sh: <http://www.w3.org/ns/shacl#> .
    <http://x/S> a sh:NodeShape ; sh:targetSubjectsOf <http://test.org/q#name> ;
        sh:property [ sh:path <http://test.org/q#name> ; sh:maxLength 1 ] .
    """
    shacl.add_shapes(om.graph, shacl.parse_shapes(text))
    run = _check(om)
    assert run.findings and all(isinstance(f.resource, str) for f in run.findings)
    assert URIRef(run.findings[0].resource) == Q.bob


def test_adding_shapes_does_not_give_a_namespace_a_second_prefix():
    om = _people()  # binds the base namespace as ":"
    shacl.add_shapes(om.graph, shacl.parse_shapes(PERSON_SHAPE))  # declares q:
    prefixes = [p for p, n in om.graph.namespaces() if str(n) == str(Q)]
    assert len(prefixes) == 1

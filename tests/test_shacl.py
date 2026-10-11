"""General SHACL: shapes in the ontology, shapes added to it, checks against them."""

import time

import pytest
from rdflib import BNode, Graph, Literal, Namespace, URIRef
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
    assert any("exactly one name" in m for m in table_messages(at))
    select_first_finding(at, "shacl_")
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
    assert any("exactly one name" in m for m in table_messages(at))
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


# -- review fixes (PR #506) ------------------------------------------------------------

PREFIXES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix q: <http://test.org/q#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def _with_shapes(om, text):
    shacl.add_shapes(om.graph, shacl.parse_shapes(PREFIXES + text))


def test_a_blank_node_target_stays_data_and_survives_removal():
    """#1: sh:targetNode names data; neither split nor remove may take it."""
    om = _people()
    person = BNode()
    om.graph.add((person, RDF.type, Q.Person))
    om.graph.add((person, Q.name, Literal("Anon")))
    om.graph.add((Q.S, RDF.type, SH.NodeShape))
    om.graph.add((Q.S, SH.targetNode, person))
    data, shapes = shacl.split_shapes(om.graph)
    assert (person, Q.name, Literal("Anon")) in data
    assert (person, Q.name, Literal("Anon")) not in shapes
    shacl.remove_shape(om.graph, Q.S)
    assert (person, Q.name, Literal("Anon")) in om.graph


def test_the_deadline_stops_a_runaway_regex():
    """#2: the time is spent inside re, where no clock check can interrupt it;
    only stopping the worker can."""
    om = _people()
    om.graph.add((Q.alice, Q.name, Literal("a" * 30 + "!")))
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; "
        'sh:property [ sh:path q:name ; sh:pattern "^(a+)+$" ] .',
    )
    began = time.monotonic()
    run = _check(om, deadline_s=1.0)
    assert time.monotonic() - began < 5
    assert run.conforms is None and "did not finish" in run.error
    # The next check gets a fresh worker and works.
    om.graph.remove((Q.alice, Q.name, None))
    om.graph.add((Q.alice, Q.name, Literal("aaa")))
    assert _check(om).error is None


def test_a_named_helper_shape_is_a_shape():
    """#3: q:Helper behind sh:node is structure, not data."""
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; sh:node q:Helper .\n"
        "q:Helper sh:property [ sh:path q:name ; sh:minCount 1 ] .",
    )
    data, shapes = shacl.split_shapes(om.graph)
    assert (Q.Helper, SH.property, None) in shapes
    assert (Q.Helper, SH.property, None) not in data
    assert _check(om).conforms is False  # alice has no name
    assert [s.name for s in shacl.list_shapes(om.graph)] == [":S"]


def test_a_returned_validation_failure_is_reported_not_raised():
    """#4: pySHACL returns a ValidationFailure for some SPARQL constraints."""
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; sh:sparql [ "
        'sh:select "SELECT $this WHERE { $this ?p ?o MINUS { $this ?p ?o } }" ] .',
    )
    run = _check(om)
    assert run.findings == [] and (run.error is None or "could not run" in run.error)


def test_warnings_show_even_when_the_data_conforms():
    """#5 (engine side): a warning-only run conforms and still has findings."""
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; sh:property [ "
        "sh:path q:name ; sh:minCount 1 ; sh:severity sh:Warning ] .",
    )
    run = _check(om)
    assert run.conforms is True
    assert [f.severity for f in run.findings] == ["warning"]
    assert run.report_ttl


def test_two_shapes_on_one_path_are_two_findings():
    """#6: same focus, same path, same label, different shapes."""
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; "
        "sh:property [ sh:path q:boss ; sh:minCount 1 ; sh:message 'needs a boss' ] ; "
        "sh:property [ sh:path q:boss ; sh:class q:Manager ; sh:minCount 1 ; "
        "sh:message 'needs a boss' ] .",
    )
    findings = [f for f in _check(om).findings if f.resource == str(Q.alice)]
    assert len({f.evidence["shape_id"] for f in findings}) == len(findings) >= 2


def test_a_pure_shapes_label_belongs_to_the_shape():
    """#7: a labelled shape targeting subjects of rdfs:label must not check
    itself, and the shapes-only export keeps its label."""
    om = _people()
    _with_shapes(
        om,
        'q:S a sh:NodeShape ; rdfs:label "Labels are short" ; '
        "sh:targetSubjectsOf rdfs:label ; "
        "sh:property [ sh:path rdfs:label ; sh:maxLength 6 ] .",
    )
    data, shapes = shacl.split_shapes(om.graph)
    assert (Q.S, RDFS.label, None) in shapes and (Q.S, RDFS.label, None) not in data
    focus = {f.resource for f in _check(om).findings}
    assert str(Q.S) not in focus
    exported = Graph().parse(
        data=om.export_to_string(content="shapes"), format="turtle"
    )
    assert (Q.S, RDFS.label, Literal("Labels are short")) in exported


def test_removing_a_shape_takes_its_typed_children():
    """#8: an exclusively owned [a sh:PropertyShape] child goes with it."""
    om = _people()
    before = set(om.graph)
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; "
        "sh:property [ a sh:PropertyShape ; sh:path q:name ; sh:minCount 1 ] .",
    )
    assert len(shacl.list_shapes(om.graph)) == 1
    shacl.remove_shape(om.graph, Q.S)
    assert shacl.list_shapes(om.graph) == []
    assert {t for t in om.graph if t not in before} == set()


def test_a_helper_two_shapes_share_outlives_one_of_them():
    om = _people()
    _with_shapes(
        om,
        "q:A a sh:NodeShape ; sh:targetClass q:Person ; sh:node q:Helper .\n"
        "q:B a sh:NodeShape ; sh:targetNode q:alice ; sh:node q:Helper .\n"
        "q:Helper sh:property [ sh:path q:name ; sh:minCount 1 ] .",
    )
    shacl.remove_shape(om.graph, Q.A)
    assert (Q.Helper, SH.property, None) in om.graph
    shacl.remove_shape(om.graph, Q.B)
    assert (Q.Helper, SH.property, None) not in om.graph


WARNING_SHAPE = PERSON_SHAPE.replace(
    "sh:minCount 1 ;", "sh:minCount 1 ; sh:severity sh:Warning ;"
)


def test_page_lists_warnings_when_the_data_conforms():
    """#5 (page side)."""
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    at.text_area[0].set_value(WARNING_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Add to ontology").click().run()
    _button(at, "Run SHACL check").click().run()
    assert any("see the notes below" in s.value for s in at.success)
    assert any("exactly one name" in m for m in table_messages(at))


def test_page_marks_results_stale_when_one_off_shapes_change():
    """#9."""
    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    at.text_area[0].set_value(WARNING_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Use for one check").click().run()
    _button(at, "Run SHACL check").click().run()
    assert not at.warning
    at.text_area[0].set_value(PERSON_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Use for one check").click().run()
    assert any("one-off shapes changed" in w.value for w in at.warning)


# -- review fixes, second round (PR #506) --------------------------------------------


def test_a_blank_node_target_keeps_its_identity_in_the_worker():
    """Data and shapes share the blank node: it must be one node in the worker."""
    om = _people()
    person = BNode()
    om.graph.add((person, RDF.type, Q.Person))
    om.graph.add((person, Q.name, Literal("Anon")))
    om.graph.add((Q.S, RDF.type, SH.NodeShape))
    om.graph.add((Q.S, SH.targetNode, person))
    prop = BNode()
    om.graph.add((Q.S, SH.property, prop))
    om.graph.add((prop, SH.path, Q.name))
    om.graph.add((prop, SH.minCount, Literal(1)))
    assert _check(om).conforms is True


def test_a_blank_node_has_value_matches_in_the_worker():
    om = _people()
    thing = BNode()
    om.graph.add((Q.alice, Q.owns, thing))
    om.graph.add((Q.bob, Q.owns, thing))
    om.graph.add((Q.S, RDF.type, SH.NodeShape))
    om.graph.add((Q.S, SH.targetClass, Q.Person))
    prop = BNode()
    om.graph.add((Q.S, SH.property, prop))
    om.graph.add((prop, SH.path, Q.owns))
    om.graph.add((prop, SH.hasValue, thing))
    assert _check(om).conforms is True


def test_a_named_sparql_constraint_belongs_to_the_shape():
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; sh:sparql q:C .\n"
        'q:C a sh:SPARQLConstraint ; sh:message "no name" ; sh:select """'
        "SELECT $this WHERE { FILTER NOT EXISTS { $this <http://test.org/q#name> ?n } }"
        '""" .',
    )
    data, shapes = shacl.split_shapes(om.graph)
    assert (Q.C, SH.select, None) in shapes and (Q.C, SH.select, None) not in data
    run = _check(om)
    assert run.error is None
    assert [f.resource for f in run.findings] == [str(Q.alice)]
    exported = Graph().parse(
        data=om.export_to_string(content="shapes"), format="turtle"
    )
    assert (Q.C, SH.select, None) in exported


def test_a_targeted_shape_another_refers_to_stays_its_own_root():
    om = _people()
    _with_shapes(
        om,
        "q:A a sh:NodeShape ; sh:targetClass q:Person ; sh:node q:B .\n"
        "q:B a sh:NodeShape ; sh:targetNode q:bob ; "
        "sh:property [ sh:path q:name ; sh:minCount 1 ] .",
    )
    assert {s.name for s in shacl.list_shapes(om.graph)} == {":A", ":B"}
    shacl.remove_shape(om.graph, Q.A)
    assert (Q.B, SH.targetNode, Q.bob) in om.graph
    assert (Q.B, SH.property, None) in om.graph


def test_a_self_referencing_targeted_shape_is_listed_and_checked():
    om = _people()
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetClass q:Person ; "
        "sh:or ( q:S [ sh:property [ sh:path q:name ; sh:minCount 1 ] ] ) .",
    )
    assert [s.name for s in shacl.list_shapes(om.graph)] == [":S"]


def test_language_tagged_values_are_separate_findings():
    om = _people()
    om.graph.add((Q.bob, Q.nick, Literal("x", lang="en")))
    om.graph.add((Q.bob, Q.nick, Literal("x", lang="de")))
    _with_shapes(
        om,
        "q:S a sh:NodeShape ; sh:targetNode q:bob ; "
        "sh:property [ sh:path q:nick ; sh:minLength 2 ] .",
    )
    assert len(_check(om).findings) == 2


def test_removing_a_shape_another_still_uses_only_drops_its_targets():
    om = _people()
    _with_shapes(
        om,
        "q:A a sh:NodeShape ; sh:targetClass q:Person ; sh:node q:B .\n"
        "q:B a sh:NodeShape ; sh:targetNode q:bob ; "
        "sh:property [ sh:path q:name ; sh:minCount 1 ] .",
    )
    shacl.remove_shape(om.graph, Q.B)
    assert (Q.B, SH.targetNode, None) not in om.graph
    assert (Q.B, SH.property, None) in om.graph  # A still needs it
    assert [s.name for s in shacl.list_shapes(om.graph)] == [":A"]


CLASS_SHAPE = """
q:Person a sh:NodeShape ; sh:property [ sh:path q:name ; sh:minCount 1 ] .
q:Team a sh:NodeShape ; sh:targetClass q:Team ; sh:property [ sh:path q:lead ; sh:node q:Person ] .
"""


def test_a_used_class_shape_is_refused_with_the_reason():
    """q:Person is a class and a shape (implicit target) that q:Team uses:
    there is no removal that keeps both the class and q:Team intact."""
    om = _people()
    _with_shapes(om, CLASS_SHAPE)
    before = set(om.graph)
    with pytest.raises(ShapesError, match="also a class") as exc:
        shacl.remove_shape(om.graph, Q.Person)
    assert ":Team" in str(exc.value)
    assert set(om.graph) == before


def test_page_explains_a_refused_removal():
    import streamlit as st  # noqa: F401 - the script below imports it

    at = AppTest.from_function(_shacl_page)
    at.run(timeout=120)
    at.text_area[0].set_value(PREFIXES + CLASS_SHAPE).run()
    _button(at, "Check shapes").click().run()
    _button(at, "Add to ontology").click().run()
    before = len(at.session_state["ontology"].graph)
    remove = [b for b in at.button if b.label == "Remove"]
    for button in remove:
        if button.key.endswith(ui_uid(str(Q.Person))):
            button.click().run()
    assert len(at.session_state["ontology"].graph) == before
    flash = at.session_state["flash_message"]
    assert flash["type"] == "error" and "also a class" in flash["message"]


def ui_uid(uri):
    from orionbelt_ontology_builder.ui import _uid

    return _uid(uri)


def table_messages(at):
    """Every message in the findings tables on the page."""
    return [
        message
        for frame in at.dataframe
        if "Message" in frame.value.columns
        for message in frame.value["Message"]
    ]


def select_first_finding(at, prefix):
    """Select the first row of the findings table whose key starts with prefix."""
    key = next(
        k
        for k in at.session_state.filtered_state
        if k.startswith(prefix) and "_table_" in k
    )
    at.session_state[key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run()

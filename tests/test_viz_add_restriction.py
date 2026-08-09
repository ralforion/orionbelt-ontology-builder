"""Adding a restriction by clicking the two classes it relates (issue #221).

Which restriction types belong in the graph flow, and which slot of the axiom
the second click fills, are the decisions worth pinning: get them wrong and the
app writes an axiom no reasoner will accept.
"""

import ast

import pytest

from orionbelt_ontology_builder.app import (
    restriction_references_class,
    restriction_takes_on_class,
    restriction_value_is_class,
)
from orionbelt_ontology_builder.ontology_manager import OntologyManager

QUALIFIED = (
    "minQualifiedCardinality",
    "maxQualifiedCardinality",
    "qualifiedCardinality",
)
VALUE_CLASS = ("someValuesFrom", "allValuesFrom")
NO_SECOND_CLASS = ("hasValue", "minCardinality", "maxCardinality", "exactCardinality")

import sources


@pytest.mark.parametrize("rtype", QUALIFIED)
def test_every_qualified_cardinality_takes_an_on_class(rtype):
    """Including ``qualifiedCardinality``, whose lower-case q used to hide it.

    A ``"Qualified" in rtype`` test matched the min and max siblings but missed
    the exact one, so that type never got an onClass selector on the
    Restrictions page and wrote a bare cardinality.
    """
    assert restriction_takes_on_class(rtype)


@pytest.mark.parametrize("rtype", VALUE_CLASS + NO_SECOND_CLASS)
def test_nothing_else_takes_an_on_class(rtype):
    assert not restriction_takes_on_class(rtype)


@pytest.mark.parametrize("rtype", VALUE_CLASS)
def test_the_value_restrictions_take_a_class_as_their_value(rtype):
    assert restriction_value_is_class(rtype)


@pytest.mark.parametrize("rtype", QUALIFIED + NO_SECOND_CLASS)
def test_nothing_else_takes_a_class_as_its_value(rtype):
    """The qualified ones count with a number; the class rides in onClass."""
    assert not restriction_value_is_class(rtype)


@pytest.mark.parametrize("rtype", VALUE_CLASS + QUALIFIED)
def test_the_graph_flow_offers_every_type_with_a_second_class(rtype):
    assert restriction_references_class(rtype)


@pytest.mark.parametrize("rtype", NO_SECOND_CLASS)
def test_the_graph_flow_leaves_out_types_with_no_second_class(rtype):
    """hasValue and the plain cardinalities describe one class on its own, so
    there is no second node to click and they stay on the Restrictions page."""
    assert not restriction_references_class(rtype)


def test_the_classifiers_cover_every_type_the_engine_knows():
    """A type added to the engine must be classified here, not silently skipped."""
    assert set(OntologyManager.RESTRICTION_TYPES) == set(
        QUALIFIED + VALUE_CLASS + NO_SECOND_CLASS
    )


def test_no_form_decides_qualified_by_case_sensitive_substring():
    """Both the add *and* the edit form must use the shared classifier.

    ``"Qualified" in rtype`` misses ``qualifiedCardinality``. In the add form
    that wrote a bare cardinality; in the edit form it was worse, since saving an
    untouched row sent ``on_class=None`` and stripped ``owl:onClass`` off an
    axiom that was already valid.
    """
    tree = ast.parse(sources.viz_text())
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.In) for op in node.ops)
        and isinstance(node.left, ast.Constant)
        and node.left.value == "Qualified"
    ]
    assert not offenders, (
        f"case-sensitive 'Qualified' membership test at line(s) {offenders}; "
        "use restriction_takes_on_class(), which also matches "
        "qualifiedCardinality"
    )


def test_editing_a_qualified_cardinality_keeps_its_on_class():
    """The regression the edit form caused: a valid axiom losing its onClass."""
    ont = OntologyManager("http://ex.org/o#")
    ont.add_class("Person")
    ont.add_class("Role")
    ont.add_object_property("hasRole")
    ont.add_restriction("Person", "hasRole", "qualifiedCardinality", 2, on_class="Role")
    rest = ont.get_restrictions()[0]
    assert rest["on_class"] == "Role"

    # Re-save the row exactly as it stands, the way the edit form does when the
    # onClass selector is rendered and its current value is submitted back.
    ident = {
        "class_name": rest["applied_to_uris"][0],
        "property_name": rest.get("property_uri") or rest["property"],
        "restriction_type": rest["type"],
        "value": rest.get("value_uri") or rest.get("value"),
        "on_class": rest.get("on_class_uri") or rest.get("on_class"),
    }
    ont.update_restriction(ident, dict(ident))

    assert ont.get_restrictions()[0]["on_class"] == "Role"
    assert "owl:onClass" in ont.graph.serialize(format="turtle")


def test_the_graph_flow_is_handed_object_properties_only():
    """A class-valued restriction on a data property is not valid OWL.

    Every restriction this flow builds fills a class slot, so a data property
    would produce ``owl:someValuesFrom :SomeClass`` against an
    ``owl:DatatypeProperty``.
    """
    src = sources.viz_text()
    call = src.split("_render_panel_add_restriction_form(\n", 1)[1].split(")", 1)[0]
    assert "data_props" not in call, (
        "the graph restriction flow must not be offered data properties"
    )
    assert "object_props" in call


def test_a_qualified_cardinality_writes_its_on_class():
    """The axiom the fix protects: qualified cardinality names the class counted."""
    ont = OntologyManager("http://ex.org/o#")
    ont.add_class("Person")
    ont.add_class("Role")
    ont.add_object_property("hasRole")
    ont.add_restriction("Person", "hasRole", "qualifiedCardinality", 2, on_class="Role")
    turtle = ont.graph.serialize(format="turtle")
    assert "owl:onClass" in turtle
    assert "owl:qualifiedCardinality" in turtle

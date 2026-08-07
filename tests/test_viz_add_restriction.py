"""Adding a restriction by clicking the two classes it relates (issue #221).

Which restriction types belong in the graph flow, and which slot of the axiom
the second click fills, are the decisions worth pinning: get them wrong and the
app writes an axiom no reasoner will accept.
"""

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

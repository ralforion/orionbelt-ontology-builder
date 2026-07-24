"""Text class-hierarchy rendering, including subClassOf cycles (issue #171)."""

from orionbelt_ontology_builder import app
from orionbelt_ontology_builder.ontology_manager import OntologyManager


def test_deep_linear_chain_renders_every_level():
    m = OntologyManager()
    prev = None
    for i in range(8):
        m.add_class(f"Level{i}", parent=prev)
        prev = f"Level{i}"

    text = app.build_class_hierarchy_text(m.get_classes())

    for i in range(8):
        assert f"Level{i}" in text
    # Root has no tree prefix; descendants are indented.
    assert text.splitlines()[0].startswith("Level0")
    assert "└──" in text


def test_subclass_cycle_does_not_recurse_forever():
    # A ⊑ B and B ⊑ A previously raised "maximum recursion depth exceeded".
    m = OntologyManager()
    m.add_class("A")
    m.add_class("B", parent="A")
    m.add_class_relation("A", "subClassOf", "B")

    text = app.build_class_hierarchy_text(m.get_classes())

    assert "A" in text and "B" in text
    assert "(cycle)" in text  # the back-edge is flagged, not followed


def test_self_loop_is_marked_as_cycle():
    m = OntologyManager()
    m.add_class("Loop")
    m.add_class_relation("Loop", "subClassOf", "Loop")

    text = app.build_class_hierarchy_text(m.get_classes())

    assert "Loop" in text
    assert "(cycle)" in text


def test_diamond_class_shown_under_each_parent():
    # Bottom ⊑ Left, Bottom ⊑ Right, both ⊑ Top: a DAG, not a cycle.
    m = OntologyManager()
    m.add_class("Top")
    m.add_class("Left", parent="Top")
    m.add_class("Right", parent="Top")
    m.add_class("Bottom", parent="Left")
    m.add_class_relation("Bottom", "subClassOf", "Right")

    text = app.build_class_hierarchy_text(m.get_classes())

    assert text.count("Bottom") == 2  # appears under Left and under Right
    assert "(cycle)" not in text

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


def test_very_deep_chain_does_not_overflow_the_stack():
    # A 1100-node linear chain exceeds Python's default recursion limit, so a
    # recursive walk raised RecursionError; the iterative walk must not (#171).
    m = OntologyManager()
    prev = None
    for i in range(1100):
        m.add_class(f"C{i}", parent=prev)
        prev = f"C{i}"

    text = app.build_class_hierarchy_text(m.get_classes())

    assert len(text.splitlines()) == 1100
    assert "C0" in text and "C1099" in text


def test_disconnected_cycle_rendered_alongside_a_normal_root():
    # An unrooted cycle must not be dropped just because a normal root exists.
    m = OntologyManager()
    m.add_class("Root")
    m.add_class("Child", parent="Root")
    m.add_class("A")
    m.add_class("B", parent="A")
    m.add_class_relation("A", "subClassOf", "B")  # A <-> B cycle, no root

    text = app.build_class_hierarchy_text(m.get_classes())

    assert "Root" in text and "Child" in text
    assert "A" in text and "B" in text  # the detached cycle is still shown
    assert "(cycle)" in text


def test_multiple_detached_cycles_all_render():
    m = OntologyManager()
    for a, b in [("A", "B"), ("C", "D")]:
        m.add_class(a)
        m.add_class(b, parent=a)
        m.add_class_relation(a, "subClassOf", b)

    text = app.build_class_hierarchy_text(m.get_classes())

    for name in ["A", "B", "C", "D"]:
        assert name in text
    assert text.count("(cycle)") == 2  # one back-edge per cycle


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

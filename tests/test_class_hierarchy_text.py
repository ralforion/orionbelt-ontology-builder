"""Text class-hierarchy rendering: subClassOf cycles (#171), and the DAG
expansion that made it exponential (#371)."""

from orionbelt_ontology_builder import app, ui
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


def _diamond_chain(levels):
    """A_i and B_i both inherit from A_(i-1) and B_(i-1).

    A DAG of 2n+1 classes and no cycles, where the number of distinct paths from
    the root doubles per level — so printing every path is exponential while the
    ontology is tiny.
    """
    m = OntologyManager()
    m.add_class("Root")
    for i in range(levels):
        for side in ("A", "B"):
            parent = "Root" if i == 0 else f"A{i - 1}"
            m.add_class(f"{side}{i}", parent=parent)
            if i:
                m.add_class_relation(f"{side}{i}", "subClassOf", f"B{i - 1}")
    return m


def test_a_class_reached_twice_is_expanded_once():
    """Every path through a DAG used to be expanded in full: 33 classes rendered
    131,071 lines, and one real ontology produced 1.1 GB of text (issue #371)."""
    m = _diamond_chain(12)  # 25 classes; 8,191 lines before this was fixed

    text = app.build_class_hierarchy_text(m.get_classes())

    assert len(text.splitlines()) < 60
    # Every class is still in there — the saving is repeats, not content.
    for name in [f"{side}{i}" for i in range(12) for side in ("A", "B")]:
        assert name in text


def test_a_class_under_two_parents_is_listed_under_both():
    """The repeat that is dropped is the *subtree*, not the class: being a
    subclass of both parents is the fact the tree is there to show."""
    m = OntologyManager()
    m.add_class("Left")
    m.add_class("Right")
    m.add_class("Both", parent="Left")
    m.add_class("Leaf", parent="Both")
    m.add_class_relation("Both", "subClassOf", "Right")

    text = app.build_class_hierarchy_text(m.get_classes())

    assert text.count("Both") == 2  # under Left and under Right
    assert text.count("Leaf") == 1  # its subtree is drawn once
    assert "(shown above)" in text  # and the second listing says so


def test_a_leaf_listed_twice_is_not_marked():
    """Nothing was withheld, so there is nothing to say. The note would only be
    noise on the classes that make up most of a hierarchy."""
    m = OntologyManager()
    m.add_class("Left")
    m.add_class("Right")
    m.add_class("Leaf", parent="Left")
    m.add_class_relation("Leaf", "subClassOf", "Right")

    text = app.build_class_hierarchy_text(m.get_classes())

    assert text.count("Leaf") == 2
    assert "(shown above)" not in text


def test_the_tree_stops_at_the_line_cap_and_says_so(monkeypatch):
    """The backstop for an ontology genuinely too large to print. Checked with a
    small cap: what matters is that it stops, counts what it left out, and does
    not read as a hierarchy that simply ends there."""
    monkeypatch.setattr(ui, "CLASS_TREE_MAX_LINES", 5)
    m = OntologyManager()
    prev = None
    for i in range(20):
        m.add_class(f"C{i}", parent=prev)
        prev = f"C{i}"

    text = app.build_class_hierarchy_text(m.get_classes())

    body, note = text.rsplit("\n\n", 1)
    assert len(body.splitlines()) == 5
    assert "stopped at 5 lines" in note
    assert "15 of 20 classes are not shown" in note

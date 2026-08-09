"""Required dropdowns can be cleared, and say so when they are.

Clearing one was already possible by selecting its text and deleting it, but
there was no cross to do it with and clearing achieved nothing useful: the value
fell back to whatever had been selected before, so the write landed on an entity
the user had explicitly cleared, with neither an error nor a confirmation.

The two halves have to stay together. A dropdown that can be cleared but is not
checked writes the wrong thing; one that is checked but cannot be cleared just
never fires. The last test here fails if they come apart.
"""

import ast
import pathlib

import pytest

from orionbelt_ontology_builder.app import missing_required

APP = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder/app.py"


# --- the message ------------------------------------------------------------


def test_nothing_missing_reads_as_none():
    assert missing_required(Subject="a", Object="b") is None


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_empty_field_is_named(empty):
    """Named, because a form has several and "something is required" sends the
    user hunting for which."""
    assert missing_required(Subject="a", Object=empty) == "Object is required."


def test_the_first_empty_field_is_the_one_reported():
    assert missing_required(Subject=None, Object=None) == "Subject is required."


def test_a_label_with_spaces_survives():
    assert (
        missing_required(**{"Applies to Class": None})
        == "Applies to Class is required."
    )


# --- the two halves stay together -------------------------------------------


def _functions_calling(name):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                return node.name
        return "<module>"

    return {
        enclosing(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    }


def test_every_form_with_a_clearable_dropdown_checks_it():
    """A cleared field must be reported, not written past.

    Both are function-scoped, so a form that grows a clearable dropdown without
    a check — or loses its check — shows up here rather than in someone's
    ontology.
    """
    clearable = _functions_calling("required_selectbox")
    checked = _functions_calling("missing_required")
    assert clearable, "no form uses required_selectbox"
    unchecked = clearable - checked
    assert not unchecked, (
        f"these forms offer a clearable dropdown but never check it: {sorted(unchecked)}"
    )


def test_no_form_checks_without_offering_one():
    """The mirror: a check with nothing clearable can never fire, which reads
    as protection that is not there."""
    clearable = _functions_calling("required_selectbox")
    checked = _functions_calling("missing_required")
    assert not (checked - clearable), sorted(checked - clearable)

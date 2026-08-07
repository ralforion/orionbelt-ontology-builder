"""The intro shown to someone with nothing loaded yet.

It says what the app is on a first visit and then gets out of the way. Both
halves matter: a banner that outlived the empty ontology would push every page's
real content down for the rest of the session, on all thirteen pages.
"""

import ast
from pathlib import Path

from orionbelt_ontology_builder.app import _ontology_is_empty
from orionbelt_ontology_builder.ontology_manager import OntologyManager

_APP = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "app.py"


HERO_TITLE = "OrionBelt® Ontology Builder"


def _hero_guards():
    """Every ``if`` whose body prints the hero title, as AST nodes."""
    tree = ast.parse(_APP.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(HERO_TITLE in ast.dump(stmt) for stmt in node.body)
    ]


def test_the_hero_is_gated_on_an_empty_ontology():
    """It must sit inside a condition, not be emitted unconditionally."""
    guards = _hero_guards()
    assert guards, f"the hero title {HERO_TITLE!r} is not inside any `if`"
    assert all("_ontology_is_empty" in ast.dump(g.test) for g in guards), (
        "the hero must be gated on _ontology_is_empty, so it disappears as soon "
        "as there is something to work on"
    )


def test_the_product_name_carries_the_trademark():
    """The README registers OrionBelt®, and this is the one place in the UI that
    prints the full product name."""
    assert HERO_TITLE in _APP.read_text(encoding="utf-8")
    readme = (_APP.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "OrionBelt®" in readme


def test_an_untouched_ontology_counts_as_empty():
    """A fresh session: metadata only, so the hero shows."""
    assert _ontology_is_empty(OntologyManager("http://example.org/o#"))


def test_one_class_is_enough_to_retire_the_hero():
    ont = OntologyManager("http://example.org/o#")
    ont.add_class("Person")
    assert not _ontology_is_empty(ont)


def test_metadata_alone_does_not_retire_the_hero():
    """Naming an ontology is not the same as having built anything in it."""
    ont = OntologyManager("http://example.org/o#")
    ont.set_ontology_metadata(label="My ontology", comment="Notes")
    assert _ontology_is_empty(ont)

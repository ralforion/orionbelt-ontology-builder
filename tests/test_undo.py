"""Tests for snapshot infrastructure and undo/redo."""

import json

from rdflib import URIRef

from ontology_manager import IMPORT_REPLACE, OntologyManager, UndoManager


def test_snapshot_roundtrip(populated_om):
    """Snapshot capture and restore preserves graph content."""
    original_classes = sorted(c["name"] for c in populated_om.get_classes())
    snapshot = populated_om.take_snapshot()

    populated_om.add_class("NewClass")
    assert "NewClass" in [c["name"] for c in populated_om.get_classes()]

    populated_om.restore_snapshot(snapshot)
    restored_classes = sorted(c["name"] for c in populated_om.get_classes())
    assert restored_classes == original_classes


def test_snapshot_preserves_namespace(populated_om):
    snapshot = populated_om.take_snapshot()
    old_base = populated_om.base_uri
    populated_om.restore_snapshot(snapshot)
    assert populated_om.base_uri == old_base


def test_undo_basic(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("Temp")
    um.checkpoint("Added Temp")

    assert "Temp" in [c["name"] for c in populated_om.get_classes()]
    um.undo()
    assert "Temp" not in [c["name"] for c in populated_om.get_classes()]


def test_redo_basic(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("Temp")
    um.checkpoint("Added Temp")

    um.undo()
    assert "Temp" not in [c["name"] for c in populated_om.get_classes()]
    um.redo()
    assert "Temp" in [c["name"] for c in populated_om.get_classes()]


def test_undo_returns_none_at_bottom(populated_om):
    um = UndoManager(populated_om)
    assert um.undo() is None


def test_redo_returns_none_when_empty(populated_om):
    um = UndoManager(populated_om)
    assert um.redo() is None


def test_checkpoint_clears_redo_stack(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("A")
    um.checkpoint("A")
    um.undo()
    assert um.can_redo()

    populated_om.add_class("B")
    um.checkpoint("B")
    assert not um.can_redo()


def test_multiple_undo_redo(populated_om):
    um = UndoManager(populated_om)

    populated_om.add_class("Step1")
    um.checkpoint("Step1")
    populated_om.add_class("Step2")
    um.checkpoint("Step2")
    populated_om.add_class("Step3")
    um.checkpoint("Step3")

    def names():
        return [c["name"] for c in populated_om.get_classes()]

    assert "Step3" in names()
    um.undo()
    assert "Step3" not in names()
    assert "Step2" in names()
    um.undo()
    assert "Step2" not in names()
    assert "Step1" in names()
    um.redo()
    assert "Step2" in names()


def test_max_history_enforced():
    om = OntologyManager()
    um = UndoManager(om, max_history=5)
    for i in range(10):
        om.add_class(f"C{i}")
        um.checkpoint(f"C{i}")
    assert len(um._undo_stack) <= 5


def test_undo_labels(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("A")
    um.checkpoint("Added A")
    populated_om.add_class("B")
    um.checkpoint("Added B")

    assert um.undo_labels == ["Added A", "Added B"]
    um.undo()
    assert um.redo_labels == ["Added B"]


def _names(om):
    return {c["name"] for c in om.get_classes()}


def test_checkpoint_holds_only_the_edit(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("Temp")
    um.checkpoint("Added Temp")
    _, changes = um._undo_stack[-1]
    assert changes and all(change.added for change in changes)
    assert len(changes) < len(populated_om.graph)


def test_undo_keeps_custom_prefixes(populated_om):
    populated_om.add_prefix("zoo", "http://zoo.example/")
    um = UndoManager(populated_om)
    populated_om.add_class("Temp")
    um.checkpoint("Added Temp")
    um.undo()
    assert dict(populated_om.graph.namespaces())["zoo"] == URIRef("http://zoo.example/")


def test_undo_drops_edits_after_the_last_checkpoint(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("A")
    um.checkpoint("A")
    populated_om.add_class("Pending")
    um.undo()
    assert "A" not in _names(populated_om)
    assert "Pending" not in _names(populated_om)
    um.redo()
    assert "A" in _names(populated_om)
    assert "Pending" not in _names(populated_om)


def test_undo_spans_a_replacing_import(populated_om):
    um = UndoManager(populated_om)
    populated_om.merge_from_string(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://other.org/o> a owl:Ontology .\n"
        "<http://other.org/o#Only> a owl:Class .\n",
        format="turtle",
        strategy=IMPORT_REPLACE,
    )
    um.checkpoint("Import ontology")
    assert _names(populated_om) == {"Only"}
    um.undo()
    assert "Person" in _names(populated_om)
    assert "Only" not in _names(populated_om)
    assert populated_om.base_uri == "http://test.org/ont#"
    um.redo()
    assert _names(populated_om) == {"Only"}
    assert populated_om.base_uri == "http://other.org/o#"


def test_undo_restores_the_base_uri(populated_om):
    um = UndoManager(populated_om)
    populated_om.set_base_uri("http://moved.org/ont#")
    um.checkpoint("Base URI")
    assert populated_om.base_uri == "http://moved.org/ont#"
    um.undo()
    assert populated_om.base_uri == "http://test.org/ont#"
    assert populated_om.get_classes()[0]["uri"].startswith("http://test.org/ont#")


def test_a_new_undo_manager_starts_from_the_current_state(populated_om):
    first = UndoManager(populated_om)
    populated_om.add_class("A")
    first.checkpoint("A")
    second = UndoManager(populated_om)
    assert not second.can_undo()
    populated_om.add_class("B")
    second.checkpoint("B")
    second.undo()
    assert "A" in _names(populated_om)
    assert "B" not in _names(populated_om)


OTHER_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "<http://other.org/o> a owl:Ontology .\n"
    "<http://other.org/o#Only> a owl:Class .\n"
)


def _bound(om):
    return dict(om.graph.namespaces())


def test_undo_reverses_only_the_added_prefix(populated_om):
    populated_om.add_prefix("zoo", "http://zoo.example/")
    um = UndoManager(populated_om)
    populated_om.add_prefix("farm", "http://farm.example/")
    um.checkpoint("Add prefix farm")
    um.undo()
    assert "farm" not in _bound(populated_om)
    assert _bound(populated_om)["zoo"] == URIRef("http://zoo.example/")
    assert "http://farm.example/" not in populated_om.get_creatable_namespaces()
    um.redo()
    assert _bound(populated_om)["farm"] == URIRef("http://farm.example/")
    assert "http://farm.example/" in populated_om.get_creatable_namespaces()


def test_undo_reverses_a_removed_prefix(populated_om):
    populated_om.add_prefix("zoo", "http://zoo.example/")
    um = UndoManager(populated_om)
    populated_om.remove_prefix("zoo")
    um.checkpoint("Remove prefix zoo")
    assert "zoo" not in _bound(populated_om)
    um.undo()
    assert _bound(populated_om)["zoo"] == URIRef("http://zoo.example/")
    assert "http://zoo.example/" in populated_om.get_creatable_namespaces()


def test_undo_of_a_load_restores_prefixes(populated_om):
    populated_om.add_prefix("zoo", "http://zoo.example/")
    um = UndoManager(populated_om)
    populated_om.load_from_string(OTHER_TTL, format="turtle")
    um.checkpoint("Load")
    assert "zoo" not in _bound(populated_om)
    um.undo()
    assert _bound(populated_om)["zoo"] == URIRef("http://zoo.example/")
    assert "http://zoo.example/" in populated_om.get_creatable_namespaces()


def test_history_leaves_named_graphs_alone(populated_om):
    """A JSON-LD named graph is stored under its own context, invisible to the
    managed graph; a redo must not move its triples into it."""
    um = UndoManager(populated_om)
    document = json.dumps(
        {
            "@context": {"owl": "http://www.w3.org/2002/07/owl#"},
            "@graph": [
                {"@id": "http://other.org/o", "@type": "owl:Ontology"},
                {"@id": "http://other.org/o#Default", "@type": "owl:Class"},
                {
                    "@id": "http://other.org/named",
                    "@graph": [
                        {"@id": "http://other.org/o#Hidden", "@type": "owl:Class"}
                    ],
                },
            ],
        }
    )
    populated_om.load_from_string(document, format="json-ld")
    um.checkpoint("Load")
    assert "Default" in _names(populated_om)
    assert "Hidden" not in _names(populated_om)
    um.undo()
    assert "Person" in _names(populated_om)
    assert "Default" not in _names(populated_om)
    um.redo()
    assert "Default" in _names(populated_om)
    assert "Hidden" not in _names(populated_om)

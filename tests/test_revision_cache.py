"""The graph revision and the listings memoised on it (issue #437).

Every change to the triples or the prefix bindings moves ``revision``; the
entity listings, the statistics and the Turtle export are computed once per
revision and handed back until it moves again.
"""

from rdflib import OWL, RDF, URIRef

from ontology_manager import OntologyManager, UndoManager


def test_add_and_remove_move_the_revision(om):
    before = om.revision
    om.add_class("Dog")
    after_add = om.revision
    assert after_add > before
    om.delete_class("Dog")
    assert om.revision > after_add


def test_a_no_op_add_is_not_a_change(om):
    om.add_class("Dog")
    before = om.revision
    om.graph.add((om._uri("Dog"), RDF.type, OWL.Class))
    assert om.revision == before


def test_prefix_bindings_move_the_revision(om):
    before = om.revision
    om.add_prefix("zoo", "http://zoo.example/")
    bound = om.revision
    assert bound > before
    om.remove_prefix("zoo")
    assert om.revision > bound


def test_listing_is_reused_until_the_graph_changes(om):
    om.add_class("Dog")
    first = om.get_classes()
    again = om.get_classes()
    assert again == first
    assert again[0] is first[0]  # the entries are shared, not rebuilt
    om.add_class("Cat")
    assert [c["name"] for c in om.get_classes()] == ["Cat", "Dog"]


def test_listing_container_belongs_to_the_caller(om):
    om.add_class("Dog")
    mine = om.get_classes()
    mine.append({"name": "Intruder"})
    assert [c["name"] for c in om.get_classes()] == ["Dog"]


def test_listings_with_arguments_are_keyed_on_them(skos_om):
    skos_om.add_concept_scheme("Other", label="Other")
    skos_om.add_concept("Rock", scheme="Other", pref_label="Rock")
    assert {c["name"] for c in skos_om.get_concepts("Other")} == {"Rock"}
    assert "Dog" in {c["name"] for c in skos_om.get_concepts("MyScheme")}
    assert len(skos_om.get_concepts()) == 4


def test_statistics_refresh_after_an_edit(populated_om):
    assert populated_om.get_statistics()["classes"] == 3
    populated_om.add_class("Robot")
    assert populated_om.get_statistics()["classes"] == 4


def test_export_refreshes_after_a_prefix_change(om):
    om.graph.add((URIRef("http://zoo.example/Lion"), RDF.type, OWL.Class))
    assert "<http://zoo.example/Lion>" in om.export_to_string("turtle")
    om.add_prefix("zoo", "http://zoo.example/")
    assert "zoo:Lion" in om.export_to_string("turtle")


def test_a_load_replaces_the_cached_listing(populated_om):
    assert "Person" in {c["name"] for c in populated_om.get_classes()}
    populated_om.load_from_string(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://other.org/o> a owl:Ontology .\n"
        "<http://other.org/o#Only> a owl:Class .\n",
        format="turtle",
    )
    assert [c["name"] for c in populated_om.get_classes()] == ["Only"]


def test_a_new_base_uri_refreshes_the_listing(populated_om):
    populated_om.set_base_uri("http://moved.org/ont#")
    assert all(
        c["uri"].startswith("http://moved.org/ont#") for c in populated_om.get_classes()
    )


def test_replaying_history_moves_the_revision(populated_om):
    um = UndoManager(populated_om)
    populated_om.add_class("Temp")
    um.checkpoint("Added Temp")
    before = populated_om.revision
    um.undo()
    assert populated_om.revision > before
    assert "Temp" not in {c["name"] for c in populated_om.get_classes()}


def test_journal_is_kept_only_for_an_undo_manager():
    om = OntologyManager()
    for i in range(5):
        om.add_class(f"C{i}")
    assert om._journal.entries == []
    um = UndoManager(om)
    om.add_class("Tracked")
    assert len(om._journal.entries) > 0
    del um
    om.add_class("Untracked")
    assert om._journal.entries == []
    # A stale entry from the old consumer is not kept either.
    UndoManager(om)
    om.add_class("Orphaned")
    assert om._journal.entries == []


def test_direct_graph_edits_are_seen(om):
    """Pages that write through ``ont.graph`` count like engine methods."""
    before = om.revision
    om.graph.add((URIRef("http://x.org/a"), RDF.type, OWL.Class))
    assert om.revision > before

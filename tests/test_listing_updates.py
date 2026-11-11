"""Listings followed edit by edit equal listings built from scratch.

The memoised listings in ``ontology_manager._LISTING_UPDATES`` follow the
journal's changes instead of being built again after every edit. Each update
rests on a claim about what its listing reads (an entity's entry reads only
the triples about it, the statistics only count). If a listing reads more
than its update claims, the followed listing goes stale.

So random edits run on the bundled samples, and after each one every such
listing is compared with the same method called past the cache. The edits
mix the engine's own operations with raw triple changes, undo and redo,
prefix changes, and a bulk change past the journal's log limit.
"""

import random
import re
from pathlib import Path

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from orionbelt_ontology_builder.ontology_manager import (
    _LISTING_UPDATES,
    SKOSXL,
    OntologyManager,
    UndoManager,
    _GraphJournal,
)

SAMPLES = (
    Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder" / "samples"
)
SAMPLE_FILES = {
    "pizza.owl": "xml",
    "prov-o.ttl": "turtle",
    "foaf.rdf": "xml",
    "wine.owl": "xml",
    "gist/gistCore14.1.0.ttl": "turtle",
    "geography-thesaurus.ttl": "turtle",
    "skos-showcase.ttl": "turtle",
}
SCHEMA_DOMAIN = URIRef("https://schema.org/domainIncludes")
#: A name the engine accepts, so it resolves to an entity in the namespace.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")


def _built_fresh(om: OntologyManager, name: str):
    return getattr(OntologyManager, name).__wrapped__(om)


def _assert_followed(om: OntologyManager, step: str) -> None:
    for name in _LISTING_UPDATES:
        assert getattr(om, name)() == _built_fresh(om, name), f"{name} after {step}"
    _assert_scheme_filters(om, step)


def _assert_scheme_filters(om: OntologyManager, step: str) -> None:
    """A scheme filter over the followed concepts keeps exactly the concepts
    _concept_in_scheme counts in, as get_concepts filtered before."""
    fresh = _built_fresh(om, "_concept_listing")
    schemes = list(om.graph.subjects(RDF.type, SKOS.ConceptScheme))
    for scheme in schemes:
        if not isinstance(scheme, URIRef):
            continue
        name = om._local_name(scheme)
        resolved = next(s for s in schemes if om._local_name(s) == name)
        expected = [
            c for c in fresh if om._concept_in_scheme(URIRef(c["uri"]), resolved)
        ]
        assert om.get_concepts(scheme=name) == expected, f"scheme {name} after {step}"


class _Editor:
    """Random edits on one ontology, each followed by an undo checkpoint."""

    def __init__(self, om: OntologyManager, seed: int) -> None:
        self.om = om
        self.rng = random.Random(seed)
        self.undo = UndoManager(om)
        self.made = 0

    # -- what there is to edit -------------------------------------------

    def _of_type(self, rdf_type) -> list[URIRef]:
        return sorted(
            s
            for s in self.om.graph.subjects(RDF.type, rdf_type)
            if isinstance(s, URIRef)
        )

    def _pick(self, rdf_type):
        found = self._of_type(rdf_type)
        return self.rng.choice(found) if found else None

    def _own(self, rdf_type) -> list[str]:
        """Local names of members in the ontology's own namespace, which the
        engine's name-based operations resolve."""
        ns = str(self.om.namespace)
        names = (
            str(s)[len(ns) :] for s in self._of_type(rdf_type) if str(s).startswith(ns)
        )
        return [name for name in names if _NAME.fullmatch(name)]

    def _new_name(self, stem: str) -> str:
        self.made += 1
        return f"{stem}{self.made}"

    # -- the edits ---------------------------------------------------------

    def add_class(self):
        parents = self._own(OWL.Class)
        parent = (
            self.rng.choice(parents) if parents and self.rng.random() < 0.7 else None
        )
        self.om.add_class(self._new_name("Cls"), parent=parent, label="New class")

    def update_class(self):
        names = self._own(OWL.Class)
        if names:
            self.om.update_class(self.rng.choice(names), new_label=f"Label {self.made}")

    def rename_class(self):
        names = self._own(OWL.Class)
        if names:
            self.om.rename_class(self.rng.choice(names), self._new_name("Renamed"))

    def delete_class(self):
        names = self._own(OWL.Class)
        if names:
            self.om.delete_class(self.rng.choice(names))

    def drop_class_type(self):
        cls = self._pick(OWL.Class)
        if cls is not None:
            self.om.graph.remove((cls, RDF.type, OWL.Class))

    def relabel_anything(self):
        subjects = sorted(
            {s for s in self.om.graph.subjects() if isinstance(s, URIRef)}, key=str
        )
        subject = self.rng.choice(subjects)
        if self.rng.random() < 0.3:
            self.om.graph.remove((subject, RDFS.label, None))
        else:
            self.om.graph.set((subject, RDFS.label, Literal(f"Relabelled {self.made}")))
            self.made += 1

    def link_classes(self):
        a, b = self._pick(OWL.Class), self._pick(OWL.Class)
        if a is not None and b is not None:
            self.om.graph.add((a, RDFS.subClassOf, b))

    def unlink_classes(self):
        links = sorted(self.om.graph.triples((None, RDFS.subClassOf, None)), key=str)
        if links:
            self.om.graph.remove(self.rng.choice(links))

    def add_restriction(self):
        names = self._own(OWL.Class)
        props = self._own(OWL.ObjectProperty)
        if names and props:
            self.om.add_restriction(
                self.rng.choice(names),
                self.rng.choice(props),
                "someValuesFrom",
                self.rng.choice(names),
            )

    def add_individual(self):
        names = self._own(OWL.Class)
        if names:
            self.om.add_individual(self._new_name("ind"), self.rng.choice(names))

    def assert_on_individual(self):
        ind = self._pick(OWL.NamedIndividual)
        other = self._pick(OWL.NamedIndividual)
        prop = self._pick(OWL.ObjectProperty) or URIRef(f"{self.om.namespace}rel")
        if ind is not None and other is not None:
            self.om.graph.add((ind, prop, other))
            self.om.graph.add((ind, RDFS.comment, Literal(f"note {self.made}")))
            self.made += 1

    def delete_individual(self):
        names = self._own(OWL.NamedIndividual)
        if names:
            self.om.delete_individual(self.rng.choice(names))

    def add_property(self):
        names = self._own(OWL.Class)
        domain = self.rng.choice(names) if names else None
        if self.rng.random() < 0.5:
            self.om.add_object_property(
                self._new_name("rel"), domain=domain, range_=domain
            )
        else:
            self.om.add_data_property(
                self._new_name("attr"), domain=domain, range_="string"
            )

    def change_property(self):
        prop = self._pick(OWL.ObjectProperty) or self._pick(OWL.DatatypeProperty)
        cls = self._pick(OWL.Class)
        if prop is None or cls is None:
            return
        choice = self.rng.randrange(5)
        if choice == 0:
            self.om.graph.set((prop, RDFS.domain, cls))
        elif choice == 1:
            self.om.graph.remove((prop, RDFS.range, None))
            self.om.graph.add((prop, SCHEMA_DOMAIN, cls))
        elif choice == 2:
            self.om.graph.add((prop, RDF.type, OWL.FunctionalProperty))
        elif choice == 3:
            self.om.graph.remove((prop, RDF.type, OWL.FunctionalProperty))
            self.om.graph.add((prop, OWL.inverseOf, prop))
        else:
            self.om.graph.set((prop, RDFS.range, XSD.integer))

    def delete_property(self):
        names = self._own(OWL.ObjectProperty) + self._own(OWL.DatatypeProperty)
        if names:
            self.om.delete_property(self.rng.choice(names))

    def touch_ontology_header(self):
        self.om.set_ontology_metadata(comment=f"Revision {self.made}")
        self.made += 1

    def change_prefixes(self):
        if self.rng.random() < 0.5:
            self.om.add_prefix(f"p{self.made}", f"http://prefix.example/{self.made}#")
            self.made += 1
        else:
            custom = [p for p in self.om._user_added_prefixes if p]
            if custom:
                self.om.remove_prefix(self.rng.choice(sorted(custom)))

    def add_concept(self):
        schemes = self._own(SKOS.ConceptScheme)
        concepts = self._own(SKOS.Concept)
        self.om.add_concept(
            self._new_name("k"),
            scheme=self.rng.choice(schemes)
            if schemes and self.rng.random() < 0.7
            else None,
            pref_label="New concept",
            broader=self.rng.choice(concepts)
            if concepts and self.rng.random() < 0.6
            else None,
        )

    def delete_concept(self):
        names = self._own(SKOS.Concept)
        if names:
            self.om.delete_concept(self.rng.choice(names))

    def relabel_concept(self):
        concept = self._pick(SKOS.Concept)
        if concept is not None:
            self.om.graph.set(
                (concept, SKOS.prefLabel, Literal(f"Concept {self.made}", lang="en"))
            )
            self.made += 1

    def move_concept(self):
        concept, other = self._pick(SKOS.Concept), self._pick(SKOS.Concept)
        if concept is not None and other is not None:
            self.om.graph.set((concept, SKOS.broader, other))
            self.om.graph.add((other, SKOS.narrower, concept))

    def scheme_side_top(self):
        scheme, concept = self._pick(SKOS.ConceptScheme), self._pick(SKOS.Concept)
        if scheme is None or concept is None:
            return
        if self.rng.random() < 0.5:
            self.om.graph.add((scheme, SKOS.hasTopConcept, concept))
        else:
            self.om.graph.remove((scheme, SKOS.hasTopConcept, None))

    def drop_in_scheme(self):
        concept = self._pick(SKOS.Concept)
        if concept is not None:
            self.om.graph.remove((concept, SKOS.inScheme, None))

    def xl_label(self):
        """A SKOS-XL label resource: added, or its literal form changed, which
        is a change to a triple about the label node, not the concept."""
        labels = sorted(self.om.graph.triples((None, SKOSXL.prefLabel, None)), key=str)
        if labels and self.rng.random() < 0.6:
            _, _, node = self.rng.choice(labels)
            self.om.graph.set(
                (node, SKOSXL.literalForm, Literal(f"XL {self.made}", lang="en"))
            )
            self.made += 1
            return
        concept = self._pick(SKOS.Concept)
        if concept is not None:
            node = BNode()
            self.om.graph.add((concept, SKOSXL.prefLabel, node))
            self.om.graph.add((node, RDF.type, SKOSXL.Label))
            self.om.graph.add(
                (node, SKOSXL.literalForm, Literal("XL label", lang="en"))
            )

    def blank_node_soup(self):
        node = BNode()
        self.om.graph.add((node, RDF.type, OWL.Class))
        self.om.graph.add((node, RDFS.label, Literal("anonymous")))

    EDITS = (
        add_class,
        update_class,
        rename_class,
        delete_class,
        drop_class_type,
        relabel_anything,
        link_classes,
        unlink_classes,
        add_restriction,
        add_individual,
        assert_on_individual,
        delete_individual,
        add_property,
        change_property,
        delete_property,
        touch_ontology_header,
        change_prefixes,
        blank_node_soup,
        add_concept,
        delete_concept,
        relabel_concept,
        move_concept,
        scheme_side_top,
        drop_in_scheme,
        xl_label,
    )

    def step(self) -> str:
        roll = self.rng.random()
        if roll < 0.08 and self.undo.can_undo():
            self.undo.undo()
            return "undo"
        if roll < 0.12 and self.undo.can_redo():
            self.undo.redo()
            return "redo"
        edit = self.rng.choice(self.EDITS)
        edit(self)
        self.undo.checkpoint(edit.__name__)
        return edit.__name__


@pytest.mark.parametrize("sample", list(SAMPLE_FILES))
def test_listings_follow_random_edits(sample):
    om = OntologyManager()
    om.load_from_file(str(SAMPLES / sample), format=SAMPLE_FILES[sample])
    editor = _Editor(om, seed=sum(map(ord, sample)))
    _assert_followed(om, "loading")
    for number in range(80):
        step = editor.step()
        # Mostly after every edit, sometimes after several, so a replay of
        # more than one change is covered too.
        if editor.rng.random() < 0.7:
            _assert_followed(om, f"edit {number}: {step}")
    _assert_followed(om, "the last edit")


def test_a_bulk_change_past_the_log_limit_is_built_again(monkeypatch):
    monkeypatch.setattr(_GraphJournal, "CACHE_LOG_LIMIT", 10)
    om = OntologyManager(base_uri="http://test.org/b#")
    om.add_class("A")
    _assert_followed(om, "the first class")
    for i in range(30):
        om.add_class(f"Bulk{i}", parent="A")
    _assert_followed(om, "thirty classes at once")


def _count_entries(monkeypatch, name: str) -> list[object]:
    built: list[object] = []
    real = getattr(OntologyManager, name)

    def counting(self, node):
        built.append(node)
        return real(self, node)

    monkeypatch.setattr(OntologyManager, name, counting)
    return built


def test_a_label_edit_builds_one_entry_not_the_listing(monkeypatch):
    om = OntologyManager(base_uri="http://test.org/l#")
    for name in ("A", "B", "C"):
        om.add_class(name)
    om.get_classes()
    built = _count_entries(monkeypatch, "_class_entry")
    om.update_class("B", new_label="Bee")
    labels = {c["name"]: c["label"] for c in om.get_classes()}
    assert labels["B"] == "Bee"
    assert built == [URIRef("http://test.org/l#B")]


def test_an_edit_the_listing_does_not_read_leaves_it_alone(monkeypatch):
    """A label on an individual touches no class."""
    om = OntologyManager(base_uri="http://test.org/l#")
    om.add_class("A")
    om.add_individual("a1", "A")
    om.get_classes()
    built = _count_entries(monkeypatch, "_class_entry")
    om.update_individual("a1", new_label="first")
    om.get_classes()
    assert built == []


def test_a_new_subclass_rebuilds_its_parent_for_the_children():
    om = OntologyManager(base_uri="http://test.org/l#")
    om.add_class("Animal")
    om.get_classes()
    om.add_class("Dog", parent="Animal")
    by_name = {c["name"]: c for c in om.get_classes()}
    assert by_name["Animal"]["children"] == ["Dog"]


def test_equal_names_sort_by_uri_either_way():
    """Two classes named alike in different namespaces: patched and built
    from scratch, they come in the same order."""
    om = OntologyManager(base_uri="http://test.org/a#")
    om.get_classes()
    om.graph.add((URIRef("http://zzz.example/Thing"), RDF.type, OWL.Class))
    om.graph.add((URIRef("http://aaa.example/Thing"), RDF.type, OWL.Class))
    uris = [c["uri"] for c in om.get_classes()]
    assert uris == ["http://aaa.example/Thing", "http://zzz.example/Thing"]
    assert uris == [c["uri"] for c in _built_fresh(om, "get_classes")]


def test_statistics_follow_the_count_exactly():
    om = OntologyManager(base_uri="http://test.org/s#")
    om.get_statistics()
    om.add_class("A")
    om.add_class("B", parent="A")
    om.add_individual("b1", "B")
    om.delete_class("A")
    om.set_ontology_metadata(label="Stats")
    assert om.get_statistics() == _built_fresh(om, "get_statistics")


def _scheme_with_concept() -> tuple[OntologyManager, URIRef, URIRef]:
    om = OntologyManager(base_uri="http://test.org/k#")
    om.add_concept_scheme("Things")
    om.add_concept("Dog", pref_label="Dog")
    om.get_concepts()
    return om, URIRef("http://test.org/k#Things"), URIRef("http://test.org/k#Dog")


def test_a_scheme_naming_its_top_concept_updates_that_concept():
    """The scheme states it (scheme skos:hasTopConcept concept): a triple
    about the scheme that changes the concept's entry."""
    om, scheme, dog = _scheme_with_concept()
    om.graph.add((scheme, SKOS.hasTopConcept, dog))
    (entry,) = om.get_concepts()
    assert entry["top_of_uris"] == [str(scheme)]
    assert om.get_concepts(scheme="Things") == [entry]
    _assert_followed(om, "hasTopConcept")


def test_a_changed_skos_xl_label_updates_its_concept():
    """The label lives on its own resource: a triple about that resource
    changes the concept's entry."""
    om, _, dog = _scheme_with_concept()
    om.graph.remove((dog, SKOS.prefLabel, None))
    label = BNode()
    om.graph.add((dog, SKOSXL.prefLabel, label))
    om.graph.add((label, SKOSXL.literalForm, Literal("Hound", lang="en")))
    assert om.get_concepts()[0]["prefLabel"] == "Hound"
    om.graph.set((label, SKOSXL.literalForm, Literal("Doggo", lang="en")))
    assert om.get_concepts()[0]["prefLabel"] == "Doggo"
    _assert_followed(om, "literalForm")

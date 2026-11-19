"""Authoring SKOS-XL labels: adding, editing, removing and converting them.

A SKOS-XL label is a resource (``skosxl:Label``) with exactly one
``skosxl:literalForm`` (SKOS Reference S52), linked from a concept by
``skosxl:prefLabel``, ``altLabel`` or ``hiddenLabel``. What is said about the
resource is the point of the extension, so these tests hold the engine to
keeping it while the text changes and to removing it only with the label.
"""

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from ontology_manager import SKOSXL, OntologyManager

BASE = "http://test.org/ont#"


def _uri(name):
    return URIRef(BASE + name)


@pytest.fixture
def om():
    om = OntologyManager(base_uri=BASE)
    om.add_concept_scheme("S", label="S")
    om.add_concept("Dog", scheme="S")
    om.set_top_concept("Dog", "S")
    om.set_concept_note("Dog", "definition", "A domesticated canine", lang="en")
    return om


def _xl(om, concept="Dog"):
    return next(c for c in om.get_concepts() if c["name"] == concept)["xl_labels"]


def _plain(om, concept="Dog"):
    return next(c for c in om.get_concepts() if c["name"] == concept)["labels"]


class TestAdding:
    def test_a_label_is_a_resource_with_one_literal_form(self, om):
        label = URIRef(om.add_xl_label("Dog", "prefLabel", "Dog", "en"))
        assert (label, RDF.type, SKOSXL.Label) in om.graph
        assert list(om.graph.objects(label, SKOSXL.literalForm)) == [
            Literal("Dog", lang="en")
        ]
        assert (_uri("Dog"), SKOSXL.prefLabel, label) in om.graph

    def test_it_is_named_after_its_concept_and_language(self, om):
        first = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        second = om.add_xl_label("Dog", "altLabel", "Pooch", "en")
        untagged = om.add_xl_label("Dog", "hiddenLabel", "dgo")
        assert first == BASE + "Dog_xl_en"
        assert second == BASE + "Dog_xl_en_2"
        assert untagged == BASE + "Dog_xl"

    def test_a_name_something_else_uses_is_not_taken(self, om):
        om.add_class("Dog_xl_en")
        assert om.add_xl_label("Dog", "altLabel", "Hound", "en") == BASE + "Dog_xl_en_2"

    def test_it_lives_in_the_concepts_namespace(self, om):
        concept = "http://other.org/vocab/Cat"
        om.graph.add((URIRef(concept), RDF.type, SKOS.Concept))
        label = om.add_xl_label(concept, "prefLabel", "Cat", "en")
        assert label == "http://other.org/vocab/Cat_xl_en"

    def test_the_concept_listing_shows_it(self, om):
        label = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        assert _xl(om)["altLabel"] == [{"value": "Hound", "lang": "en", "label": label}]
        assert _plain(om)["altLabel"] == []

    def test_adding_the_same_text_again_returns_the_same_label(self, om):
        first = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        triples = len(om.graph)
        assert om.add_xl_label("Dog", "altLabel", "Hound", "en") == first
        assert len(om.graph) == triples

    @pytest.mark.parametrize(
        ("kind", "value", "lang"),
        [
            ("nickname", "Dog", "en"),
            ("prefLabel", "   ", "en"),
            ("prefLabel", "Dog", "not a tag"),
        ],
    )
    def test_bad_input_is_refused_before_anything_is_written(
        self, om, kind, value, lang
    ):
        triples = len(om.graph)
        with pytest.raises(ValueError):
            om.add_xl_label("Dog", kind, value, lang)
        assert len(om.graph) == triples

    def test_a_refused_pref_label_leaves_no_concept_behind(self, om):
        """Checked before the concept is written, not after (review of #574)."""
        triples = len(om.graph)
        with pytest.raises(ValueError):
            om.add_concept("Cat", scheme="S", pref_label="   ", pref_label_xl=True)
        with pytest.raises(ValueError):
            om.add_concept("Cat", pref_label="Cat", lang="no tag", pref_label_xl=True)
        assert len(om.graph) == triples
        assert "Cat" not in [c["name"] for c in om.get_concepts()]

    def test_add_concept_can_write_its_pref_label_as_skos_xl(self, om):
        om.add_concept(
            "Cat", scheme="S", pref_label="Cat", lang="en", pref_label_xl=True
        )
        assert _xl(om, "Cat")["prefLabel"][0]["value"] == "Cat"
        assert _plain(om, "Cat")["prefLabel"] == []


class TestOnePrefLabelPerLanguage:
    """S14 holds across both forms, because a SKOS-XL prefLabel entails the
    plain one with its text (S55). A new prefLabel replaces a different one in
    its language whichever form either is in, as a plain one always has."""

    def test_an_xl_pref_label_replaces_a_plain_one(self, om):
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        om.add_xl_label("Dog", "prefLabel", "Hound", "en")
        assert _plain(om)["prefLabel"] == []
        assert [i["value"] for i in _xl(om)["prefLabel"]] == ["Hound"]

    def test_an_xl_pref_label_replaces_another_xl_one(self, om):
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.add_xl_label("Dog", "prefLabel", "Hound", "en")
        assert [i["value"] for i in _xl(om)["prefLabel"]] == ["Hound"]
        assert (None, SKOSXL.literalForm, Literal("Dog", lang="en")) not in om.graph
        assert len(list(om.graph.subjects(RDF.type, SKOSXL.Label))) == 1

    def test_a_plain_pref_label_replaces_an_xl_one(self, om):
        old = om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.set_concept_label("Dog", "prefLabel", "Hound", "en")
        assert _xl(om)["prefLabel"] == []
        assert (URIRef(old), None, None) not in om.graph

    def test_the_same_text_in_both_forms_is_one_label_and_stays(self, om):
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        assert [i["value"] for i in _xl(om)["prefLabel"]] == ["Dog"]
        assert [i["value"] for i in _plain(om)["prefLabel"]] == ["Dog"]

    def test_other_languages_are_left_alone(self, om):
        om.add_xl_label("Dog", "prefLabel", "Hund", "de")
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        assert sorted(i["value"] for i in _xl(om)["prefLabel"]) == ["Dog", "Hund"]

    def test_alt_labels_are_repeatable(self, om):
        om.add_xl_label("Dog", "altLabel", "Hound", "en")
        om.add_xl_label("Dog", "altLabel", "Pooch", "en")
        assert len(_xl(om)["altLabel"]) == 2


class TestEditing:
    NOTE = Literal("Coined in 1990", lang="en")

    def test_the_text_changes_and_the_resource_stays(self, om):
        label = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        om.graph.add((URIRef(label), SKOS.note, self.NOTE))
        om.set_xl_label_text(label, "Hound dog", "en-GB")
        assert _xl(om)["altLabel"] == [
            {"value": "Hound dog", "lang": "en-GB", "label": label}
        ]
        assert (URIRef(label), SKOS.note, self.NOTE) in om.graph

    def test_editing_leaves_exactly_one_literal_form(self, om):
        """Which also repairs a label that broke S52 with two."""
        label = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        om.graph.add((URIRef(label), SKOSXL.literalForm, Literal("Hund", lang="de")))
        om.set_xl_label_text(label, "Hound", "en")
        assert len(list(om.graph.objects(URIRef(label), SKOSXL.literalForm))) == 1

    def test_an_edit_that_would_break_s14_is_refused(self, om):
        """An edit must not quietly delete another label to make room."""
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        german = om.add_xl_label("Dog", "prefLabel", "Hund", "de")
        with pytest.raises(ValueError, match="S14"):
            om.set_xl_label_text(german, "Doggy", "en")
        assert sorted(i["value"] for i in _xl(om)["prefLabel"]) == ["Dog", "Hund"]

    def test_moving_a_pref_label_onto_its_own_text_is_fine(self, om):
        label = om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        om.set_xl_label_text(label, "Dog", "en")
        assert [i["value"] for i in _xl(om)["prefLabel"]] == ["Dog"]

    @pytest.fixture
    def two_forms(self, om):
        """A label resource breaking S52 with two literal forms, as imported."""
        label = URIRef(om.add_xl_label("Dog", "altLabel", "Alias", "en"))
        om.graph.add((label, SKOSXL.literalForm, Literal("Anderer", lang="de")))
        return str(label)

    def test_replacing_changes_one_literal_form_and_keeps_the_rest(self, om, two_forms):
        """The editor edits one row; the other form must not vanish with it."""
        om.set_xl_label_text(two_forms, "Hound", "en", replacing=("Alias", "en"))
        assert set(om.graph.objects(URIRef(two_forms), SKOSXL.literalForm)) == {
            Literal("Hound", lang="en"),
            Literal("Anderer", lang="de"),
        }

    def test_replacing_a_form_the_label_does_not_have_is_refused(self, om, two_forms):
        with pytest.raises(ValueError, match="no literal form"):
            om.set_xl_label_text(two_forms, "Hound", "en", replacing=("Gone", "en"))

    def test_the_forms_a_label_keeps_count_for_s14(self, om):
        label = URIRef(om.add_xl_label("Dog", "prefLabel", "Dog", "en"))
        om.graph.add((label, SKOSXL.literalForm, Literal("Hund", lang="de")))
        with pytest.raises(ValueError, match="S14"):
            om.set_xl_label_text(str(label), "Doggy", "en", replacing=("Hund", "de"))

    def test_something_that_is_not_a_label_is_refused(self, om):
        with pytest.raises(ValueError, match="not a SKOS-XL label"):
            om.set_xl_label_text(BASE + "Dog", "Dog", "en")

    def test_an_empty_text_is_refused(self, om):
        label = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        with pytest.raises(ValueError):
            om.set_xl_label_text(label, "  ", "en")


class TestRemoving:
    def test_the_label_and_what_is_said_about_it_go(self, om):
        label = URIRef(om.add_xl_label("Dog", "altLabel", "Hound", "en"))
        om.graph.add((label, SKOS.note, Literal("Coined in 1990", lang="en")))
        other = URIRef(om.add_xl_label("Dog", "altLabel", "Pooch", "en"))
        om.graph.add((other, SKOSXL.labelRelation, label))
        assert om.remove_xl_label("Dog", str(label)) is True
        assert (label, None, None) not in om.graph
        assert (None, None, label) not in om.graph
        assert [i["value"] for i in _xl(om)["altLabel"]] == ["Pooch"]

    def test_a_label_another_concept_shares_stays_for_it(self, om):
        om.add_concept("Hound", scheme="S")
        label = URIRef(om.add_xl_label("Dog", "altLabel", "Hound", "en"))
        om.graph.add((_uri("Hound"), SKOSXL.prefLabel, label))
        om.remove_xl_label("Dog", str(label))
        assert (label, SKOSXL.literalForm, Literal("Hound", lang="en")) in om.graph
        assert _xl(om, "Hound")["prefLabel"][0]["label"] == str(label)

    def test_a_label_that_is_also_an_entity_is_only_unlinked(self, om):
        """S48 broken on import; deleting the label must not take the class."""
        om.add_class("Oddity")
        om.graph.add((_uri("Dog"), SKOSXL.altLabel, _uri("Oddity")))
        om.graph.add((_uri("Oddity"), SKOSXL.literalForm, Literal("Odd", lang="en")))
        om.remove_xl_label("Dog", BASE + "Oddity")
        assert "Oddity" in [c["name"] for c in om.get_classes()]

    def test_a_label_that_is_also_a_collection_is_only_unlinked(self, om):
        """skos:Collection is no entity kind of this app's, and a blank node
        has no name to check: neither may lose its own statements (review of
        #574)."""
        for node in (_uri("Pack"), BNode()):
            om.graph.add((node, RDF.type, SKOS.Collection))
            om.graph.add((node, SKOS.member, _uri("Dog")))
            om.graph.add((node, SKOSXL.literalForm, Literal("Pack", lang="en")))
            om.graph.add((_uri("Dog"), SKOSXL.altLabel, node))
            om.remove_xl_label("Dog", om._node_ref(node))
            assert (_uri("Dog"), SKOSXL.altLabel, node) not in om.graph
            assert (node, RDF.type, SKOS.Collection) in om.graph
            assert (node, SKOS.member, _uri("Dog")) in om.graph

    def test_a_label_linked_under_two_kinds_loses_only_the_one_asked_for(self, om):
        """An import can link one resource as altLabel and hiddenLabel (S58);
        deleting the altLabel row must leave the hiddenLabel."""
        label = om.add_xl_label("Dog", "altLabel", "Hound", "en")
        om.graph.add((_uri("Dog"), SKOSXL.hiddenLabel, URIRef(label)))
        assert om.remove_xl_label("Dog", label, "altLabel") is True
        assert _xl(om)["altLabel"] == []
        assert _xl(om)["hiddenLabel"][0]["label"] == label
        assert (URIRef(label), SKOSXL.literalForm, None) in om.graph

    def test_a_blank_node_label_is_addressable(self, om):
        """Imported vocabularies may give label resources no URI."""
        node = BNode()
        om.graph.add((_uri("Dog"), SKOSXL.altLabel, node))
        om.graph.add((node, RDF.type, SKOSXL.Label))
        om.graph.add((node, SKOSXL.literalForm, Literal("Hound", lang="en")))
        ref = _xl(om)["altLabel"][0]["label"]
        assert ref.startswith("_:")
        om.set_xl_label_text(ref, "Pooch", "en")
        assert _xl(om)["altLabel"][0]["value"] == "Pooch"
        assert om.remove_xl_label("Dog", ref) is True
        assert (node, None, None) not in om.graph

    def test_a_label_the_concept_does_not_have_is_not_removed(self, om):
        om.add_concept("Cat", scheme="S")
        label = om.add_xl_label("Cat", "altLabel", "Kitty", "en")
        assert om.remove_xl_label("Dog", label) is False
        assert (URIRef(label), SKOSXL.literalForm, None) in om.graph

    def test_deleting_the_concept_deletes_its_labels(self, om):
        label = URIRef(om.add_xl_label("Dog", "prefLabel", "Dog", "en"))
        om.delete_concept("Dog")
        assert (label, None, None) not in om.graph

    def test_deleting_a_concept_keeps_a_label_another_one_shares(self, om):
        om.add_concept("Hound", scheme="S")
        label = URIRef(om.add_xl_label("Dog", "altLabel", "Hound", "en"))
        om.graph.add((_uri("Hound"), SKOSXL.prefLabel, label))
        om.delete_concept("Dog")
        assert (label, SKOSXL.literalForm, None) in om.graph


class TestConverting:
    @pytest.fixture
    def plain(self, om):
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        om.set_concept_label("Dog", "prefLabel", "Hund", "de")
        om.set_concept_label("Dog", "altLabel", "Hound", "en")
        om.set_concept_label("Dog", "hiddenLabel", "dgo", "en")
        return om

    def test_plain_labels_become_skos_xl(self, plain):
        assert plain.convert_labels_to_xl() == 4
        assert all(not v for v in _plain(plain).values())
        assert sorted(i["value"] for i in _xl(plain)["prefLabel"]) == ["Dog", "Hund"]
        assert [i["value"] for i in _xl(plain)["altLabel"]] == ["Hound"]
        assert [i["value"] for i in _xl(plain)["hiddenLabel"]] == ["dgo"]

    def test_a_plain_copy_of_an_xl_label_is_folded_into_it(self, plain):
        label = plain.add_xl_label("Dog", "altLabel", "Hound", "en")
        plain.convert_labels_to_xl()
        assert _xl(plain)["altLabel"] == [
            {"value": "Hound", "lang": "en", "label": label}
        ]

    def test_skos_xl_labels_become_plain(self, plain):
        plain.convert_labels_to_xl()
        assert plain.convert_xl_labels_to_plain() == 4
        assert all(not v for v in _xl(plain).values())
        assert sorted(i["value"] for i in _plain(plain)["prefLabel"]) == ["Dog", "Hund"]
        assert not list(plain.graph.subjects(RDF.type, SKOSXL.Label))

    def test_keeping_the_skos_xl_labels_adds_plain_copies(self, plain):
        """The dumbed-down form for consumers that read plain SKOS only."""
        plain.convert_labels_to_xl()
        assert plain.convert_xl_labels_to_plain(keep_xl=True) == 4
        assert sum(len(v) for v in _xl(plain).values()) == 4
        assert sum(len(v) for v in _plain(plain).values()) == 4
        assert plain.convert_xl_labels_to_plain(keep_xl=True) == 0

    def test_a_label_without_one_literal_form_is_left_for_the_author(self, om):
        node = BNode()
        om.graph.add((_uri("Dog"), SKOSXL.prefLabel, node))
        om.graph.add((node, SKOSXL.literalForm, Literal("Dog", lang="en")))
        om.graph.add((node, SKOSXL.literalForm, Literal("Hound", lang="en")))
        assert om.convert_xl_labels_to_plain() == 0
        assert (_uri("Dog"), SKOSXL.prefLabel, node) in om.graph

    def test_round_trips_validate_clean(self, plain):
        assert plain.validate_skos() == []
        plain.convert_labels_to_xl()
        assert plain.validate_skos() == []
        plain.convert_xl_labels_to_plain(keep_xl=True)
        assert plain.validate_skos() == []
        plain.convert_xl_labels_to_plain()
        assert plain.validate_skos() == []


class TestWhichFormTheVocabularyUses:
    def test_a_plain_vocabulary_prefers_plain(self, om):
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        assert om.prefers_skos_xl() is False

    def test_an_xl_vocabulary_prefers_skos_xl(self, om):
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        assert om.prefers_skos_xl() is True

    def test_plain_copies_of_xl_labels_do_not_change_that(self, om):
        """As AGROVOC publishes: SKOS-XL labels and the plain ones they entail."""
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.convert_xl_labels_to_plain(keep_xl=True)
        assert om.prefers_skos_xl() is True

    def test_an_unlabelled_vocabulary_prefers_plain(self, om):
        assert om.prefers_skos_xl() is False

    def test_the_counts(self, om):
        om.add_concept("Cat", scheme="S")
        om.set_concept_label("Dog", "prefLabel", "Dog", "en")
        om.add_xl_label("Cat", "prefLabel", "Cat", "en")
        om.add_xl_label("Cat", "altLabel", "Kitty", "en")
        assert om.label_form_counts() == {
            "plain": 1,
            "xl": 2,
            "plain_concepts": 1,
            "xl_concepts": 1,
        }


class TestSearch:
    """A vocabulary labelled in SKOS-XL is found by its labels, not only by
    its local names."""

    def test_an_xl_pref_label_is_found(self, om):
        om.add_xl_label("Dog", "prefLabel", "Domestic dog", "en")
        hit = next(r for r in om.search("domestic") if r["name"] == "Dog")
        assert hit["match_field"] == "prefLabel"
        assert hit["label"] == "Domestic dog"

    def test_an_xl_alt_label_is_found(self, om):
        om.add_xl_label("Dog", "altLabel", "Pooch", "en")
        hit = next(r for r in om.search("pooch") if r["name"] == "Dog")
        assert hit["match_field"] == "altLabel"

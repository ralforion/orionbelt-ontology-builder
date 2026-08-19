"""Tests for the language-aware, multi-valued SKOS data model (WS-3).

The engine used to expose one untagged ``prefLabel``, one ``definition`` and
one ``broader`` per concept. These cover what it exposes now: labels and notes
per language, notation, top concepts, mappings to external vocabularies, and
the write-time refusals that keep the hierarchy acyclic.
"""

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import SKOS

from ontology_manager import OntologyManager

WIKIDATA_DOG = "http://www.wikidata.org/entity/Q144"


@pytest.fixture
def om():
    return OntologyManager(base_uri="http://test.org/ont#")


@pytest.fixture
def dogs(om):
    """One concept in one scheme, to hang label/note tests off."""
    om.add_concept_scheme("Animals")
    om.add_concept("Dogs", scheme="Animals")
    return om


def _concept(om, name):
    return next(c for c in om.get_concepts() if c["name"] == name)


class TestLabels:
    def test_pref_labels_per_language(self, dogs):
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en")
        dogs.set_concept_label("Dogs", "prefLabel", "Hunde", lang="de")
        assert _concept(dogs, "Dogs")["labels"]["prefLabel"] == [
            {"value": "Hunde", "lang": "de"},
            {"value": "Dogs", "lang": "en"},
        ]

    def test_pref_label_replaces_same_language(self, dogs):
        """SKOS Reference S14: at most one prefLabel per language tag."""
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en")
        dogs.set_concept_label("Dogs", "prefLabel", "Doggos", lang="en")
        dogs.set_concept_label("Dogs", "prefLabel", "Hunde", lang="de")
        pref = _concept(dogs, "Dogs")["labels"]["prefLabel"]
        assert [v["value"] for v in pref] == ["Hunde", "Doggos"]

    def test_untagged_pref_label_is_its_own_slot(self, dogs):
        """An untagged label does not collide with a tagged one."""
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs")
        dogs.set_concept_label("Dogs", "prefLabel", "Hunde", lang="de")
        assert len(_concept(dogs, "Dogs")["labels"]["prefLabel"]) == 2

    @pytest.mark.parametrize("kind", ["altLabel", "hiddenLabel"])
    def test_alt_and_hidden_are_repeatable(self, dogs, kind):
        dogs.set_concept_label("Dogs", kind, "Canines", lang="en")
        dogs.set_concept_label("Dogs", kind, "Doggies", lang="en")
        assert len(_concept(dogs, "Dogs")["labels"][kind]) == 2

    def test_remove_label(self, dogs):
        dogs.set_concept_label("Dogs", "altLabel", "Canines", lang="en")
        assert dogs.remove_concept_label("Dogs", "altLabel", "Canines", lang="en")
        assert _concept(dogs, "Dogs")["labels"]["altLabel"] == []

    def test_remove_label_matches_language_too(self, dogs):
        """Same text, different tag, is a different literal."""
        dogs.set_concept_label("Dogs", "altLabel", "Hunde", lang="de")
        assert not dogs.remove_concept_label("Dogs", "altLabel", "Hunde", lang="en")
        assert len(_concept(dogs, "Dogs")["labels"]["altLabel"]) == 1

    def test_blank_label_refused(self, dogs):
        with pytest.raises(ValueError, match="cannot be empty"):
            dogs.set_concept_label("Dogs", "prefLabel", "   ", lang="en")

    def test_malformed_language_tag_refused(self, dogs):
        with pytest.raises(ValueError):
            dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en_GB")

    def test_unknown_kind_names_the_alternatives(self, dogs):
        with pytest.raises(ValueError, match="prefLabel"):
            dogs.set_concept_label("Dogs", "notALabel", "x")


class TestNotes:
    def test_notes_are_repeatable_and_tagged(self, dogs):
        dogs.set_concept_note("Dogs", "scopeNote", "Domestic only", lang="en")
        dogs.set_concept_note("Dogs", "scopeNote", "Nur Haushunde", lang="de")
        assert len(_concept(dogs, "Dogs")["notes"]["scopeNote"]) == 2

    def test_all_documentation_kinds_available(self, dogs):
        for kind in OntologyManager.SKOS_NOTE_KINDS:
            dogs.set_concept_note("Dogs", kind, f"a {kind}", lang="en")
        notes = _concept(dogs, "Dogs")["notes"]
        assert all(notes[kind] for kind in OntologyManager.SKOS_NOTE_KINDS)

    def test_remove_note(self, dogs):
        dogs.set_concept_note("Dogs", "definition", "A dog", lang="en")
        assert dogs.remove_concept_note("Dogs", "definition", "A dog", lang="en")
        assert _concept(dogs, "Dogs")["notes"]["definition"] == []


class TestNotation:
    def test_set_and_replace(self, dogs):
        dogs.set_concept_notation("Dogs", "636.7")
        assert _concept(dogs, "Dogs")["notation"] == "636.7"
        dogs.set_concept_notation("Dogs", "636.8")
        assert _concept(dogs, "Dogs")["notation"] == "636.8"

    def test_empty_value_clears(self, dogs):
        dogs.set_concept_notation("Dogs", "636.7")
        dogs.set_concept_notation("Dogs", "")
        assert _concept(dogs, "Dogs")["notation"] == ""

    def test_notation_carries_a_datatype_never_a_language(self, dogs):
        """A notation is a code in a symbol scheme, not text in a language."""
        dogs.set_concept_notation("Dogs", "636.7", datatype="http://example.org/ddc")
        value = dogs.graph.value(URIRef("http://test.org/ont#Dogs"), SKOS.notation)
        assert isinstance(value, Literal)
        assert value.language is None
        assert str(value.datatype) == "http://example.org/ddc"


class TestTopConcepts:
    def test_writes_both_directions(self, dogs):
        dogs.set_top_concept("Dogs", "Animals")
        concept = URIRef("http://test.org/ont#Dogs")
        scheme = URIRef("http://test.org/ont#Animals")
        assert (concept, SKOS.topConceptOf, scheme) in dogs.graph
        assert (scheme, SKOS.hasTopConcept, concept) in dogs.graph
        assert _concept(dogs, "Dogs")["top_of"] == ["Animals"]

    def test_top_concept_is_in_its_scheme(self, om):
        om.add_concept_scheme("Animals")
        om.add_concept("Dogs")
        om.set_top_concept("Dogs", "Animals")
        assert "Animals" in _concept(om, "Dogs")["schemes"]

    def test_retract_removes_both_directions(self, dogs):
        dogs.set_top_concept("Dogs", "Animals")
        dogs.set_top_concept("Dogs", "Animals", is_top=False)
        concept = URIRef("http://test.org/ont#Dogs")
        scheme = URIRef("http://test.org/ont#Animals")
        assert (concept, SKOS.topConceptOf, scheme) not in dogs.graph
        assert (scheme, SKOS.hasTopConcept, concept) not in dogs.graph


class TestMappings:
    def test_map_to_an_external_uri(self, dogs):
        dogs.add_concept_mapping("Dogs", "exactMatch", WIKIDATA_DOG)
        assert _concept(dogs, "Dogs")["mappings"]["exactMatch"] == [WIKIDATA_DOG]

    def test_target_must_be_absolute(self, dogs):
        with pytest.raises(ValueError, match="absolute IRI"):
            dogs.add_concept_mapping("Dogs", "exactMatch", "Cats")

    def test_non_http_schemes_accepted(self, dogs):
        dogs.add_concept_mapping("Dogs", "closeMatch", "urn:example:dog")
        assert _concept(dogs, "Dogs")["mappings"]["closeMatch"] == ["urn:example:dog"]

    def test_semantic_relations_refused_here(self, dogs):
        with pytest.raises(ValueError, match="mapping property"):
            dogs.add_concept_mapping("Dogs", "broader", WIKIDATA_DOG)

    def test_target_that_cannot_be_serialised_is_refused(self, dogs):
        """A scheme is not enough: rdflib stores any string and only objects
        when asked to serialize, so this would break every later export."""
        with pytest.raises(ValueError, match="no spaces"):
            dogs.add_concept_mapping(
                "Dogs", "exactMatch", "http://example.org/bad path"
            )

    def test_an_accepted_target_still_serialises(self, dogs):
        dogs.add_concept_mapping("Dogs", "exactMatch", WIKIDATA_DOG)
        assert "Q144" in dogs.graph.serialize(format="turtle")


class TestRemoveRelation:
    def test_removes_the_auto_added_inverse(self, om):
        om.add_concept("Animal")
        om.add_concept("Dog")
        om.add_concept_relation("Dog", "broader", "Animal")
        assert om.remove_concept_relation("Dog", "broader", "Animal")
        assert _concept(om, "Dog")["broader"] == []
        assert _concept(om, "Animal")["narrower"] == []

    def test_removes_the_symmetric_triple(self, om):
        om.add_concept("Cat")
        om.add_concept("Dog")
        om.add_concept_relation("Dog", "related", "Cat")
        om.remove_concept_relation("Dog", "related", "Cat")
        assert _concept(om, "Cat")["related"] == []

    def test_reports_when_nothing_was_there(self, om):
        om.add_concept("Dog")
        om.add_concept("Cat")
        assert not om.remove_concept_relation("Dog", "related", "Cat")


class TestCycleGuard:
    @pytest.fixture
    def chain(self, om):
        for name in ("Animal", "Mammal", "Dog"):
            om.add_concept(name)
        om.add_concept_relation("Mammal", "broader", "Animal")
        om.add_concept_relation("Dog", "broader", "Mammal")
        return om

    def test_transitive_cycle_refused(self, chain):
        with pytest.raises(ValueError, match="cycle"):
            chain.add_concept_relation("Animal", "broader", "Dog")

    def test_narrower_direction_refused_too(self, chain):
        with pytest.raises(ValueError, match="cycle"):
            chain.add_concept_relation("Dog", "narrower", "Animal")

    def test_self_relation_refused(self, chain):
        with pytest.raises(ValueError, match="its own broader"):
            chain.add_concept_relation("Dog", "broader", "Dog")

    def test_self_related_refused(self, chain):
        with pytest.raises(ValueError, match="its own"):
            chain.add_concept_relation("Dog", "related", "Dog")

    def test_update_concept_refuses_too(self, chain):
        with pytest.raises(ValueError, match="cycle"):
            chain.update_concept("Animal", new_broader="Dog")

    def test_refusal_leaves_the_hierarchy_untouched(self, chain):
        """A rejected re-parent must not orphan the concept it refused.

        ``update_concept`` drops the old broader before adding the new one, so
        the guard has to run first or a refused edit costs the user the parent
        they already had.
        """
        with pytest.raises(ValueError):
            chain.update_concept("Mammal", new_broader="Dog")
        assert _concept(chain, "Mammal")["broader"] == ["Animal"]
        assert _concept(chain, "Animal")["narrower"] == ["Mammal"]

    def test_replacing_broader_is_all_or_nothing(self, chain):
        """A refused re-parent must not also drop the parent that was there.

        ``set_concept_broader`` removes the old parents before adding the new
        ones, which is what lets a concept move under a former descendant. A
        refusal partway through would otherwise reject the edit *and* leave the
        concept with no parent at all.
        """
        with pytest.raises(ValueError, match="cycle"):
            chain.set_concept_broader("Mammal", ["Dog"])
        assert _concept(chain, "Mammal")["broader"] == ["Animal"]
        assert _concept(chain, "Animal")["narrower"] == ["Mammal"]
        assert _concept(chain, "Dog")["broader"] == ["Mammal"]

    def test_replacing_broader_allows_a_legal_swap(self, chain):
        chain.add_concept("Pet")
        chain.set_concept_broader("Dog", ["Pet"])
        assert _concept(chain, "Dog")["broader"] == ["Pet"]
        assert _concept(chain, "Mammal")["narrower"] == []

    def test_replacing_broader_sets_several(self, chain):
        chain.add_concept("Pet")
        chain.set_concept_broader("Dog", ["Mammal", "Pet"])
        assert sorted(_concept(chain, "Dog")["broader"]) == ["Mammal", "Pet"]

    def test_replacing_broader_with_nothing_clears_it(self, chain):
        chain.set_concept_broader("Dog", [])
        assert _concept(chain, "Dog")["broader"] == []
        assert _concept(chain, "Mammal")["narrower"] == []

    def test_poly_hierarchy_is_allowed(self, om):
        for name in ("Animal", "Pet", "Dog"):
            om.add_concept(name)
        om.add_concept_relation("Dog", "broader", "Animal")
        om.add_concept_relation("Dog", "broader", "Pet")
        assert sorted(_concept(om, "Dog")["broader"]) == ["Animal", "Pet"]


class TestBackwardCompatibility:
    def test_flat_keys_are_computed_from_the_structured_ones(self, dogs):
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en")
        dogs.set_concept_label("Dogs", "altLabel", "Canines", lang="en")
        dogs.set_concept_note("Dogs", "definition", "A dog", lang="en")
        concept = _concept(dogs, "Dogs")
        assert concept["prefLabel"] == "Dogs"
        assert concept["definition"] == "A dog"
        assert concept["altLabels"] == ["Canines"]

    def test_flat_pref_label_is_deterministic(self, dogs):
        """Untagged wins; otherwise the first tag alphabetically."""
        dogs.set_concept_label("Dogs", "prefLabel", "Hunde", lang="de")
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en")
        assert _concept(dogs, "Dogs")["prefLabel"] == "Hunde"
        dogs.set_concept_label("Dogs", "prefLabel", "Untagged")
        assert _concept(dogs, "Dogs")["prefLabel"] == "Untagged"


class TestRoundTrip:
    def test_serialises_and_reparses_identically(self, dogs):
        """Correctness here is defined by an external parser, not by us."""
        dogs.set_concept_label("Dogs", "prefLabel", "Dogs", lang="en")
        dogs.set_concept_label("Dogs", "prefLabel", "Hunde", lang="de")
        dogs.set_concept_label("Dogs", "altLabel", "Canines", lang="en")
        dogs.set_concept_label("Dogs", "hiddenLabel", "dogz", lang="en")
        dogs.set_concept_note("Dogs", "scopeNote", "Domestic only", lang="en")
        dogs.set_concept_notation("Dogs", "636.7")
        dogs.set_top_concept("Dogs", "Animals")
        dogs.add_concept_mapping("Dogs", "exactMatch", WIKIDATA_DOG)

        reparsed = Graph().parse(
            data=dogs.graph.serialize(format="turtle"), format="turtle"
        )
        assert set(reparsed) == set(dogs.graph)

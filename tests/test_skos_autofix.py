"""Tests for `autofix_skos` (WS-2).

Fixtures write triples directly rather than going through the API. The API
refuses several of the things a fixer exists to repair (it will not create a
cycle, a self-relation or an untagged label where one already has a tag), so a
fixture built through it could not reach the cases at all. This is also the
shape a broken vocabulary actually arrives in: an imported file.

The two tests that matter most are parametrized over every fixable type:
a fixer must clear its own check, and must not introduce a different one.
A wrong report is a nuisance; a wrong repair is written into the user's graph.
"""

import pathlib

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, SKOS, XSD

from ontology_manager import SKOSXL, OntologyManager

BASE = "http://test.org/ont#"
FIXABLE = sorted(OntologyManager.SKOS_AUTOFIXES)


def _uri(name):
    return URIRef(BASE + name)


def _concept(om, name, *, labelled=True, documented=True):
    uri = _uri(name)
    om.graph.add((uri, RDF.type, SKOS.Concept))
    om.graph.add((uri, SKOS.inScheme, _uri("S")))
    if labelled:
        om.graph.add((uri, SKOS.prefLabel, Literal(name, lang="en")))
    if documented:
        om.graph.add((uri, SKOS.definition, Literal("A definition", lang="en")))
    return uri


@pytest.fixture
def broken():
    """One vocabulary tripping every fixable check at once.

    Deliberately not one fixture per fixer: running a fixer against a graph
    that has other problems too is the real case, and it is how a fixer that
    reaches too far shows up.
    """
    om = OntologyManager(base_uri=BASE)
    om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
    animal = _concept(om, "Animal")
    mammal = _concept(om, "Mammal")
    dog = _concept(om, "Dog")
    pet = _concept(om, "Pet")

    om.graph.add((mammal, SKOS.broader, animal))
    om.graph.add((dog, SKOS.broader, mammal))
    om.graph.add((dog, SKOS.broader, animal))  # hierarchy_redundancy
    om.graph.add((pet, SKOS.broader, animal))
    om.graph.add((animal, SKOS.broader, _uri("Ghost")))  # dangling_relation
    om.graph.add((pet, SKOS.related, pet))  # self_relation
    om.graph.add((dog, SKOS.altLabel, Literal("Dog", lang="en")))  # label_overlap
    om.graph.add((pet, SKOS.altLabel, Literal("Untagged")))  # missing_lang
    om.graph.add((mammal, SKOS.topConceptOf, _uri("S")))  # top_with_broader
    om.graph.add((_uri("S"), SKOS.hasTopConcept, mammal))
    om.graph.add((animal, SKOS.topConceptOf, _uri("S")))
    return om


@pytest.fixture
def awkward():
    """The shapes the first fixture could not reach.

    Typed literals, a re-tag that would break S14, an untagged label whose text
    already belongs to another kind, and a SKOS-XL label. Every one of these
    slipped past the property tests below while `broken` was their only input,
    which is the argument for having two.
    """
    om = OntologyManager(base_uri=BASE)
    om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))

    # A typed label reads as untagged and must still be replaced, not duplicated.
    typed = _concept(om, "Typed", labelled=False)
    om.graph.add((typed, SKOS.prefLabel, Literal("Typed", datatype=XSD.string)))
    om.graph.add((typed, SKOS.altLabel, Literal("Typed", datatype=XSD.string)))

    # Re-tagging this to en would put two prefLabels in one language.
    clash = _concept(om, "Clash")
    om.graph.add((clash, SKOS.prefLabel, Literal("Hund")))

    # Re-tagging this to en would collide with its own prefLabel.
    overlap = _concept(om, "Overlap")
    om.graph.add((overlap, SKOS.altLabel, Literal("Overlap")))

    # A SKOS-XL label, which no fixer may touch.
    xl_concept = _concept(om, "Xl", labelled=False)
    label = _uri("xl_label")
    om.graph.add((label, RDF.type, SKOSXL.Label))
    om.graph.add((label, SKOSXL.literalForm, Literal("Untagged")))
    om.graph.add((xl_concept, SKOSXL.prefLabel, label))

    for name in ("Typed", "Clash", "Overlap", "Xl"):
        om.graph.add((_uri(name), SKOS.topConceptOf, _uri("S")))
        om.graph.add((_uri("S"), SKOS.hasTopConcept, _uri(name)))
    return om


def _fix(om, kind):
    """Run one fixer, supplying the language the tag fixer needs."""
    if kind == "missing_lang":
        return om.autofix_skos(kind, lang="en")
    return om.autofix_skos(kind)


def _counts(om):
    counts: dict[str, int] = {}
    for issue in om.validate_skos():
        counts[issue["type"]] = counts.get(issue["type"], 0) + 1
    return counts


class TestEveryFixerAgreesWithItsCheck:
    @pytest.mark.parametrize("kind", FIXABLE)
    def test_the_check_stops_reporting(self, broken, kind):
        """The invariant the whole workstream rests on."""
        if kind == "broader_cycle":
            broken.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        assert _counts(broken).get(kind), f"fixture does not trip {kind}"
        _fix(broken, kind)
        assert kind not in _counts(broken)

    @pytest.mark.parametrize("fixture", ["broken", "awkward"])
    @pytest.mark.parametrize("kind", FIXABLE)
    def test_no_other_class_of_issue_appears(self, request, fixture, kind):
        """A repair that trades one problem for another is not a repair.

        Run over both fixtures: this property held on `broken` alone while the
        fixers were still creating S14 violations out of untagged labels,
        because that fixture had no concept where a re-tag could collide.
        """
        om = request.getfixturevalue(fixture)
        if kind == "broader_cycle" and fixture == "broken":
            om.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        before = _counts(om)
        _fix(om, kind)
        after = _counts(om)
        introduced = {k: after[k] for k in after if after[k] > before.get(k, 0)}
        assert not introduced, f"{kind} introduced {introduced} on {fixture}"

    @pytest.mark.parametrize("fixture", ["broken", "awkward"])
    @pytest.mark.parametrize("kind", FIXABLE)
    def test_a_fixer_never_claims_more_than_it_did(self, request, fixture, kind):
        """A count above zero has to mean the check reports fewer afterwards."""
        om = request.getfixturevalue(fixture)
        if kind == "broader_cycle" and fixture == "broken":
            om.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        before = _counts(om).get(kind, 0)
        if _fix(om, kind):
            assert _counts(om).get(kind, 0) < before, (
                f"{kind} reported work but {before} issues remain on {fixture}"
            )

    @pytest.mark.parametrize("kind", FIXABLE)
    def test_running_it_twice_changes_nothing_the_second_time(self, broken, kind):
        if kind == "broader_cycle":
            broken.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        _fix(broken, kind)
        assert _fix(broken, kind) == 0

    @pytest.mark.parametrize("kind", FIXABLE)
    def test_it_reports_how_much_it_did(self, broken, kind):
        if kind == "broader_cycle":
            broken.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        assert _fix(broken, kind) > 0

    @pytest.mark.parametrize(
        "kind",
        [k for k in FIXABLE if k not in ("broader_cycle", "hierarchy_redundancy")],
    )
    def test_the_count_matches_what_was_reported(self, broken, kind):
        """So the panel's "Fix 3 issues" is followed by "Fixed 3".

        The two iterative fixers are excluded: removing one edge can clear
        several reported cycles, and can make a second redundant edge no longer
        redundant, so their count is what they removed rather than what was
        reported.
        """
        expected = _counts(broken).get(kind, 0)
        assert expected > 0, f"fixture does not trip {kind}"
        assert _fix(broken, kind) == expected


class TestInversesGoToo:
    """`add_concept_relation` writes both directions, so a fixer that removed
    one would leave a half-edge the UI cannot see or delete."""

    def test_self_relation(self, broken):
        broken.autofix_skos("self_relation")
        pet = _uri("Pet")
        assert (pet, SKOS.related, pet) not in broken.graph

    def test_dangling_relation_takes_the_inverse(self, om_with_dangling_pair):
        om = om_with_dangling_pair
        om.autofix_skos("dangling_relation")
        assert (_uri("Ghost"), SKOS.narrower, _uri("Animal")) not in om.graph

    def test_hierarchy_redundancy(self, broken):
        broken.autofix_skos("hierarchy_redundancy")
        assert (_uri("Animal"), SKOS.narrower, _uri("Dog")) not in broken.graph

    def test_broader_cycle(self, broken):
        broken.graph.add((_uri("Animal"), SKOS.broader, _uri("Dog")))
        broken.graph.add((_uri("Dog"), SKOS.narrower, _uri("Animal")))
        broken.autofix_skos("broader_cycle")
        assert not [i for i in broken.validate_skos() if i["type"] == "broader_cycle"]


@pytest.fixture
def om_with_dangling_pair():
    om = OntologyManager(base_uri=BASE)
    om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
    animal = _concept(om, "Animal")
    om.graph.add((animal, SKOS.broader, _uri("Ghost")))
    om.graph.add((_uri("Ghost"), SKOS.narrower, animal))
    return om


class TestSkosXlIsNeverTouched:
    """This app writes plain SKOS. Repairing a SKOS-XL label would mean editing
    a label resource it cannot author, so those issues are left alone."""

    @pytest.fixture
    def xl(self):
        om = OntologyManager(base_uri=BASE)
        om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
        concept = _concept(om, "A", labelled=False)
        label = _uri("lbl")
        om.graph.add((label, RDF.type, SKOSXL.Label))
        om.graph.add((label, SKOSXL.literalForm, Literal("Untagged")))
        om.graph.add((concept, SKOSXL.prefLabel, label))
        return om

    def test_an_untagged_xl_label_is_left_alone(self, xl):
        assert xl.autofix_skos("missing_lang", lang="en") == 0
        assert (_uri("lbl"), SKOSXL.literalForm, Literal("Untagged")) in xl.graph

    def test_a_clash_involving_an_xl_label_is_left_alone(self, xl):
        """Which spelling the author meant to keep is not ours to guess."""
        xl.graph.add((_uri("A"), SKOS.altLabel, Literal("Untagged", lang="en")))
        before = len(xl.graph)
        assert xl.autofix_skos("label_overlap") == 0
        assert len(xl.graph) == before


class TestLiteralIdentity:
    """A label's datatype is part of the node, so a rebuilt literal misses it.

    `_tagged_literals` reports a label as (value, language), which is all the
    checks need. A fixer that turned that back into `Literal(value)` did not
    match `"Dog"^^xsd:string` in the graph: the old literal survived, a tagged
    one was added beside it, and the fixer reported success. Removals go through
    `remove_concept_label`, which matches the node that is actually there.
    """

    @pytest.fixture
    def typed(self):
        om = OntologyManager(base_uri=BASE)
        om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
        _concept(om, "A", labelled=False)
        return om

    def test_a_typed_label_is_replaced_not_duplicated(self, typed):
        typed.graph.add(
            (_uri("A"), SKOS.prefLabel, Literal("Dog", datatype=XSD.string))
        )
        assert typed.autofix_skos("missing_lang", lang="en") == 1
        labels = list(typed.graph.objects(_uri("A"), SKOS.prefLabel))
        assert len(labels) == 1
        assert labels[0].language == "en"

    def test_a_typed_label_clash_is_really_removed(self, typed):
        for prop in (SKOS.prefLabel, SKOS.altLabel):
            typed.graph.add((_uri("A"), prop, Literal("Dog", datatype=XSD.string)))
        assert typed.autofix_skos("label_overlap") == 1
        assert not [i for i in typed.validate_skos() if i["type"] == "label_overlap"]


class TestARetagThatWouldBreakSomethingElseIsRefused:
    """The fixer would rather leave a warning than create an error."""

    @pytest.fixture
    def om(self):
        manager = OntologyManager(base_uri=BASE)
        manager.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
        _concept(manager, "A", labelled=False)
        return manager

    def test_a_second_pref_label_in_one_language_is_not_created(self, om):
        om.graph.add((_uri("A"), SKOS.prefLabel, Literal("Dog", lang="en")))
        om.graph.add((_uri("A"), SKOS.prefLabel, Literal("Hund")))
        assert om.autofix_skos("missing_lang", lang="en") == 0
        assert "multi_prefLabel_per_lang" not in [i["type"] for i in om.validate_skos()]

    def test_an_overlap_is_not_created(self, om):
        om.graph.add((_uri("A"), SKOS.prefLabel, Literal("Dog", lang="en")))
        om.graph.add((_uri("A"), SKOS.altLabel, Literal("Dog")))
        assert om.autofix_skos("missing_lang", lang="en") == 0
        assert "label_overlap" not in [i["type"] for i in om.validate_skos()]

    def test_a_re_tag_with_no_collision_still_happens(self, om):
        om.graph.add((_uri("A"), SKOS.prefLabel, Literal("Dog", lang="en")))
        om.graph.add((_uri("A"), SKOS.altLabel, Literal("Hound")))
        assert om.autofix_skos("missing_lang", lang="en") == 1


class TestLabelOverlapKeepsTheMoreVisibleLabel:
    @pytest.fixture
    def om(self):
        manager = OntologyManager(base_uri=BASE)
        manager.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
        _concept(manager, "A", labelled=False)
        return manager

    def test_pref_label_survives_alt_label(self, om):
        for prop in (SKOS.prefLabel, SKOS.altLabel):
            om.graph.add((_uri("A"), prop, Literal("Same", lang="en")))
        om.autofix_skos("label_overlap")
        assert (_uri("A"), SKOS.prefLabel, Literal("Same", lang="en")) in om.graph
        assert (_uri("A"), SKOS.altLabel, Literal("Same", lang="en")) not in om.graph

    def test_alt_label_survives_hidden_label(self, om):
        for prop in (SKOS.altLabel, SKOS.hiddenLabel):
            om.graph.add((_uri("A"), prop, Literal("Same", lang="en")))
        om.autofix_skos("label_overlap")
        assert (_uri("A"), SKOS.altLabel, Literal("Same", lang="en")) in om.graph
        assert (_uri("A"), SKOS.hiddenLabel, Literal("Same", lang="en")) not in om.graph

    def test_a_literal_in_all_three_leaves_only_the_pref_label(self, om):
        for prop in (SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel):
            om.graph.add((_uri("A"), prop, Literal("Same", lang="en")))
        # One issue, not two: the check reports the literal once.
        assert om.autofix_skos("label_overlap") == 1
        assert (_uri("A"), SKOS.prefLabel, Literal("Same", lang="en")) in om.graph


class TestHierarchyRedundancyDoesNotDetach:
    def test_two_mutually_implying_edges_lose_only_one(self):
        """Recomputing between removals is what keeps a concept attached."""
        om = OntologyManager(base_uri=BASE)
        om.graph.add((_uri("S"), RDF.type, SKOS.ConceptScheme))
        for name in ("Animal", "Mammal", "Dog"):
            _concept(om, name)
        om.graph.add((_uri("Mammal"), SKOS.broader, _uri("Animal")))
        om.graph.add((_uri("Dog"), SKOS.broader, _uri("Mammal")))
        om.graph.add((_uri("Dog"), SKOS.broader, _uri("Animal")))

        om.autofix_skos("hierarchy_redundancy")
        dog = next(c for c in om.get_concepts() if c["name"] == "Dog")
        assert dog["broader"] == ["Mammal"]


class TestMissingLang:
    def test_a_language_is_required(self, broken):
        with pytest.raises(ValueError, match="language tag is required"):
            broken.autofix_skos("missing_lang")

    def test_a_malformed_tag_is_refused(self, broken):
        with pytest.raises(ValueError):
            broken.autofix_skos("missing_lang", lang="en_GB")

    def test_already_tagged_labels_are_untouched(self, broken):
        broken.autofix_skos("missing_lang", lang="de")
        assert (_uri("Dog"), SKOS.prefLabel, Literal("Dog", lang="en")) in broken.graph

    def test_the_tag_is_applied(self, broken):
        broken.autofix_skos("missing_lang", lang="de")
        assert (
            _uri("Pet"),
            SKOS.altLabel,
            Literal("Untagged", lang="de"),
        ) in broken.graph
        assert (_uri("Pet"), SKOS.altLabel, Literal("Untagged")) not in broken.graph


class TestTheCatalogue:
    def test_every_fixable_type_is_a_real_check(self):
        unknown = set(OntologyManager.SKOS_AUTOFIXES) - set(OntologyManager.SKOS_CHECKS)
        assert not unknown, f"not a check type: {sorted(unknown)}"

    def test_an_unknown_fix_names_the_alternatives(self, broken):
        with pytest.raises(ValueError, match="fixable:"):
            broken.autofix_skos("not_a_fix")

    def test_a_check_that_is_not_fixable_is_refused(self, broken):
        """`undocumented` needs an author, not an algorithm."""
        with pytest.raises(ValueError, match="No autofix"):
            broken.autofix_skos("undocumented")

    def test_the_readme_documents_every_fix(self):
        """Same guard as the check table: naming it is not documenting it."""
        readme = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        stale = [
            kind
            for kind, summary in OntologyManager.SKOS_AUTOFIXES.items()
            if f"`{kind}`" not in readme or " ".join(summary.split()) not in readme
        ]
        assert not stale, f"README.md does not match SKOS_AUTOFIXES for: {stale}"

    def test_the_readme_states_the_right_number_of_fixes(self):
        """A count in prose drifts the moment a fixer is added."""
        readme = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        expected = f"{len(OntologyManager.SKOS_AUTOFIXES)} of the checks"
        assert expected in readme, f"README.md should say {expected!r}"

    def test_every_entry_describes_itself(self):
        for kind, summary in OntologyManager.SKOS_AUTOFIXES.items():
            assert summary.endswith("."), kind
            assert len(summary) > 20, kind

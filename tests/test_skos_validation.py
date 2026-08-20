"""One test per SKOS validation check (WS-1).

`validate_skos` used to check five things. These cover what it checks now, one
fixture per `type` code, plus the tier gating and the shape of an issue.

Each test asserts on the `type` rather than the message, so wording can change
without churning the suite, and every fixture is built to trip exactly one
check: a fixture that trips two makes it impossible to tell which one broke.
"""

import ast
import pathlib

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, SKOS

from ontology_manager import SKOSXL, OntologyManager


@pytest.fixture
def om():
    return OntologyManager(base_uri="http://test.org/ont#")


@pytest.fixture
def vocab(om):
    """A documented two-concept vocabulary that reports nothing.

    Tests bend one thing about it and assert the one check that fires, so the
    starting point has to be genuinely silent.
    """
    om.add_concept_scheme("Scheme", label="Scheme")
    om.add_concept("Animal", scheme="Scheme")
    om.set_concept_label("Animal", "prefLabel", "Animal", lang="en")
    om.set_concept_note("Animal", "definition", "A living organism", lang="en")
    om.set_top_concept("Animal", "Scheme")
    om.add_concept("Dog", scheme="Scheme", broader="Animal")
    om.set_concept_label("Dog", "prefLabel", "Dog", lang="en")
    om.set_concept_note("Dog", "definition", "A domesticated canine", lang="en")
    return om


def _types(om, **kwargs):
    return [i["type"] for i in om.validate_skos(**kwargs)]


def _of_type(om, kind, **kwargs):
    return [i for i in om.validate_skos(**kwargs) if i["type"] == kind]


class TestBaseline:
    def test_the_fixture_is_silent(self, vocab):
        assert vocab.validate_skos() == []


class TestLabelChecks:
    def test_missing_pref_label(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        vocab.set_concept_note("Cat", "definition", "A feline", lang="en")
        assert "missing_prefLabel" in _types(vocab)

    def test_missing_pref_label_is_an_error(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        assert _of_type(vocab, "missing_prefLabel")[0]["severity"] == "error"

    def test_two_pref_labels_in_one_language(self, vocab):
        """S14 allows at most one per tag; only an import can produce two."""
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Dog"),
                SKOS.prefLabel,
                Literal("Hound", lang="en"),
            )
        )
        assert "multi_prefLabel_per_lang" in _types(vocab)

    def test_pref_labels_in_different_languages_are_fine(self, vocab):
        vocab.set_concept_label("Dog", "prefLabel", "Hund", lang="de")
        assert "multi_prefLabel_per_lang" not in _types(vocab)

    def test_empty_label(self, vocab):
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Dog"),
                SKOS.altLabel,
                Literal("   ", lang="en"),
            )
        )
        assert "empty_label" in _types(vocab)

    def test_missing_language_tag(self, vocab):
        vocab.set_concept_label("Dog", "altLabel", "Hound")
        assert "missing_lang" in _types(vocab)

    def test_a_malformed_tag_cannot_reach_the_graph(self, vocab):
        """Why there is no `bad_lang` check.

        rdflib validates the tag when the Literal is built, by the API and by
        the parser alike, so a malformed one never lands in the graph for a
        validator to find.
        """
        with pytest.raises(ValueError):
            Literal("Hound", lang="en_GB")

    def test_label_overlap_across_kinds(self, vocab):
        """S13: the three label properties are pairwise disjoint."""
        vocab.set_concept_label("Dog", "altLabel", "Dog", lang="en")
        assert "label_overlap" in _types(vocab)

    def test_notation_with_a_language_tag(self, vocab):
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Dog"),
                SKOS.notation,
                Literal("636.7", lang="en"),
            )
        )
        assert "notation_lang_tagged" in _types(vocab)

    def test_notation_with_a_datatype_is_fine(self, vocab):
        vocab.set_concept_notation("Dog", "636.7", datatype="http://example.org/ddc")
        assert "notation_lang_tagged" not in _types(vocab)


class TestRelationChecks:
    def test_self_relation(self, vocab):
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Dog"),
                SKOS.related,
                URIRef("http://test.org/ont#Dog"),
            )
        )
        assert "self_relation" in _types(vocab)

    def test_dangling_relation(self, vocab):
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Dog"),
                SKOS.related,
                URIRef("http://test.org/ont#Ghost"),
            )
        )
        assert "dangling_relation" in _types(vocab)

    def test_a_mapping_to_another_vocabulary_is_not_dangling(self, vocab):
        """Pointing outside the graph is what a mapping property is for."""
        vocab.add_concept_mapping(
            "Dog", "exactMatch", "http://www.wikidata.org/entity/Q144"
        )
        assert "dangling_relation" not in _types(vocab)

    def test_related_to_an_ancestor(self, vocab):
        """S27: skos:related is disjoint with skos:broaderTransitive."""
        vocab.add_concept_relation("Dog", "related", "Animal")
        assert "relation_clash" in _types(vocab)

    def test_related_to_an_unrelated_concept_is_fine(self, vocab):
        vocab.add_concept("Kennel", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Kennel", "prefLabel", "Kennel", lang="en")
        vocab.set_concept_note("Kennel", "definition", "A dog house", lang="en")
        assert "relation_clash" not in _types(vocab)


class TestHierarchyChecks:
    def test_redundant_broader(self, vocab):
        """A parent already reachable through another parent."""
        vocab.add_concept("Pet", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Pet", "prefLabel", "Pet", lang="en")
        vocab.set_concept_note("Pet", "definition", "A kept animal", lang="en")
        vocab.add_concept_relation(
            "Dog", "broader", "Pet"
        )  # Dog -> Animal and Dog -> Pet -> Animal
        assert "hierarchy_redundancy" in _types(vocab)

    def test_plain_poly_hierarchy_is_not_redundant(self, vocab):
        vocab.add_concept("Pet", scheme="Scheme")
        vocab.set_concept_label("Pet", "prefLabel", "Pet", lang="en")
        vocab.set_concept_note("Pet", "definition", "A kept animal", lang="en")
        vocab.set_top_concept("Pet", "Scheme")
        vocab.add_concept_relation("Dog", "broader", "Pet")
        assert "hierarchy_redundancy" not in _types(vocab)

    def test_orphan(self, vocab):
        vocab.add_concept("Loner", scheme="Scheme")
        vocab.set_concept_label("Loner", "prefLabel", "Loner", lang="en")
        vocab.set_concept_note("Loner", "definition", "Alone", lang="en")
        assert "orphan" in _types(vocab)

    def test_a_top_concept_is_not_an_orphan(self, vocab):
        vocab.add_concept("Plant", scheme="Scheme")
        vocab.set_concept_label("Plant", "prefLabel", "Plant", lang="en")
        vocab.set_concept_note("Plant", "definition", "A living organism", lang="en")
        vocab.set_top_concept("Plant", "Scheme")
        assert "orphan" not in _types(vocab)

    def test_top_concept_with_a_broader_in_the_same_scheme(self, vocab):
        vocab.set_top_concept("Dog", "Scheme")  # Dog already has broader Animal
        assert "top_with_broader" in _types(vocab)

    def test_top_concept_with_a_broader_in_another_scheme_is_fine(self, vocab):
        """Legitimate: a concept can head one scheme and sit under another."""
        vocab.add_concept_scheme("Other", label="Other")
        vocab.set_top_concept("Dog", "Other")
        assert "top_with_broader" not in _types(vocab)


class TestSchemeChecks:
    def test_concept_in_no_scheme(self, vocab):
        vocab.add_concept("Stray", broader="Animal")
        vocab.set_concept_label("Stray", "prefLabel", "Stray", lang="en")
        vocab.set_concept_note("Stray", "definition", "Unowned", lang="en")
        assert "no_scheme" in _types(vocab)

    def test_duplicate_pref_label_within_a_scheme(self, vocab):
        vocab.add_concept("Hound", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Hound", "prefLabel", "Dog", lang="en")
        vocab.set_concept_note("Hound", "definition", "A dog", lang="en")
        assert "duplicate_prefLabel" in _types(vocab)

    def test_the_same_pair_is_not_also_reported_vocabulary_wide(self, vocab):
        """Within-scheme and vocabulary-wide duplication are different problems;
        one pair should not produce both."""
        vocab.add_concept("Hound", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Hound", "prefLabel", "Dog", lang="en")
        vocab.set_concept_note("Hound", "definition", "A dog", lang="en")
        assert "ambiguous_prefLabel" not in _types(vocab)

    def test_ambiguous_pref_label_across_schemes(self, vocab):
        vocab.add_concept_scheme("Other", label="Other")
        vocab.add_concept("Hound", scheme="Other")
        vocab.set_concept_label("Hound", "prefLabel", "Dog", lang="en")
        vocab.set_concept_note("Hound", "definition", "A dog", lang="en")
        vocab.set_top_concept("Hound", "Other")
        assert "ambiguous_prefLabel" in _types(vocab)

    def test_mapping_between_two_concepts_of_one_scheme(self, vocab):
        vocab.add_concept_mapping("Dog", "exactMatch", "http://test.org/ont#Animal")
        assert "mapping_within_scheme" in _types(vocab)


class TestEditorialChecks:
    def test_undocumented(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Cat", "prefLabel", "Cat", lang="en")
        assert "undocumented" in _types(vocab)

    def test_a_scope_note_counts_as_documentation(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Cat", "prefLabel", "Cat", lang="en")
        vocab.set_concept_note("Cat", "scopeNote", "Domestic only", lang="en")
        assert "undocumented" not in _types(vocab)

    def test_valueless_association_between_siblings(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Cat", "prefLabel", "Cat", lang="en")
        vocab.set_concept_note("Cat", "definition", "A feline", lang="en")
        vocab.add_concept_relation("Dog", "related", "Cat")
        assert "valueless_association" in _types(vocab)

    def test_disconnected_cluster(self, vocab):
        for name in ("Rock", "Pebble"):
            vocab.add_concept(name, scheme="Scheme")
            vocab.set_concept_label(name, "prefLabel", name, lang="en")
            vocab.set_concept_note(name, "definition", "A mineral", lang="en")
        vocab.add_concept_relation("Pebble", "broader", "Rock")
        vocab.set_top_concept("Rock", "Scheme")
        found = _of_type(vocab, "disconnected_components")
        assert len(found) == 1
        assert "2 concepts" in found[0]["message"]

    def test_one_connected_vocabulary_reports_no_clusters(self, vocab):
        assert "disconnected_components" not in _types(vocab)


class TestCycles:
    def test_cycle_through_any_parent(self, vocab):
        vocab.add_concept("Pet", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Pet", "prefLabel", "Pet", lang="en")
        vocab.set_concept_note("Pet", "definition", "A kept animal", lang="en")
        vocab.graph.add(
            (
                URIRef("http://test.org/ont#Animal"),
                SKOS.broader,
                URIRef("http://test.org/ont#Pet"),
            )
        )
        assert "broader_cycle" in _types(vocab)


class TestTiers:
    def test_errors_always_run(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        types = _types(vocab, check_editorial=False, check_conventions=False)
        assert types == ["missing_prefLabel"]

    def test_conventions_can_be_switched_off(self, vocab):
        vocab.set_concept_label("Dog", "altLabel", "Hound")  # untagged
        assert "missing_lang" in _types(vocab)
        assert "missing_lang" not in _types(vocab, check_conventions=False)

    def test_editorial_can_be_switched_off(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme", broader="Animal")
        vocab.set_concept_label("Cat", "prefLabel", "Cat", lang="en")
        assert "undocumented" in _types(vocab)
        assert "undocumented" not in _types(vocab, check_editorial=False)


class TestIssueShape:
    def test_every_issue_carries_a_subject_uri(self, vocab):
        """The UI navigates by URI: a local name may name two concepts."""
        vocab.add_concept("Cat", scheme="Scheme")
        for issue in vocab.validate_skos():
            assert issue["subject_uri"].startswith("http")
            assert set(issue) == {
                "severity",
                "type",
                "subject",
                "subject_uri",
                "message",
            }

    def test_errors_sort_before_warnings_before_info(self, vocab):
        vocab.add_concept("Cat", scheme="Scheme")  # trips all three tiers
        severities = [i["severity"] for i in vocab.validate_skos()]
        assert severities == sorted(
            severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s]
        )


class TestOneDirectionalImports:
    """A published vocabulary asserts one side of an inverse, not both.

    SKOS declares broader/narrower inverses and related symmetric, but almost
    every real file carries only ``B skos:broader A``. Our own writes
    materialise both sides, so a validator that reads one direction works on a
    graph this app built and quietly fails on an imported one, which is the
    graph validation is actually for.
    """

    @staticmethod
    def _seed(om, *names, in_scheme=True):
        """Concepts written straight into the graph, no inverses materialised.

        ``in_scheme=False`` omits the skos:inScheme triple, for the tests about
        membership implied by a top-concept assertion: seeding it would mask
        the very thing they check.
        """
        base = "http://test.org/ont#"
        om.add_concept_scheme("S")
        for name in names:
            uri = URIRef(base + name)
            om.graph.add((uri, RDF.type, SKOS.Concept))
            if in_scheme:
                om.graph.add((uri, SKOS.inScheme, URIRef(base + "S")))
            om.graph.add((uri, SKOS.prefLabel, Literal(name, lang="en")))
            om.graph.add((uri, SKOS.definition, Literal("A definition", lang="en")))
        return base

    def test_a_parent_with_only_broader_asserted_is_not_an_orphan(self, om):
        base = self._seed(om, "Animal", "Dog")
        om.graph.add((URIRef(base + "Dog"), SKOS.broader, URIRef(base + "Animal")))
        assert "orphan" not in _types(om)

    def test_a_child_with_only_narrower_asserted_is_not_an_orphan(self, om):
        base = self._seed(om, "Animal", "Dog")
        om.graph.add((URIRef(base + "Animal"), SKOS.narrower, URIRef(base + "Dog")))
        assert "orphan" not in _types(om)

    def test_hierarchy_is_visible_through_a_narrower_only_import(self, om):
        """S27 has to see the hierarchy however it was asserted."""
        base = self._seed(om, "Animal", "Dog")
        om.graph.add((URIRef(base + "Animal"), SKOS.narrower, URIRef(base + "Dog")))
        om.graph.add((URIRef(base + "Dog"), SKOS.related, URIRef(base + "Animal")))
        assert "relation_clash" in _types(om)

    def test_a_cycle_asserted_only_as_narrower_is_found(self, om):
        base = self._seed(om, "A", "B")
        om.graph.add((URIRef(base + "A"), SKOS.narrower, URIRef(base + "B")))
        om.graph.add((URIRef(base + "B"), SKOS.narrower, URIRef(base + "A")))
        assert "broader_cycle" in _types(om)

    def test_a_scheme_side_top_concept_is_not_an_orphan(self, om):
        """``scheme skos:hasTopConcept concept`` with no concept-side triple."""
        base = self._seed(om, "Animal")
        om.graph.add((URIRef(base + "S"), SKOS.hasTopConcept, URIRef(base + "Animal")))
        assert "orphan" not in _types(om)

    def test_a_scheme_side_top_concept_is_in_that_scheme(self, om):
        """skos:topConceptOf is a sub-property of skos:inScheme."""
        base = self._seed(om, "Animal")
        om.graph.add((URIRef(base + "S"), SKOS.hasTopConcept, URIRef(base + "Animal")))
        assert "no_scheme" not in _types(om)
        concept = next(c for c in om.get_concepts() if c["name"] == "Animal")
        assert concept["top_of"] == ["S"]
        assert concept["schemes"] == ["S"]

    def test_a_scheme_side_top_concept_is_found_by_scheme_filter(self, om):
        base = self._seed(om, "Animal", in_scheme=False)
        om.graph.add((URIRef(base + "S"), SKOS.hasTopConcept, URIRef(base + "Animal")))
        assert [c["name"] for c in om.get_concepts(scheme=base + "S")] == ["Animal"]
        assert om.get_concept_schemes()[0]["concept_count"] == 1

    def test_membership_is_not_double_counted(self, om):
        """All three assertions at once still describe one membership."""
        base = self._seed(om, "Animal", in_scheme=False)
        for triple in (
            (URIRef(base + "S"), SKOS.hasTopConcept, URIRef(base + "Animal")),
            (URIRef(base + "Animal"), SKOS.topConceptOf, URIRef(base + "S")),
            (URIRef(base + "Animal"), SKOS.inScheme, URIRef(base + "S")),
        ):
            om.graph.add(triple)
        concept = next(c for c in om.get_concepts() if c["name"] == "Animal")
        assert concept["top_of"] == ["S"]
        assert concept["schemes"] == ["S"]
        assert om.get_concept_schemes()[0]["concept_count"] == 1

    def test_related_asserted_one_way_reaches_both_concepts(self, om):
        base = self._seed(om, "Cat", "Dog")
        om.graph.add((URIRef(base + "Cat"), SKOS.related, URIRef(base + "Dog")))
        assert "orphan" not in _types(om)


class TestLanguageIsPartOfLiteralIdentity:
    def test_same_text_in_different_languages_is_not_an_overlap(self, vocab):
        """S13 is about the same object, and a language tag is part of one."""
        vocab.set_concept_label("Dog", "altLabel", "Dog", lang="de")
        assert "label_overlap" not in _types(vocab)

    def test_same_text_in_the_same_language_still_is(self, vocab):
        vocab.set_concept_label("Dog", "altLabel", "Dog", lang="en")
        assert "label_overlap" in _types(vocab)

    def test_alt_and_hidden_clash_without_a_pref_label_involved(self, vocab):
        """S13 makes the three *pairwise* disjoint, not each disjoint from
        prefLabel: an altLabel matching a hiddenLabel is as much a clash."""
        vocab.set_concept_label("Dog", "altLabel", "Alias", lang="en")
        vocab.set_concept_label("Dog", "hiddenLabel", "Alias", lang="en")
        found = _of_type(vocab, "label_overlap")
        assert len(found) == 1
        assert "altLabel and hiddenLabel" in found[0]["message"]

    def test_one_literal_in_all_three_kinds_is_reported_once(self, vocab):
        vocab.set_concept_label("Dog", "prefLabel", "Alias", lang="en")
        vocab.set_concept_label("Dog", "altLabel", "Alias", lang="en")
        vocab.set_concept_label("Dog", "hiddenLabel", "Alias", lang="en")
        found = _of_type(vocab, "label_overlap")
        assert len(found) == 1
        assert "prefLabel and altLabel and hiddenLabel" in found[0]["message"]

    def test_alt_and_hidden_in_different_languages_do_not_clash(self, vocab):
        vocab.set_concept_label("Dog", "altLabel", "Alias", lang="en")
        vocab.set_concept_label("Dog", "hiddenLabel", "Alias", lang="de")
        assert "label_overlap" not in _types(vocab)


class TestEveryNotationIsChecked:
    def test_a_tagged_notation_alongside_a_typed_one(self, vocab):
        """``graph.value`` returns one arbitrary object, so this was a coin flip."""
        dog = URIRef("http://test.org/ont#Dog")
        vocab.graph.add(
            (
                dog,
                SKOS.notation,
                Literal("636.7", datatype=URIRef("http://example.org/ddc")),
            )
        )
        vocab.graph.add((dog, SKOS.notation, Literal("bad", lang="en")))
        assert "notation_lang_tagged" in _types(vocab)


class TestCheckCatalogue:
    """`SKOS_CHECKS` describes exactly the checks the validator can emit.

    Read out of the source rather than out of a run: a check that only fires on
    an exotic graph would otherwise drift out of the documentation unnoticed,
    and the catalogue is what the page and the README both render.
    """

    @staticmethod
    def _emitted() -> set:
        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "orionbelt_ontology_builder"
            / "ontology_manager.py"
        )
        pairs = set()
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_skos_issue"
                and len(node.args) >= 2
            ):
                continue
            severity, kind = node.args[0], node.args[1]
            assert isinstance(severity, ast.Constant) and isinstance(
                kind, ast.Constant
            ), "severity and type must be literals, or this test cannot read them"
            pairs.add((kind.value, severity.value))
        return pairs

    def test_every_check_is_documented(self):
        undocumented = {
            kind
            for kind, _ in self._emitted()
            if kind not in OntologyManager.SKOS_CHECKS
        }
        assert not undocumented, (
            f"emitted but not in SKOS_CHECKS: {sorted(undocumented)}"
        )

    def test_nothing_documented_is_unreachable(self):
        emitted = {kind for kind, _ in self._emitted()}
        stale = set(OntologyManager.SKOS_CHECKS) - emitted
        assert not stale, f"in SKOS_CHECKS but never emitted: {sorted(stale)}"

    def test_documented_severity_matches_what_is_emitted(self):
        for kind, severity in sorted(self._emitted()):
            assert OntologyManager.SKOS_CHECKS[kind]["severity"] == severity, (
                f"{kind} is emitted as {severity} but documented as "
                f"{OntologyManager.SKOS_CHECKS[kind]['severity']}"
            )

    def test_every_entry_is_complete(self):
        for kind, entry in OntologyManager.SKOS_CHECKS.items():
            assert set(entry) == {"severity", "summary", "source"}, kind
            assert entry["summary"].endswith("."), (
                f"{kind}: summary reads as a sentence"
            )
            assert entry["severity"] in {"error", "warning", "info"}, kind

    @staticmethod
    def _readme() -> str:
        return (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )

    def test_the_readme_documents_every_check(self):
        readme = self._readme()
        missing = [k for k in OntologyManager.SKOS_CHECKS if f"`{k}`" not in readme]
        assert not missing, f"not documented in README.md: {missing}"

    def test_the_readme_says_what_the_catalogue_says(self):
        """The README table is generated from the catalogue but stored static.

        Checking only that each check is *named* there let a description go two
        revisions stale while the test stayed green. The wording is the part a
        reader relies on, so it is the part worth pinning.
        """
        readme = self._readme()
        stale = [
            kind
            for kind, entry in OntologyManager.SKOS_CHECKS.items()
            if " ".join(entry["summary"].split()) not in readme
        ]
        assert not stale, (
            "README.md describes these checks differently from SKOS_CHECKS, "
            f"regenerate its table: {stale}"
        )

    def test_the_readme_states_the_right_number_of_checks(self):
        """A count in prose drifts the moment a check is added."""
        readme = self._readme()
        expected = f"{len(OntologyManager.SKOS_CHECKS)} checks in three tiers"
        assert expected in readme, f"README.md should say {expected!r}"

    def test_the_readme_cites_the_same_sources(self):
        readme = self._readme()
        for kind, entry in OntologyManager.SKOS_CHECKS.items():
            summary = " ".join(entry["summary"].split())
            row = next((line for line in readme.splitlines() if summary in line), None)
            assert row is not None, kind
            assert entry["source"] in row, (
                f"{kind}: README cites something other than {entry['source']!r}"
            )


class TestSkosXl:
    """SKOS-XL labels are read, not authored.

    Every fixture writes triples directly, because SKOS-XL only ever arrives by
    import: this app has no way to author it, so a fixture built through the API
    could not reach the case at all.
    """

    BASE = "http://test.org/ont#"

    @classmethod
    def _xl_labelled(cls, om, name, kind="prefLabel", text="Alpha", lang="en"):
        """A concept whose only label of ``kind`` is a SKOS-XL one."""
        concept = URIRef(cls.BASE + name)
        label = URIRef(f"{cls.BASE}label_{name}_{kind}")
        om.graph.add((URIRef(cls.BASE + "S"), RDF.type, SKOS.ConceptScheme))
        om.graph.add((concept, RDF.type, SKOS.Concept))
        om.graph.add((concept, SKOS.inScheme, URIRef(cls.BASE + "S")))
        om.graph.add((concept, SKOS.definition, Literal("A definition", lang="en")))
        om.graph.add((label, RDF.type, SKOSXL.Label))
        om.graph.add(
            (
                label,
                SKOSXL.literalForm,
                Literal(text, lang=lang) if lang else Literal(text),
            )
        )
        om.graph.add((concept, OntologyManager.SKOS_XL_LABEL_KINDS[kind], label))
        return concept

    def test_an_xl_pref_label_is_a_pref_label(self, om):
        """Otherwise every concept of a SKOS-XL vocabulary is an error."""
        self._xl_labelled(om, "A")
        assert "missing_prefLabel" not in _types(om)

    def test_a_concept_with_no_label_at_all_still_reports(self, om):
        om.graph.add((URIRef(self.BASE + "S"), RDF.type, SKOS.ConceptScheme))
        om.graph.add((URIRef(self.BASE + "A"), RDF.type, SKOS.Concept))
        om.graph.add((URIRef(self.BASE + "A"), SKOS.inScheme, URIRef(self.BASE + "S")))
        assert "missing_prefLabel" in _types(om)

    def test_xl_labels_are_readable(self, om):
        self._xl_labelled(om, "A")
        concept = om.get_concepts()[0]
        assert concept["xl_labels"]["prefLabel"] == [{"value": "Alpha", "lang": "en"}]

    def test_xl_labels_are_not_mixed_into_the_editable_ones(self, om):
        """The editor writes plain SKOS; merging them would give a SKOS-XL label
        a delete button that does nothing."""
        self._xl_labelled(om, "A")
        assert om.get_concepts()[0]["labels"]["prefLabel"] == []

    def test_the_flat_label_falls_back_to_xl(self, om):
        """So the graph, the dashboard and the concept list show a name."""
        self._xl_labelled(om, "A")
        assert om.get_concepts()[0]["prefLabel"] == "Alpha"

    def test_a_plain_label_wins_the_flat_key(self, om):
        concept = self._xl_labelled(om, "A")
        om.graph.add((concept, SKOS.prefLabel, Literal("Plain", lang="en")))
        assert om.get_concepts()[0]["prefLabel"] == "Plain"

    def test_a_label_resource_without_a_literal_form_contributes_nothing(self, om):
        om.graph.add((URIRef(self.BASE + "S"), RDF.type, SKOS.ConceptScheme))
        om.graph.add((URIRef(self.BASE + "A"), RDF.type, SKOS.Concept))
        label = URIRef(self.BASE + "empty_label")
        om.graph.add((label, RDF.type, SKOSXL.Label))
        om.graph.add((URIRef(self.BASE + "A"), SKOSXL.prefLabel, label))
        assert om.get_concepts()[0]["xl_labels"]["prefLabel"] == []
        assert "missing_prefLabel" in _types(om)

    def test_the_vocabulary_is_reported_once_not_once_per_concept(self, om):
        """AGROVOC would otherwise produce one line per concept."""
        for name in ("A", "B", "C"):
            self._xl_labelled(om, name)
        found = _of_type(om, "skos_xl_labels")
        assert len(found) == 1
        assert "3 concepts" in found[0]["message"]

    def test_nothing_is_reported_for_a_plain_skos_vocabulary(self, vocab):
        assert "skos_xl_labels" not in _types(vocab)

    def test_the_notice_is_editorial(self, om):
        self._xl_labelled(om, "A")
        assert "skos_xl_labels" not in _types(om, check_editorial=False)

    def test_alt_and_hidden_xl_labels_are_read_too(self, om):
        for kind in ("altLabel", "hiddenLabel"):
            self._xl_labelled(om, "A", kind=kind, text=f"XL {kind}")
        concept = om.get_concepts()[0]
        assert concept["xl_labels"]["altLabel"][0]["value"] == "XL altLabel"
        assert concept["xl_labels"]["hiddenLabel"][0]["value"] == "XL hiddenLabel"

    # --- SKOS-XL labels take part in the integrity conditions -------------
    #
    # A skosxl:prefLabel with a literalForm entails the plain skos:prefLabel
    # (SKOS Reference B.3.4.2), so it is subject to every rule a plain label
    # is. Suppressing missing_prefLabel and stopping there left the rest as
    # false negatives.

    def test_two_xl_pref_labels_in_one_language_break_s14(self, om):
        concept = self._xl_labelled(om, "A", text="One")
        second = URIRef(self.BASE + "label_A_second")
        om.graph.add((second, RDF.type, SKOSXL.Label))
        om.graph.add((second, SKOSXL.literalForm, Literal("Two", lang="en")))
        om.graph.add((concept, SKOSXL.prefLabel, second))
        assert "multi_prefLabel_per_lang" in _types(om)

    def test_duplicate_xl_pref_labels_in_a_scheme_are_found(self, om):
        self._xl_labelled(om, "A", text="Same")
        self._xl_labelled(om, "B", text="Same")
        assert "duplicate_prefLabel" in _types(om)

    def test_a_plain_pref_label_clashes_with_an_xl_alt_label(self, om):
        """S13 disjointness does not care which spelling asserted the label."""
        concept = self._xl_labelled(om, "A", kind="altLabel", text="Dog")
        om.graph.add((concept, SKOS.prefLabel, Literal("Dog", lang="en")))
        assert "label_overlap" in _types(om)

    def test_an_xl_label_entailing_a_plain_one_is_not_a_clash(self, om):
        """The entailment makes them the same statement, not two labels.

        Without deduplication, spelling a label both ways would report S14 and
        S13 violations against itself.
        """
        concept = self._xl_labelled(om, "A", text="Dog")
        om.graph.add((concept, SKOS.prefLabel, Literal("Dog", lang="en")))
        types = _types(om)
        assert "multi_prefLabel_per_lang" not in types
        assert "label_overlap" not in types

    def test_an_untagged_xl_label_is_reported_like_a_plain_one(self, om):
        self._xl_labelled(om, "A", text="Alpha", lang=None)
        assert "missing_lang" in _types(om)

    def test_skosxl_is_not_offered_as_a_place_to_create_entities(self, om):
        """It is a vocabulary this app reads, not one the user mints in."""
        assert str(SKOSXL) not in om.get_creatable_namespaces()

    def test_the_prefix_survives_a_load(self, om, tmp_path):
        """Loading replaces the graph, and only rdflib's own defaults survive.

        skosxl is not one of them, so an imported SKOS-XL vocabulary exported
        as `ns1:` until the standard prefixes were rebound.
        """
        source = tmp_path / "xl.ttl"
        source.write_text(
            "<http://example.org/o#A> a "
            "<http://www.w3.org/2004/02/skos/core#Concept> ;\n"
            "  <http://www.w3.org/2008/05/skos-xl#prefLabel> "
            "<http://example.org/o#lbl> .\n"
            "<http://example.org/o#lbl> a "
            "<http://www.w3.org/2008/05/skos-xl#Label> ;\n"
            '  <http://www.w3.org/2008/05/skos-xl#literalForm> "Alpha"@en .\n',
            encoding="utf-8",
        )
        om.load_from_file(str(source))
        assert "skosxl" in {prefix for prefix, _ in om.graph.namespaces()}
        assert "skosxl:" in om.graph.serialize(format="turtle")

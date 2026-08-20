"""Dublin Core metadata on a ConceptScheme.

`add_concept_scheme` took a label and a comment, while every published
vocabulary carries a title, a creator, a licence and dates on its scheme.

The point of these tests is that the fields are not all strings. A date is
typed by how much of it was given, a licence is a resource rather than text
about one, and a creator may be either. Storing all of them as plain literals
would round-trip fine and be wrong.
"""

import pathlib

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, SKOS, XSD

from ontology_manager import OntologyManager

BASE = "http://test.org/ont#"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
ORCID = "https://orcid.org/0000-0002-1825-0097"


@pytest.fixture
def om():
    manager = OntologyManager(base_uri=BASE)
    manager.add_concept_scheme("Animals")
    return manager


def _meta(om, field):
    return om.get_concept_schemes()[0]["metadata"][field]


def _objects(om, prop):
    return list(om.graph.objects(URIRef(BASE + "Animals"), prop))


class TestTextFields:
    def test_a_title_per_language(self, om):
        om.set_scheme_metadata("Animals", "title", "Animal Thesaurus", lang="en")
        om.set_scheme_metadata("Animals", "title", "Tierthesaurus", lang="de")
        assert [v["value"] for v in _meta(om, "title")] == [
            "Tierthesaurus",
            "Animal Thesaurus",
        ]

    def test_a_second_title_in_one_language_replaces_the_first(self, om):
        """A scheme has one title in English, not a list of them."""
        om.set_scheme_metadata("Animals", "title", "First", lang="en")
        om.set_scheme_metadata("Animals", "title", "Second", lang="en")
        assert [v["value"] for v in _meta(om, "title")] == ["Second"]

    def test_a_malformed_language_tag_is_refused(self, om):
        with pytest.raises(ValueError):
            om.set_scheme_metadata("Animals", "title", "Title", lang="en_GB")

    def test_a_blank_value_is_refused(self, om):
        with pytest.raises(ValueError, match="cannot be empty"):
            om.set_scheme_metadata("Animals", "title", "   ", lang="en")


class TestDatesAreTypedByPrecision:
    """A vocabulary that records only the year should not have to invent a day,
    and typing "2019" as xsd:date would claim a precision it does not have."""

    @pytest.mark.parametrize(
        ("value", "datatype"),
        [
            ("2019", XSD.gYear),
            ("2019-03", XSD.gYearMonth),
            ("2019-03-01", XSD.date),
        ],
    )
    def test_precision(self, om, value, datatype):
        om.set_scheme_metadata("Animals", "created", value)
        stored = _objects(om, DCTERMS.created)[0]
        assert stored.datatype == datatype
        assert str(stored) == value

    @pytest.mark.parametrize(
        "value", ["yesterday", "01-03-2019", "2019-3-1", "20190301"]
    )
    def test_a_value_that_is_not_a_date_is_refused(self, om, value):
        with pytest.raises(ValueError, match="YYYY"):
            om.set_scheme_metadata("Animals", "created", value)

    def test_a_new_date_replaces_the_old_one(self, om):
        om.set_scheme_metadata("Animals", "modified", "2019")
        om.set_scheme_metadata("Animals", "modified", "2026-08-20")
        assert len(_objects(om, DCTERMS.modified)) == 1


class TestResourceFields:
    def test_a_licence_is_a_resource_not_a_string(self, om):
        """A consumer follows a licence IRI; it cannot follow text about one."""
        om.set_scheme_metadata("Animals", "license", CC_BY)
        stored = _objects(om, DCTERMS.license)[0]
        assert isinstance(stored, URIRef)
        assert str(stored) == CC_BY

    def test_a_licence_must_be_an_absolute_iri(self, om):
        with pytest.raises(ValueError, match="absolute IRI"):
            om.set_scheme_metadata("Animals", "license", "CC-BY-4.0")

    def test_a_licence_that_cannot_be_serialised_is_refused(self, om):
        with pytest.raises(ValueError, match="no spaces"):
            om.set_scheme_metadata(
                "Animals", "license", "https://example.org/a licence"
            )


class TestAgentFields:
    """Both spellings are used in the wild, and an IRI stored as a string does
    not resolve for a consumer."""

    def test_a_name_is_stored_as_text(self, om):
        om.set_scheme_metadata("Animals", "creator", "RALFORION d.o.o.")
        assert isinstance(_objects(om, DCTERMS.creator)[0], Literal)

    def test_an_identifier_is_stored_as_a_resource(self, om):
        om.set_scheme_metadata("Animals", "creator", ORCID)
        assert isinstance(_objects(om, DCTERMS.creator)[0], URIRef)

    def test_creators_are_repeatable(self, om):
        om.set_scheme_metadata("Animals", "creator", "A Person")
        om.set_scheme_metadata("Animals", "creator", "Another Person")
        assert len(_meta(om, "creator")) == 2

    def test_the_reader_says_which_is_which(self, om):
        om.set_scheme_metadata("Animals", "creator", "A Person")
        om.set_scheme_metadata("Animals", "creator", ORCID)
        by_value = {v["value"]: v["is_iri"] for v in _meta(om, "creator")}
        assert by_value == {"A Person": False, ORCID: True}


class TestRemoval:
    def test_one_value(self, om):
        om.set_scheme_metadata("Animals", "creator", "A Person")
        om.set_scheme_metadata("Animals", "creator", "Another Person")
        assert om.remove_scheme_metadata("Animals", "creator", "A Person")
        assert [v["value"] for v in _meta(om, "creator")] == ["Another Person"]

    def test_a_typed_date_is_really_removed(self, om):
        """The stored term is typed, so a rebuilt plain literal would miss it."""
        om.set_scheme_metadata("Animals", "created", "2019")
        assert om.remove_scheme_metadata("Animals", "created", "2019")
        assert _meta(om, "created") == []

    def test_an_iri_valued_creator_is_really_removed(self, om):
        om.set_scheme_metadata("Animals", "creator", ORCID)
        assert om.remove_scheme_metadata("Animals", "creator", ORCID)
        assert _meta(om, "creator") == []

    def test_language_is_matched(self, om):
        om.set_scheme_metadata("Animals", "title", "Same", lang="en")
        om.set_scheme_metadata("Animals", "title", "Same", lang="de")
        om.remove_scheme_metadata("Animals", "title", "Same", "en")
        assert [v["lang"] for v in _meta(om, "title")] == ["de"]

    def test_clearing_a_field(self, om):
        om.set_scheme_metadata("Animals", "creator", "A Person")
        om.set_scheme_metadata("Animals", "creator", "Another Person")
        assert om.remove_scheme_metadata("Animals", "creator")
        assert _meta(om, "creator") == []

    def test_removing_what_is_not_there(self, om):
        assert not om.remove_scheme_metadata("Animals", "creator", "Nobody")


class TestTheCatalogue:
    def test_an_unknown_field_names_the_alternatives(self, om):
        with pytest.raises(ValueError, match="title"):
            om.set_scheme_metadata("Animals", "notAField", "x")

    def test_version_info_is_owl_not_dublin_core(self, om):
        """Recorded because it is the one field that is not DC."""
        om.set_scheme_metadata("Animals", "versionInfo", "1.2.0")
        assert _objects(om, OWL.versionInfo) == [Literal("1.2.0")]

    def test_the_readme_documents_every_field(self):
        """Same guard as the check table: naming it is not documenting it."""
        readme = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        missing = [f for f in OntologyManager.SCHEME_METADATA if f"`{f}`" not in readme]
        assert not missing, f"not documented in README.md: {missing}"

    def test_every_entry_is_complete(self):
        for field, entry in OntologyManager.SCHEME_METADATA.items():
            assert set(entry) == {"property", "kind", "single"}, field
            assert entry["kind"] in {"text", "agent", "date", "iri", "plain"}, field


class TestSchemesAreAddressedByUri:
    """Two schemes can share a local name across namespaces (issue #87 part B)."""

    def test_metadata_lands_on_the_right_scheme(self, om):
        other = "http://other.example/ns#Animals"
        om.graph.add((URIRef(other), RDF.type, SKOS.ConceptScheme))
        om.set_scheme_metadata(other, "title", "The other one", lang="en")

        titles = {
            s["uri"]: [v["value"] for v in s["metadata"]["title"]]
            for s in om.get_concept_schemes()
        }
        assert titles[other] == ["The other one"]
        assert titles[BASE + "Animals"] == []


class TestValidation:
    def test_a_scheme_with_no_title_is_reported(self, om):
        assert "scheme_untitled" in {i["type"] for i in om.validate_skos()}

    def test_a_title_settles_it(self, om):
        om.set_scheme_metadata("Animals", "title", "Animals", lang="en")
        assert "scheme_untitled" not in {i["type"] for i in om.validate_skos()}

    def test_an_rdfs_label_settles_it_too(self):
        """The check is about a consumer having something to show, not about
        which vocabulary supplied it."""
        manager = OntologyManager(base_uri=BASE)
        manager.add_concept_scheme("Animals", label="Animals")
        assert "scheme_untitled" not in {i["type"] for i in manager.validate_skos()}

    def test_it_is_editorial(self, om):
        assert "scheme_untitled" not in {
            i["type"] for i in om.validate_skos(check_editorial=False)
        }


class TestRoundTrip:
    def test_metadata_survives_turtle(self, om):
        om.set_scheme_metadata("Animals", "title", "Animal Thesaurus", lang="en")
        om.set_scheme_metadata("Animals", "creator", ORCID)
        om.set_scheme_metadata("Animals", "license", CC_BY)
        om.set_scheme_metadata("Animals", "created", "2019")
        om.set_scheme_metadata("Animals", "versionInfo", "1.2.0")

        from rdflib import Graph

        reparsed = Graph().parse(
            data=om.graph.serialize(format="turtle"), format="turtle"
        )
        assert set(reparsed) == set(om.graph)

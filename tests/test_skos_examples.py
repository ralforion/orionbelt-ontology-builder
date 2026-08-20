"""The SKOS examples practise what the validator preaches.

Two guards, and the second is the one that matters. Asserting an example
validates clean is easy to satisfy by accident: an empty file passes. So the
showcase is also asserted to *contain* the things it exists to demonstrate,
or it could be quietly hollowed out and stay green.
"""

import pathlib

import pytest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import templates

SAMPLES = (
    pathlib.Path(__file__).resolve().parents[1]
    / "orionbelt_ontology_builder"
    / "samples"
)
BASE = "http://example.org/ontology#"


def _loaded(path, base=BASE):
    om = OntologyManager(base_uri=base)
    om.graph.parse(str(path), format="turtle")
    return om


@pytest.fixture
def showcase():
    return _loaded(SAMPLES / "skos-showcase.ttl", "http://example.org/showcase#")


class TestTheStarterTemplate:
    """A template that opens with a screenful of warnings teaches the wrong
    thing, especially now that most of them are one button-click from fixed."""

    @pytest.fixture
    def built(self):
        template = next(t for t in templates.TEMPLATES if t["name"] == "SKOS Thesaurus")
        om = OntologyManager(base_uri=BASE)
        om.graph.parse(data=template["turtle"].format(base_uri=BASE), format="turtle")
        return om

    def test_it_validates_clean_at_every_tier(self, built):
        assert built.validate_skos() == []

    def test_it_demonstrates_the_data_model(self, built):
        """Otherwise "clean" could be achieved by leaving things out."""
        concepts = built.get_concepts()
        assert len(concepts) >= 5
        assert any(len(c["labels"]["prefLabel"]) > 1 for c in concepts), (
            "no concept carries a prefLabel in more than one language"
        )
        assert any(c["labels"]["altLabel"] for c in concepts), "no altLabel"
        assert any(c["notation"] for c in concepts), "no notation"
        assert any(c["top_of"] for c in concepts), "no top concept"
        assert any(
            any(c["mappings"][rel] for rel in OntologyManager.SKOS_MAPPING_RELATIONS)
            for c in concepts
        ), "nothing mapped to another vocabulary"


class TestTheShowcaseSample:
    def test_it_validates_clean_at_every_tier(self, showcase):
        assert showcase.validate_skos() == []

    def test_it_shows_what_a_template_has_no_room_for(self, showcase):
        concepts = showcase.get_concepts()
        assert len(showcase.get_concept_schemes()) >= 2, "only one scheme"

        poly = [c for c in concepts if len(c["broader_uris"]) > 1]
        assert poly, "no concept has more than one parent"

        in_two_schemes = [c for c in concepts if len(c["scheme_uris"]) > 1]
        assert in_two_schemes, "no concept belongs to two schemes"

        languages = {
            item["lang"] for c in concepts for item in c["labels"]["prefLabel"]
        }
        assert len(languages) >= 3, f"only {len(languages)} languages: {languages}"

        assert any(c["labels"]["hiddenLabel"] for c in concepts), "no hiddenLabel"
        assert any(c["notes"]["scopeNote"] for c in concepts), "no scopeNote"
        assert any(c["related_uris"] for c in concepts), "no associative relation"

    def test_its_mappings_leave_the_vocabulary(self, showcase):
        """A mapping between two concepts of one scheme is a check, not a demo."""
        known = {c["uri"] for c in showcase.get_concepts()}
        targets = [
            target
            for c in showcase.get_concepts()
            for rel in OntologyManager.SKOS_MAPPING_RELATIONS
            for target in c["mappings"][rel]
        ]
        assert targets, "nothing mapped"
        assert not [t for t in targets if t in known]

    def test_the_poly_hierarchy_is_not_redundant(self, showcase):
        """Two parents where one is an ancestor of the other would be a warning
        rather than a demonstration."""
        assert not [
            i for i in showcase.validate_skos() if i["type"] == "hierarchy_redundancy"
        ]


class TestEveryBundledSample:
    """A sample shipping SKOS errors would be teaching from a broken example."""

    @pytest.mark.parametrize(
        "path", sorted(SAMPLES.glob("*.ttl")), ids=lambda p: p.name
    )
    def test_no_skos_errors(self, path):
        om = _loaded(path)
        errors = [
            i
            for i in om.validate_skos(check_conventions=False, check_editorial=False)
            if i["severity"] == "error"
        ]
        assert not errors, [i["message"] for i in errors]

    def test_the_geography_sample_still_shows_the_validator_working(self):
        """Its disconnected branches are left in on purpose.

        A sample that reports nothing demonstrates nothing about validation, so
        this one keeps its flaws and `samples/README.md` says so. If it is ever
        tidied up, this test should be deleted along with that note rather than
        quietly adjusted.
        """
        om = _loaded(SAMPLES / "geography-thesaurus.ttl")
        found = {i["type"] for i in om.validate_skos()}
        assert "disconnected_components" in found

    def test_the_geography_sample_is_otherwise_sound(self):
        om = _loaded(SAMPLES / "geography-thesaurus.ttl")
        assert not [
            i for i in om.validate_skos() if i["severity"] in ("error", "warning")
        ]


class TestTheSamplesReadme:
    def test_the_showcase_is_listed(self):
        readme = (SAMPLES / "README.md").read_text(encoding="utf-8")
        assert "skos-showcase.ttl" in readme

    def test_the_geography_flaws_are_documented(self):
        readme = (SAMPLES / "README.md").read_text(encoding="utf-8")
        assert "disconnected" in readme.lower(), (
            "samples/README.md should say the geography sample's disconnected "
            "branches are deliberate, or the next reader will 'fix' them"
        )

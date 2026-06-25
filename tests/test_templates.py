"""Tests for ontology templates."""

import hashlib
from unittest.mock import patch

import pytest
from rdflib import Graph
from orionbelt_ontology_builder import templates as templates_module
from orionbelt_ontology_builder.templates import (
    get_template_names,
    get_template,
    render_template,
    get_upper_ontology_names,
    get_upper_ontology,
    load_upper_ontology_module,
    get_reference_ontology_names,
    get_reference_ontology,
    load_reference_ontology_module,
    _fetch_with_cache,
)
from ontology_manager import OntologyManager


class TestTemplateDefinitions:
    def test_template_names(self):
        names = get_template_names()
        assert len(names) == 5
        assert "Organization" in names
        assert "SKOS Thesaurus" in names

    def test_get_template(self):
        t = get_template("Organization")
        assert t is not None
        assert "description" in t
        assert "turtle" in t

    def test_get_nonexistent_template(self):
        assert get_template("Nonexistent") is None

    def test_render_replaces_base_uri(self):
        t = get_template("Organization")
        rendered = render_template(t, "http://example.org/ont#")
        assert "http://example.org/ont#" in rendered
        assert "{base_uri}" not in rendered


class TestTemplateValidity:
    @pytest.mark.parametrize("name", get_template_names())
    def test_valid_turtle(self, name):
        t = get_template(name)
        rendered = render_template(t, "http://test.org/ont#")
        g = Graph()
        g.parse(data=rendered, format="turtle")
        assert len(g) > 0


class TestTemplateApplication:
    def test_merge_template(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("ExistingClass")
        t = get_template("Organization")
        rendered = render_template(t, "http://test.org/ont#")
        om.merge_from_string(rendered, "turtle")
        classes = [c["name"] for c in om.get_classes()]
        assert "Organization" in classes
        assert "ExistingClass" in classes  # preserved

    def test_replace_template(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        om.add_class("ExistingClass")
        t = get_template("Organization")
        rendered = render_template(t, "http://test.org/ont#")
        om.load_from_string(rendered, "turtle")
        classes = [c["name"] for c in om.get_classes()]
        assert "Organization" in classes
        assert "ExistingClass" not in classes  # replaced

    def test_skos_template_creates_concepts(self):
        om = OntologyManager(base_uri="http://test.org/ont#")
        t = get_template("SKOS Thesaurus")
        rendered = render_template(t, "http://test.org/ont#")
        om.load_from_string(rendered, "turtle")
        schemes = om.get_concept_schemes()
        assert len(schemes) >= 1
        concepts = om.get_concepts()
        assert len(concepts) >= 5


class TestUpperOntologies:
    def test_upper_ontology_names(self):
        names = get_upper_ontology_names()
        assert "gist (Semantic Arts)" in names

    def test_get_upper_ontology(self):
        upper = get_upper_ontology("gist (Semantic Arts)")
        assert upper is not None
        assert upper["version"] == "14.1.0"
        assert len(upper["modules"]) == 4

    def test_get_nonexistent_upper_ontology(self):
        assert get_upper_ontology("Nonexistent") is None

    def test_load_gist_core_module(self):
        upper = get_upper_ontology("gist (Semantic Arts)")
        core = next(m for m in upper["modules"] if m["name"] == "gistCore")
        content = load_upper_ontology_module(core)
        assert "@prefix gist:" in content
        assert "owl:Class" in content

    def test_gist_core_valid_turtle(self):
        upper = get_upper_ontology("gist (Semantic Arts)")
        core = next(m for m in upper["modules"] if m["name"] == "gistCore")
        content = load_upper_ontology_module(core)
        g = Graph()
        g.parse(data=content, format="turtle")
        assert len(g) > 100

    def test_merge_gist_into_ontology(self):
        om = OntologyManager(base_uri="http://test.org/myont#")
        om.add_class("MyClass")
        upper = get_upper_ontology("gist (Semantic Arts)")
        for mod in upper["modules"]:
            if mod.get("required") or mod.get("default"):
                content = load_upper_ontology_module(mod)
                om.merge_from_string(content, "turtle")
        classes = [c["name"] for c in om.get_classes()]
        assert "MyClass" in classes
        assert "Organization" in classes
        assert "Event" in classes
        assert "Person" in classes
        assert len(classes) > 90

    def test_gist_has_required_module(self):
        upper = get_upper_ontology("gist (Semantic Arts)")
        required = [m for m in upper["modules"] if m.get("required")]
        assert len(required) == 1
        assert required[0]["name"] == "gistCore"

    def test_gufo_listed(self):
        names = get_upper_ontology_names()
        assert "gUFO (UFO / OntoUML)" in names

    def test_get_gufo_upper_ontology(self):
        upper = get_upper_ontology("gUFO (UFO / OntoUML)")
        assert upper is not None
        assert upper["version"] == "1.0.0"
        assert "CC BY 4.0" in upper["license"]
        assert len(upper["modules"]) == 1
        assert upper["modules"][0]["name"] == "gufo"
        assert upper["modules"][0].get("required") is True

    def test_gufo_core_valid_turtle(self):
        upper = get_upper_ontology("gUFO (UFO / OntoUML)")
        core = upper["modules"][0]
        content = load_upper_ontology_module(core)
        g = Graph()
        g.parse(data=content, format="turtle")
        assert len(g) > 100

    def test_merge_gufo_into_ontology(self):
        om = OntologyManager(base_uri="http://test.org/myont#")
        om.add_class("MyClass")
        upper = get_upper_ontology("gUFO (UFO / OntoUML)")
        for mod in upper["modules"]:
            if mod.get("required") or mod.get("default"):
                content = load_upper_ontology_module(mod)
                om.merge_from_string(content, "turtle")
        classes = [c["name"] for c in om.get_classes()]
        assert "MyClass" in classes
        assert "Endurant" in classes
        assert "Event" in classes
        assert "Kind" in classes
        assert "Relator" in classes


class TestReferenceOntologies:
    def test_reference_names(self):
        names = get_reference_ontology_names()
        assert "PROV-O" in names
        assert "FOAF (Friend of a Friend)" in names
        assert "GoodRelations" in names

    def test_get_reference_ontology(self):
        ref = get_reference_ontology("PROV-O")
        assert ref is not None
        assert ref["modules"][0].get("file") == "prov-o.ttl"

    def test_get_nonexistent_reference(self):
        assert get_reference_ontology("Nonexistent") is None

    def test_load_bundled_prov_o(self):
        ref = get_reference_ontology("PROV-O")
        mod = ref["modules"][0]
        content = load_reference_ontology_module(mod)
        g = Graph()
        g.parse(data=content, format=mod.get("format", "turtle"))
        assert len(g) > 100

    def test_load_bundled_foaf_xml(self):
        ref = get_reference_ontology("FOAF (Friend of a Friend)")
        mod = ref["modules"][0]
        content = load_reference_ontology_module(mod)
        g = Graph()
        g.parse(data=content, format=mod.get("format", "xml"))
        assert len(g) > 50

    def test_merge_prov_o_into_ontology(self):
        om = OntologyManager(base_uri="http://test.org/myont#")
        om.add_class("MyClass")
        ref = get_reference_ontology("PROV-O")
        mod = ref["modules"][0]
        content = load_reference_ontology_module(mod)
        om.merge_from_string(content, mod.get("format", "turtle"))
        classes = [c["name"] for c in om.get_classes()]
        assert "MyClass" in classes
        assert any(c in classes for c in ("Activity", "Agent", "Entity"))

    def test_module_without_file_or_url_raises(self):
        with pytest.raises(ValueError):
            load_reference_ontology_module({"name": "broken"})

    def test_fetch_uses_disk_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(templates_module, "CACHE_DIR", tmp_path)
        payload = b"@prefix : <http://test/> . :A a :B ."
        sha = hashlib.sha256(payload).hexdigest()

        # Pre-seed cache so no network call should happen
        cache_file = tmp_path / f"{sha}.dat"
        cache_file.write_bytes(payload)

        with patch(
            "orionbelt_ontology_builder.templates.urllib.request.urlopen"
        ) as mock_urlopen:
            result = _fetch_with_cache("https://example.invalid/x", sha)
            mock_urlopen.assert_not_called()
        assert result == payload.decode("utf-8")

    def test_fetch_verifies_sha256_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(templates_module, "CACHE_DIR", tmp_path)
        payload = b"actual content"
        wrong_sha = "0" * 64

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch(
            "orionbelt_ontology_builder.templates.urllib.request.urlopen",
            return_value=_Resp(),
        ):
            with pytest.raises(RuntimeError, match="SHA256 mismatch"):
                _fetch_with_cache("https://example.invalid/x", wrong_sha)

        # Mismatched fetch must NOT poison the cache
        assert not (tmp_path / f"{wrong_sha}.dat").exists()

    def test_fetch_caches_after_download(self, tmp_path, monkeypatch):
        monkeypatch.setattr(templates_module, "CACHE_DIR", tmp_path)
        payload = b"valid content here"
        sha = hashlib.sha256(payload).hexdigest()

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch(
            "orionbelt_ontology_builder.templates.urllib.request.urlopen",
            return_value=_Resp(),
        ) as mock:
            result1 = _fetch_with_cache("https://example.invalid/x", sha)
            result2 = _fetch_with_cache("https://example.invalid/x", sha)
            # Second call should hit the cache, not the network
            assert mock.call_count == 1

        assert result1 == result2 == payload.decode("utf-8")
        assert (tmp_path / f"{sha}.dat").exists()

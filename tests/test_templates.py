"""Tests for ontology templates."""

import pytest
from rdflib import Graph
from templates import (get_template_names, get_template, render_template,
                       get_upper_ontology_names, get_upper_ontology,
                       load_upper_ontology_module)
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

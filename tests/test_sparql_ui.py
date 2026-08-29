"""The SPARQL page runs a query, reports limits, and refuses to write.

The engine's own guarantees are covered in test_sparql.py; these check that the
page is wired to them — that a query typed into the text area reaches
``run_query`` with the page's limits, and that what comes back is shown rather
than swallowed.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.views.sparql import EXAMPLE_QUERIES, _prefix_rows


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle", label="Bicycle")
        om.add_class("Wheel", label="Wheel")
        om.add_class("Tandem", parent="Bicycle", label="Tandem")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["sparql_query_text"] = os.environ["SPARQL_Q"]
        rows = os.environ.get("SPARQL_ROWS")
        if rows:
            st.session_state["sparql_max_rows"] = int(rows)

    app.render_sparql()


def _run(query, *, max_rows=None, click=True):
    os.environ["SPARQL_Q"] = query
    if max_rows is None:
        os.environ.pop("SPARQL_ROWS", None)
    else:
        os.environ["SPARQL_ROWS"] = str(max_rows)
    at = AppTest.from_function(_script)
    at.run(timeout=120)
    assert not at.exception, at.exception
    if click:
        at.button[0].click().run(timeout=120)
        assert not at.exception, at.exception
    return at


def _captions(at):
    return " ".join(c.value for c in at.caption)


def _warnings(at):
    return " ".join(w.value for w in at.warning)


def test_a_select_query_reports_its_rows():
    at = _run("SELECT ?c WHERE { ?c a owl:Class }")
    assert not at.error
    assert "3 rows in" in _captions(at)


def test_an_ask_query_shows_a_verdict():
    at = _run("ASK { ?s a owl:Class }")
    assert not at.error
    assert at.metric[0].value == "true"


def test_an_update_is_refused_on_the_page():
    at = _run("INSERT DATA { <http://a> <http://b> <http://c> }")
    assert at.error
    assert "read-only" in at.error[0].value


def test_a_syntax_error_is_shown_not_raised():
    at = _run("SELECT ?c WHERE { ?c a owl:Class")
    assert at.error


def test_the_row_limit_is_applied_and_announced():
    at = _run("SELECT ?s ?p ?o WHERE { ?s ?p ?o }", max_rows=2)
    assert not at.error
    assert "Showing the first 2 rows" in _warnings(at)


def test_an_empty_result_says_so():
    at = _run("SELECT ?s WHERE { ?s a <http://nope.example/Missing> }")
    assert not at.error
    assert any("matched nothing" in i.value for i in at.info)


def test_an_empty_result_points_at_the_prefixes():
    # The mistake behind an empty result is usually a prefixed name resolved
    # into a namespace the ontology does not use, and that fails silently.
    at = _run("SELECT ?s WHERE { ?s a <http://nope.example/Missing> }")
    assert "own namespace" in _captions(at)


def test_the_page_lists_the_prefixes_that_name_something():
    at = _run("SELECT ?s WHERE { ?s a owl:Class }", click=False)
    assert any("Prefixes in this ontology" in e.label for e in at.expander)


class TestPrefixRows:
    """What the prefix list says a name in each namespace looks like."""

    def test_the_ontology_namespace_comes_first_as_the_empty_prefix(self):
        om = OntologyManager()
        om.add_class("Person")
        assert _prefix_rows(om)[0] == {"Prefix": ":", "Namespace": om.base_uri}

    def test_an_imported_namespace_keeps_its_own_prefix(self):
        om = OntologyManager()
        om.add_prefix("foaf", "http://xmlns.com/foaf/0.1/")
        om.add_class("Person", namespace="http://xmlns.com/foaf/0.1/")
        rows = {row["Namespace"]: row["Prefix"] for row in _prefix_rows(om)}
        assert rows["http://xmlns.com/foaf/0.1/"] == "foaf:"

    def test_a_namespace_nothing_names_is_shown_in_full(self):
        om = OntologyManager()
        om.add_class("Widget", namespace="http://un.bound.example/ns#")
        rows = {row["Namespace"]: row["Prefix"] for row in _prefix_rows(om)}
        assert rows["http://un.bound.example/ns#"].startswith("<http://un.bound")


def test_the_page_renders_before_anything_is_run():
    at = _run("", click=False)
    assert not at.error
    assert not at.warning


def test_running_a_query_leaves_the_ontology_alone():
    """The page is the only thing a user can point at the graph, so the
    read-only promise is worth asserting end to end, not just in the engine."""
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    at = _run("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert not at.error
    om = at.session_state["ontology"]
    assert len(om.get_classes()) == 3
    # rdflib's URI shortening binds generated ``ns1:`` prefixes as it goes, so
    # a query could leave prefixes behind on the ontology it only read.
    assert set(om.graph.namespaces()) == set(OntologyManager().graph.namespaces())


def test_picking_an_example_fills_the_editor():
    at = _run("", click=False)
    at.selectbox[0].select("Class hierarchy").run(timeout=120)
    assert not at.exception, at.exception
    assert at.session_state["sparql_query_text"] == EXAMPLE_QUERIES["Class hierarchy"]


def test_every_example_query_runs():
    """An example that does not parse is worse than no example at all."""
    from orionbelt_ontology_builder import sparql
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    om = OntologyManager()
    om.add_class("Person", label="Person")
    om.add_concept_scheme("Scheme")
    om.add_concept("Animal", scheme="Scheme", pref_label="Animal")
    for name, query in EXAMPLE_QUERIES.items():
        result = sparql.run_query(om.graph, query)
        assert result.form in sparql.READ_ONLY_FORMS, name


def test_a_timed_out_query_does_not_claim_it_matched_nothing(monkeypatch):
    """A query stopped by the deadline produced no rows *yet*. Reporting that
    as an empty answer states the opposite of what happened."""
    from orionbelt_ontology_builder import sparql
    from orionbelt_ontology_builder.views import sparql as page

    shown: list[str] = []
    monkeypatch.setattr(page.st, "info", lambda msg, *a, **k: shown.append(msg))
    monkeypatch.setattr(page.st, "warning", lambda msg, *a, **k: shown.append(msg))
    monkeypatch.setattr(page.st, "caption", lambda msg, *a, **k: None)

    page._render_result(sparql.QueryResult(form="SELECT", timed_out=True))
    assert not any("matched nothing" in m for m in shown)
    assert any("time limit" in m for m in shown)

    shown.clear()
    page._render_result(sparql.QueryResult(form="SELECT"))
    assert any("matched nothing" in m for m in shown)


# --- the editor ------------------------------------------------------------


def test_the_editor_themes_are_real_ace_themes():
    """A typo here does not raise, it silently renders an unstyled editor."""
    from streamlit_ace import THEMES

    from orionbelt_ontology_builder.views import sparql as page

    assert page._EDITOR_THEME_LIGHT in THEMES
    assert page._EDITOR_THEME_DARK in THEMES


def test_the_editor_theme_is_not_one_that_leaves_sparql_black():
    """Ace themes only colour the token classes they choose to, and SPARQL
    emits ``ace_variable ace_other`` / ``ace_support ace_type``. The 'github'
    theme styles neither and gives ace_keyword bold with no colour, so the
    whole query renders flat black. Measured in the browser, not guessed.
    """
    from orionbelt_ontology_builder.views import sparql as page

    assert page._EDITOR_THEME_LIGHT != "github"
    assert page._EDITOR_THEME_DARK != "github"


@pytest.mark.parametrize(
    ("theme_type", "expected"),
    [("dark", "_EDITOR_THEME_DARK"), ("light", "_EDITOR_THEME_LIGHT")],
)
def test_the_editor_follows_the_app_theme(monkeypatch, theme_type, expected):
    from orionbelt_ontology_builder.views import sparql as page

    monkeypatch.setattr(
        page.st,
        "context",
        type("C", (), {"theme": type("T", (), {"type": theme_type})}),
    )
    assert page._editor_theme() == getattr(page, expected)


def test_the_editor_falls_back_to_light_when_the_theme_is_unreadable(monkeypatch):
    """st.context.theme is not available in every Streamlit context."""
    from orionbelt_ontology_builder.views import sparql as page

    class Boom:
        @property
        def theme(self):
            raise RuntimeError("no context")

    monkeypatch.setattr(page.st, "context", Boom())
    assert page._editor_theme() == page._EDITOR_THEME_LIGHT


def test_picking_an_example_remounts_the_editor():
    """Ace treats ``value`` as initial content only, so an example has to
    remount the component under a new key or the editor keeps showing what the
    user had before."""
    at = _run("", click=False)
    at.selectbox[0].select("Class hierarchy").run(timeout=120)
    assert not at.exception, at.exception
    assert at.session_state["sparql_editor_nonce"] >= 1
    assert at.session_state["sparql_query_text"] == EXAMPLE_QUERIES["Class hierarchy"]


def test_the_page_still_works_without_the_editor_component(monkeypatch):
    """The editor is a nicety; querying is the feature. If streamlit-ace cannot
    be imported the page must still render and run queries."""
    from orionbelt_ontology_builder.views import sparql as page

    monkeypatch.setattr(page, "st_ace", None)
    shown: dict = {}
    monkeypatch.setattr(page.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(
        page.st, "container", lambda **k: __import__("contextlib").nullcontext()
    )
    monkeypatch.setattr(
        page.st, "text_area", lambda *a, **k: shown.setdefault("fell_back", True) and ""
    )
    page._render_editor()
    assert shown.get("fell_back") is True

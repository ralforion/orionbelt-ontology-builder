"""The Dashboard page: its Overview and Settings, and the charts it draws."""

from rdflib import URIRef
from rdflib.namespace import OWL, RDF, RDFS
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ontology_manager import OntologyManager
from orionbelt_ontology_builder.quality import QualityConfig, RuleSettings, analyze
from orionbelt_ontology_builder.views.charts import (
    column_bars,
    describe,
    meter_list,
    ranked_bars,
)
from orionbelt_ontology_builder.views.dashboard import (
    _not_counted_by_quality,
    _Validation,
)
from orionbelt_ontology_builder.views.validation import quality_run_key


def test_a_meter_is_drawn_on_a_track_of_its_own_hue():
    spec = meter_list(
        [("Class labels", 3, 4), ("Concept labels", 0, 0)], "#123456", ink="#FAFAFA"
    )
    track, fill, name, figure = spec["layer"]
    assert track["mark"]["color"] == fill["mark"]["color"] == "#123456"
    assert track["mark"]["opacity"] < 1
    values = spec["data"]["values"]
    assert [v["figure"] for v in values] == ["3 of 4 · 75%", "0 of 0 · 0%"]
    assert [v["share"] for v in values] == [0.75, 0.0]
    # Text wears the theme's text colour, never the accent: Vega's default
    # black cannot be read on a dark background.
    assert name["mark"]["color"] == figure["mark"]["color"] == "#FAFAFA"


def test_bars_are_thin_and_leave_room_for_the_value_at_their_tip():
    for spec in (
        ranked_bars([("a", 10), ("b", 4)], "#123456", what="Findings", ink="#FAFAFA"),
        column_bars(
            [("0", 10), ("1", 4)],
            "#123456",
            x_title="Depth",
            what="Classes",
            ink="#FAFAFA",
        ),
    ):
        bar, label = spec["layer"]
        assert bar["mark"]["size"] <= 24
        scale = next(
            iter(bar["encoding"][c] for c in ("x", "y") if c in bar["encoding"])
        )
        assert scale["scale"]["domain"][1] > 10
        assert label["encoding"]["text"]["field"] == "count"
        assert label["mark"]["color"] == "#FAFAFA"


def test_every_chart_keeps_the_height_it_asks_for():
    """Streamlit's default ``fit`` takes the padding out of the height, which
    squeezed a one-row chart to a sliver; ``fit-x`` fits only the width."""
    for spec in (
        meter_list([("a", 1, 2)], "#123456", ink="#000"),
        ranked_bars([("a", 1)], "#123456", what="Labels", ink="#000"),
        column_bars([("0", 1)], "#123456", x_title="Depth", what="Classes", ink="#000"),
    ):
        assert spec["autosize"]["type"] == "fit-x"


def test_a_ranked_chart_never_drops_a_name():
    spec = ranked_bars([("a", 10), ("b", 10)], "#123456", what="Findings", ink="#000")
    assert spec["encoding"]["y"]["axis"]["labelOverlap"] is False


def test_a_chart_has_a_text_alternative():
    assert (
        describe([("Classes", 1200), ("Other (2)", 3)]) == "Classes 1,200; Other (2) 3"
    )


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager
    from orionbelt_ontology_builder.views import dashboard

    dashboard.CHECKS_AUTORUN_MAX_TRIPLES = int(os.environ.get("AUTORUN_MAX", "10000"))
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri="http://test.org/o#")
        if not os.environ.get("EMPTY"):
            om.add_class("Bicycle", label="Bicycle")
            om.add_class("Wheel")
            om.add_class("Tandem", parent="Bicycle")
            om.add_object_property("hasPart", domain="Bicycle", range_="Wheel")
            om.add_individual("bike1", "Bicycle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_quality_configs_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["nav_radio"] = "Dashboard"
        st.session_state["dash_active_tab"] = os.environ.get("DASH_TAB", "Overview")
    if os.environ.get("WHOLE_APP"):
        app.main()
    else:
        app.render_dashboard()


def _metrics(at) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def _run(monkeypatch, **env) -> AppTest:
    for name in ("AUTORUN_MAX", "EMPTY", "DASH_TAB", "WHOLE_APP"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    at = AppTest.from_function(_script)
    at.run(timeout=60)
    assert not at.exception, at.exception
    return at


def test_the_overview_leads_with_counts_and_runs_the_checks(monkeypatch):
    at = _run(monkeypatch)
    metrics = _metrics(at)
    assert metrics["Classes"] == "3"
    assert metrics["Individuals"] == "1"
    assert metrics["Depth"] == "1"

    om = at.session_state["ontology"]
    run = at.session_state[quality_run_key(om)]
    assert run.graph_fingerprint == om.revision_token()
    # The run is the Quality section's own, so its counts are the ones shown.
    for severity, label in (("warning", "Warnings"), ("info", "Info")):
        count = sum(f.severity == severity for f in run.findings)
        assert metrics[next(k for k in metrics if k.endswith(label))] == str(count)
    assert not [b for b in at.button if b.key == "dash_run_checks"]
    # One class with individuals is a sentence, not a one-bar chart.
    assert any(m.value == "1 individual, all of class Bicycle." for m in at.markdown), [
        m.value for m in at.markdown
    ]


def test_validation_leaves_out_what_model_quality_counts(monkeypatch):
    # Wheel and Tandem have no label: Q001 warnings under Model quality, and
    # nothing under Validation, which used to count them as well.
    at = _run(monkeypatch)
    om = at.session_state["ontology"]
    assert {i["type"] for i in om.validate()} >= {"missing_label"}
    run = at.session_state[quality_run_key(om)]
    unlabelled = {f.resource for f in run.by_rule("Q001")}
    assert {"http://test.org/o#Wheel", "http://test.org/o#Tandem"} <= unlabelled
    assert [s.value for s in at.success] == ["No structural problems found."]


NS = "http://test.org/o#"


def _validation_panel(om, config=None) -> list[str]:
    """The issue types the dashboard's Validation panel shows for ``om``."""
    validation = _Validation(
        om.revision_token(),
        om.validate(check_missing_domain_range=False),
        om.class_cycles(),
    )
    findings = analyze(om, config or QualityConfig()).all_findings()
    return [i["type"] for i in _not_counted_by_quality(validation, findings)]


def _cycle(om, *names, kind=OWL.Class):
    for name in names:
        om.graph.add((URIRef(NS + name), RDF.type, kind))
    for child, parent in zip(names, names[1:] + names[:1], strict=True):
        om.graph.add((URIRef(NS + child), RDFS.subClassOf, URIRef(NS + parent)))


def test_a_cycle_quality_reports_is_counted_there_only():
    om = OntologyManager(base_uri=NS)
    _cycle(om, "A", "B")
    _cycle(om, "C")  # its own subclass: Q009's, not Q006's
    assert [i["type"] for i in om.validate()].count("class_cycle") == 2
    assert "class_cycle" not in _validation_panel(om)


def test_a_cycle_quality_cannot_see_stays_under_validation():
    # rdfs:Class, not owl:Class: Q006 does not reach it (Codex review of #564).
    om = OntologyManager(base_uri=NS)
    _cycle(om, "A", "B", kind=RDFS.Class)
    assert _validation_panel(om) == ["class_cycle"]
    # Nor does it once Q006 is switched off.
    om = OntologyManager(base_uri=NS)
    _cycle(om, "A", "B")
    off = QualityConfig(rules={"Q006": RuleSettings(enabled=False)})
    assert _validation_panel(om, off) == ["class_cycle"]


def test_a_class_outside_the_own_scope_keeps_its_missing_label():
    om = OntologyManager(base_uri=NS)
    om.add_class("Own", label="Own")
    om.add_class("Unlabelled")
    om.graph.add((URIRef("http://other.org/Imported"), RDF.type, OWL.Class))
    om.graph.add(
        (URIRef(NS + "Own"), RDFS.subClassOf, URIRef("http://other.org/Imported"))
    )
    om.graph.add((URIRef(NS + "Unlabelled"), RDFS.subClassOf, URIRef(NS + "Own")))
    issues = om.validate(check_missing_domain_range=False)
    assert {i["subject_uri"] for i in issues if i["type"] == "missing_label"} == {
        NS + "Unlabelled",
        "http://other.org/Imported",
    }
    assert _validation_panel(om) == ["missing_label"]


def test_a_large_ontology_waits_for_a_click(monkeypatch):
    at = _run(monkeypatch, AUTORUN_MAX="1")
    om = at.session_state["ontology"]
    assert quality_run_key(om) not in at.session_state
    assert any("run by themselves" in c.value for c in at.caption)

    at.button(key="dash_run_checks").click().run(timeout=60)
    assert at.session_state[quality_run_key(om)].graph_fingerprint == (
        om.revision_token()
    )

    # An edit leaves the results up, marked, until the next click.
    om.add_class("Saddle")
    at.run(timeout=60)
    assert any("changed since" in w.value for w in at.warning)
    assert at.button(key="dash_run_checks")


def test_settings_hold_the_metadata_form(monkeypatch):
    at = _run(monkeypatch, DASH_TAB="Settings")
    assert at.text_input[0].label == "Base URI"
    assert at.text_input[0].value == "http://test.org/o#"
    assert not at.metric


def test_an_empty_ontology_points_to_import(monkeypatch):
    at = _run(monkeypatch, EMPTY="1")
    assert any("Nothing to measure yet" in i.value for i in at.info)
    assert not at.metric  # no row of zeros
    assert at.subheader[0].value == "o"  # the header card stays (http://test.org/o)
    at.button(key="dash_open_import").click().run(timeout=60)
    assert at.session_state["search_navigate_to"] == "Import / Export"


def test_open_quality_lands_on_the_quality_section(monkeypatch):
    at = _run(monkeypatch, WHOLE_APP="1")
    at.button(key="dash_open_quality").click().run(timeout=60)
    assert not at.exception, at.exception
    assert at.session_state["nav_radio"] == "Validation & Reasoning"
    assert any(s.value == "Model Quality" for s in at.subheader)

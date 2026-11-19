"""SKOS-XL labels on the SKOS page: the concept editor and the SKOS-XL section."""

from streamlit.testing.v1 import AppTest

BASE = "http://test.org/k#"


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    base = "http://test.org/k#"
    if "ontology" not in st.session_state:
        om = OntologyManager(base_uri=base)
        om.add_concept_scheme("Things")
        om.add_concept("Dog", scheme="Things")
        om.add_xl_label("Dog", "prefLabel", "Dog", "en")
        om.add_xl_label("Dog", "altLabel", "Hound", "en")
        om.add_concept("Cat", scheme="Things", pref_label="Cat", lang="en")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # Dog's card open in edit mode, keyed as the page keys it.
        st.session_state["active_skos"] = (
            str(abs(hash(base + "Dog")))[:8],
            "edit",
        )
    st.session_state.setdefault("skos_active_tab", "Concepts")
    app.render_skos_vocabulary()


def _run(tab="Concepts"):
    at = AppTest.from_function(_script)
    at.session_state["skos_active_tab"] = tab
    at.run(timeout=60)
    assert not at.exception, at.exception
    return at


def _ck():
    return str(abs(hash(BASE + "Dog")))[:8]


def _xl_rows(at):
    return [m.value for m in at.markdown if m.value.startswith("`skosxl:")]


class TestTheConceptEditor:
    def test_skos_xl_labels_are_rows_with_edit_and_delete(self):
        at = _run()
        assert _xl_rows(at) == ["`skosxl:prefLabel`", "`skosxl:altLabel`"]
        assert (
            len([b for b in at.button if (b.key or "").startswith(f"del_xl_{_ck()}")])
            == 2
        )
        assert len([b for b in at.button if (b.key or "").startswith("xl_save_")]) == 2

    def test_the_add_row_offers_the_skos_xl_kinds_first_here(self):
        """Dog's vocabulary labels in SKOS-XL as much as in plain SKOS."""
        at = _run()
        kind = at.selectbox(key=f"add_lit_kind_{_ck()}")
        assert {"skosxl:prefLabel", "skosxl:altLabel", "skosxl:hiddenLabel"} <= set(
            kind.options
        )
        assert kind.value == "skosxl:prefLabel"

    def test_adding_a_skos_xl_label(self):
        at = _run()
        at.selectbox(key=f"add_lit_kind_{_ck()}").set_value("skosxl:hiddenLabel")
        at.text_input(key=f"add_lit_text_{_ck()}_0").set_value("dgo")
        at.button(key=f"add_lit_btn_{_ck()}").click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        om = at.session_state["ontology"]
        dog = next(c for c in om.get_concepts() if c["name"] == "Dog")
        assert [i["value"] for i in dog["xl_labels"]["hiddenLabel"]] == ["dgo"]
        assert "`skosxl:hiddenLabel`" in _xl_rows(at)

    def test_editing_a_skos_xl_label_keeps_its_resource(self):
        at = _run()
        om = at.session_state["ontology"]
        before = next(c for c in om.get_concepts() if c["name"] == "Dog")
        label = before["xl_labels"]["altLabel"][0]["label"]
        text = next(
            t
            for t in at.text_input
            if (t.key or "").startswith("xl_text_") and t.value == "Hound"
        )
        text.set_value("Hound dog")
        save = next(
            b
            for b in at.button
            if b.key == "xl_save_" + text.key.removeprefix("xl_text_")
        )
        save.click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        dog = next(c for c in om.get_concepts() if c["name"] == "Dog")
        assert dog["xl_labels"]["altLabel"] == [
            {"value": "Hound dog", "lang": "en", "label": label}
        ]

    def test_deleting_a_skos_xl_label(self):
        at = _run()
        at.button(key=f"del_xl_{_ck()}_1").click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        om = at.session_state["ontology"]
        dog = next(c for c in om.get_concepts() if c["name"] == "Dog")
        assert dog["xl_labels"]["altLabel"] == []
        assert _xl_rows(at) == ["`skosxl:prefLabel`"]


class TestTheSkosXlSection:
    def test_it_counts_both_forms(self):
        at = _run("SKOS-XL")
        values = {m.label: m.value for m in at.metric}
        assert values == {"Plain labels": "1", "SKOS-XL labels": "2"}

    def test_converting_plain_labels_to_skos_xl(self):
        at = _run("SKOS-XL")
        at.button(key="skosxl_to_xl").click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        counts = at.session_state["ontology"].label_form_counts()
        assert (counts["plain"], counts["xl"]) == (0, 3)
        assert at.button(key="skosxl_to_xl").disabled

    def test_adding_plain_copies_keeps_the_skos_xl_labels(self):
        at = _run("SKOS-XL")
        assert at.checkbox(key="skosxl_keep_xl").value is True
        at.button(key="skosxl_to_plain").click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        counts = at.session_state["ontology"].label_form_counts()
        assert (counts["plain"], counts["xl"]) == (3, 2)

    def test_replacing_skos_xl_labels_with_plain_ones(self):
        at = _run("SKOS-XL")
        at.checkbox(key="skosxl_keep_xl").uncheck()
        at.run(timeout=60)
        at.button(key="skosxl_to_plain").click()
        at.run(timeout=60)
        assert not at.exception, at.exception
        counts = at.session_state["ontology"].label_form_counts()
        assert (counts["plain"], counts["xl"]) == (3, 0)

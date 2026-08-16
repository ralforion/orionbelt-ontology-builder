"""The Language fields pick from a pack instead of being typed (issue #252).

Driven through ``render_add_annotation`` and ``render_annotation_form`` rather
than the page, for the reason the other annotation UI tests give: the page's tab
picker is a ``segmented_control``, which AppTest mis-serializes.

Note when extending these: AppTest can only select an option that is already in
the list, so what a user *types* into an ``accept_new_options`` dropdown cannot
be simulated here. Assertions about a typed tag therefore belong on
``languages.code_from_option`` and ``ui.language_tag_error`` (see
``test_language_packs.py``).
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import languages


def _add_script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Animal")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    resources = [
        {
            "name": c["name"],
            "label": c.get("label"),
            "type": "Class",
            "display": c["name"],
        }
        for c in ont.get_classes()
    ]
    app.render_add_annotation(ont, resources)


def _edit_script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Animal")
        # A tag no built-in pack lists: a regional subtag.
        om.add_annotation("Animal", "rdfs:comment", "a beast", lang="pt-BR")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    classes = ont.get_classes()
    ann = ont.get_annotations("Animal")[0]
    app.render_annotation_form(
        ont,
        next(c for c in classes if c["name"] == "Animal")["uri"],
        ann,
        "row0",
        classes,
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
    )


def _run(script, **session):
    at = AppTest.from_function(script)
    for key, value in session.items():
        at.session_state[key] = value
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _options(at, key):
    """The dropdown's options, unpadded.

    Every entity dropdown is padded to a fixed width for search ranking
    (``_pad_option``), and AppTest reports options as the widget formats them.
    """
    return [o.strip() for o in at.selectbox(key=key).options]


def test_the_language_field_offers_the_active_packs_codes_with_their_names():
    at = _run(_add_script)
    options = _options(at, "ann_lang")
    assert "eng · English" in options
    # The alpha-3 pack is the default, and its point is a language ISO 639-1
    # cannot name.
    assert "grc · Greek, Ancient" in options
    assert "en · English" not in options


def test_switching_the_pack_switches_the_codes_on_offer():
    from orionbelt_ontology_builder import app

    at = _run(_add_script, **{app.ACTIVE_LANG_PACK_KEY: languages.ALPHA2_PACK})
    options = _options(at, "ann_lang")
    assert "en · English" in options
    assert "eng · English" not in options


def test_adding_writes_the_bare_code_not_the_option_text():
    at = _run(_add_script)
    at.selectbox(key="ann_predicate").set_value("rdfs:label")
    at.text_area(key="ann_value").set_value("Tier")
    at.selectbox(key="ann_lang").set_value("deu · German")
    at.button[0].click().run(timeout=120)
    assert not at.exception, at.exception

    anns = at.session_state["ontology"].get_annotations("Animal")
    assert [(a["value"], a["language"]) for a in anns] == [("Tier", "deu")]


def test_the_language_stays_put_for_the_next_annotation():
    """The value is what changes from one annotation to the next; a run of
    labels in one language should not mean picking it again each time."""
    at = _run(_add_script)
    at.selectbox(key="ann_predicate").set_value("rdfs:label")
    at.text_area(key="ann_value").set_value("Tier")
    at.selectbox(key="ann_lang").set_value("deu · German")
    at.button[0].click().run(timeout=120)
    assert not at.exception, at.exception

    assert at.text_area(key="ann_value").value == ""
    assert at.selectbox(key="ann_lang").value == "deu · German"


def test_a_tag_outside_the_pack_is_offered_and_survives_a_save():
    """Switching packs must not quietly rewrite the tag of an annotation you
    open to edit for another reason."""
    at = _run(_edit_script)
    assert at.selectbox(key="ann_lang_row0").value == "pt-BR"

    at.text_input[1].set_value("a large beast")
    at.button(key="FormSubmitter:edit_ann_row0-Save").click().run(timeout=120)
    assert not at.exception, at.exception

    anns = at.session_state["ontology"].get_annotations("Animal")
    assert [(a["value"], a["language"]) for a in anns] == [("a large beast", "pt-BR")]

"""The Language Packs tab: making, switching and deleting a pack (issue #252).

The pack's rows are a ``data_editor``, which AppTest cannot type into, so what
is driven here is everything around it — create, delete, and the deferred
re-selection each of those does, since assigning a widget's value after the
widget has been drawn is an exception rather than a no-op.

The script draws the sidebar picker *before* the page, as the app does. That
ordering is the point rather than scenery: deleting the pack in use used to
write the picker's own key from the page body, which is exactly the assignment
Streamlit refuses, and with the page rendered on its own nothing noticed.
"""

import pytest
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app, languages


@pytest.fixture(autouse=True)
def no_disk_persist(monkeypatch):
    """Nothing here may reach the filesystem.

    The sidebar picker saves the packs after a change, and on a local/desktop
    run that save goes to ``~/.orionbelt_ontology_builder/config.json`` — the
    developer's own. Belt and braces with the env-var guard in ``conftest``.
    """
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)


def _script():
    import streamlit as st

    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        st.session_state.ontology = OntologyManager()
        st.session_state["_autosave_restored"] = True
        # No browser storage: mounting that component under AppTest hangs, and
        # what is driven here is the picker, not the persistence (which
        # test_language_packs.py covers). ``None`` is the cached handle
        # _get_local_storage() hands back when the component is unavailable.
        st.session_state["_local_storage"] = None

    from orionbelt_ontology_builder import app

    app.render_language_pack_sidebar()
    app.render_language_packs()


def _run(**session):
    at = AppTest.from_function(_script)
    for key, value in session.items():
        at.session_state[key] = value
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _packs(at):
    """The custom packs in the app-test's session, not this process's."""
    if app.CUSTOM_LANG_PACKS_KEY not in at.session_state:
        return {}
    return at.session_state[app.CUSTOM_LANG_PACKS_KEY]


def _create(at, name, start_from="Empty"):
    at.text_input(key="lang_pack_new_name").set_value(name)
    at.selectbox(key="lang_pack_new_from").set_value(start_from)
    at.button(key="lang_pack_create").click().run(timeout=120)
    assert not at.exception, at.exception
    return at


def test_the_tab_opens_on_the_pack_that_is_in_use():
    at = _run(**{app.ACTIVE_LANG_PACK_KEY: languages.ALPHA2_PACK})
    assert at.selectbox(key="lang_pack_edit_select").value == languages.ALPHA2_PACK


def test_a_new_pack_is_created_and_becomes_the_one_being_edited():
    at = _run()
    _create(at, "Project codes")

    assert _packs(at) == {"Project codes": []}
    assert at.selectbox(key="lang_pack_edit_select").value == "Project codes"
    # The name box is cleared, so the next create doesn't reuse it by accident.
    assert at.text_input(key="lang_pack_new_name").value == ""


def test_a_pack_can_start_from_a_built_in_one():
    at = _run()
    _create(at, "Trimmed", start_from=languages.ALPHA2_PACK)

    entries = _packs(at)["Trimmed"]
    assert entries == languages.builtin_pack(languages.ALPHA2_PACK)


def test_a_name_already_taken_is_refused():
    at = _run()
    _create(at, "Mine")
    _create(at, "Mine")
    assert "already exists" in at.error[0].value
    assert list(_packs(at)) == ["Mine"]


def test_a_built_in_pack_is_shown_but_not_editable():
    at = _run(**{app.ACTIVE_LANG_PACK_KEY: languages.ALPHA3_PACK})
    assert at.dataframe  # a read-only listing, with no Save beside it
    assert not [b for b in at.button if b.key.startswith("lang_pack_save_")]
    assert "can't be edited" in at.caption[1].value


def test_deleting_the_pack_in_use_asks_first_and_then_falls_back():
    at = _run()
    _create(at, "Mine")
    pack_key = app._uid("Mine")
    # Put it in use first: deleting the *active* pack is the case that took the
    # page down, because the fallback was written to the sidebar picker's own
    # key from the page body, after the picker had been drawn.
    at.selectbox(key=app.ACTIVE_LANG_PACK_KEY).set_value("Mine").run(timeout=120)
    assert not at.exception, at.exception

    at.button(key=f"lang_pack_del_{pack_key}").click().run(timeout=120)
    assert not at.exception, at.exception
    assert _packs(at)  # still there: it only armed the confirm
    assert at.warning

    at.button(key=f"lang_pack_del_yes_{pack_key}").click().run(timeout=120)
    assert not at.exception, at.exception
    assert _packs(at) == {}
    assert at.selectbox(key="lang_pack_edit_select").value == languages.DEFAULT_PACK
    # And the sidebar, whose pack has gone out from under it.
    assert at.selectbox(key=app.ACTIVE_LANG_PACK_KEY).value == languages.DEFAULT_PACK

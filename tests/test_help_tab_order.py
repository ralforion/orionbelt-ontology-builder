"""Tab walks field to field, and the help text comes along (issue #383).

A help tooltip renders as a real button, and since Streamlit 1.62 rebuilt the
widgets on react-aria it sits in the tab order — before the field it belongs to,
so tabbing through a form stopped twice per field, and a clearable dropdown
added its cross on top of that.

Taking those out of the tab order is only honest if the text the icon holds goes
somewhere a keyboard reaches, and Streamlit does not put it on the field: it
lives in the tooltip and nowhere else until the tooltip opens. So every ``help=``
the app passes is collected on its way to the widget and put on the field as a
description.

The DOM half runs in the browser, so it is pinned at the source level; the
collecting half is Python and is exercised directly.
"""

import json

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import ui


@pytest.fixture
def session(monkeypatch):
    """A session_state stand-in: dict access plus the attribute access ui uses."""

    class _State(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:  # pragma: no cover - mirrors Streamlit
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


# --- collecting the text ----------------------------------------------------


def test_a_widget_s_help_is_collected_on_its_way_past(session):
    ui.start_help_capture()
    ui.install_help_capture()
    calls = []
    st.text_input("Class Name *", help="A local name", key="probe")
    assert session[ui.HELP_TEXTS_KEY]["Class Name *"] == "A local name"
    assert calls == []


def test_a_widget_without_help_is_not_recorded(session):
    ui.start_help_capture()
    ui.install_help_capture()
    st.text_input("Label", key="probe2")
    assert "Label" not in session[ui.HELP_TEXTS_KEY]


def test_the_label_is_found_by_type_not_by_position(session):
    """The same function is called two ways.

    ``st.text_input(label, ...)`` passes the label first; a widget drawn on the
    sidebar or in a column arrives as ``dg.text_input(dg, label, ...)``, with the
    container first. Reading position 0 recorded the container and lost the help
    of every sidebar widget — two icons on every page of the app.
    """
    ui.start_help_capture()
    ui.install_help_capture()
    st.sidebar.checkbox("Autosave to this browser", help="Keep a copy", key="probe4")
    assert session[ui.HELP_TEXTS_KEY]["Autosave to this browser"] == "Keep a copy"


def test_the_wrapping_is_idempotent():
    """main() calls it on every render; wrapping the wrapper would stack a layer
    per rerun for the life of the process."""
    ui.install_help_capture()
    once = st.text_input
    ui.install_help_capture()
    assert st.text_input is once


def test_each_render_starts_from_nothing(session):
    """Otherwise a page that no longer draws a field keeps carrying its help,
    and the text lands on a same-named field somewhere else."""
    ui.start_help_capture()
    ui.install_help_capture()
    st.text_input("Gone next time", help="x", key="probe3")
    ui.start_help_capture()
    assert session[ui.HELP_TEXTS_KEY] == {}


# --- what is handed to the browser ------------------------------------------


def test_the_text_reaches_the_page_as_data_not_as_script():
    """Quotes and backslashes in a help string must not be able to end the
    script they ride in."""
    html = ui.help_wiring_html({'A "quoted" label': "back\\slash and 'quotes'"})
    payload = html.split("var HELP = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(payload) == {'A "quoted" label': "back\\slash and 'quotes'"}


def test_only_the_help_icons_and_the_clear_crosses_leave_the_tab_order():
    """Streamlit puts the same tooltip wrapper on real controls — the image
    Fullscreen button is one — so the icons are matched by their own label."""
    js = ui._HELP_WIRING_JS
    assert 'button[aria-label^="Help for "]' in js
    assert 'button[aria-label="Clear value"]' in js
    assert '[data-testid="stTooltipHoverTarget"] button:not' not in js


def test_the_text_is_put_where_a_screen_reader_meets_it():
    js = ui._HELP_WIRING_JS
    assert "aria-describedby" in js, "what screen readers read today"
    assert "aria-description" in js, "and where the same thing is heading"


def test_the_wiring_is_redone_when_the_page_under_it_changes():
    """Streamlit rebuilds its DOM on every rerun while this frame is mounted
    once, so without the observer the fix survives exactly one render."""
    assert "MutationObserver" in ui._HELP_WIRING_JS


def test_the_selectors_are_not_built_from_label_text():
    """A label carrying a quote would have to be escaped into a selector, and
    the escaping is the part that breaks silently."""
    js = ui._HELP_WIRING_JS
    assert "'[aria-label=\"' +" not in js
    assert "getAttribute('aria-label')" in js


def test_the_field_is_found_from_the_icon_not_from_the_label():
    """A button's name is its text and not an aria-label, and two widgets on a
    page can carry the same label — so the walk goes from the icon to the
    container Streamlit wraps that one widget in."""
    js = ui._HELP_WIRING_JS
    assert "closest('[data-testid=\"stElementContainer\"]')" in js
    assert 'button:not([aria-label^="Help for "])' in js, "never the icon itself"


# --- and on a real page -----------------------------------------------------


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_local_storage"] = None
        st.session_state["nav_radio"] = "Classes"
        st.session_state["cls_active_tab"] = "Add Class"
    app.main()


def test_a_rendered_page_hands_over_the_help_it_drew():
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception

    texts = at.session_state[ui.HELP_TEXTS_KEY]
    assert texts, "the Add Class form passes help= to several fields"
    assert any("class" in t.lower() for t in texts.values()), texts

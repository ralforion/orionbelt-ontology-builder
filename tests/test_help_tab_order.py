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
    st.text_input("Class Name *", help="A local name", key="probe")
    assert session[ui.HELP_TEXTS_KEY]["by_label"]["Class Name *"] == "A local name"
    assert session[ui.HELP_TEXTS_KEY]["by_key"]["probe"] == "A local name"


def test_a_widget_without_help_is_not_recorded(session):
    ui.start_help_capture()
    ui.install_help_capture()
    st.text_input("Label", key="probe2")
    assert "Label" not in session[ui.HELP_TEXTS_KEY]["by_label"]


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
    assert session[ui.HELP_TEXTS_KEY]["by_label"]["Autosave to this browser"] == (
        "Keep a copy"
    )


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
    assert session[ui.HELP_TEXTS_KEY] == {"by_key": {}, "by_label": {}}


# --- what is handed to the browser ------------------------------------------


def test_a_row_of_identical_buttons_keeps_its_own_help(session):
    """The case the review of PR #410 found.

    A page draws a 🗑️ per row, each with the help its own row needs — "Delete
    this creator", "Delete this prefLabel". Keyed by the label, one of them
    would answer for all of them, and every button would carry the wrong
    description while its icon was taken out of the tab order. The widget key
    is the only thing that tells them apart.
    """
    ui.start_help_capture()
    ui.install_help_capture()
    st.button("🗑️", key="del_meta_0", help="Delete this creator")
    st.button("🗑️", key="del_meta_1", help="Delete this prefLabel")

    store = session[ui.HELP_TEXTS_KEY]
    assert store["by_key"]["del_meta_0"] == "Delete this creator"
    assert store["by_key"]["del_meta_1"] == "Delete this prefLabel"
    # And the label they share is dropped rather than guessed at.
    assert store["by_label"]["🗑️"] is None
    assert "🗑️" not in json.loads(_payload(ui.page_shim_html(store), "BY_LABEL"))


def test_a_label_two_widgets_agree_on_still_carries(session):
    """Only disagreement is ambiguous. The same help twice is one answer."""
    ui.start_help_capture()
    ui.install_help_capture()
    st.button("🗑️", key="del_a", help="Delete this row")
    st.button("🗑️", key="del_b", help="Delete this row")
    assert session[ui.HELP_TEXTS_KEY]["by_label"]["🗑️"] == "Delete this row"


def test_an_icon_whose_help_cannot_be_placed_keeps_its_tab_stop():
    """The safety rule: the tab stop goes only where the text has landed."""
    js = ui._HELP_WIRING_JS
    apply_fn = js[js.index("function apply(") :]
    assert "if (!control) continue;" in apply_fn, apply_fn
    assert apply_fn.index("if (!control) continue;") < apply_fn.index(
        "icon.setAttribute('tabindex', '-1')"
    ), "the icon is only de-tabbed after its text is placed"


def test_the_key_is_read_off_the_container_not_built_into_a_selector():
    """A widget key is app-authored text; it could carry anything."""
    js = ui._HELP_WIRING_JS
    assert "function keyOf(" in js
    assert "'st-key-'" in js
    assert "'.st-key-' +" not in js


def _payload(html, name):
    return html.split(f"var {name} = ", 1)[1].split(";\n", 1)[0]


def test_the_text_reaches_the_page_as_data_not_as_script():
    """Quotes and backslashes in a help string must not be able to end the
    script they ride in."""
    store = {
        "by_key": {},
        "by_label": {'A "quoted" label': "back\\slash and 'quotes'"},
    }
    payload = _payload(ui.page_shim_html(store), "BY_LABEL")
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


# --- Enter takes the first match again (issue #384) --------------------------


def test_enter_is_only_taken_over_in_a_multiselect():
    """The single selectbox still commits its first match on Enter in 1.62, so
    it is left alone; the multiselect is the one that stopped."""
    js = ui._ENTER_INSERTS_JS
    assert '[data-testid="stMultiSelect"]' in js
    assert "stSelectbox" not in js


def test_the_bulk_row_is_not_what_enter_takes():
    """A bulk row is always first, so an unqualified "first option" would insert
    every match when one was asked for.

    Matched by the shape of its key rather than either key literally: Streamlit
    uses "__select_all__" with the box empty and "__select_matches__" once a
    query is typed, and skipping only the first let the second through — which
    is the case that matters, since it is the one a typed query produces (Codex
    review of PR #412).
    """
    js = ui._ENTER_INSERTS_JS
    assert "/^__.*__$/" in js, js
    assert "SENTINEL.test(key)" in js
    assert "'__select_all__'" not in js, "not one literal key"


def test_the_empty_state_row_is_not_clicked():
    """ "No results" is a row like any other in the DOM, and clicking it is not
    harmless: it took the whole filter down to one class in testing. Real
    options carry aria-selected; it does not."""
    js = ui._ENTER_INSERTS_JS
    assert "aria-selected" in js
    assert "=== null) continue" in js


def test_enter_is_left_alone_wherever_it_already_does_something():
    """Nothing typed, list closed, or an option already highlighted: react-aria
    answers all three itself, and a form's Enter must still submit."""
    js = ui._ENTER_INSERTS_JS
    for guard in (
        "if (!input.value) return;",
        "aria-expanded",
        "aria-activedescendant",
        "event.defaultPrevented",
    ):
        assert guard in js, guard


def test_the_handler_replaces_itself_rather_than_stacking():
    """The frame is re-created whenever its arguments change, and each new
    document would otherwise leave the last one's handler on the parent."""
    js = ui._ENTER_INSERTS_JS
    assert "removeEventListener('keydown'" in js
    assert "__orionbeltEnterShim" in js


def test_the_handler_runs_before_react_aria_closes_the_list():
    js = ui._ENTER_INSERTS_JS
    assert "addEventListener('keydown', onEnter, true)" in js, "capture phase"


def test_both_shims_ride_in_one_frame():
    """A component is an iframe, and these are mounted on every rerun."""
    html = ui.page_shim_html({"by_key": {}, "by_label": {}})
    assert html.count("<script>") == 2
    assert "MutationObserver" in html and "__orionbeltEnterShim" in html


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

    texts = at.session_state[ui.HELP_TEXTS_KEY]["by_label"]
    assert texts, "the Add Class form passes help= to several fields"
    assert any("class" in t.lower() for t in texts.values() if t), texts

"""The node options panel must stay open while you edit the filter (issue #267).

Streamlit's expander resets its open/closed state to the ``expanded`` argument
whenever its *label* changes, so the "what is hidden" note used to snap the
panel shut after every class you added or removed. The note now reaches the
label as generated content and the label string never moves.
"""

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Shown")
        om.add_class("Hidden")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        # Start from a narrowed filter — one class hidden — which is what puts a
        # note on the label. `known` carries both, so the deselected one reads
        # as deliberately hidden rather than newly created.
        uris = [c["uri"] for c in om.get_classes()]
        shown = [u for u in uris if u.endswith("Shown")]
        st.session_state["_viz_cfg_selected_class_uris"] = shown
        st.session_state["_viz_cfg_known_class_uris"] = set(uris)
    app.render_visualization()


def _rendered():
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


def test_the_hidden_note_never_reaches_the_expander_label():
    at = _rendered()
    labels = [e.label for e in at.expander]
    # Named for what it holds in both modes: focus mode replaces the filter
    # controls with its own, so "Filter Nodes" described only half of it
    # (issue #305).
    assert "Node options" in labels
    assert not [
        label for label in labels if "hidden" in label or label != label.strip()
    ], labels


def test_the_note_is_written_as_generated_content_instead():
    at = _rendered()
    assert at.session_state["_viz_hidden_note"] == "1 hidden by the node filter"
    styles = [
        e.proto.body for e in at.get("html") if "--viz-hidden-note" in e.proto.body
    ]
    assert styles, "no stylesheet carries the note"
    assert '--viz-hidden-note: "1 hidden by the node filter"' in styles[0]


def test_no_note_renders_nothing():
    assert app.viz_hidden_note_style("") == (
        '<style>.st-key-viz_filter_nodes { --viz-hidden-note: ""; }</style>'
    )


def test_the_focus_switch_is_not_inside_the_panel_it_controls():
    """It swaps the panel's contents, so it cannot live in the panel.

    A checkbox reachable only by opening a collapsed expander, while ten
    display toggles that matter far less sit in the open (issue #305).
    """
    at = _rendered()
    assert [c for c in at.checkbox if c.label == "Focus on one node"], (
        "the focus switch is missing"
    )
    inside = [
        c
        for expander in at.expander
        for c in expander.checkbox
        if c.label == "Focus on one node"
    ]
    assert not inside, "the focus switch is back inside the panel it swaps"


def test_entity_names_cannot_break_out_of_the_stylesheet():
    """Seed names reach the note, so the CSS string has to survive quotes,
    backslashes and anything that could end the style element early."""
    style = app.viz_hidden_note_style('Focused on <"a\\b">')
    assert "</style>" not in style[: -len("</style>")]
    assert '--viz-hidden-note: "Focused on \\00003c\\"a\\\\b\\">"' in style

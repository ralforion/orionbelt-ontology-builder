"""The source page."""

import streamlit as st


def render_source():
    """Render the source view page."""
    st.header("Source (Turtle)")
    ont = st.session_state.ontology
    try:
        turtle_src = ont.export_to_string(format="turtle")
        st.code(turtle_src, language="turtle", line_numbers=True)
    except Exception as e:  # noqa: BLE001 - serialization failure must show as a message
        st.error(f"Error serializing ontology: {e}")

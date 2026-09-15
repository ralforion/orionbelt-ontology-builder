"""The source page."""

import streamlit as st

#: Above this many characters of Turtle the page waits for a click before
#: rendering. The serialization is memoised on the graph revision, so what a
#: rerun then pays for is ``st.code`` shipping and highlighting the whole text
#: again, and at a megabyte that is what the reader waits on (issue #437).
SOURCE_AUTO_RENDER_MAX_CHARS = 1_000_000


def render_source():
    """Render the source view page."""
    st.header("Source (Turtle)")
    ont = st.session_state.ontology
    try:
        turtle_src = ont.export_to_string(format="turtle")
    except Exception as e:  # noqa: BLE001 - serialization failure must show as a message
        st.error(f"Error serializing ontology: {e}")
        return
    if len(turtle_src) > SOURCE_AUTO_RENDER_MAX_CHARS and not st.session_state.get(
        "_source_show_large"
    ):
        st.caption(
            f"{len(turtle_src) / 1_000_000:.1f} MB, "
            f"{turtle_src.count(chr(10)) + 1:,} lines. "
            "A source this large takes a moment to show."
        )
        if st.button("Show source", key="btn_source_show"):
            st.session_state["_source_show_large"] = True
        else:
            return
    st.code(turtle_src, language="turtle", line_numbers=True)

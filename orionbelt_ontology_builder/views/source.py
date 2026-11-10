"""The source page."""

import streamlit as st

#: The revision token the source was last generated for (see
#: ``OntologyManager.revision_token``).
_GENERATED = "_source_generated_for"


def render_source():
    """Render the source view page.

    Visiting the page writes nothing. The Turtle is generated on request,
    because at 213k triples writing it takes 2.5 s and showing it ships
    megabytes to the browser, and a visit that only wanted a look at the
    page should not wait for that. Once generated it is shown again on every
    visit while the ontology is unchanged, from the serialization the engine
    keeps for that revision. After an edit it waits to be generated again
    rather than being rewritten on its own.
    """
    st.header("Source (Turtle)")
    ont = st.session_state.ontology
    token = ont.revision_token()
    generated_for = st.session_state.get(_GENERATED)

    if generated_for != token:
        triples = len(ont.graph)
        if generated_for is None:
            st.caption(f"{triples:,} triples. The source is written when you ask.")
            label = "Generate source"
        else:
            st.caption(
                f"{triples:,} triples. The ontology changed since the source "
                "was generated."
            )
            label = "Regenerate source"
        if not st.button(label, key="btn_source_generate"):
            return
        st.session_state[_GENERATED] = token

    try:
        turtle_src = ont.export_to_string(format="turtle")
    except Exception as e:  # noqa: BLE001 - serialization failure must show as a message
        st.error(f"Error serializing ontology: {e}")
        return
    st.code(turtle_src, language="turtle", line_numbers=True)

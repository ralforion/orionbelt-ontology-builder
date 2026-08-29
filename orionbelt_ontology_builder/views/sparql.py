"""The SPARQL query page.

Read-only by design: the engine in :mod:`..sparql` accepts SELECT/ASK/CONSTRUCT/
DESCRIBE and refuses every update form, so edits keep going through the editor
pages where they are checkpointed and can be undone.
"""

import streamlit as st

from .. import sparql
from ..ui import _download_or_save, log_error

#: Starter queries. Written against prefixes every ontology here has bound —
#: ``owl:``/``rdfs:``/``skos:`` from the standard set, and ``:`` for the
#: ontology's own namespace — so they run as-is without editing.
EXAMPLE_QUERIES: dict[str, str] = {
    "Classes and their labels": """SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
ORDER BY ?label""",
    "Class hierarchy": """SELECT ?child ?parent WHERE {
  ?child rdfs:subClassOf ?parent .
  FILTER(isIRI(?parent))
}
ORDER BY ?parent ?child""",
    "Properties with domain and range": """SELECT ?property ?domain ?range WHERE {
  VALUES ?kind { owl:ObjectProperty owl:DatatypeProperty }
  ?property a ?kind .
  OPTIONAL { ?property rdfs:domain ?domain }
  OPTIONAL { ?property rdfs:range ?range }
}
ORDER BY ?property""",
    "Individuals and their types": """SELECT ?individual ?type WHERE {
  ?individual a owl:NamedIndividual , ?type .
  FILTER(?type != owl:NamedIndividual)
}
ORDER BY ?type ?individual""",
    "Classes with no label": """SELECT ?class WHERE {
  ?class a owl:Class .
  FILTER NOT EXISTS { ?class rdfs:label ?any }
  FILTER(isIRI(?class))
}
ORDER BY ?class""",
    "Triples per predicate": """SELECT ?predicate (COUNT(*) AS ?count) WHERE {
  ?s ?predicate ?o
}
GROUP BY ?predicate
ORDER BY DESC(?count)""",
    "SKOS concepts and broader terms": """SELECT ?concept ?prefLabel ?broader WHERE {
  ?concept a skos:Concept .
  OPTIONAL { ?concept skos:prefLabel ?prefLabel }
  OPTIONAL { ?concept skos:broader ?broader }
}
ORDER BY ?prefLabel""",
    "Everything about one resource (CONSTRUCT)": """CONSTRUCT { ?s ?p ?o }
WHERE {
  ?s ?p ?o .
  FILTER(?s = :Person)
}""",
}

_QUERY_KEY = "sparql_query_text"
_RESULT_KEY = "sparql_last_result"
_ERROR_KEY = "sparql_last_error"


def _load_example() -> None:
    """Put the picked example in the editor.

    Runs as a widget callback, which is the only point at which the text area's
    session-state key can still be written for the coming rerun.
    """
    name = st.session_state.get("sparql_example")
    if name and name in EXAMPLE_QUERIES:
        st.session_state[_QUERY_KEY] = EXAMPLE_QUERIES[name]
        st.session_state.pop(_RESULT_KEY, None)
        st.session_state.pop(_ERROR_KEY, None)


def _render_select_result(result: sparql.QueryResult) -> None:
    if not result.rows:
        # Only an empty result that actually finished matched nothing. A query
        # stopped by the deadline produced no rows *yet*, and telling the user
        # its answer is empty would be wrong.
        if not result.timed_out:
            st.info("The query ran and matched nothing.")
        return
    st.dataframe(
        [dict(zip(result.columns, row, strict=False)) for row in result.rows],
        use_container_width=True,
        hide_index=True,
    )
    _download_or_save(
        "Download results (CSV)",
        sparql.rows_to_csv(result.columns, result.rows),
        "query-results.csv",
        mime="text/csv",
        key="sparql_csv",
    )


def _render_graph_result(result: sparql.QueryResult) -> None:
    if result.graph is None or len(result.graph) == 0:
        if not result.timed_out:
            st.info("The query ran and matched nothing.")
        return
    try:
        turtle = result.graph.serialize(format="turtle")
    except Exception as e:  # noqa: BLE001 - a serialization failure is a message, not a crash
        st.error(f"Could not serialize the result: {e}")
        return
    st.code(turtle, language="turtle", line_numbers=True)
    _download_or_save(
        "Download results (Turtle)",
        turtle,
        "query-results.ttl",
        mime="text/turtle",
        key="sparql_ttl",
    )


def _render_result(result: sparql.QueryResult) -> None:
    """Show the outcome, warnings first: a capped or cut-short result is still
    shown, but the user has to be told it is not the whole answer."""
    if result.timed_out:
        produced = (
            "What it produced before then is below."
            if result.rows
            else "It had not produced any rows yet."
        )
        st.warning(
            f"The query hit its time limit and was stopped. {produced} Narrow "
            "the query, or raise the time limit."
        )
    if result.truncated:
        st.warning(
            f"Showing the first {result.row_count} rows; the query matched more. "
            "Raise the row limit or add a LIMIT clause to see a different slice."
        )

    if result.form == "ASK":
        st.metric("Result", "true" if result.ask else "false")
        st.caption(f"Ran in {result.elapsed:.2f}s.")
        return

    noun = "triple" if result.form in ("CONSTRUCT", "DESCRIBE") else "row"
    plural = "" if result.row_count == 1 else "s"
    st.caption(f"{result.row_count} {noun}{plural} in {result.elapsed:.2f}s.")

    if result.form in ("CONSTRUCT", "DESCRIBE"):
        _render_graph_result(result)
    else:
        _render_select_result(result)


def render_sparql():
    """Render the SPARQL query page."""
    st.header("SPARQL Query")
    st.caption(
        "Query the loaded ontology with SELECT, ASK, CONSTRUCT or DESCRIBE. "
        "This page is read-only — updates (INSERT, DELETE, LOAD) are not "
        "accepted, so edits stay in the editor pages where they can be undone."
    )

    ont = st.session_state.ontology

    st.selectbox(
        "Start from an example",
        ["", *EXAMPLE_QUERIES],
        format_func=lambda name: name or "Choose an example…",
        key="sparql_example",
        on_change=_load_example,
    )

    query_text = st.text_area(
        "Query",
        height=240,
        key=_QUERY_KEY,
        placeholder="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10",
        help=(
            "The ontology's prefixes are already declared, so you can write "
            "`owl:Class` or `:Person` without a PREFIX line."
        ),
    )

    limit_col, timeout_col, run_col = st.columns([2, 2, 1])
    with limit_col:
        max_rows = st.number_input(
            "Row limit",
            min_value=1,
            max_value=sparql.MAX_ROWS_CEILING,
            value=sparql.DEFAULT_MAX_ROWS,
            step=100,
            key="sparql_max_rows",
            help=(
                "Stops reading results past this many rows. A query with "
                "ORDER BY or GROUP BY still has to evaluate in full before the "
                "first row exists — the time limit is what bounds that."
            ),
        )
    with timeout_col:
        timeout_seconds = st.number_input(
            "Time limit (seconds)",
            min_value=int(sparql.MIN_TIMEOUT_SECONDS),
            max_value=int(sparql.MAX_TIMEOUT_SECONDS),
            value=int(sparql.DEFAULT_TIMEOUT_SECONDS),
            step=1,
            key="sparql_timeout",
            help="A query that runs longer than this is stopped.",
        )
    with run_col:
        st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        run = st.button("Run query", type="primary", use_container_width=True)

    if run:
        st.session_state.pop(_RESULT_KEY, None)
        st.session_state.pop(_ERROR_KEY, None)
        try:
            with st.spinner("Running query…"):
                st.session_state[_RESULT_KEY] = sparql.run_query(
                    ont.graph,
                    query_text,
                    timeout_seconds=timeout_seconds,
                    max_rows=max_rows,
                )
        except sparql.QueryError as e:
            st.session_state[_ERROR_KEY] = str(e)
        except Exception as e:  # noqa: BLE001 - a bad query must not take the page down
            log_error(e, context="SPARQL query")
            st.session_state[_ERROR_KEY] = str(e)

    # Held in session state so the result survives the rerun a download button
    # or a control change triggers.
    if st.session_state.get(_ERROR_KEY):
        st.error(st.session_state[_ERROR_KEY])
    elif st.session_state.get(_RESULT_KEY) is not None:
        _render_result(st.session_state[_RESULT_KEY])

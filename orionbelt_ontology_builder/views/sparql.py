"""The SPARQL query page.

Read-only by design: the engine in :mod:`..sparql` accepts SELECT/ASK/CONSTRUCT/
DESCRIBE and refuses every update form, so edits keep going through the editor
pages where they are checkpointed and can be undone.
"""

import streamlit as st

from .. import sparql
from ..ui import _download_or_save, log_error

try:
    from streamlit_ace import st_ace
except ImportError:  # pragma: no cover - exercised only without the extra
    # The editor is a nicety; querying is the feature. If the component cannot
    # be imported the page falls back to a plain monospace text area rather
    # than failing to render at all.
    st_ace = None

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
#: Bumped to force a fresh editor instance. The Ace component treats ``value``
#: as initial content, so loading an example has to remount it under a new key
#: or the editor keeps showing what the user had before.
_EDITOR_NONCE = "sparql_editor_nonce"
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
        st.session_state[_EDITOR_NONCE] = st.session_state.get(_EDITOR_NONCE, 0) + 1
        st.session_state.pop(_RESULT_KEY, None)
        st.session_state.pop(_ERROR_KEY, None)


_EDITOR_HELP = (
    "The ontology's prefixes are already declared, so you can write "
    "`owl:Class` or `:Person` without a PREFIX line. `:` is this ontology's "
    "own namespace; an imported vocabulary keeps its own prefix."
)

#: Shown with an empty result and beside the prefix list. A prefixed name that
#: points at the wrong namespace is valid SPARQL, so it does not fail — it
#: matches nothing, which reads like an empty ontology rather than a typo.
_NAMESPACE_HINT = (
    "`:` is this ontology's own namespace. An entity that came in with an "
    "imported or upper ontology keeps that vocabulary's prefix, so it is "
    "`foaf:Person`, not `:Person`."
)
_PLACEHOLDER = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"


#: Ace themes for the app's two appearances. Chosen by measuring what each
#: actually colours, not by name: Ace themes only style the token classes they
#: choose to, and SPARQL emits ``ace_variable ace_other`` and
#: ``ace_support ace_type`` for its variables and prefixed names. The obvious
#: pick, ``github``, styles neither — it gives ``ace_keyword`` bold weight and
#: no colour, and colours only ``ace_variable.ace_class``, so a whole query
#: renders in flat black. These two give keywords, variables, prefixed names
#: and strings four distinct colours, on grounds that match the app's own.
_EDITOR_THEME_LIGHT = "chrome"
_EDITOR_THEME_DARK = "tomorrow_night"


def _editor_theme() -> str:
    """An Ace theme matching the app's appearance. Light is the safe default:
    the browser only reports its theme from the second render on."""
    try:
        is_dark = st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001 - theme detection is cosmetic, never fatal
        is_dark = False
    return _EDITOR_THEME_DARK if is_dark else _EDITOR_THEME_LIGHT


def _render_editor() -> str:
    """The query editor, syntax-highlighted where the component is available.

    ``auto_update=True`` matters: left at its default the component renders its
    own separate apply button and never reports edits on blur, so pressing Run
    would submit the previous query. On, it commits after a short debounce, so
    what is on screen is what runs.
    """
    st.caption("Query")
    current = st.session_state.get(_QUERY_KEY, "")
    if st_ace is None:
        # Keyed container so the monospace rule in _CUSTOM_CSS reaches this one
        # text area without restyling every other text area in the app.
        with st.container(key="sparql_editor"):
            return st.text_area(
                "Query",
                height=240,
                key=_QUERY_KEY,
                placeholder=_PLACEHOLDER,
                help=_EDITOR_HELP,
                label_visibility="collapsed",
            )
    edited = st_ace(
        value=current,
        placeholder=_PLACEHOLDER,
        language="sparql",
        theme=_editor_theme(),
        height=260,
        font_size=14,
        tab_size=2,
        wrap=True,
        show_gutter=True,
        auto_update=True,
        key=f"sparql_ace_{st.session_state.get(_EDITOR_NONCE, 0)}",
    )
    edited = edited or ""
    st.session_state[_QUERY_KEY] = edited
    st.caption(_EDITOR_HELP)
    return edited


def _prefix_rows(ont) -> list[dict[str, str]]:
    """How to write a name in each namespace the ontology actually holds.

    Not every binding: the graph carries ~30 prefixes rdflib binds by default,
    almost none of which name anything here, and a list that long is one nobody
    reads. ``get_creatable_namespaces`` is the same set the entity forms offer
    — the base namespace, plus every namespace an existing entity or a bound
    import prefix puts in play — which is exactly where a prefixed name in a
    query can point and find something.
    """
    by_namespace: dict[str, list[str]] = {}
    for prefix, namespace in ont.graph.namespaces():
        by_namespace.setdefault(str(namespace), []).append(str(prefix))

    rows = []
    for namespace in ont.get_creatable_namespaces():
        bound = by_namespace.get(namespace, [])
        named = next((p for p in bound if p), None)
        if namespace == ont.base_uri:
            label = ":"
        elif named:
            label = f"{named}:"
        else:
            # Nothing names it, so the only way to write it is in full.
            label = f"<{namespace}…>"
        rows.append({"Prefix": label, "Namespace": namespace})
    return rows


def _render_prefixes(ont) -> None:
    """The namespaces in play, under the editor where a query is being written."""
    with st.expander("Prefixes in this ontology"):
        st.caption(_NAMESPACE_HINT)
        st.dataframe(_prefix_rows(ont), use_container_width=True, hide_index=True)
        st.caption(
            "`owl:`, `rdf:`, `rdfs:`, `xsd:`, `skos:`, `dc:` and `dcterms:` are "
            "always declared too, along with the prefixes rdflib binds by default."
        )


def _matched_nothing() -> None:
    """Say the result is empty, and name the likeliest reason it is.

    An empty result has no error to read, so the one thing worth pointing at is
    the mistake that produces one silently: a prefixed name resolved into a
    namespace the ontology does not use.
    """
    st.info("The query ran and matched nothing.")
    st.caption(f"{_NAMESPACE_HINT} The prefix list under the editor has them all.")


def _render_select_result(result: sparql.QueryResult) -> None:
    if not result.rows:
        # Only an empty result that actually finished matched nothing. A query
        # stopped by the deadline produced no rows *yet*, and telling the user
        # its answer is empty would be wrong.
        if not result.timed_out:
            _matched_nothing()
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
            _matched_nothing()
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

    query_text = _render_editor()
    _render_prefixes(ont)

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

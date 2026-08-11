"""The restrictions page."""

import streamlit as st

from ..ui import (
    LIST_PAGE_SIZE,
    _filter_restrictions,
    _open_entity,
    _paginate_rows,
    _restriction_matches_edge,
    _sort_restrictions,
    render_add_restriction,
    render_restriction_row,
)


def render_restrictions():
    """Render the restrictions management page."""
    st.header("Restrictions")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    restrictions = ont.get_restrictions()

    # Seeded in session_state rather than passed as ``default=``, the way the
    # Classes page already does it: the graph's "Open full editor" pre-sets this
    # key, and Streamlit warns when a keyed widget gets both (issue #152).
    if "rest_active_tab" not in st.session_state:
        st.session_state["rest_active_tab"] = "View Restrictions"
    _rest_tab = st.segmented_control(
        "Section",
        ["View Restrictions", "Add Restriction"],
        key="rest_active_tab",
        label_visibility="collapsed",
    )
    if not _rest_tab:
        _rest_tab = "View Restrictions"

    if _rest_tab == "View Restrictions":
        if not restrictions:
            st.info("No restrictions defined yet.")
        else:
            # Search + sort so a specific restriction is findable without
            # scrolling the whole list (issue #148).
            _rest_query = st.text_input(
                "Search restrictions",
                key="rest_search",
                placeholder="Bicycle hasPart Wheel",
                help=(
                    "Paste class, property and value to find just that "
                    "restriction, or type any words to match a property, type, "
                    "value or class. Use `*` for a part you don't want to pin."
                ),
            )
            _rest_sort = st.checkbox("Sort alphabetically", key="rest_sort")
            _view_restrictions = _filter_restrictions(restrictions, _rest_query)
            if _rest_sort:
                _view_restrictions = _sort_restrictions(_view_restrictions)
            if not _view_restrictions:
                st.caption("No restrictions match your search.")
            # A restriction edge in the graph asks for its row's editor here
            # (issue #152). Row keys are positional, so the row has to be found
            # in the list first — and the list paged to it.
            _open_edge = st.session_state.pop("_rest_open_edge", None)
            if _open_edge:
                _hit = next(
                    (
                        i
                        for i, r in enumerate(_view_restrictions)
                        if _restriction_matches_edge(r, tuple(_open_edge))
                    ),
                    None,
                )
                if _hit is not None:
                    _page = st.session_state.get("rest_page", 1)
                    if len(_view_restrictions) > LIST_PAGE_SIZE:
                        _page = _hit // LIST_PAGE_SIZE + 1
                        st.session_state["rest_page"] = _page
                        _hit %= LIST_PAGE_SIZE
                    _open_entity("rest", f"{_page}_{_hit}", "edit")
            # Rows rather than one expander each: a long list reads as a table
            # of class / property / type / value instead of a wall of collapsed
            # boxes, and it paginates like the Relations lists do.
            _rest_rows = _paginate_rows(_view_restrictions, "rest_page", "restrictions")
            # Read after paging, so the key the row gets is the page the selector
            # settled on rather than a stale one.
            _rest_page = st.session_state.get("rest_page", 1)
            for _row_i, rest in enumerate(_rest_rows):
                # Key by page and position: unique per render, and stable while
                # the page is. (Keying by the restriction itself would collide
                # when a class carries two identical ones.)
                render_restriction_row(
                    ont,
                    rest,
                    f"{_rest_page}_{_row_i}",
                    classes,
                    object_props + data_props,
                )

    if _rest_tab == "Add Restriction":
        render_add_restriction(ont, classes, object_props + data_props)

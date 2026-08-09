"""The relations page."""

import streamlit as st

from ..ui import (
    LIST_PAGE_SIZE,
    _apply_class_relation_add,
    _external_uri_target,
    _filter_relations,
    _open_entity,
    _pad_option,
    _paginate_rows,
    _relation_spec,
    _sort_relations,
    _uid,
    build_class_options,
    build_uri_options,
    missing_required,
    render_relation_rows,
    required_selectbox,
    save_checkpoint,
    show_message,
)


def render_relations():
    """Render the relations management page."""
    st.header("Relations")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    individuals = ont.get_individuals()

    # Seeded in session_state rather than passed as ``default=``, for the same
    # reason as the Restrictions page above (issue #152).
    if "rel_active_tab" not in st.session_state:
        st.session_state["rel_active_tab"] = "View Relations"
    _rel_tab = st.segmented_control(
        "Section",
        [
            "View Relations",
            "Class Relations",
            "Property Relations",
            "Individual Relations",
        ],
        key="rel_active_tab",
        label_visibility="collapsed",
    )
    if not _rel_tab:
        _rel_tab = "View Relations"

    if _rel_tab == "View Relations":
        st.subheader("All Relations")

        # Search + sort across all three relation lists (issue #148).
        _rel_query = st.text_input(
            "Search relations",
            key="rel_search",
            placeholder="capacitor disjointWith inductor",
            help=(
                "Paste a whole relation to find just that one, or type any words "
                "to match a subject, relation or object. Use `*` for a part you "
                "don't want to pin: `* disjointWith inductor`."
            ),
        )
        _rel_sort = st.checkbox("Sort alphabetically", key="rel_sort")

        def _prep_rels(rels):
            rels = _filter_relations(rels, _rel_query)
            return _sort_relations(rels) if _rel_sort else rels

        # Class relations
        _raw_class_relations = ont.get_class_relations()
        class_relations = _prep_rels(_raw_class_relations)
        # A relation edge in the graph asks for its row's editor here (issue
        # #152). The row key is URI-derived, so only the page has to be found;
        # the request is dropped either way, or a deleted relation would keep
        # asking to be opened.
        _open_edge = st.session_state.pop("_rel_open_edge", None)
        if _open_edge:
            _hit = next(
                (
                    i
                    for i, r in enumerate(class_relations)
                    if (r.get("subject_uri"), r["relation"], r.get("object_uri"))
                    == tuple(_open_edge)
                ),
                None,
            )
            if _hit is not None:
                if len(class_relations) > LIST_PAGE_SIZE:
                    st.session_state["rel_class_page"] = _hit // LIST_PAGE_SIZE + 1
                _open_entity("crel", _uid("|".join(_open_edge)), "edit")
        if _raw_class_relations:
            st.write("**Class Relations:**")
            if not class_relations:
                st.caption("No class relations match your search.")
            render_relation_rows(
                ont,
                _paginate_rows(class_relations, "rel_class_page", "class relations"),
                _relation_spec("crel", ont, classes),
            )
        else:
            st.info("No class relations defined.")

        st.divider()

        # Property relations
        _raw_prop_relations = ont.get_property_relations()
        prop_relations = _prep_rels(_raw_prop_relations)
        if _raw_prop_relations:
            st.write("**Property Relations:**")
            if not prop_relations:
                st.caption("No property relations match your search.")
            render_relation_rows(
                ont,
                _paginate_rows(prop_relations, "rel_prop_page", "property relations"),
                _relation_spec("prel", ont, object_props + data_props),
            )
        else:
            st.info("No property relations defined.")

        st.divider()

        # Individual relations
        _raw_ind_relations = ont.get_individual_relations()
        ind_relations = _prep_rels(_raw_ind_relations)
        if _raw_ind_relations:
            st.write("**Individual Relations:**")
            if not ind_relations:
                st.caption("No individual relations match your search.")
            render_relation_rows(
                ont,
                _paginate_rows(ind_relations, "rel_ind_page", "individual relations"),
                _relation_spec("irel", ont, individuals),
            )
        else:
            st.info("No individual relations defined.")

    if _rel_tab == "Class Relations":
        st.subheader("Add Class Relation")

        if len(classes) < 1:
            st.warning(
                "Add at least one class to create a relation "
                "(link it to another class or to an external URI)."
            )
        else:
            with st.form("add_class_relation_form"):
                cls_opts, cls_lookup = build_class_options(classes)
                col1, col2, col3 = st.columns(3)

                with col1:
                    class1_disp = required_selectbox(
                        "Class 1",
                        cls_opts,
                        key="crel_class1",
                        current_display=cls_opts[0] if cls_opts else None,
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.CLASS_RELATIONS),
                        key="crel_type",
                    )
                with col3:
                    class2_disp = required_selectbox(
                        "Class 2",
                        cls_opts,
                        key="crel_class2",
                        current_display=cls_opts[0] if cls_opts else None,
                        format_func=_pad_option,
                    )

                st.caption("""
                - **subClassOf**: Class 1 is a subclass of Class 2
                - **equivalentClass**: Class 1 and Class 2 have the same instances
                - **disjointWith**: Class 1 and Class 2 have no common instances
                """)

                class2_uri, ext_err = _external_uri_target(
                    ont,
                    cls_lookup.get(class2_disp),
                    key="crel_class2_ext",
                    label="Class 2",
                )
                submitted = st.form_submit_button("Add Class Relation")
                if submitted:
                    class2_show = (
                        class2_disp
                        if class2_uri == cls_lookup.get(class2_disp)
                        else class2_uri
                    )
                    # Class 2 is checked as the resolved target, since an
                    # external URI legitimately stands in for the pick.
                    if _missing := missing_required(
                        **{"Class 1": class1_disp, "Class 2": class2_uri}
                    ):
                        show_message(_missing, "error")
                    elif ext_err:
                        show_message(ext_err, "error")
                    elif _apply_class_relation_add(
                        ont,
                        cls_lookup.get(class1_disp),
                        relation_type,
                        class2_uri,
                        class1_disp,
                        class2_show,
                    ):
                        st.rerun()

    if _rel_tab == "Property Relations":
        st.subheader("Add Property Relation")

        all_props = object_props + data_props
        if len(all_props) < 1:
            st.warning(
                "Add at least one property to create a relation "
                "(link it to another property or to an external URI)."
            )
        else:
            with st.form("add_property_relation_form"):
                prop_opts, prop_lookup = build_uri_options(all_props)
                col1, col2, col3 = st.columns(3)

                with col1:
                    prop1_disp = required_selectbox(
                        "Property 1",
                        prop_opts,
                        key="prel_prop1",
                        current_display=prop_opts[0] if prop_opts else None,
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.PROPERTY_RELATIONS),
                        key="prel_type",
                    )
                with col3:
                    prop2_disp = required_selectbox(
                        "Property 2",
                        prop_opts,
                        key="prel_prop2",
                        current_display=prop_opts[0] if prop_opts else None,
                        format_func=_pad_option,
                    )

                st.caption("""
                - **subPropertyOf**: Property 1 is a sub-property of Property 2
                - **equivalentProperty**: Property 1 and Property 2 have the same meaning
                - **inverseOf**: Property 1 is the inverse of Property 2 (e.g., hasParent / hasChild)
                """)

                prop2_uri, ext_err = _external_uri_target(
                    ont,
                    prop_lookup.get(prop2_disp),
                    key="prel_prop2_ext",
                    label="Property 2",
                )
                submitted = st.form_submit_button("Add Property Relation")
                if submitted:
                    prop1_uri = prop_lookup.get(prop1_disp)
                    prop2_show = (
                        prop2_disp
                        if prop2_uri == prop_lookup.get(prop2_disp)
                        else prop2_uri
                    )
                    if _missing := missing_required(
                        **{"Property 1": prop1_disp, "Property 2": prop2_uri}
                    ):
                        show_message(_missing, "error")
                    elif ext_err:
                        show_message(ext_err, "error")
                    elif prop1_uri == prop2_uri:
                        show_message("Please select two different properties!", "error")
                    else:
                        ont.add_property_relation(prop1_uri, relation_type, prop2_uri)
                        save_checkpoint("Add property relation")
                        show_message(
                            f"Relation added: {prop1_disp} {relation_type} {prop2_show}",
                            "success",
                        )
                        st.rerun()

    if _rel_tab == "Individual Relations":
        st.subheader("Add Individual Relation")

        if len(individuals) < 1:
            st.warning(
                "Add at least one individual to create a relation "
                "(link it to another individual or to an external URI)."
            )
        else:
            with st.form("add_individual_relation_form"):
                ind_opts, ind_lookup = build_uri_options(individuals)
                col1, col2, col3 = st.columns(3)

                with col1:
                    ind1_disp = required_selectbox(
                        "Individual 1",
                        ind_opts,
                        key="irel_ind1",
                        current_display=ind_opts[0] if ind_opts else None,
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.INDIVIDUAL_RELATIONS),
                        key="irel_type",
                    )
                with col3:
                    ind2_disp = required_selectbox(
                        "Individual 2",
                        ind_opts,
                        key="irel_ind2",
                        current_display=ind_opts[0] if ind_opts else None,
                        format_func=_pad_option,
                    )

                st.caption("""
                - **sameAs**: Individual 1 and Individual 2 refer to the same entity
                - **differentFrom**: Individual 1 and Individual 2 are definitely different entities
                """)

                ind2_uri, ext_err = _external_uri_target(
                    ont,
                    ind_lookup.get(ind2_disp),
                    key="irel_ind2_ext",
                    label="Individual 2",
                )
                submitted = st.form_submit_button("Add Individual Relation")
                if submitted:
                    ind1_uri = ind_lookup.get(ind1_disp)
                    ind2_show = (
                        ind2_disp if ind2_uri == ind_lookup.get(ind2_disp) else ind2_uri
                    )
                    if _missing := missing_required(
                        **{"Individual 1": ind1_disp, "Individual 2": ind2_uri}
                    ):
                        show_message(_missing, "error")
                    elif ext_err:
                        show_message(ext_err, "error")
                    elif ind1_uri == ind2_uri:
                        show_message(
                            "Please select two different individuals!", "error"
                        )
                    else:
                        ont.add_individual_relation(ind1_uri, relation_type, ind2_uri)
                        save_checkpoint("Add individual relation")
                        show_message(
                            f"Relation added: {ind1_disp} {relation_type} {ind2_show}",
                            "success",
                        )
                        st.rerun()

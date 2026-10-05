"""The relations page."""

import streamlit as st

from ..ui import (
    LIST_PAGE_SIZE,
    _apply_class_relation_add,
    _external_uri_target,
    _filter_relations,
    _open_entity,
    _paginate_rows,
    _relation_spec,
    _sort_relations,
    _uid,
    build_class_options,
    build_entity_options,
    build_uri_options,
    missing_required,
    render_relation_rows,
    required_selectbox,
    save_checkpoint,
    set_flash_message,
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
            "Custom Relations",
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

        st.divider()

        # Custom relations (issue #484)
        _raw_custom_relations = ont.get_custom_relations()
        custom_relations = _prep_rels(_raw_custom_relations)
        # A custom relation edge in the graph asks for its row the way a class
        # relation edge does above.
        _open_custom = st.session_state.pop("_rel_open_custom_edge", None)
        if _open_custom:
            _hit = next(
                (
                    i
                    for i, r in enumerate(custom_relations)
                    if (r["subject_uri"], r["relation_uri"], r["object_uri"])
                    == tuple(_open_custom)
                ),
                None,
            )
            if _hit is not None:
                if len(custom_relations) > LIST_PAGE_SIZE:
                    st.session_state["rel_custom_page"] = _hit // LIST_PAGE_SIZE + 1
                _open_entity("cusrel", _uid("|".join(_open_custom)), "edit")
        if _raw_custom_relations:
            st.write("**Custom Relations:**")
            if not custom_relations:
                st.caption("No custom relations match your search.")
            render_relation_rows(
                ont,
                _paginate_rows(custom_relations, "rel_custom_page", "custom relations"),
                _relation_spec("cusrel", ont, []),
            )
        else:
            st.info("No custom relations defined.")

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

    if _rel_tab == "Custom Relations":
        _render_custom_relations_tab(ont)


def _render_custom_relations_tab(ont):
    """Add a custom relation, or convert restrictions into them (issue #484)."""
    st.subheader("Add Custom Relation")
    st.caption(
        "A direct link between two resources through a relation you name, such "
        "as `step1 nextItem step2`. The relation is declared as an annotation "
        "property, so the ontology stays OWL 2 DL and a sequence can be followed "
        "in SPARQL with a plain property path (`:nextItem*`). Reasoners give it "
        "no meaning: use a restriction when you need inference."
    )
    ent_opts, ent_lookup = build_entity_options(ont)
    if len(ent_opts) < 2:
        st.warning("Add at least two classes, properties or individuals to link.")
    else:
        types = {t["display"]: t["uri"] for t in ont.get_custom_relation_types()}
        with st.form("add_custom_relation_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                subj_disp = required_selectbox(
                    "Subject",
                    ent_opts,
                    key="cusrel_subject",
                    current_display=ent_opts[0],
                )
            with col2:
                type_disp = st.selectbox(
                    "Relation",
                    list(types),
                    index=None,
                    key="cusrel_type",
                    placeholder="Pick one, or name a new one below",
                )
                new_name = st.text_input(
                    "…or a new relation",
                    key="cusrel_new",
                    placeholder="nextItem",
                    help="A name like 'nextItem', a bound prefix like 'ex:next', "
                    "or a full URI. Overrides the pick above.",
                ).strip()
            with col3:
                obj_disp = required_selectbox(
                    "Object",
                    ent_opts,
                    key="cusrel_object",
                    current_display=ent_opts[0],
                )
            if st.form_submit_button("Add Custom Relation"):
                relation = new_name or types.get(type_disp or "")
                subj_uri = ent_lookup.get(subj_disp)
                obj_uri = ent_lookup.get(obj_disp)
                if _missing := missing_required(
                    Subject=subj_uri, Relation=relation, Object=obj_uri
                ):
                    show_message(_missing, "error")
                elif subj_uri == obj_uri:
                    show_message("Please select two different resources!", "error")
                else:
                    try:
                        ont.add_custom_relation(subj_uri, relation, obj_uri)
                    except ValueError as e:
                        show_message(str(e), "error")
                    else:
                        save_checkpoint("Add custom relation")
                        set_flash_message(
                            f"Relation added: {subj_disp} "
                            f"{new_name or type_disp} {obj_disp}",
                            "success",
                            toast=True,
                        )
                        st.rerun()

    st.divider()
    st.subheader("Convert Restrictions")
    st.caption(
        "Turn every `someValuesFrom` restriction on a property into a direct "
        "link: `A subClassOf (p some B)` becomes `A p B`. Other restrictions on "
        "the property are left as they are. Undo takes back the whole "
        "conversion."
    )
    props = ont.get_convertible_restriction_properties()
    if not props:
        st.info("No someValuesFrom restrictions between declared classes to convert.")
        return
    # Picked by URI: two properties can share a name, and a caption-keyed
    # list kept only one of them (Codex review of PR #493).
    by_uri = {p["uri"]: p for p in props}
    with st.form("convert_restrictions_form"):
        picked = st.selectbox(
            "Property",
            list(by_uri),
            format_func=lambda uri: (
                f"{by_uri[uri]['display']} ({by_uri[uri]['count']} "
                f"link{'s' if by_uri[uri]['count'] != 1 else ''})"
            ),
            key="cusrel_conv_prop",
        )
        relation = st.text_input(
            "Relation name",
            key="cusrel_conv_name",
            placeholder="Same as the property",
            help="Leave empty to keep the property's name. Keeping the "
            "restrictions needs a different name: a property used in a "
            "restriction is an object property, and OWL 2 DL does not allow it "
            "to be an annotation property as well.",
        ).strip()
        mode = st.radio(
            "Restrictions",
            ["Remove them (move)", "Keep them (copy)"],
            key="cusrel_conv_mode",
            horizontal=True,
        )
        if st.form_submit_button("Convert"):
            prop = by_uri[picked]
            try:
                made = ont.convert_restrictions_to_relations(
                    prop["uri"],
                    relation=relation or None,
                    keep_restrictions=mode.startswith("Keep"),
                )
            except ValueError as e:
                show_message(str(e), "error")
            else:
                save_checkpoint("Convert restrictions to custom relations")
                set_flash_message(
                    f"Converted {made} restriction link{'s' if made != 1 else ''} "
                    f"on {prop['display']} into custom relations.",
                    "success",
                    toast=True,
                )
                st.rerun()

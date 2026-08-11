"""The properties page."""

import streamlit as st

from ..ui import (
    _build_name_collision_set,
    _bulk_result_message,
    _cb_confirm_delete,
    _cb_toggle_edit,
    _cb_toggle_view,
    _cb_view_to_edit,
    _custom_uri_field,
    _disambiguated_name,
    _is_open,
    _namespace_option_index,
    _pad_option,
    _rename_or_move,
    _resolve_list_view,
    _uid,
    build_class_options,
    build_namespace_options,
    build_uri_options,
    clearable_selectbox,
    confirm_delete,
    get_ontology_manager_class,
    missing_required,
    required_selectbox,
    save_checkpoint,
    set_flash_message,
    show_message,
)


def render_properties():
    """Render the properties management page."""
    st.header("Properties")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    class_names = [c["name"] for c in classes]
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    obj_prop_names = [p["name"] for p in object_props]
    data_prop_names = [p["name"] for p in data_props]

    _prop_tab = st.segmented_control(
        "Section",
        [
            "Object Properties",
            "Data Properties",
            "Add Object Property",
            "Add Data Property",
            "Bulk Operations",
        ],
        default="Object Properties",
        key="prop_active_tab",
        label_visibility="collapsed",
    )
    if not _prop_tab:
        _prop_tab = "Object Properties"

    if _prop_tab == "Object Properties":
        st.subheader("Object Properties")
        if not object_props:
            st.info("No object properties defined yet.")
        else:
            # Filter by domain class
            filter_class_obj = st.selectbox(
                "Filter by Domain Class",
                options=["All"] + class_names + ["(No domain)"],
                key="filter_obj_prop_class",
            )

            filtered_obj_props = object_props
            if filter_class_obj == "(No domain)":
                filtered_obj_props = [p for p in object_props if not p["domain"]]
            elif filter_class_obj != "All":
                filtered_obj_props = [
                    p for p in object_props if p["domain"] == filter_class_obj
                ]

            st.caption(
                f"Showing {len(filtered_obj_props)} of {len(object_props)} properties"
            )

            op_collisions = _build_name_collision_set(object_props)
            filtered_obj_props, _ = _resolve_list_view(
                filtered_obj_props,
                "objprop",
                lambda p: _uid(p["uri"]),
                "objprop_view_page",
                "properties",
            )

            for prop in filtered_obj_props:
                prop_uid = _uid(prop["uri"])
                disp_name = _disambiguated_name(prop, op_collisions)
                _op_expanded = _is_open("objprop", prop_uid)
                with st.expander(
                    f"🔗 **{disp_name}** ({prop['domain'] or '?'} → {prop['range'] or '?'})",
                    expanded=_op_expanded,
                ):
                    st.write(
                        f"**URI:** `{prop['uri']}`"
                        if prop["uri"].startswith("http://example.org/")
                        else f"**URI:** {prop['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_objprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("objprop", prop_uid),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_objprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("objprop", prop_uid),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_objprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"objprop_{prop_uid}",),
                        )

                    # View details
                    if _is_open("objprop", prop_uid, "view"):
                        st.divider()
                        st.write(f"**Name:** {prop['name']}")
                        st.write(f"**Label:** {prop['label'] or '—'}")
                        st.write(f"**Comment:** {prop['comment'] or '—'}")
                        st.write(f"**Domain:** {prop['domain'] or '—'}")
                        st.write(f"**Range:** {prop['range'] or '—'}")
                        st.write(
                            f"**Characteristics:** {', '.join(prop['characteristics']) if prop['characteristics'] else '—'}"
                        )
                        st.write(f"**Inverse of:** {prop.get('inverse_of') or '—'}")
                        st.button(
                            "✏️ Edit",
                            key=f"btn_view_to_edit_objprop_{prop_uid}",
                            on_click=_cb_view_to_edit,
                            args=("objprop", prop_uid),
                        )

                    if confirm_delete(prop["uri"], "property", f"objprop_{prop_uid}"):
                        ont.delete_property(prop["uri"])
                        save_checkpoint("Delete property")
                        set_flash_message(f"Property '{disp_name}' deleted!", "success")
                        st.rerun()

                    # Inline edit form
                    if _is_open("objprop", prop_uid, "edit"):
                        st.divider()
                        with st.form(f"edit_objprop_form_{prop_uid}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=prop["name"],
                                key=f"objp_name_{prop_uid}",
                                help="Renaming updates every reference to this "
                                "property, including assertions that use it — "
                                "no links are lost.",
                            )
                            ns_opts, ns_lookup = build_namespace_options(ont)
                            ns_disp = required_selectbox(
                                "Namespace",
                                ns_opts,
                                key=f"objp_ns_{prop_uid}",
                                current_display=ns_opts[
                                    _namespace_option_index(
                                        ont, ns_opts, ns_lookup, prop["uri"]
                                    )
                                ]
                                if ns_opts
                                else None,
                                help="Moving to another namespace re-points "
                                "every reference to this property.",
                            )
                            new_namespace = ns_lookup.get(ns_disp)
                            new_name = _custom_uri_field(
                                prop["uri"],
                                new_name,
                                key=f"custom_uri_objp_{prop_uid}",
                            )
                            new_label = st.text_input(
                                "Label", value=prop["label"], key=f"objp_lbl_{prop_uid}"
                            )
                            new_comment = st.text_area(
                                "Comment",
                                value=prop["comment"],
                                key=f"objp_cmt_{prop_uid}",
                            )
                            # Build URI-keyed dropdowns for Domain/Range so a
                            # foaf:Organization domain isn't silently rewritten
                            # to myont:Organization on save.
                            cls_opts, cls_lookup = build_class_options(
                                classes, include_none=True
                            )
                            cur_dom_uri = prop.get("domain_uri", "")
                            cur_rng_uri = prop.get("range_uri", "")
                            cur_dom_disp = next(
                                (d for d, u in cls_lookup.items() if u == cur_dom_uri),
                                "None",
                            )
                            cur_rng_disp = next(
                                (d for d, u in cls_lookup.items() if u == cur_rng_uri),
                                "None",
                            )
                            col1, col2 = st.columns(2)
                            with col1:
                                dom_disp = clearable_selectbox(
                                    "Domain",
                                    cls_opts,
                                    key=f"objp_dom_{prop_uid}",
                                    current_display=cur_dom_disp
                                    if cur_dom_disp in cls_opts
                                    else None,
                                    format_func=_pad_option,
                                )
                            with col2:
                                rng_disp = clearable_selectbox(
                                    "Range",
                                    cls_opts,
                                    key=f"objp_rng_{prop_uid}",
                                    current_display=cur_rng_disp
                                    if cur_rng_disp in cls_opts
                                    else None,
                                    format_func=_pad_option,
                                )

                            if st.form_submit_button("Save Changes"):
                                # An empty namespace reads as the base URI, so a
                                # cleared one would move the property there and
                                # re-point every reference to it. Flashed rather
                                # than shown, since the rerun below would wipe
                                # anything drawn inline here.
                                if _missing := missing_required(Namespace=ns_disp):
                                    set_flash_message(_missing, "error")
                                    st.rerun()
                                if (
                                    new_name
                                    and new_name != prop["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                # Rename/move first so later updates hit the new URI.
                                ok, current_ref = _rename_or_move(
                                    ont,
                                    ont.rename_property,
                                    prop["uri"],
                                    prop["name"],
                                    new_name,
                                    new_namespace,
                                )
                                if not ok:
                                    show_message(
                                        f"Cannot move/rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                    st.rerun()

                                new_dom_uri = cls_lookup.get(dom_disp) or ""
                                new_rng_uri = cls_lookup.get(rng_disp) or ""
                                ont.update_property(
                                    current_ref,
                                    new_label=new_label,
                                    new_comment=new_comment,
                                    new_domain=new_dom_uri,
                                    new_range=new_rng_uri,
                                )
                                save_checkpoint("Update property")
                                st.session_state.pop("active_objprop", None)
                                show_message("Property updated!", "success")
                                st.rerun()

    if _prop_tab == "Data Properties":
        st.subheader("Data Properties")
        if not data_props:
            st.info("No data properties defined yet.")
        else:
            # Filter by domain class
            filter_class_data = st.selectbox(
                "Filter by Domain Class",
                options=["All"] + class_names + ["(No domain)"],
                key="filter_data_prop_class",
            )

            filtered_data_props = data_props
            if filter_class_data == "(No domain)":
                filtered_data_props = [p for p in data_props if not p["domain"]]
            elif filter_class_data != "All":
                filtered_data_props = [
                    p for p in data_props if p["domain"] == filter_class_data
                ]

            st.caption(
                f"Showing {len(filtered_data_props)} of {len(data_props)} properties"
            )

            datatypes = list(get_ontology_manager_class().XSD_DATATYPES.keys())

            dp_collisions = _build_name_collision_set(data_props)
            filtered_data_props, _ = _resolve_list_view(
                filtered_data_props,
                "dataprop",
                lambda p: _uid(p["uri"]),
                "dataprop_view_page",
                "properties",
            )

            for prop in filtered_data_props:
                prop_uid = _uid(prop["uri"])
                disp_name = _disambiguated_name(prop, dp_collisions)
                _dp_expanded = _is_open("dataprop", prop_uid)
                with st.expander(
                    f"📝 **{disp_name}** ({prop['domain'] or '?'} → {prop['range']})",
                    expanded=_dp_expanded,
                ):
                    st.write(
                        f"**URI:** `{prop['uri']}`"
                        if prop["uri"].startswith("http://example.org/")
                        else f"**URI:** {prop['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_dataprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("dataprop", prop_uid),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_dataprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("dataprop", prop_uid),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_dataprop_{prop_uid}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"dataprop_{prop_uid}",),
                        )

                    # View details
                    if _is_open("dataprop", prop_uid, "view"):
                        st.divider()
                        st.write(f"**Name:** {prop['name']}")
                        st.write(f"**Label:** {prop['label'] or '—'}")
                        st.write(f"**Comment:** {prop['comment'] or '—'}")
                        st.write(f"**Domain:** {prop['domain'] or '—'}")
                        st.write(f"**Range (Datatype):** {prop['range']}")
                        st.write(
                            f"**Functional:** {'Yes' if prop['functional'] else 'No'}"
                        )
                        st.button(
                            "✏️ Edit",
                            key=f"btn_view_to_edit_dataprop_{prop_uid}",
                            on_click=_cb_view_to_edit,
                            args=("dataprop", prop_uid),
                        )

                    if confirm_delete(prop["uri"], "property", f"dataprop_{prop_uid}"):
                        ont.delete_property(prop["uri"])
                        save_checkpoint("Delete property")
                        set_flash_message(f"Property '{disp_name}' deleted!", "success")
                        st.rerun()

                    # Inline edit form
                    if _is_open("dataprop", prop_uid, "edit"):
                        st.divider()
                        with st.form(f"edit_dataprop_form_{prop_uid}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=prop["name"],
                                key=f"dp_name_{prop_uid}",
                                help="Renaming updates every reference to this "
                                "property, including assertions that use it — "
                                "no links are lost.",
                            )
                            ns_opts, ns_lookup = build_namespace_options(ont)
                            ns_disp = required_selectbox(
                                "Namespace",
                                ns_opts,
                                key=f"dp_ns_{prop_uid}",
                                current_display=ns_opts[
                                    _namespace_option_index(
                                        ont, ns_opts, ns_lookup, prop["uri"]
                                    )
                                ]
                                if ns_opts
                                else None,
                                help="Moving to another namespace re-points "
                                "every reference to this property.",
                            )
                            new_namespace = ns_lookup.get(ns_disp)
                            new_name = _custom_uri_field(
                                prop["uri"],
                                new_name,
                                key=f"custom_uri_dp_{prop_uid}",
                            )
                            new_label = st.text_input(
                                "Label", value=prop["label"], key=f"dp_lbl_{prop_uid}"
                            )
                            new_comment = st.text_area(
                                "Comment",
                                value=prop["comment"],
                                key=f"dp_cmt_{prop_uid}",
                            )
                            cls_opts, cls_lookup = build_class_options(
                                classes, include_none=True
                            )
                            cur_dom_uri = prop.get("domain_uri", "")
                            cur_dom_disp = next(
                                (d for d, u in cls_lookup.items() if u == cur_dom_uri),
                                "None",
                            )
                            col1, col2 = st.columns(2)
                            with col1:
                                dom_disp = clearable_selectbox(
                                    "Domain",
                                    cls_opts,
                                    key=f"dp_dom_{prop_uid}",
                                    current_display=cur_dom_disp
                                    if cur_dom_disp in cls_opts
                                    else None,
                                    format_func=_pad_option,
                                )
                            with col2:
                                current_range = (
                                    prop["range"]
                                    if prop["range"] in datatypes
                                    else "string"
                                )
                                new_range = required_selectbox(
                                    "Range (Datatype)",
                                    datatypes,
                                    key=f"dp_rng_{prop_uid}",
                                    current_display=current_range,
                                )

                            if st.form_submit_button("Save Changes"):
                                # An empty namespace reads as the base URI, so a
                                # cleared one would move the property there and
                                # re-point every reference to it. Flashed rather
                                # than shown, since the rerun below would wipe
                                # anything drawn inline here.
                                if _missing := missing_required(
                                    **{
                                        "Namespace": ns_disp,
                                        "Range (Datatype)": new_range,
                                    }
                                ):
                                    set_flash_message(_missing, "error")
                                    st.rerun()
                                if (
                                    new_name
                                    and new_name != prop["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                # Rename/move first so later updates hit the new URI.
                                ok, current_ref = _rename_or_move(
                                    ont,
                                    ont.rename_property,
                                    prop["uri"],
                                    prop["name"],
                                    new_name,
                                    new_namespace,
                                )
                                if not ok:
                                    show_message(
                                        f"Cannot move/rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                    st.rerun()

                                new_dom_uri = cls_lookup.get(dom_disp) or ""
                                ont.update_property(
                                    current_ref,
                                    new_label=new_label,
                                    new_comment=new_comment,
                                    new_domain=new_dom_uri,
                                    new_range=new_range,
                                )
                                save_checkpoint("Update property")
                                st.session_state.pop("active_dataprop", None)
                                show_message("Property updated!", "success")
                                st.rerun()

    if _prop_tab == "Add Object Property":
        st.subheader("Add Object Property")

        # The mode selector lives ABOVE the form on purpose: widgets inside an
        # st.form don't trigger a rerun until submit, so an in-form radio could
        # not reactively swap the rendered fields.
        _op_mode = st.radio(
            "Mode",
            ["New property", "Reuse existing property"],
            horizontal=True,
            key="obj_prop_mode",
            help=(
                "Reuse links an existing property to another class pair via a "
                "restriction, so one property can connect many pairs "
                "(A→P→B, C→P→D) without duplicating it."
            ),
        )

        if _op_mode == "Reuse existing property":
            if not object_props:
                st.info(
                    "No object properties yet. Create one with **New property** "
                    "first, then reuse it here."
                )
            elif not classes:
                st.info("Add at least one class to link via a property.")
            else:
                st.caption(
                    "Reuse a single property across class pairs. Each pair is "
                    "recorded as a restriction on the source class, which is the "
                    "OWL-correct way to keep one property and intact reasoning "
                    "(repeating domain/range would intersect, not union)."
                )
                with st.form("reuse_obj_prop_form"):
                    reuse_opts, reuse_lookup = build_uri_options(object_props)
                    prop_disp = required_selectbox(
                        "Existing property *",
                        reuse_opts,
                        key="reuse_prop_existing",
                        current_display=reuse_opts[0] if reuse_opts else None,
                        format_func=_pad_option,
                    )

                    cls_opts, cls_lookup = build_class_options(classes)
                    col1, col2 = st.columns(2)
                    with col1:
                        source_disp = required_selectbox(
                            "Source class *",
                            cls_opts,
                            key="reuse_prop_source",
                            current_display=cls_opts[0] if cls_opts else None,
                            format_func=_pad_option,
                        )
                    with col2:
                        target_disp = required_selectbox(
                            "Target class *",
                            cls_opts,
                            key="reuse_prop_target",
                            current_display=cls_opts[0] if cls_opts else None,
                            format_func=_pad_option,
                        )

                    link_disp = st.radio(
                        "Link type",
                        ["allValuesFrom (recommended)", "someValuesFrom"],
                        key="reuse_link_type",
                        help=(
                            "allValuesFrom: if the source relates via this "
                            "property, the value is a target (types the pair, no "
                            "existence claim). someValuesFrom: the source relates "
                            "via this property to some target (asserts existence)."
                        ),
                    )

                    linked = st.form_submit_button("Link classes")
                    if linked:
                        prop_name = reuse_lookup.get(prop_disp)
                        source = cls_lookup.get(source_disp)
                        target = cls_lookup.get(target_disp)
                        if _missing := missing_required(
                            **{
                                "Existing property": prop_disp,
                                "Source class": source_disp,
                                "Target class": target_disp,
                            }
                        ):
                            show_message(_missing, "error")
                        elif not (prop_name and source and target):
                            show_message(
                                "Property, source and target are required!", "error"
                            )
                        else:
                            semantics = (
                                "some"
                                if link_disp.startswith("someValuesFrom")
                                else "all"
                            )
                            ont.link_classes(
                                source, prop_name, target, semantics=semantics
                            )
                            save_checkpoint("Reuse object property")
                            _rtype = (
                                "someValuesFrom"
                                if semantics == "some"
                                else "allValuesFrom"
                            )
                            show_message(
                                f"Linked {source_disp} → {prop_disp} → "
                                f"{target_disp} ({_rtype}).",
                                "success",
                            )
                            st.rerun()
        else:
            with st.form("add_obj_prop_form"):
                name = st.text_input("Property Name *")
                label = st.text_input("Label")
                comment = st.text_area("Comment")

                cls_opts, cls_lookup = build_class_options(classes, include_none=True)
                obj_prop_opts, obj_prop_lookup = build_uri_options(
                    object_props, include_none=True
                )
                col1, col2 = st.columns(2)
                with col1:
                    domain_disp = clearable_selectbox(
                        "Domain (Class)",
                        cls_opts,
                        key="add_objprop_domain",
                        current_display=cls_opts[0] if cls_opts else None,
                        format_func=_pad_option,
                    )
                with col2:
                    range_disp = clearable_selectbox(
                        "Range (Class)",
                        cls_opts,
                        key="add_objprop_range",
                        current_display=cls_opts[0] if cls_opts else None,
                        format_func=_pad_option,
                    )

                st.write("**Property Characteristics:**")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    functional = st.checkbox("Functional")
                    asymmetric = st.checkbox("Asymmetric")
                with col2:
                    inverse_functional = st.checkbox("Inverse Functional")
                    reflexive = st.checkbox("Reflexive")
                with col3:
                    transitive = st.checkbox("Transitive")
                    irreflexive = st.checkbox("Irreflexive")
                with col4:
                    symmetric = st.checkbox("Symmetric")

                inverse_disp = clearable_selectbox(
                    "Inverse Of",
                    obj_prop_opts,
                    key="add_objprop_inverse",
                    current_display=obj_prop_opts[0] if obj_prop_opts else None,
                    format_func=_pad_option,
                )
                ns_options, ns_lookup = build_namespace_options(ont)
                ns_display = clearable_selectbox(
                    "Namespace",
                    ns_options,
                    key="add_objprop_ns",
                    current_display=ns_options[0] if ns_options else None,
                    help="Namespace the property is created in (default is the base URI)",
                )

                submitted = st.form_submit_button("Add Object Property")
                if submitted:
                    ns_val = ns_lookup.get(ns_display)
                    prop_uris = {p["uri"] for p in object_props} | {
                        p["uri"] for p in data_props
                    }
                    if not name:
                        show_message("Property name is required!", "error")
                    elif reason := ont.invalid_name_reason(name):
                        show_message(reason, "error")
                    elif str(ont._uri(name, ns_val)) in prop_uris:
                        show_message(f"Property '{name}' already exists!", "error")
                    else:
                        ont.add_object_property(
                            name,
                            domain=cls_lookup.get(domain_disp),
                            range_=cls_lookup.get(range_disp),
                            label=label,
                            comment=comment,
                            functional=functional,
                            inverse_functional=inverse_functional,
                            transitive=transitive,
                            symmetric=symmetric,
                            asymmetric=asymmetric,
                            reflexive=reflexive,
                            irreflexive=irreflexive,
                            inverse_of=obj_prop_lookup.get(inverse_disp),
                            namespace=ns_val,
                        )
                        save_checkpoint("Add object property")
                        show_message(f"Object property '{name}' added!", "success")
                        st.rerun()

    if _prop_tab == "Add Data Property":
        st.subheader("Add Data Property")

        with st.form("add_data_prop_form"):
            name = st.text_input("Property Name *", key="data_prop_name")
            label = st.text_input("Label", key="data_prop_label")
            comment = st.text_area("Comment", key="data_prop_comment")

            cls_opts, cls_lookup = build_class_options(classes, include_none=True)
            col1, col2 = st.columns(2)
            with col1:
                domain_disp = clearable_selectbox(
                    "Domain (Class)",
                    cls_opts,
                    key="data_prop_domain",
                    current_display=cls_opts[0] if cls_opts else None,
                    format_func=_pad_option,
                )
            with col2:
                datatypes = list(get_ontology_manager_class().XSD_DATATYPES.keys())
                range_ = required_selectbox(
                    "Range (Datatype)",
                    datatypes,
                    key="data_prop_range",
                    current_display=datatypes[0] if datatypes else None,
                )

            functional = st.checkbox("Functional", key="data_prop_functional")
            ns_options, ns_lookup = build_namespace_options(ont)
            ns_display = clearable_selectbox(
                "Namespace",
                ns_options,
                key="data_prop_namespace",
                current_display=ns_options[0] if ns_options else None,
                help="Namespace the property is created in (default is the base URI)",
            )

            submitted = st.form_submit_button("Add Data Property")
            if submitted and (
                _missing := missing_required(**{"Range (Datatype)": range_})
            ):
                show_message(_missing, "error")
            elif submitted:
                ns_val = ns_lookup.get(ns_display)
                prop_uris = {p["uri"] for p in object_props} | {
                    p["uri"] for p in data_props
                }
                if not name:
                    show_message("Property name is required!", "error")
                elif reason := ont.invalid_name_reason(name):
                    show_message(reason, "error")
                elif str(ont._uri(name, ns_val)) in prop_uris:
                    show_message(f"Property '{name}' already exists!", "error")
                else:
                    ont.add_data_property(
                        name,
                        domain=cls_lookup.get(domain_disp),
                        range_=range_,
                        label=label,
                        comment=comment,
                        functional=functional,
                        namespace=ns_val,
                    )
                    save_checkpoint("Add data property")
                    show_message(f"Data property '{name}' added!", "success")
                    st.rerun()

    if _prop_tab == "Bulk Operations":
        import pandas as pd

        bulk_op = st.radio(
            "Operation", ["Add", "Edit", "Delete"], horizontal=True, key="bulk_prop_op"
        )

        if bulk_op == "Add":
            st.subheader("Bulk Add Properties")
            prop_type = st.radio(
                "Property Type",
                ["Object Property", "Data Property"],
                horizontal=True,
                key="bulk_prop_type",
            )
            st.caption(
                "Enter one property per line, or CSV: Name, Domain, Range, Label. "
                "Use ';' as the separator when a label contains commas."
            )
            bulk_text = st.text_area(
                "Property entries",
                height=200,
                key="bulk_props_text",
                placeholder="hasFriend\nhasEnemy\n\nor CSV:\nhasFriend, Person, Person, has friend",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(
                    bulk_text,
                    default_columns=["name", "domain", "range", "label"],
                )
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    ptype = "object" if prop_type == "Object Property" else "data"
                    if st.button(
                        "Create All Properties", type="primary", key="bulk_create_props"
                    ):
                        result = ont.bulk_add_properties(entries, property_type=ptype)
                        save_checkpoint("Bulk add properties")
                        _msg, _type = _bulk_result_message(result, "propert(ies)")
                        set_flash_message(_msg, _type)
                        st.rerun()

        elif bulk_op == "Edit":
            st.subheader("Bulk Edit Properties")
            st.caption("Edit property labels in a spreadsheet.")
            all_props = object_props + data_props
            if not all_props:
                st.info("No properties to edit.")
            else:
                edit_data = [
                    {
                        "Name": p["name"],
                        "Label": p.get("label") or "",
                        "Type": "Object" if p in object_props else "Data",
                        "Domain": p.get("domain") or "",
                        "Range": p.get("range") or "",
                    }
                    for p in all_props
                ]
                df = pd.DataFrame(edit_data)
                edited_df = st.data_editor(
                    df,
                    key="bulk_edit_props_editor",
                    width="stretch",
                    disabled=["Name", "Type"],
                )
                if st.button("Apply Changes", type="primary", key="bulk_apply_props"):
                    changes = 0
                    for _, row in edited_df.iterrows():
                        orig = next(
                            (p for p in all_props if p["name"] == row["Name"]), None
                        )
                        if not orig:
                            continue
                        new_label = row["Label"]
                        old_label = orig.get("label") or ""
                        if new_label != old_label:
                            ont.update_property(row["Name"], new_label=new_label)
                            changes += 1
                    if changes:
                        save_checkpoint("Bulk edit properties")
                        show_message(f"Updated {changes} propert(ies)", "success")
                        st.rerun()
                    else:
                        show_message("No changes detected.", "info")

        else:  # Delete
            st.subheader("Bulk Delete Properties")
            all_prop_names = obj_prop_names + data_prop_names
            if not all_prop_names:
                st.info("No properties to delete.")
            else:
                selected = st.multiselect(
                    "Select properties to delete",
                    all_prop_names,
                    key="bulk_delete_props_select",
                )
                if selected:
                    st.warning(
                        f"This will delete {len(selected)} propert(ies) and all their references."
                    )
                    if st.button(
                        "Delete Selected", type="primary", key="bulk_delete_props_btn"
                    ):
                        result = ont.bulk_delete_properties(selected)
                        save_checkpoint("Bulk delete properties")
                        show_message(
                            f"Deleted {len(result['deleted'])} propert(ies)", "success"
                        )
                        st.rerun()

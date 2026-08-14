"""The individuals page."""

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
    _rename_or_move,
    _resolve_list_view,
    _uid,
    build_namespace_options,
    clearable_selectbox,
    confirm_delete,
    missing_required,
    required_selectbox,
    save_checkpoint,
    set_flash_message,
    show_message,
)


def render_individuals():
    """Render the individuals management page."""
    st.header("Individuals")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    class_names = [c["name"] for c in classes]
    individuals = ont.get_individuals()
    ind_names = [i["name"] for i in individuals]
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()

    _ind_tab = st.segmented_control(
        "Section",
        ["View Individuals", "Add Individual", "Add Property Value", "Bulk Operations"],
        default="View Individuals",
        key="ind_active_tab",
        label_visibility="collapsed",
    )
    if not _ind_tab:
        _ind_tab = "View Individuals"

    if _ind_tab == "View Individuals":
        if not individuals:
            st.info("No individuals defined yet.")
        else:
            # Use URI hash for unique widget keys (name may not be unique across namespaces)
            ind_collisions = _build_name_collision_set(individuals)

            # Master `individuals` list is reused elsewhere in this page, so keep
            # it intact and iterate only the current page here.
            _page_inds, _ = _resolve_list_view(
                individuals,
                "ind",
                lambda i: _uid(i["uri"]),
                "ind_view_page",
                "individuals",
            )

            for ind in _page_inds:
                classes_str = (
                    ", ".join(ind["classes"]) if ind["classes"] else "No class"
                )
                _ik = _uid(ind["uri"])
                disp_ind_name = _disambiguated_name(ind, ind_collisions)
                _ind_expanded = _is_open("ind", _ik)
                with st.expander(
                    f"👤 **{disp_ind_name}** ({classes_str})", expanded=_ind_expanded
                ):
                    st.write(
                        f"**URI:** `{ind['uri']}`"
                        if ind["uri"].startswith("http://example.org/")
                        else f"**URI:** {ind['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_ind_{_ik}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("ind", _ik),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_ind_{_ik}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("ind", _ik),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_ind_{_ik}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"ind_{_ik}",),
                        )

                    # View details
                    if _is_open("ind", _ik, "view"):
                        st.divider()
                        st.write(f"**Name:** {ind['name']}")
                        st.write(f"**Label:** {ind['label'] or '—'}")
                        st.write(f"**Comment:** {ind['comment'] or '—'}")
                        st.write(
                            f"**Classes:** {', '.join(ind['classes']) if ind['classes'] else '—'}"
                        )
                        if ind["properties"]:
                            st.write("**Property Values:**")
                            for prop in ind["properties"]:
                                st.write(f"  - {prop['property']}: {prop['value']}")
                        else:
                            st.write("**Property Values:** —")
                        st.button(
                            "✏️ Edit",
                            key=f"btn_view_to_edit_ind_{_ik}",
                            on_click=_cb_view_to_edit,
                            args=("ind", _ik),
                        )

                    if confirm_delete(ind["uri"], "individual", f"ind_{_ik}"):
                        ont.delete_individual(ind["uri"])
                        save_checkpoint("Delete individual")
                        set_flash_message(
                            f"Individual '{disp_ind_name}' deleted!", "success"
                        )
                        st.rerun()

                    # Resource usages
                    with st.expander("Show Usages", expanded=False):
                        usages = ont.get_resource_usages(ind["uri"])
                        if usages["inbound"]:
                            st.markdown("**Referenced by:**")
                            for u in usages["inbound"]:
                                st.write(f"- {u['subject']} *{u['predicate']}*")
                        if usages["outbound"]:
                            st.markdown("**References:**")
                            for u in usages["outbound"]:
                                st.write(f"- *{u['predicate']}* {u['object']}")
                        if not usages["inbound"] and not usages["outbound"]:
                            st.caption("No usages found.")

                    # Inline edit form
                    if _is_open("ind", _ik, "edit"):
                        st.divider()
                        with st.form(f"edit_ind_form_{_ik}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=ind["name"],
                                key=f"ind_name_{_ik}",
                                help="Renaming updates every reference to this "
                                "individual — no links are lost, unlike "
                                "delete-and-recreate.",
                            )
                            ns_opts, ns_lookup = build_namespace_options(ont)
                            ns_disp = required_selectbox(
                                "Namespace",
                                ns_opts,
                                key=f"ind_ns_{_ik}",
                                current_display=ns_opts[
                                    _namespace_option_index(
                                        ont, ns_opts, ns_lookup, ind["uri"]
                                    )
                                ]
                                if ns_opts
                                else None,
                                help="Moving to another namespace re-points "
                                "every reference to this individual.",
                            )
                            new_namespace = ns_lookup.get(ns_disp)
                            new_name = _custom_uri_field(
                                ind["uri"], new_name, key=f"custom_uri_ind_{_ik}"
                            )
                            new_label = st.text_input(
                                "Label", value=ind["label"], key=f"ind_lbl_{_ik}"
                            )
                            new_comment = st.text_area(
                                "Comment", value=ind["comment"], key=f"ind_cmt_{_ik}"
                            )

                            st.write("**Manage Classes:**")
                            current_classes = ind["classes"]
                            available_classes = [
                                c for c in class_names if c not in current_classes
                            ]

                            col1, col2 = st.columns(2)
                            with col1:
                                add_class = clearable_selectbox(
                                    "Add to Class",
                                    ["None"] + available_classes,
                                    key=f"ind_add_cls_{_ik}",
                                    current_display="None",
                                )
                            with col2:
                                remove_class = clearable_selectbox(
                                    "Remove from Class",
                                    ["None"] + current_classes,
                                    key=f"ind_rem_cls_{_ik}",
                                    current_display="None",
                                )

                            if st.form_submit_button("Save Changes"):
                                # An empty namespace reads as the base URI, so a
                                # cleared one would move the individual there
                                # and re-point every reference to it.
                                if _missing := missing_required(Namespace=ns_disp):
                                    set_flash_message(_missing, "error")
                                    st.rerun()
                                if (
                                    new_name
                                    and new_name != ind["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                # Rename/move first so later updates hit the new URI.
                                ok, current_ref = _rename_or_move(
                                    ont,
                                    "individual",
                                    ont.rename_individual,
                                    ind["uri"],
                                    ind["name"],
                                    new_name,
                                    new_namespace,
                                )
                                if not ok:
                                    show_message(
                                        f"Cannot move/rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                    st.rerun()

                                ont.update_individual(
                                    current_ref,
                                    new_label=new_label,
                                    new_comment=new_comment,
                                    add_class=add_class
                                    if add_class != "None"
                                    else None,
                                    remove_class=remove_class
                                    if remove_class != "None"
                                    else None,
                                )
                                save_checkpoint("Update individual")
                                st.session_state.pop("active_ind", None)
                                show_message("Individual updated!", "success")
                                st.rerun()

    if _ind_tab == "Add Individual":
        st.subheader("Add Individual")

        if not class_names:
            st.warning("Please create at least one class before adding individuals.")
        else:
            with st.form("add_individual_form"):
                name = st.text_input("Individual Name *")
                label = st.text_input("Label")
                comment = st.text_area("Comment")
                class_type = required_selectbox(
                    "Class Type *",
                    class_names,
                    key="add_ind_class_type",
                    current_display=class_names[0] if class_names else None,
                )
                ns_options, ns_lookup = build_namespace_options(ont)
                ns_display = clearable_selectbox(
                    "Namespace",
                    ns_options,
                    key="add_ind_ns",
                    current_display=ns_options[0] if ns_options else None,
                    help="Namespace the individual is created in (default is the base URI)",
                )

                submitted = st.form_submit_button("Add Individual")
                if submitted:
                    ns_val = ns_lookup.get(ns_display)
                    if _missing := missing_required(**{"Class Type": class_type}):
                        show_message(_missing, "error")
                    elif not name:
                        show_message("Individual name is required!", "error")
                    elif reason := ont.invalid_name_reason(name):
                        show_message(reason, "error")
                    elif taken := ont.name_conflict_reason(name, "individual", ns_val):
                        show_message(taken, "error")
                    else:
                        ont.add_individual(
                            name,
                            class_type,
                            label=label,
                            comment=comment,
                            namespace=ns_val,
                        )
                        save_checkpoint("Add individual")
                        show_message(f"Individual '{name}' added!", "success")
                        st.rerun()

    if _ind_tab == "Add Property Value":
        st.subheader("Add Property Value to Individual")

        if not individuals:
            st.warning("Please create at least one individual first.")
        elif not object_props and not data_props:
            st.warning("Please create at least one property first.")
        else:
            with st.form("add_prop_value_form"):
                individual = required_selectbox(
                    "Select Individual",
                    ind_names,
                    key="add_pv_individual",
                    current_display=ind_names[0] if ind_names else None,
                )

                prop_type = st.radio(
                    "Property Type", ["Object Property", "Data Property"]
                )

                if prop_type == "Object Property":
                    prop_options = [p["name"] for p in object_props]
                    property_name = required_selectbox(
                        "Property",
                        prop_options if prop_options else ["No properties"],
                        key="add_pv_obj_prop",
                        current_display=(prop_options or ["No properties"])[0],
                    )
                    value = required_selectbox(
                        "Value (Individual)",
                        ind_names,
                        key="add_pv_obj_value",
                        current_display=ind_names[0] if ind_names else None,
                    )
                    is_object = True
                else:
                    prop_options = [p["name"] for p in data_props]
                    property_name = required_selectbox(
                        "Property",
                        prop_options if prop_options else ["No properties"],
                        key="add_pv_data_prop",
                        current_display=(prop_options or ["No properties"])[0],
                    )
                    value = st.text_input("Value")
                    is_object = False

                submitted = st.form_submit_button("Add Property Value")
                if submitted:
                    if _missing := missing_required(
                        **{"Select Individual": individual, "Property": property_name}
                    ):
                        show_message(_missing, "error")
                    elif property_name == "No properties":
                        show_message("Please select a property!", "error")
                    elif not value:
                        show_message("Please provide a value!", "error")
                    else:
                        ont.add_individual_property(
                            individual,
                            property_name,
                            value,
                            is_object_property=is_object,
                        )
                        save_checkpoint("Add property assertion")
                        show_message(
                            f"Property value added to '{individual}'!", "success"
                        )
                        st.rerun()

    if _ind_tab == "Bulk Operations":
        import pandas as pd

        bulk_op = st.radio(
            "Operation", ["Add", "Edit", "Delete"], horizontal=True, key="bulk_ind_op"
        )

        if bulk_op == "Add":
            st.subheader("Bulk Add Individuals")
            st.caption(
                "Enter one individual per line as CSV: Name, Class, Label. "
                "Use ';' as the separator when a label contains commas."
            )
            bulk_text = st.text_area(
                "Individual entries",
                height=200,
                key="bulk_individuals_text",
                placeholder="alice, Person, Alice\nbob, Person, Bob",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(
                    bulk_text, default_columns=["name", "class", "label"]
                )
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    if st.button(
                        "Create All Individuals",
                        type="primary",
                        key="bulk_create_individuals",
                    ):
                        result = ont.bulk_add_individuals(entries)
                        save_checkpoint("Bulk add individuals")
                        _msg, _type = _bulk_result_message(result, "individual(s)")
                        set_flash_message(_msg, _type)
                        st.rerun()

        elif bulk_op == "Edit":
            st.subheader("Bulk Edit Individuals")
            st.caption("Edit individual labels in a spreadsheet.")
            if not individuals:
                st.info("No individuals to edit.")
            else:
                edit_data = [
                    {
                        "Name": i["name"],
                        "Label": i.get("label") or "",
                        "Class": ", ".join(i.get("classes", [])),
                    }
                    for i in individuals
                ]
                df = pd.DataFrame(edit_data)
                edited_df = st.data_editor(
                    df,
                    key="bulk_edit_ind_editor",
                    width="stretch",
                    disabled=["Name", "Class"],
                )
                if st.button("Apply Changes", type="primary", key="bulk_apply_ind"):
                    changes = 0
                    for _, row in edited_df.iterrows():
                        orig = next(
                            (i for i in individuals if i["name"] == row["Name"]), None
                        )
                        if not orig:
                            continue
                        new_label = row["Label"]
                        old_label = orig.get("label") or ""
                        if new_label != old_label:
                            ont.update_individual(row["Name"], new_label=new_label)
                            changes += 1
                    if changes:
                        save_checkpoint("Bulk edit individuals")
                        show_message(f"Updated {changes} individual(s)", "success")
                        st.rerun()
                    else:
                        show_message("No changes detected.", "info")

        else:  # Delete
            st.subheader("Bulk Delete Individuals")
            if not individuals:
                st.info("No individuals to delete.")
            else:
                selected = st.multiselect(
                    "Select individuals to delete",
                    ind_names,
                    key="bulk_delete_ind_select",
                )
                if selected:
                    st.warning(
                        f"This will delete {len(selected)} individual(s) and all their references."
                    )
                    if st.button(
                        "Delete Selected", type="primary", key="bulk_delete_ind_btn"
                    ):
                        result = ont.bulk_delete_individuals(selected)
                        save_checkpoint("Bulk delete individuals")
                        show_message(
                            f"Deleted {len(result['deleted'])} individual(s)", "success"
                        )
                        st.rerun()

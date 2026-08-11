"""The classes page."""

import streamlit as st

from ..ui import (
    _apply_class_edit,
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
    _renamed_ref,
    _resolve_list_view,
    _uid,
    build_class_options,
    build_namespace_options,
    clearable_selectbox,
    confirm_delete,
    format_label_name,
    missing_required,
    render_add_class_form,
    required_selectbox,
    save_checkpoint,
    set_flash_message,
    show_message,
)


def render_classes():
    """Render the classes management page."""
    st.header("Classes")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    class_names = [c["name"] for c in classes]

    # Seed the selection in session_state rather than passing ``default=``:
    # graph-view "Open editor" pre-sets this key (see _open_full_editor) before
    # the widget renders, and Streamlit warns when a keyed widget gets both a
    # ``default`` and a session-state value. Seeding only when unset keeps that
    # programmatic selection intact and silences the warning.
    if "cls_active_tab" not in st.session_state:
        st.session_state["cls_active_tab"] = "View Classes"
    _cls_tab = st.segmented_control(
        "Section",
        ["View Classes", "Add Class", "Edit/Delete Class", "Bulk Operations"],
        key="cls_active_tab",
        label_visibility="collapsed",
    )
    if not _cls_tab:
        _cls_tab = "View Classes"

    if _cls_tab == "View Classes":
        if not classes:
            st.info("No classes defined yet. Add a class to get started.")
        else:
            # Class hierarchy view
            st.subheader("Class Hierarchy")

            collisions = _build_name_collision_set(classes)

            # Sort classes by display name, but put actively viewed class first
            sorted_classes = sorted(
                classes,
                key=lambda c: format_label_name(
                    _disambiguated_name(c, collisions), c.get("label")
                ).lower(),
            )

            # Single-active selection + pagination (issues #140 / #143 / #146).
            # The full list stays available in the "All Classes" table below.
            _page_classes, _ = _resolve_list_view(
                sorted_classes,
                "class",
                lambda c: _uid(c["uri"]),
                "cls_view_page",
                "classes",
            )

            for cls in _page_classes:
                cls_uid = _uid(cls["uri"])
                disp_name = _disambiguated_name(cls, collisions)
                display_name = format_label_name(disp_name, cls.get("label"))
                _cls_expanded = _is_open("class", cls_uid)
                with st.expander(f"📦 **{display_name}**", expanded=_cls_expanded):
                    st.write(
                        f"**URI:** `{cls['uri']}`"
                        if cls["uri"].startswith("http://example.org/")
                        else f"**URI:** {cls['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_class_{cls_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("class", cls_uid),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_class_{cls_uid}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("class", cls_uid),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_class_{cls_uid}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"class_{cls_uid}",),
                        )

                    # View details
                    if _is_open("class", cls_uid, "view"):
                        st.divider()
                        st.write(f"**Name:** {cls['name']}")
                        st.write(f"**Label:** {cls['label'] or '—'}")
                        st.write(f"**Comment:** {cls['comment'] or '—'}")
                        st.write(
                            f"**Parent Class:** {', '.join(cls['parents']) if cls['parents'] else '—'}"
                        )
                        if cls["children"]:
                            st.write(f"**Children:** {', '.join(cls['children'])}")
                        st.button(
                            "✏️ Edit",
                            key=f"btn_view_to_edit_class_{cls_uid}",
                            on_click=_cb_view_to_edit,
                            args=("class", cls_uid),
                        )

                    if confirm_delete(cls["uri"], "class", f"class_{cls_uid}"):
                        ont.delete_class(cls["uri"])
                        save_checkpoint("Delete class")
                        set_flash_message(f"Class '{disp_name}' deleted!", "success")
                        st.rerun()

                    # Inline edit form
                    if _is_open("class", cls_uid, "edit"):
                        st.divider()
                        with st.form(f"edit_class_form_{cls_uid}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=cls["name"],
                                key=f"name_{cls_uid}",
                                help="Renaming updates every reference to this "
                                "class — no links are lost, unlike "
                                "delete-and-recreate.",
                            )
                            new_label = st.text_input(
                                "Label", value=cls["label"], key=f"lbl_{cls_uid}"
                            )
                            new_comment = st.text_area(
                                "Comment", value=cls["comment"], key=f"cmt_{cls_uid}"
                            )
                            other_classes = [c for c in class_names if c != cls["name"]]
                            current_parent = (
                                cls["parents"][0] if cls["parents"] else "None"
                            )
                            new_parent = clearable_selectbox(
                                "Parent Class",
                                ["None"] + other_classes,
                                key=f"par_{cls_uid}",
                                current_display=current_parent
                                if current_parent in other_classes
                                else "None",
                            )

                            if st.form_submit_button("Save Changes"):
                                # Handle rename first — pass URI so cross-namespace duplicates resolve correctly
                                current_ref = cls["uri"]
                                if new_name and new_name != cls["name"]:
                                    if reason := ont.invalid_name_reason(new_name):
                                        show_message(reason, "error")
                                        st.rerun()
                                    if ont.rename_class(cls["uri"], new_name):
                                        # Rename preserves the class's namespace.
                                        current_ref = _renamed_ref(
                                            ont, cls["uri"], new_name
                                        )
                                        save_checkpoint("Rename class")
                                        show_message(
                                            f"Class renamed to '{new_name}'", "success"
                                        )
                                    else:
                                        show_message(
                                            f"Cannot rename: '{new_name}' already exists!",
                                            "error",
                                        )
                                        st.rerun()

                                if cls["parents"] and new_parent != cls["parents"][0]:
                                    ont.update_class(
                                        current_ref, remove_parent=cls["parents"][0]
                                    )
                                ont.update_class(
                                    current_ref,
                                    new_label=new_label,
                                    new_comment=new_comment,
                                    new_parent=new_parent
                                    if new_parent != "None"
                                    else None,
                                )
                                save_checkpoint("Update class")
                                st.session_state.pop("active_class", None)
                                show_message("Class updated!", "success")
                                st.rerun()

            # Table view
            st.subheader("All Classes")
            class_data = []
            for c in sorted_classes:
                class_data.append(
                    {
                        "Name": c["name"],
                        "Label": c["label"],
                        "Parents": ", ".join(c["parents"]),
                        "Children": ", ".join(c["children"]),
                        "Comment": c["comment"][:50] + "..."
                        if len(c["comment"]) > 50
                        else c["comment"],
                    }
                )
            st.dataframe(class_data, width="stretch")

    if _cls_tab == "Add Class":
        st.subheader("Add New Class")
        if render_add_class_form(ont, classes, "add_class_form"):
            st.rerun()

    if _cls_tab == "Edit/Delete Class":
        st.subheader("Edit or Delete Class")

        if not classes:
            st.info("No classes to edit.")
        else:
            # Build options with disambiguated name · Label format; lookup is by URI
            class_options, class_lookup = build_class_options(classes)
            selected_display = clearable_selectbox(
                "Select Class",
                class_options,
                key="edit_class_select",
                current_display=class_options[0] if class_options else None,
                format_func=_pad_option,
            )
            selected_uri = class_lookup.get(selected_display)
            class_info = (
                next((c for c in classes if c["uri"] == selected_uri), None)
                if selected_uri
                else None
            )

            if class_info:
                selected_uid = _uid(class_info["uri"])
                selected_class = class_info[
                    "name"
                ]  # local-name shorthand for messaging
                st.subheader(f"Edit: {selected_display}")

                with st.form("edit_class_form"):
                    new_name = st.text_input(
                        "Name (URI local part)",
                        value=class_info["name"],
                        help="Renaming updates every reference to this class — "
                        "no links are lost, unlike delete-and-recreate.",
                    )
                    ns_options, ns_lookup = build_namespace_options(ont)
                    ns_index = _namespace_option_index(
                        ont, ns_options, ns_lookup, class_info["uri"]
                    )
                    new_ns_display = required_selectbox(
                        "Namespace",
                        ns_options,
                        key=f"edit_cls_ns_{selected_uid}",
                        current_display=ns_options[ns_index] if ns_options else None,
                        help="Moving to another namespace re-points every "
                        "reference to this class.",
                    )
                    new_namespace = ns_lookup.get(new_ns_display)
                    new_name = _custom_uri_field(
                        class_info["uri"],
                        new_name,
                        key=f"custom_uri_class_{selected_uid}",
                    )
                    new_label = st.text_input("Label", value=class_info["label"])
                    new_comment = st.text_area("Comment", value=class_info["comment"])

                    other_classes = [c for c in class_names if c != selected_class]
                    current_parent = (
                        class_info["parents"][0] if class_info["parents"] else "None"
                    )
                    new_parent = clearable_selectbox(
                        "Parent Class",
                        ["None"] + other_classes,
                        key=f"edit_cls_parent_{selected_uid}",
                        current_display=current_parent
                        if current_parent in other_classes
                        else "None",
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        update_btn = st.form_submit_button("Update Class")
                    with col2:
                        delete_btn = st.form_submit_button(
                            "Delete Class", type="secondary"
                        )

                    if update_btn and (
                        _missing := missing_required(Namespace=new_ns_display)
                    ):
                        # An empty namespace reads as the base URI, so a cleared
                        # one would move the class there and re-point every
                        # reference, silently.
                        show_message(_missing, "error")
                    elif update_btn:
                        if _apply_class_edit(
                            ont,
                            class_info,
                            new_name,
                            new_label,
                            new_comment,
                            new_parent,
                            new_namespace=new_namespace,
                        ):
                            save_checkpoint("Update class")
                            show_message(
                                f"Class '{new_name or selected_display}' updated!",
                                "success",
                            )
                        st.rerun()

                    if delete_btn:
                        st.session_state[
                            f"confirm_delete_class_detail_{selected_uid}"
                        ] = True
                        st.rerun()

                if confirm_delete(
                    class_info["uri"], "class", f"class_detail_{selected_uid}"
                ):
                    ont.delete_class(class_info["uri"])
                    save_checkpoint("Delete class")
                    set_flash_message(f"Class '{selected_display}' deleted!", "success")
                    st.rerun()

                # Resource usages / backlinks
                with st.expander("Show Usages"):
                    usages = ont.get_resource_usages(class_info["uri"])
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

    if _cls_tab == "Bulk Operations":
        import pandas as pd

        bulk_op = st.radio(
            "Operation", ["Add", "Edit", "Delete"], horizontal=True, key="bulk_class_op"
        )

        if bulk_op == "Add":
            st.subheader("Bulk Add Classes")
            st.caption(
                "Enter one class name per line, or use CSV format: Name, Label, "
                "Parent. Use ';' as the separator when a label contains commas."
            )
            bulk_text = st.text_area(
                "Class entries",
                height=200,
                key="bulk_classes_text",
                placeholder="Dog\nCat\nBird\n\nor CSV:\nDog, A Dog, Animal\nCat, A Cat, Animal",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(
                    bulk_text, default_columns=["name", "label", "parent"]
                )
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    if st.button(
                        "Create All Classes", type="primary", key="bulk_create_classes"
                    ):
                        result = ont.bulk_add_classes(entries)
                        save_checkpoint("Bulk add classes")
                        _msg, _type = _bulk_result_message(result, "class(es)")
                        set_flash_message(_msg, _type)
                        st.rerun()

        elif bulk_op == "Edit":
            st.subheader("Bulk Edit Classes")
            st.caption("Edit class labels and comments in a spreadsheet.")
            if not classes:
                st.info("No classes to edit.")
            else:
                edit_data = [
                    {
                        "Name": c["name"],
                        "Label": c.get("label") or "",
                        "Comment": c.get("comment") or "",
                        "Parent": c["parents"][0] if c.get("parents") else "",
                    }
                    for c in classes
                ]
                df = pd.DataFrame(edit_data)
                edited_df = st.data_editor(
                    df,
                    key="bulk_edit_classes_editor",
                    width="stretch",
                    disabled=["Name"],
                )
                if st.button("Apply Changes", type="primary", key="bulk_apply_classes"):
                    changes = 0
                    for _, row in edited_df.iterrows():
                        orig = next(
                            (c for c in classes if c["name"] == row["Name"]), None
                        )
                        if not orig:
                            continue
                        new_label = (
                            row["Label"]
                            if row["Label"] != (orig.get("label") or "")
                            else None
                        )
                        new_comment = (
                            row["Comment"]
                            if row["Comment"] != (orig.get("comment") or "")
                            else None
                        )
                        old_parent = orig["parents"][0] if orig.get("parents") else ""
                        new_parent = row["Parent"]
                        if (
                            new_label is not None
                            or new_comment is not None
                            or new_parent != old_parent
                        ):
                            ont.update_class(
                                row["Name"],
                                new_label=row["Label"]
                                if new_label is not None
                                else None,
                                new_comment=row["Comment"]
                                if new_comment is not None
                                else None,
                                remove_parent=old_parent
                                if old_parent and new_parent != old_parent
                                else None,
                                new_parent=new_parent
                                if new_parent and new_parent != old_parent
                                else None,
                            )
                            changes += 1
                    if changes:
                        save_checkpoint("Bulk edit classes")
                        show_message(f"Updated {changes} class(es)", "success")
                        st.rerun()
                    else:
                        show_message("No changes detected.", "info")

        else:  # Delete
            st.subheader("Bulk Delete Classes")
            if not classes:
                st.info("No classes to delete.")
            else:
                selected = st.multiselect(
                    "Select classes to delete",
                    class_names,
                    key="bulk_delete_classes_select",
                )
                if selected:
                    st.warning(
                        f"This will delete {len(selected)} class(es) and all their references."
                    )
                    if st.button(
                        "Delete Selected", type="primary", key="bulk_delete_classes_btn"
                    ):
                        result = ont.bulk_delete_classes(selected)
                        save_checkpoint("Bulk delete classes")
                        show_message(
                            f"Deleted {len(result['deleted'])} class(es)", "success"
                        )
                        st.rerun()

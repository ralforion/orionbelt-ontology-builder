"""The annotations page."""

import streamlit as st

from ..ui import (
    _cb_toggle_edit,
    _close_entity,
    _is_open,
    _uid,
    clearable_selectbox,
    format_label_name,
    render_add_annotation,
    render_annotation_form,
    save_checkpoint,
    set_flash_message,
    show_message,
)


def render_annotations():
    """Render the annotations management page."""
    st.header("Annotations")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    individuals = ont.get_individuals()

    # Combine all resources with their labels
    all_resources = []
    for c in classes:
        display = format_label_name(c["name"], c.get("label"))
        all_resources.append(
            {
                "name": c["name"],
                "uri": c["uri"],
                "label": c.get("label"),
                "type": "Class",
                "display": display,
            }
        )
    for p in object_props:
        display = format_label_name(p["name"], p.get("label"))
        all_resources.append(
            {
                "name": p["name"],
                "uri": p["uri"],
                "label": p.get("label"),
                "type": "Object Property",
                "display": display,
            }
        )
    for p in data_props:
        display = format_label_name(p["name"], p.get("label"))
        all_resources.append(
            {
                "name": p["name"],
                "uri": p["uri"],
                "label": p.get("label"),
                "type": "Data Property",
                "display": display,
            }
        )
    for i in individuals:
        display = format_label_name(i["name"], i.get("label"))
        all_resources.append(
            {
                "name": i["name"],
                "uri": i["uri"],
                "label": i.get("label"),
                "type": "Individual",
                "display": display,
            }
        )

    # Sort all resources by display text
    all_resources.sort(key=lambda r: r["display"].lower())

    _ann_tab = st.segmented_control(
        "Section",
        ["View Annotations", "Add Annotation", "Bulk Edit"],
        default="View Annotations",
        key="ann_active_tab",
        label_visibility="collapsed",
    )
    if not _ann_tab:
        _ann_tab = "View Annotations"

    if _ann_tab == "View Annotations":
        if not all_resources:
            st.info(
                "No resources to annotate. Create classes, properties, or individuals first."
            )
        else:
            # Filter by resource type
            col1, col2 = st.columns([1, 3])
            with col1:
                filter_types = ["All"] + list({r["type"] for r in all_resources})
                selected_type = st.selectbox(
                    "Filter by Type", options=filter_types, key="filter_type"
                )

            # Filter resources based on selection
            if selected_type == "All":
                filtered_resources = all_resources
            else:
                filtered_resources = [
                    r for r in all_resources if r["type"] == selected_type
                ]

            with col2:
                if filtered_resources:
                    _view_opts = [r["display"] for r in filtered_resources]
                    selected = clearable_selectbox(
                        "Select Resource",
                        _view_opts,
                        key="view_annotations_select",
                        current_display=_view_opts[0] if _view_opts else None,
                    )
                else:
                    selected = None
                    st.info(f"No {selected_type} resources found.")

            if selected:
                # Find the actual resource name from display string
                resource = next(
                    (r for r in filtered_resources if r["display"] == selected), None
                )
                if resource:
                    resource_name = resource["name"]
                    annotations = ont.get_annotations(resource_name)

                    if not annotations:
                        st.info(f"No annotations found for '{resource_name}'")
                    else:
                        st.subheader(f"Annotations for {selected}")
                        resource_uri = resource.get("uri") or resource_name
                        for _ai, ann in enumerate(annotations):
                            # By position, the way the restriction rows are
                            # keyed: a resource can carry two annotations that
                            # differ only in language, and they would otherwise
                            # share a key and open each other's editor.
                            row_key = f"{_uid(resource_uri)}_{_ai}"
                            col1, col2, col3, col4 = st.columns([2, 4, 0.7, 0.7])
                            with col1:
                                # Show prefixed predicate (e.g., rdfs:label, skos:prefLabel)
                                predicate_display = ann.get(
                                    "predicate_prefixed", ann["predicate"]
                                )
                                st.write(f"**{predicate_display}**")
                            with col2:
                                lang_str = (
                                    f" @{ann['language']}"
                                    if ann.get("language")
                                    else ""
                                )
                                dtype_str = (
                                    f" ({ann['datatype']})"
                                    if ann.get("datatype")
                                    else ""
                                )
                                st.write(f"{ann['value']}{lang_str}{dtype_str}")
                            with col3:
                                st.button(
                                    "✏️",
                                    key=f"edit_ann_{row_key}",
                                    help="Edit this annotation",
                                    on_click=_cb_toggle_edit,
                                    args=("ann", row_key),
                                )
                            with col4:
                                if st.button(
                                    "🗑️",
                                    key=f"del_ann_{row_key}",
                                    help="Delete this annotation",
                                ):
                                    ont.delete_annotation(
                                        resource_name,
                                        ann.get("predicate_uri", ann["predicate"]),
                                        ann["value"],
                                        lang=ann.get("language"),
                                        # Full URI, and the resource/literal
                                        # distinction: passing the display local
                                        # name or treating an IRI object as a
                                        # literal deletes nothing while
                                        # reporting success (issue #223 review).
                                        datatype=ann.get("datatype_uri")
                                        or ann.get("datatype"),
                                        value_is_uri=bool(ann.get("is_uri")),
                                    )
                                    save_checkpoint("Delete annotation")
                                    set_flash_message("Annotation deleted!", "success")
                                    st.rerun()

                            if _is_open("ann", row_key, "edit"):
                                render_annotation_form(
                                    ont,
                                    resource_uri,
                                    ann,
                                    row_key,
                                    classes,
                                    object_props,
                                    data_props,
                                    individuals,
                                    on_close=lambda: _close_entity("ann"),
                                )

    if _ann_tab == "Add Annotation":
        render_add_annotation(ont, all_resources)

    if _ann_tab == "Bulk Edit":
        st.subheader("Bulk Edit Annotations")
        st.caption(
            "Edit annotations in a spreadsheet. Add rows to create, mark action as 'delete' to remove."
        )

        # Build initial data from existing annotations
        annotation_data = []
        for res in all_resources:
            annots = ont.get_annotations(res["name"])
            for a in annots:
                annotation_data.append(
                    {
                        "Resource": res["name"],
                        "Predicate": a.get(
                            "predicate_prefixed", a.get("predicate", "")
                        ),
                        "Value": a.get("value", ""),
                        "Language": a.get("language", ""),
                        "Action": "keep",
                    }
                )

        import pandas as pd

        if annotation_data:
            df = pd.DataFrame(annotation_data)
        else:
            df = pd.DataFrame(
                columns=["Resource", "Predicate", "Value", "Language", "Action"]
            )

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            column_config={
                "Action": st.column_config.SelectboxColumn(
                    "Action",
                    options=["keep", "add", "delete"],
                    default="add",
                ),
            },
            key="bulk_annotations_editor",
            width="stretch",
        )

        if st.button("Apply Changes", type="primary", key="bulk_apply_annotations"):
            updates = []
            for _, row in edited_df.iterrows():
                action = row.get("Action", "keep")
                if action in ("add", "delete"):
                    updates.append(
                        {
                            "resource": row["Resource"],
                            "predicate": row["Predicate"],
                            "value": row["Value"],
                            "lang": row.get("Language", ""),
                            "action": action,
                        }
                    )
            if updates:
                result = ont.bulk_update_annotations(updates)
                save_checkpoint("Bulk edit annotations")
                msg = f"Applied {result['applied']} change(s)"
                if result["errors"]:
                    msg += f", {len(result['errors'])} error(s)"
                # Flash (not show_message) so the summary survives the rerun below.
                set_flash_message(msg, "success" if not result["errors"] else "warning")
                st.rerun()
            else:
                show_message(
                    "No changes to apply. Set Action to 'add' or 'delete'.", "info"
                )

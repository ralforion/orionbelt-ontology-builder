"""The annotations page."""

import streamlit as st

from .. import languages
from ..ui import (
    _cb_toggle_edit,
    _close_entity,
    _download_or_save,
    _is_open,
    _uid,
    active_language_pack,
    clearable_selectbox,
    delete_custom_language_pack,
    format_label_name,
    language_pack_entries,
    language_pack_names,
    render_add_annotation,
    render_annotation_form,
    save_checkpoint,
    save_custom_language_pack,
    set_flash_message,
    show_message,
)


def _rename_annotation_type(ont, ann_type, new_name):
    """Apply one annotation-type rename, reporting why it was refused (#287).

    Returns True when the graph changed; the caller reruns. The engine tells the
    two refusals apart: a name it cannot use at all raises, a name already taken
    comes back as False, and only the second is about this ontology's contents.
    """
    new_name = (new_name or "").strip()
    if not new_name:
        show_message("Annotation type name is required!", "error")
        return False
    try:
        renamed = ont.rename_annotation_property(ann_type["uri"], new_name)
    except ValueError as exc:
        show_message(str(exc), "error")
        return False
    if not renamed:
        show_message(f"Cannot rename: '{new_name}' is already in use!", "error")
        return False
    save_checkpoint("Rename annotation type")
    return True


def render_annotation_types(ont):
    """Render the "Annotation Types" tab.

    A separate function so it can be driven directly in tests, for the reason
    given on :func:`render_add_annotation`: the page's tab picker is a
    ``segmented_control``, which AppTest mis-serializes.
    """
    st.subheader("Annotation Types")
    st.caption(
        "The annotation types this ontology defines itself. Renaming one "
        "rewrites every annotation that uses it, so no values are lost. Types "
        "from another vocabulary (rdfs:label, skos:definition, an imported "
        "ontology's) are defined there, not here, and are not listed."
    )

    ann_types = ont.get_custom_annotation_properties()
    if not ann_types:
        st.info(
            "No custom annotation types yet. Add an annotation under "
            "'Add Annotation' with a type of your own to create one."
        )
        return

    for ann_type in ann_types:
        row_key = _uid(ann_type["uri"])
        col1, col2, col3 = st.columns([3, 3, 0.7])
        with col1:
            st.write(f"**{ann_type['display']}**")
        with col2:
            uses = ann_type["usage"]
            st.write(f"{uses} annotation{'' if uses == 1 else 's'}")
        with col3:
            st.button(
                "✏️",
                key=f"edit_anntype_{row_key}",
                help="Rename this annotation type",
                on_click=_cb_toggle_edit,
                args=("anntype", row_key),
            )

        if _is_open("anntype", row_key, "edit"):
            with st.form(f"rename_anntype_form_{row_key}"):
                new_name = st.text_input(
                    "Name",
                    value=ann_type["local_name"],
                    key=f"anntype_name_{row_key}",
                    help="A name keeps the type in its current namespace. A "
                    "bound prefix ('ex:note') or a full URI moves it.",
                )
                fcol1, fcol2 = st.columns(2)
                with fcol1:
                    submitted = st.form_submit_button(
                        "Rename", type="primary", use_container_width=True
                    )
                with fcol2:
                    cancelled = st.form_submit_button(
                        "Cancel", use_container_width=True
                    )

            if cancelled:
                _close_entity("anntype")
                st.rerun()
            if submitted and _rename_annotation_type(ont, ann_type, new_name):
                _close_entity("anntype")
                set_flash_message(
                    f"Annotation type renamed to '{new_name.strip()}'", "success"
                )
                st.rerun()


def custom_pack_names() -> list[str]:
    """Names already taken by a custom pack, for the two create paths."""
    return [n for n in language_pack_names() if n not in languages.BUILTIN_PACKS]


def _pack_rows_to_entries(frame) -> list[dict]:
    """The editor's rows as pack entries.

    ``fillna`` before anything else: a cell the user left alone comes back as
    NaN, and a NaN read as a string is the code ``nan`` — a valid language tag,
    which is exactly how it would have reached the graph unnoticed.
    """
    rows = frame.fillna("").astype(str).to_dict("records")
    return [
        {"code": r.get("Code", "").strip(), "label": r.get("Language", "").strip()}
        for r in rows
    ]


def render_language_packs():
    """Render the "Language Packs" tab (issue #252).

    Where packs are made; *which* pack is in use is the sidebar's picker, since
    it applies to the Language fields on three pages and in the graph panel.
    The built-in packs are read-only lists to copy from — they are the way back
    to a known set of codes, so nothing here can overwrite one.
    """
    import pandas as pd

    st.subheader("Language Packs")
    st.caption(
        "Which codes the Language fields offer. Two packs ship with the app; "
        "a pack of your own can be the short list of languages this ontology "
        "actually uses, or codes for a language no standard names. Pick the "
        "pack in use in the sidebar."
    )

    # A widget's value can't be assigned once it has been instantiated, so the
    # create / import / delete paths flag which pack to show next and it is
    # applied here, before the picker is drawn — the same deferral the
    # annotation type picker uses.
    if _next := st.session_state.pop("_lang_pack_select_next", None):
        st.session_state["lang_pack_edit_select"] = _next
    if st.session_state.pop("_lang_pack_clear_new_name", False):
        st.session_state["lang_pack_new_name"] = ""

    names = language_pack_names()
    # Opens on the pack in use, then follows this picker. Seeded into session
    # state rather than passed as ``index``: a widget given both a default and
    # a session-state value draws a warning above the page.
    if "lang_pack_edit_select" not in st.session_state:
        _active = active_language_pack()
        st.session_state["lang_pack_edit_select"] = (
            _active if _active in names else names[0]
        )
    viewing = st.selectbox("Pack", names, key="lang_pack_edit_select")
    entries = language_pack_entries(viewing)
    frame = pd.DataFrame(
        [{"Code": e["code"], "Language": e["label"]} for e in entries],
        columns=["Code", "Language"],
    )
    is_builtin = viewing in languages.BUILTIN_PACKS
    # Keyed by pack: one editor key across packs would carry the rows you typed
    # into one pack over into the next one you looked at.
    pack_key = _uid(viewing)

    if is_builtin:
        st.caption(
            f"{len(entries)} codes. Built-in packs can't be edited — copy one "
            "below to make a version of your own."
        )
        st.dataframe(frame, hide_index=True, width="stretch")
    else:
        edited = st.data_editor(
            frame,
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "Code": st.column_config.TextColumn(
                    "Code",
                    help="The tag written into the ontology: letters, "
                    "optionally '-' and more letters or digits. For a language "
                    "no standard names, use 'x-yourcode' or one of "
                    "'qaa'–'qtz'.",
                    required=True,
                ),
                "Language": st.column_config.TextColumn(
                    "Language", help="Shown beside the code, e.g. 'Old Norse'."
                ),
            },
            key=f"lang_pack_rows_{pack_key}",
            width="stretch",
        )
        save_col, del_col = st.columns(2)
        with save_col:
            if st.button(
                "Save pack",
                type="primary",
                use_container_width=True,
                key=f"lang_pack_save_{pack_key}",
            ):
                reason = save_custom_language_pack(
                    viewing, _pack_rows_to_entries(edited)
                )
                if reason:
                    show_message(reason, "error")
                else:
                    set_flash_message(f"Pack '{viewing}' saved!", "success")
                    st.rerun()
        with del_col:
            if st.button(
                "Delete pack",
                use_container_width=True,
                key=f"lang_pack_del_{pack_key}",
            ):
                st.session_state["_lang_pack_confirm_delete"] = viewing
        if st.session_state.get("_lang_pack_confirm_delete") == viewing:
            st.warning(
                f"Delete '{viewing}'? Annotations already tagged with its codes "
                "keep them; only the list goes."
            )
            yes_col, no_col = st.columns(2)
            with yes_col:
                if st.button(
                    "Confirm delete",
                    type="primary",
                    use_container_width=True,
                    key=f"lang_pack_del_yes_{pack_key}",
                ):
                    delete_custom_language_pack(viewing)
                    st.session_state.pop("_lang_pack_confirm_delete", None)
                    st.session_state["_lang_pack_select_next"] = languages.DEFAULT_PACK
                    set_flash_message(f"Pack '{viewing}' deleted.", "success")
                    st.rerun()
            with no_col:
                if st.button(
                    "Cancel",
                    use_container_width=True,
                    key=f"lang_pack_del_no_{pack_key}",
                ):
                    st.session_state.pop("_lang_pack_confirm_delete", None)
                    st.rerun()

    _download_or_save(
        "Download pack",
        languages.pack_to_json(viewing, entries),
        f"{viewing.replace(' ', '_')}.json",
        mime="application/json",
        key=f"lang_pack_{pack_key}",
    )

    st.divider()
    st.markdown("**New pack**")
    new_col, from_col = st.columns([2, 2])
    with new_col:
        new_name = st.text_input(
            "Name", key="lang_pack_new_name", placeholder="Project codes"
        )
    with from_col:
        start_from = st.selectbox(
            "Start from",
            ["Empty", *names],
            key="lang_pack_new_from",
            help="Copy an existing pack's codes into the new one, then trim it.",
        )
    if st.button("Create pack", key="lang_pack_create"):
        seed = [] if start_from == "Empty" else language_pack_entries(start_from)
        if new_name.strip() in custom_pack_names():
            show_message(f"'{new_name.strip()}' already exists.", "error")
        elif reason := save_custom_language_pack(new_name, seed):
            show_message(reason, "error")
        else:
            # Point the pack picker at what was just created, so the editor
            # below it is the new pack's rather than the one copied from.
            st.session_state["_lang_pack_select_next"] = new_name.strip()
            st.session_state["_lang_pack_clear_new_name"] = True
            set_flash_message(f"Pack '{new_name.strip()}' created!", "success")
            st.rerun()

    st.divider()
    st.markdown("**Import a pack**")
    uploaded = st.file_uploader(
        "Pack file (.json)", type=["json"], key="lang_pack_upload"
    )
    import_name = st.text_input(
        "Name it",
        key="lang_pack_import_name",
        help="Leave empty to use the name inside the file.",
    )
    if uploaded is not None and st.button("Import pack", key="lang_pack_import"):
        try:
            file_name, file_entries = languages.pack_from_json(
                uploaded.getvalue().decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError) as exc:
            show_message(str(exc), "error")
            return
        target = import_name.strip() or file_name
        if not target:
            show_message("The file has no name in it — name it above.", "error")
        elif target in custom_pack_names():
            show_message(f"'{target}' already exists. Name it something else.", "error")
        elif reason := save_custom_language_pack(target, file_entries):
            show_message(reason, "error")
        else:
            st.session_state["_lang_pack_select_next"] = target
            set_flash_message(
                f"Pack '{target}' imported ({len(file_entries)} codes).", "success"
            )
            st.rerun()


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
        [
            "View Annotations",
            "Add Annotation",
            "Annotation Types",
            "Language Packs",
            "Bulk Edit",
        ],
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

    if _ann_tab == "Annotation Types":
        render_annotation_types(ont)

    if _ann_tab == "Language Packs":
        render_language_packs()

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

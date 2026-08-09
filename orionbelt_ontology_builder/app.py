"""
OrionBelt Ontology Builder - A Streamlit application for building, editing,
and managing OWL ontologies.
"""

import logging
from pathlib import Path as _Path

import streamlit as st

from . import local_store

# Re-exported so the top-level compatibility shims and the tests keep
# addressing these by ``app.<name>``, which is how they were written when
# this module held everything.
logger = logging.getLogger(__name__)

from .ui import (  # noqa: F401
    _ANN_ID_PARTS,
    _BRAND,
    _BRAND_CSS,
    _BRAND_TINT,
    _CLASS_DISPLAY_GAP,
    _CLASS_TOKEN_SEPARATORS,
    _CUSTOM_CSS,
    _DARK_ACCENT,
    _DARK_CSS,
    _DARK_TINT,
    _EDGE_ID_SEP,
    _FAVICON,
    _FILTER_KINDS,
    _KEEP_NAMESPACE,
    _NAV_KIND_BY_TYPE,
    _PAGE_BY_TYPE,
    _PRECISE_NAV_TYPES,
    _SEARCH_ANY,
    _VIZ_INT_RANGES,
    _VIZ_PERSIST_KEYS,
    APP_NAME,
    APP_VERSION,
    AUTOSAVE_DEBOUNCE_SECONDS,
    AUTOSAVE_KEY,
    AUTOSAVE_MAX_BYTES,
    FOCUS_BUILD_MAX_NODES,
    GITHUB_ISSUES_URL,
    GRAPH_MAX_NODES,
    LABEL_NAME_SEPARATOR,
    LIST_PAGE_SIZE,
    SEARCH_PAD_WIDTH,
    VIZ_FILE_STATE_KEY,
    VIZ_FILE_STATE_MAX_FILES,
    VIZ_SETTINGS_KEY,
    _apply_annotation_edit,
    _apply_class_edit,
    _apply_class_relation_add,
    _apply_individual_edit,
    _apply_property_edit,
    _apply_restriction_add,
    _apply_viz_settings,
    _autosave_ready,
    _autosave_tick,
    _block_disk_persist,
    _build_name_collision_set,
    _bulk_result_message,
    _cb_confirm_delete,
    _cb_toggle_edit,
    _cb_toggle_view,
    _cb_view_to_edit,
    _clear_viz_file_session_state,
    _close_entity,
    _content_hash,
    _current_mutation_count,
    _custom_uri_field,
    _disambiguated_name,
    _disk_restore_source,
    _download_or_save,
    _edge_id,
    _edge_id_parts,
    _external_uri_target,
    _filter_relations,
    _filter_restrictions,
    _fmt_unknown,
    _get_active,
    _get_local_storage,
    _is_open,
    _load_linked_file,
    _mark_disk_source_saved,
    _matches_slots,
    _namespace_option_index,
    _nav_open_entity,
    _ontology_is_empty,
    _open_entity,
    _pad_option,
    _page_bounds,
    _paginate_rows,
    _panel_add_kind,
    _panel_add_parent,
    _panel_close_add,
    _panel_confirm_dialog,
    _panel_delete_edge,
    _panel_delete_entity,
    _panel_drop_selection,
    _persist_autosave_to_disk,
    _persist_autosave_to_localstorage,
    _persist_viz_file_state,
    _persist_viz_settings,
    _prefix_for_uri,
    _rdf_format_for_path,
    _relation_spec,
    _rename_or_move,
    _renamed_ref,
    _render_disk_autosave_sidebar,
    _render_panel_add_annotation_form,
    _render_panel_add_buttons,
    _render_panel_add_class_form,
    _render_panel_add_individual_form,
    _render_panel_add_relation_form,
    _render_panel_add_restriction_form,
    _render_panel_annotation_editor,
    _render_panel_entity_editor,
    _render_panel_relation_editor,
    _render_panel_restriction_editor,
    _resolve_list_view,
    _restore_autosave_from_disk,
    _restore_viz_file_state,
    _restore_viz_settings,
    _restriction_matches_edge,
    _slot_options,
    _sort_relations,
    _sort_restrictions,
    _str_list,
    _uid,
    _uri_local_name,
    _uri_option_index,
    _viz_file_state_id,
    _viz_file_state_payload,
    _viz_live_selection,
    _viz_selection_key,
    _viz_settings_payload,
    _viz_widget_missing,
    annotation_ename,
    annotation_matches_ename,
    annotation_option_for_predicate,
    annotation_predicate_options,
    annotation_subject_options,
    build_class_hierarchy_text,
    build_class_options,
    build_filter_entries,
    build_namespace_options,
    build_uri_options,
    clearable_selectbox,
    confirm_delete,
    display_flash_message,
    filter_entry_token,
    focus_seeds_from_selection,
    format_label_name,
    get_ontology_manager_class,
    graph_node_cap,
    init_session_state,
    log_error,
    maybe_restore_autosave,
    missing_required,
    panel_subject_uri,
    parent_option_index,
    parse_filter_text,
    parse_search_query,
    persist_autosave,
    prioritise_find_target,
    prune_reused_focus_seeds,
    reconcile_filter_selection,
    render_add_annotation,
    render_add_class_form,
    render_add_restriction,
    render_annotation_form,
    render_relation_form,
    render_relation_rows,
    render_restriction_editor,
    render_restriction_form,
    render_restriction_row,
    required_selectbox,
    resolve_annotation_predicate_choice,
    resolve_picked_object,
    restriction_references_class,
    restriction_takes_on_class,
    restriction_value_is_class,
    save_checkpoint,
    seed_filter_from_saved,
    set_flash_message,
    show_message,
    viz_drop_focus_seeds,
    viz_filter_changed,
    viz_find_changed,
    viz_focus_toggle,
    viz_hidden_caption,
    viz_mark_ontology_seen,
    viz_ontology_was_replaced,
    viz_sync,
)


def _page_title() -> str:
    """Browser-tab / window title. Uses the current ontology's name so multiple
    instances are distinguishable when switching tabs (issue #90): its
    rdfs:label, else the last segment of the base URI, else the app name.

    The ontology is restored after this runs on the very first render, so the
    first paint shows the app name and it updates to the ontology name on the
    next rerun.
    """
    ont = st.session_state.get("ontology")
    if ont is not None:
        try:
            name = (ont.get_ontology_metadata().get("label") or "").strip()
        except Exception:  # noqa: BLE001 - best-effort label read; falls back to the URI
            name = ""
        if not name:
            base = ont.base_uri.rstrip("#/")
            name = base.split("/")[-1].split("#")[-1]
        if name:
            return f"{name} · OrionBelt"
    return APP_NAME


def _configure_page() -> None:
    """Apply page config and custom CSS. Called from main() so it fires on
    every Streamlit rerun (CSS markdown only persists for the rerun in which it
    was emitted).

    set_page_config is re-issued on *every* run — the browser resets the tab
    title to the Streamlit default on reruns where it is not called, so it must
    be re-asserted each time for the ontology name to persist (issue #90). The
    title is recomputed each run so it also tracks the current ontology. Only
    the first call steers the sidebar, so later runs don't fight a sidebar the
    user has collapsed."""
    title = _page_title()
    page_icon = str(_FAVICON) if _FAVICON.exists() else None
    if "_page_configured" not in st.session_state:
        # First run steers the sidebar open; later runs must not, so a title
        # change doesn't fight a sidebar the user has collapsed.
        st.session_state["_page_configured"] = True
        st.set_page_config(
            page_title=title,
            page_icon=page_icon,
            layout="wide",
            initial_sidebar_state="expanded",
        )
    else:
        st.set_page_config(page_title=title, page_icon=page_icon, layout="wide")
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    # Force the brand primary on key controls in every theme (Streamlit's preset
    # themes would otherwise revert it to red), then lighten tab/pill accents in
    # dark mode (injected after, so it wins there).
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    try:
        if st.context.theme.get("type") == "dark":
            st.markdown(_DARK_CSS, unsafe_allow_html=True)
    except Exception:
        logger.debug(
            "Dark-theme CSS skipped: st.context.theme unavailable", exc_info=True
        )
    if "app_started" not in st.session_state:
        st.session_state.app_started = True
        logger.info(f"{APP_NAME} v{APP_VERSION}")


def request_autosave_flush() -> None:
    """Force the next autosave to write now, skipping the debounce window.

    Call after important actions (import, new ontology, linking a file) so a
    large, deliberate change is persisted immediately. Applies to whichever
    backend is active.
    """
    st.session_state["_force_autosave_flush"] = True


def render_autosave_sidebar():
    """Sidebar controls: toggle autosave and discard the saved session."""
    # Local/desktop runs persist to disk and get a different control set.
    if local_store.local_persist_enabled():
        _render_disk_autosave_sidebar()
        return
    ls = _get_local_storage()
    if ls is None:
        return
    st.sidebar.checkbox(
        "Autosave to this browser",
        value=st.session_state.get("_autosave_enabled", True),
        key="_autosave_enabled",
        help=(
            "Saves your ontology in this browser's local storage and restores "
            "it automatically if the page reloads. Local to this browser only "
            "— not a replacement for Export."
        ),
    )
    if (
        st.session_state.get("_autosave_enabled", True)
        and st.session_state.get("_ls_saved_rev") == _current_mutation_count()
        and not _ontology_is_empty(st.session_state.ontology)
    ):
        st.sidebar.caption("✓ Saved in this browser")
    if st.sidebar.button(
        "Discard saved session", key="_autosave_discard", use_container_width=True
    ):
        # Reset the workspace to a clean slate. We deliberately don't call the
        # component's deleteItem (its delete path is unreliable); instead the
        # now-empty graph is mirrored out by persist_autosave on the rerun,
        # overwriting the saved copy via the dependable setItem path.
        OntologyManager = get_ontology_manager_class()
        st.session_state.ontology = OntologyManager()
        try:
            from .ontology_manager import UndoManager

            st.session_state.undo_manager = UndoManager(st.session_state.ontology)
        except ImportError:
            st.session_state.undo_manager = None
        # Mark dirty and force an immediate flush so the now-empty graph
        # overwrites the saved copy via the dependable setItem path.
        st.session_state["_ls_saved_rev"] = None
        st.session_state["_ls_oversized_rev"] = None
        st.session_state["_ont_mutation_count"] = (
            st.session_state.get("_ont_mutation_count", 0) + 1
        )
        request_autosave_flush()
        st.toast("Cleared this browser's autosave and reset the workspace.", icon="🗑️")
        st.rerun()


def render_dashboard():
    """Render the dashboard/overview page."""
    st.header("Dashboard")

    ont = st.session_state.ontology
    stats = ont.get_statistics()
    metadata = ont.get_ontology_metadata()

    # Ontology metadata section
    st.subheader("Ontology Information")
    col1, col2 = st.columns(2)

    with col1:
        base_uri = st.text_input(
            "Base URI",
            value=ont.base_uri,
            help="The namespace URI for your ontology (e.g., http://example.org/ontology#)",
        )
        label = st.text_input("Label (rdfs:label)", value=metadata.get("label", ""))
        comment = st.text_area(
            "Comment (rdfs:comment)", value=metadata.get("comment", "")
        )

    with col2:
        version_iri = st.text_input(
            "Version IRI",
            value=metadata.get("version_iri", ""),
            help="Optional IRI identifying this version of the ontology",
        )
        creator = st.text_input("Creator", value=metadata.get("creator", ""))

        if st.button("Update Metadata"):
            # Update base URI if changed
            if base_uri and base_uri != ont.base_uri:
                ont.set_base_uri(base_uri)
                show_message(f"Base URI updated to: {ont.base_uri}", "success")

            ont.set_ontology_metadata(
                label=label,
                comment=comment,
                creator=creator,
                version_iri=version_iri if version_iri else None,
            )
            save_checkpoint("Update metadata")
            show_message("Metadata updated successfully!", "success")
            st.rerun()

    # Imports section
    st.subheader("Ontology Imports")
    imports = ont.get_imports()

    if imports:
        for imp in imports:
            col1, col2 = st.columns([5, 1])
            with col1:
                st.code(imp)
            with col2:
                if st.button("Remove", key=f"rm_import_{imp}"):
                    ont.remove_import(imp)
                    save_checkpoint("Remove import")
                    st.rerun()

    with st.expander("Add Import"):
        new_import = st.text_input(
            "Import URI", placeholder="http://example.org/other-ontology"
        )
        if st.button("Add Import") and new_import:
            ont.add_import(new_import)
            save_checkpoint("Add import")
            show_message(f"Import added: {new_import}", "success")
            st.rerun()

    # Prefixes section
    st.subheader("Namespace Prefixes")
    all_prefixes = ont.get_all_prefixes()

    if all_prefixes:
        prefix_data = {"Prefix": [], "Namespace": [], "Source": []}
        for p in all_prefixes:
            prefix_data["Prefix"].append(p["prefix"])
            prefix_data["Namespace"].append(p["namespace"])
            prefix_data["Source"].append(p["source"])
        st.dataframe(prefix_data, width="stretch", hide_index=True)
    else:
        st.info("No prefixes defined.")

    with st.expander("Add Custom Prefix"):
        col_pfx, col_ns = st.columns(2)
        with col_pfx:
            new_prefix = st.text_input(
                "Prefix", placeholder="foaf", key="new_prefix_name"
            )
        with col_ns:
            new_ns = st.text_input(
                "Namespace URI",
                placeholder="http://xmlns.com/foaf/0.1/",
                key="new_prefix_ns",
            )
        if st.button("Add Prefix", key="add_prefix_btn"):
            _pfx = (new_prefix or "").strip()
            _ns = (new_ns or "").strip()
            if not _pfx or not _ns:
                show_message("Both prefix and namespace URI are required.", "warning")
            elif any(c.isspace() for c in _ns):
                show_message("Namespace URI cannot contain spaces.", "warning")
            else:
                bound = ont.add_prefix(_pfx, _ns)
                save_checkpoint("Add prefix")
                # A namespace URI needs a trailing '#' or '/' so entities created
                # in it get a separator; note it when we add one (issue #115).
                note = "" if bound == _ns else f" (normalized to {bound})"
                set_flash_message(f"Added prefix '{_pfx}'{note}", "success")
                st.rerun()

    # Show remove buttons for custom prefixes
    custom_pfx = [p for p in all_prefixes if p["source"] == "custom"]
    if custom_pfx:
        st.caption("Remove custom prefixes:")
        for p in custom_pfx:
            col_name, col_rm = st.columns([4, 1])
            with col_name:
                st.text(f"{p['prefix']}: {p['namespace']}")
            with col_rm:
                if st.button("Remove", key=f"rm_pfx_{p['prefix']}"):
                    ont.remove_prefix(p["prefix"])
                    save_checkpoint("Remove prefix")
                    set_flash_message(f"Removed prefix '{p['prefix']}'", "success")
                    st.rerun()

    st.divider()

    # Statistics
    st.subheader("Statistics")
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric("Classes", stats["classes"])
    with col2:
        st.metric("Object Properties", stats["object_properties"])
    with col3:
        st.metric("Data Properties", stats["data_properties"])
    with col4:
        st.metric("Individuals", stats["individuals"])
    with col5:
        st.metric("Restrictions", stats["restrictions"])
    with col6:
        st.metric("Content Triples", stats["content_triples"])

    st.divider()

    # Quick validation section
    st.subheader("Quick Validation")
    col1, col2 = st.columns([1, 3])

    with col1:
        if st.button("🔍 Validate Ontology", type="primary"):
            issues = ont.validate(check_missing_domain_range=False)
            st.session_state.validation_results = issues

    with col2:
        if "validation_results" in st.session_state:
            issues = st.session_state.validation_results
            if not issues:
                st.success("✅ No issues found! The ontology is valid.")
            else:
                errors = [i for i in issues if i["severity"] == "error"]
                warnings = [i for i in issues if i["severity"] == "warning"]
                infos = [i for i in issues if i["severity"] == "info"]

                if errors:
                    st.error(f"❌ {len(errors)} error(s)")
                if warnings:
                    st.warning(f"⚠️ {len(warnings)} warning(s)")
                if infos:
                    st.info(f"ℹ️ {len(infos)} info message(s)")

                with st.expander("View Details"):
                    for issue in issues:
                        icon = (
                            "❌"
                            if issue["severity"] == "error"
                            else "⚠️"
                            if issue["severity"] == "warning"
                            else "ℹ️"
                        )
                        st.write(f"{icon} **{issue['subject']}**: {issue['message']}")


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
                    elif str(ont._uri(name, ns_val)) in {i["uri"] for i in individuals}:
                        show_message(f"Individual '{name}' already exists!", "error")
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


def render_skos_vocabulary():
    """Render the SKOS Vocabulary management page."""
    st.header("SKOS Vocabulary")

    ont = st.session_state.ontology
    schemes = ont.get_concept_schemes()
    concepts = ont.get_concepts()
    # URI-keyed dropdown options for scheme/concept selectors (issue #87 part B):
    # a scheme or concept moved to a custom URI can share a local name with
    # another, so pass the picked URI to the engine instead of a bare local name
    # that would resolve through the base namespace. ``.get(sentinel)`` returns
    # None for the "All"/"None" entries, which is what the engine expects.
    scheme_opts, scheme_lookup = build_uri_options(schemes)

    # Clean up unused navigation flag
    st.session_state.pop("_skos_navigate_to_concept", None)

    _skos_tab = st.segmented_control(
        "Section",
        ["Concepts", "Concept Schemes", "Concept Hierarchy", "SKOS Validation"],
        default="Concepts",
        key="skos_active_tab",
        label_visibility="collapsed",
    )
    if not _skos_tab:
        _skos_tab = "Concepts"

    if _skos_tab == "Concept Schemes":
        st.subheader("Concept Schemes")
        if not schemes:
            st.info("No concept schemes defined yet.")
        else:
            for scheme in schemes:
                display_name = format_label_name(scheme["name"], scheme.get("label"))
                # Key and address schemes by a URI-derived id, not the local name:
                # a scheme moved to a custom URI can share a local name with
                # another, which would collide Streamlit widget keys and make
                # local-name-based actions ambiguous (issue #87 part B).
                _sk = str(abs(hash(scheme["uri"])))[:8]
                _scheme_expanded = _is_open("scheme", _sk)
                with st.expander(
                    f"📚 **{display_name}** ({scheme['concept_count']} concepts)",
                    expanded=_scheme_expanded,
                ):
                    st.write(
                        f"**URI:** `{scheme['uri']}`"
                        if scheme["uri"].startswith("http://example.org/")
                        else f"**URI:** {scheme['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("scheme", _sk),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("scheme", _sk),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"scheme_{_sk}",),
                        )

                    if _is_open("scheme", _sk, "view"):
                        st.divider()
                        st.write(f"**Name:** {scheme['name']}")
                        st.write(f"**Label:** {scheme['label'] or '—'}")
                        st.write(f"**Comment:** {scheme['comment'] or '—'}")
                        st.write(f"**Concepts:** {scheme['concept_count']}")

                    if confirm_delete(scheme["uri"], "concept", f"scheme_{_sk}"):
                        ont.delete_concept_scheme(scheme["uri"])
                        save_checkpoint("Delete concept scheme")
                        set_flash_message(
                            f"Scheme '{scheme['name']}' deleted!", "success"
                        )
                        st.rerun()

                    if _is_open("scheme", _sk, "edit"):
                        st.divider()
                        with st.form(f"edit_scheme_form_{_sk}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=scheme["name"],
                                key=f"scheme_name_{_sk}",
                                help="Renaming updates every reference, including "
                                "the inScheme links from its concepts — no "
                                "membership is lost.",
                            )
                            new_label = st.text_input(
                                "Label",
                                value=scheme["label"] or "",
                                key=f"scheme_lbl_{_sk}",
                            )
                            new_comment = st.text_area(
                                "Comment",
                                value=scheme["comment"] or "",
                                key=f"scheme_cmt_{_sk}",
                            )
                            new_name = _custom_uri_field(
                                scheme["uri"],
                                new_name,
                                key=f"custom_uri_scheme_{_sk}",
                            )
                            if st.form_submit_button("Save Changes"):
                                if (
                                    new_name
                                    and new_name != scheme["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                renamed = bool(new_name and new_name != scheme["name"])
                                # Address the scheme by its actual URI so a scheme
                                # in a non-base namespace resolves; target is the
                                # URI it now lives at (issue #87 part B).
                                if renamed and not ont.rename_concept_scheme(
                                    scheme["uri"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = (
                                        _renamed_ref(ont, scheme["uri"], new_name)
                                        if renamed
                                        else scheme["uri"]
                                    )
                                    ont.update_concept_scheme(
                                        target,
                                        new_label=new_label,
                                        new_comment=new_comment,
                                    )
                                    save_checkpoint("Update concept scheme")
                                    _new_sk = str(abs(hash(target)))[:8]
                                    _open_entity("scheme", _new_sk)
                                    show_message(
                                        f"Scheme '{scheme['name']}' updated!", "success"
                                    )
                                    st.rerun()

        st.divider()
        st.subheader("Add Concept Scheme")
        with st.form("add_scheme_form"):
            s_name = st.text_input("Scheme Name *")
            s_label = st.text_input("Label")
            s_comment = st.text_area("Comment")
            if st.form_submit_button("Add Scheme"):
                if not s_name:
                    show_message("Scheme name is required!", "error")
                elif reason := ont.invalid_name_reason(s_name):
                    show_message(reason, "error")
                elif str(ont._uri(s_name)) in {s["uri"] for s in schemes}:
                    # Reject by target URI, not local name, so a base scheme can
                    # be recreated after an existing one is moved to a custom URI
                    # (issue #87 part B), mirroring the class/property/individual
                    # add flows.
                    show_message(f"Scheme '{s_name}' already exists!", "error")
                else:
                    ont.add_concept_scheme(
                        s_name, label=s_label or None, comment=s_comment or None
                    )
                    save_checkpoint("Add concept scheme")
                    show_message(f"Scheme '{s_name}' added!", "success")
                    st.rerun()

    if _skos_tab == "Concepts":
        st.subheader("Concepts")
        if not concepts:
            st.info("No concepts defined yet.")
        else:
            # Filter by scheme
            filter_scheme = st.selectbox(
                "Filter by Scheme",
                ["All"] + scheme_opts,
                key="concept_filter_scheme",
                format_func=_pad_option,
            )
            filtered = (
                concepts
                if filter_scheme == "All"
                else ont.get_concepts(scheme=scheme_lookup.get(filter_scheme))
            )

            def _concept_key(c):
                return str(abs(hash(c["uri"])))[:8]

            # Single-active selection + pagination, keyed by the concept's URI
            # hash (local names may collide across schemes).
            filtered, _ = _resolve_list_view(
                filtered, "skos", _concept_key, "skos_view_page", "concepts"
            )

            for concept in filtered:
                pref = concept["prefLabel"] or concept["name"]
                display_name = format_label_name(
                    concept["name"], pref if pref != concept["name"] else ""
                )
                badges = []
                if concept["broader"]:
                    badges.append(f"broader: {', '.join(concept['broader'])}")
                if concept["schemes"]:
                    badges.append(f"scheme: {', '.join(concept['schemes'])}")
                badge_str = f" — {'; '.join(badges)}" if badges else ""

                # Use URI hash for unique widget keys (local name may not be unique)
                _ck = str(abs(hash(concept["uri"])))[:8]

                _skos_expanded = _is_open("skos", _ck)
                with st.expander(
                    f"🏷️ **{display_name}**{badge_str}", expanded=_skos_expanded
                ):
                    st.write(
                        f"**URI:** `{concept['uri']}`"
                        if concept["uri"].startswith("http://example.org/")
                        else f"**URI:** {concept['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_{_ck}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("skos", _ck),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_{_ck}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("skos", _ck),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_{_ck}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"c_{_ck}",),
                        )

                    # View details
                    if _is_open("skos", _ck, "view"):
                        st.divider()
                        st.write(f"**Name:** {concept['name']}")
                        st.write(f"**prefLabel:** {concept['prefLabel'] or '—'}")
                        st.write(f"**definition:** {concept['definition'] or '—'}")
                        if concept["altLabels"]:
                            st.write(
                                f"**altLabels:** {', '.join(concept['altLabels'])}"
                            )
                        if concept["broader"]:
                            st.write(f"**broader:** {', '.join(concept['broader'])}")
                        if concept["narrower"]:
                            st.write(f"**narrower:** {', '.join(concept['narrower'])}")
                        if concept["related"]:
                            st.write(f"**related:** {', '.join(concept['related'])}")
                        if concept["schemes"]:
                            st.write(f"**schemes:** {', '.join(concept['schemes'])}")

                        # Add relation inline
                        with st.popover("Add Relation"):
                            rel_type = st.selectbox(
                                "Relation",
                                list(ont.SKOS_RELATIONS.keys()),
                                key=f"rel_type_{_ck}",
                            )
                            _rel_opts, _rel_lookup = build_uri_options(
                                [c for c in concepts if c["uri"] != concept["uri"]]
                            )
                            rel_target = required_selectbox(
                                "Target Concept",
                                _rel_opts,
                                key=f"rel_target_{_ck}",
                                current_display=_rel_opts[0] if _rel_opts else None,
                                format_func=_pad_option,
                            )
                            _add_rel = st.button("Add", key=f"add_rel_{_ck}")
                            if _add_rel and (
                                _missing := missing_required(
                                    **{"Target Concept": rel_target}
                                )
                            ):
                                show_message(_missing, "error")
                            elif _add_rel and rel_target:
                                # Address both concepts by their actual URIs: a
                                # concept moved to a non-base namespace (e.g. via a
                                # custom URI) would not resolve through the base
                                # namespace, and two concepts can share a local
                                # name across namespaces (issue #87 part B).
                                ont.add_concept_relation(
                                    concept["uri"],
                                    rel_type,
                                    _rel_lookup.get(rel_target),
                                )
                                save_checkpoint("Add concept relation")
                                show_message(f"Added {rel_type} relation!", "success")
                                st.rerun()

                        st.button(
                            "✏️ Edit",
                            key=f"btn_v2e_{_ck}",
                            on_click=_cb_view_to_edit,
                            args=("skos", _ck),
                        )

                    if confirm_delete(concept["uri"], "concept", f"c_{_ck}"):
                        ont.delete_concept(concept["uri"])
                        save_checkpoint("Delete concept")
                        set_flash_message(
                            f"Concept '{concept['name']}' deleted!", "success"
                        )
                        st.rerun()

                    # Inline edit form
                    if _is_open("skos", _ck, "edit"):
                        st.divider()
                        with st.form(f"edit_concept_form_{_ck}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=concept["name"],
                                key=f"cname_{_ck}",
                                help="Renaming updates every reference to this "
                                "concept (broader/narrower, inScheme, etc.) — "
                                "nothing is lost, unlike delete-and-recreate.",
                            )
                            new_pref = st.text_input(
                                "Preferred Label",
                                value=concept["prefLabel"] or "",
                                key=f"pref_{_ck}",
                            )
                            new_def = st.text_area(
                                "Definition",
                                value=concept["definition"] or "",
                                key=f"def_{_ck}",
                            )

                            # Broader concept — URI-keyed so a broader concept in
                            # a non-base namespace resolves unambiguously (#87).
                            _broader_opts, _broader_lookup = build_uri_options(
                                [c for c in concepts if c["uri"] != concept["uri"]]
                            )
                            _cur_broader_uri = (
                                concept["broader_uris"][0]
                                if concept["broader_uris"]
                                else None
                            )
                            _cur_broader_disp = next(
                                (
                                    d
                                    for d, u in _broader_lookup.items()
                                    if u == _cur_broader_uri
                                ),
                                "None",
                            )
                            broader_options = ["None"] + _broader_opts
                            new_broader = clearable_selectbox(
                                "Broader Concept",
                                broader_options,
                                key=f"broader_{_ck}",
                                current_display=_cur_broader_disp
                                if _cur_broader_disp in broader_options
                                else "None",
                                format_func=_pad_option,
                            )

                            # Scheme — URI-keyed for the same reason.
                            _cur_scheme_uri = (
                                concept["scheme_uris"][0]
                                if concept.get("scheme_uris")
                                else None
                            )
                            _cur_scheme_disp = next(
                                (
                                    d
                                    for d, u in scheme_lookup.items()
                                    if u == _cur_scheme_uri
                                ),
                                "None",
                            )
                            scheme_options = ["None"] + scheme_opts
                            new_scheme = clearable_selectbox(
                                "Scheme",
                                scheme_options,
                                key=f"scheme_{_ck}",
                                current_display=_cur_scheme_disp
                                if _cur_scheme_disp in scheme_options
                                else "None",
                                format_func=_pad_option,
                            )
                            new_name = _custom_uri_field(
                                concept["uri"],
                                new_name,
                                key=f"custom_uri_concept_{_ck}",
                            )

                            if st.form_submit_button("Save Changes"):
                                # Rename first (updates all references) so the
                                # rest of the update targets the new name.
                                if (
                                    new_name
                                    and new_name != concept["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                renamed = bool(new_name and new_name != concept["name"])
                                # Address the concept by its actual URI so a
                                # concept in a non-base namespace (e.g. moved via
                                # a custom URI) resolves; ``target`` is the full
                                # URI it now lives at, which later updates use
                                # instead of a base-namespace local name (#87).
                                if renamed and not ont.rename_concept(
                                    concept["uri"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = (
                                        _renamed_ref(ont, concept["uri"], new_name)
                                        if renamed
                                        else concept["uri"]
                                    )
                                    # Handle broader change (resolve by URI)
                                    broader_val = _broader_lookup.get(new_broader) or ""
                                    old_broader = _cur_broader_uri or ""
                                    broader_changed = broader_val != old_broader

                                    # Handle scheme change (resolve by URI)
                                    old_scheme = _cur_scheme_uri or ""
                                    new_scheme_val = scheme_lookup.get(new_scheme) or ""
                                    add_s = (
                                        new_scheme_val
                                        if new_scheme_val
                                        and new_scheme_val != old_scheme
                                        else None
                                    )
                                    remove_s = (
                                        old_scheme
                                        if old_scheme and old_scheme != new_scheme_val
                                        else None
                                    )

                                    _update_kwargs = {
                                        "new_pref_label": new_pref,
                                        "new_definition": new_def,
                                        "add_scheme": add_s,
                                        "remove_scheme": remove_s,
                                    }
                                    if broader_changed:
                                        _update_kwargs["new_broader"] = broader_val
                                    ont.update_concept(target, **_update_kwargs)
                                    save_checkpoint("Update concept")
                                    _new_ck = (
                                        str(abs(hash(target)))[:8] if renamed else _ck
                                    )
                                    _open_entity("skos", _new_ck)
                                    show_message(
                                        f"Concept '{target}' updated!", "success"
                                    )
                                    st.rerun()

        st.divider()
        st.subheader("Add Concept")
        with st.form("add_concept_form"):
            c_name = st.text_input("Concept Name *")
            c_pref = st.text_input("Preferred Label")
            c_def = st.text_area("Definition")
            c_scheme = clearable_selectbox(
                "Scheme",
                ["None"] + scheme_opts,
                key="concept_scheme_select",
                current_display="None",
                format_func=_pad_option,
            )
            _add_broader_opts, _add_broader_lookup = build_uri_options(concepts)
            c_broader = clearable_selectbox(
                "Broader Concept",
                ["None"] + _add_broader_opts,
                key="concept_broader_select",
                current_display="None",
                format_func=_pad_option,
            )
            c_lang = st.text_input("Language Tag (e.g., en, de)", key="concept_lang")
            if st.form_submit_button("Add Concept"):
                if not c_name:
                    show_message("Concept name is required!", "error")
                elif reason := ont.invalid_name_reason(c_name):
                    show_message(reason, "error")
                elif str(ont._uri(c_name)) in {c["uri"] for c in concepts}:
                    # Reject by target URI, not local name, so a base concept can
                    # be recreated after an existing one is moved to a custom URI
                    # (issue #87 part B).
                    show_message(f"Concept '{c_name}' already exists!", "error")
                else:
                    ont.add_concept(
                        c_name,
                        scheme=scheme_lookup.get(c_scheme),
                        pref_label=c_pref or None,
                        definition=c_def or None,
                        broader=_add_broader_lookup.get(c_broader),
                        lang=c_lang or None,
                    )
                    save_checkpoint("Add concept")
                    show_message(f"Concept '{c_name}' added!", "success")
                    st.rerun()

    if _skos_tab == "Concept Hierarchy":
        st.subheader("Concept Hierarchy")
        if not concepts:
            st.info("No concepts to display.")
        else:
            h_scheme = st.selectbox(
                "Scheme",
                ["All"] + scheme_opts,
                key="hierarchy_scheme_select",
                format_func=_pad_option,
            )
            hierarchy = ont.get_concept_hierarchy(
                scheme=scheme_lookup.get(h_scheme) if h_scheme != "All" else None
            )

            # Find root concepts (those that are not narrower of any other)
            all_children = set()
            for children in hierarchy.values():
                all_children.update(children)
            roots = [name for name in hierarchy if name not in all_children]

            def render_tree(name, indent=0):
                concept_data = next((c for c in concepts if c["name"] == name), None)
                pref = (
                    concept_data["prefLabel"]
                    if concept_data and concept_data["prefLabel"]
                    else name
                )
                st.markdown(
                    f"{'&nbsp;&nbsp;&nbsp;&nbsp;' * indent}{'└─ ' if indent > 0 else ''}**{pref}** ({name})"
                )
                for child in sorted(hierarchy.get(name, [])):
                    render_tree(child, indent + 1)

            for root in sorted(roots):
                render_tree(root)

            if not roots and hierarchy:
                st.warning("All concepts have broader concepts — possible cycle.")

    if _skos_tab == "SKOS Validation":
        st.subheader("SKOS Validation")
        if st.button("Run SKOS Validation", key="run_skos_validation"):
            issues = ont.validate_skos()
            if not issues:
                st.success("No SKOS issues found!")
            else:
                for issue in issues:
                    severity = issue["severity"]
                    icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
                        severity, "⚪"
                    )
                    st.markdown(
                        f"{icon} **{issue['type']}** — {issue['subject']}: {issue['message']}"
                    )


def render_import_export():
    """Render the import/export page."""
    st.header("Import / Export")

    ont = st.session_state.ontology

    _ie_tabs = [
        "Import",
        "Export",
        "New Ontology",
        "Templates",
        "Upper Ontologies",
        "Reference Ontologies",
    ]
    _ie_tab = st.segmented_control(
        "Section",
        _ie_tabs,
        default="Import",
        key="ie_active_tab",
        label_visibility="collapsed",
    )
    if not _ie_tab:
        _ie_tab = "Import"

    if _ie_tab == "Import":
        st.subheader("Import Ontology")

        # Initialize import preview state
        if "import_preview" not in st.session_state:
            st.session_state.import_preview = None
        if "import_content" not in st.session_state:
            st.session_state.import_content = None
        if "import_format" not in st.session_state:
            st.session_state.import_format = None

        # Check if ontology is empty (only default scaffolding, no user content)
        _stats = ont.get_statistics()
        _ont_is_empty = (
            _stats["classes"] == 0
            and _stats["object_properties"] == 0
            and _stats["data_properties"] == 0
            and _stats["individuals"] == 0
            and _stats.get("concepts", 0) == 0
        )

        if st.session_state.get("_ontology_cleared"):
            st.success(st.session_state.pop("_ontology_cleared"))

        with st.popover("Clear Ontology", disabled=_ont_is_empty):
            st.warning(
                "This will delete all classes, properties, individuals, and triples."
            )
            if st.button("Confirm Clear", type="primary", key="clear_ontology_btn"):
                base_uri = str(ont.namespace)
                st.session_state.ontology = get_ontology_manager_class()(
                    base_uri=base_uri
                )
                from .ontology_manager import UndoManager

                st.session_state.undo_manager = UndoManager(st.session_state.ontology)
                # Replacing the graph is a deliberate change; bump the revision
                # and flush so the cleared state is persisted immediately.
                st.session_state["_ont_mutation_count"] = (
                    st.session_state.get("_ont_mutation_count", 0) + 1
                )
                request_autosave_flush()
                st.session_state["_ontology_cleared"] = "Ontology cleared!"
                st.rerun()

        def _direct_import(content, format_):
            """Import directly without preview (for empty ontologies)."""
            try:
                ont.load_from_string(content, format=format_)
                st.session_state.ontology = ont
                save_checkpoint("Import ontology")
                request_autosave_flush()
                set_flash_message(
                    f"Ontology imported successfully! ({len(ont.graph)} triples)",
                    "success",
                )
                # Clear file uploader by incrementing its key
                st.session_state["import_uploader_key"] = (
                    st.session_state.get("import_uploader_key", 0) + 1
                )
                st.rerun()
            except Exception as e:  # noqa: BLE001 - malformed import must show as a message, not a traceback
                show_message(f"Error importing ontology: {e!s}", "error")

        # Step 1: Source selection (only when no preview active)
        if st.session_state.import_preview is None:
            import_method = st.radio("Import Method", ["Upload File", "Paste Content"])

            if import_method == "Upload File":
                _max_upload_mb = st.get_option("server.maxUploadSize")
                uploaded_file = st.file_uploader(
                    "Choose an ontology file",
                    type=["ttl", "owl", "rdf", "xml", "n3", "nt", "jsonld", "json"],
                    help=(
                        "Supported formats: Turtle (.ttl), RDF/XML (.owl, .rdf, .xml), "
                        "N3 (.n3), N-Triples (.nt), JSON-LD (.jsonld, .json). "
                        f"Maximum file size: {_max_upload_mb} MB — raise it via "
                        "server.maxUploadSize in .streamlit/config.toml."
                    ),
                    key=f"import_uploader_{st.session_state.get('import_uploader_key', 0)}",
                )

                if uploaded_file:
                    format_map = {
                        "ttl": "turtle",
                        "owl": "xml",
                        "rdf": "xml",
                        "xml": "xml",
                        "n3": "n3",
                        "nt": "nt",
                        "jsonld": "json-ld",
                        "json": "json-ld",
                    }
                    ext = uploaded_file.name.split(".")[-1].lower()
                    format_ = format_map.get(ext, "turtle")

                    btn_label = "Import" if _ont_is_empty else "Preview Import"
                    if st.button(btn_label):
                        try:
                            content = uploaded_file.read().decode("utf-8")
                            if _ont_is_empty:
                                _direct_import(content, format_)
                            else:
                                preview = ont.preview_import(content, format=format_)
                                st.session_state.import_preview = preview
                                st.session_state.import_content = content
                                st.session_state.import_format = format_
                                st.rerun()
                        except Exception as e:  # noqa: BLE001 - malformed import must show as a message, not a traceback
                            show_message(f"Error parsing file: {e!s}", "error")

            else:
                content = st.text_area("Paste Ontology Content", height=300)
                format_ = st.selectbox(
                    "Format", ["turtle", "xml", "n3", "nt", "json-ld"]
                )

                btn_label = "Import" if _ont_is_empty else "Preview Import"
                if st.button(btn_label):
                    if not content:
                        show_message("Please paste ontology content!", "error")
                    else:
                        try:
                            if _ont_is_empty:
                                _direct_import(content, format_)
                            else:
                                preview = ont.preview_import(content, format=format_)
                                st.session_state.import_preview = preview
                                st.session_state.import_content = content
                                st.session_state.import_format = format_
                                st.rerun()
                        except Exception as e:  # noqa: BLE001 - malformed import must show as a message, not a traceback
                            show_message(f"Error parsing content: {e!s}", "error")

        # Step 2: Review panel
        else:
            preview = st.session_state.import_preview
            diff = preview["diff"]
            diff_stats = diff["stats"]

            st.info(
                "Review the import changes below, then choose an import mode and apply."
            )

            # Import mode selector
            from .ontology_manager import (
                IMPORT_MERGE,
                IMPORT_MERGE_OVERWRITE,
                IMPORT_REPLACE,
            )

            strategy = st.radio(
                "Import Mode",
                ["Replace", "Merge", "Merge (Overwrite)"],
                captions=[
                    "Replace current ontology with imported content",
                    "Add imported content to current ontology (keep both)",
                    "Add imported content, overwrite conflicts with imported values",
                ],
                key="import_strategy_radio",
            )
            strategy_map = {
                "Replace": IMPORT_REPLACE,
                "Merge": IMPORT_MERGE,
                "Merge (Overwrite)": IMPORT_MERGE_OVERWRITE,
            }
            selected_strategy = strategy_map[strategy]

            # Statistics comparison
            st.subheader("Statistics Comparison")
            current_stats = ont.get_statistics()
            incoming_stats = preview["incoming_stats"]

            col_cur, col_inc = st.columns(2)
            with col_cur:
                st.caption("Current Ontology")
                st.metric("Classes", current_stats["classes"])
                st.metric("Object Properties", current_stats["object_properties"])
                st.metric("Data Properties", current_stats["data_properties"])
                st.metric("Individuals", current_stats["individuals"])
                st.metric("Total Triples", current_stats["total_triples"])
            with col_inc:
                incoming_meta = preview.get("incoming_meta", {})
                inc_label = incoming_meta.get("label", "")
                inc_uri = incoming_meta.get("uri", "")
                if inc_label:
                    st.caption(f"Incoming Content — **{inc_label}**")
                elif inc_uri:
                    st.caption(f"Incoming Content — {inc_uri}")
                else:
                    st.caption("Incoming Content")
                st.metric("Classes", incoming_stats["classes"])
                st.metric("Object Properties", incoming_stats["object_properties"])
                st.metric("Data Properties", incoming_stats["data_properties"])
                st.metric("Individuals", incoming_stats["individuals"])
                st.metric("Total Triples", incoming_stats["total_triples"])

            # Apply / Cancel buttons (compact, above the change report)
            col_apply, col_cancel, _ = st.columns([1, 1, 4])
            with col_apply:
                if st.button("Apply Import", type="primary"):
                    try:
                        content = st.session_state.import_content
                        format_ = st.session_state.import_format
                        if selected_strategy == IMPORT_REPLACE:
                            ont.load_from_string(content, format=format_)
                        else:
                            ont.merge_from_string(
                                content, format=format_, strategy=selected_strategy
                            )
                        st.session_state.ontology = ont
                        save_checkpoint("Import ontology")
                        request_autosave_flush()
                        st.session_state.import_preview = None
                        st.session_state.import_content = None
                        st.session_state.import_format = None
                        triples = len(ont.graph)
                        set_flash_message(
                            f"Ontology imported successfully! ({triples} triples)",
                            "success",
                        )
                        st.rerun()
                    except Exception as e:  # noqa: BLE001 - malformed import must show as a message, not a traceback
                        show_message(f"Error applying import: {e!s}", "error")
            with col_cancel:
                if st.button("Cancel"):
                    st.session_state.import_preview = None
                    st.session_state.import_content = None
                    st.session_state.import_format = None
                    st.rerun()

            # Diff summary
            with st.expander(
                f"Changes: {diff_stats['added']} triples added, "
                f"{diff_stats['removed']} removed, "
                f"{diff_stats['resources_modified']} resources modified",
                expanded=True,
            ):
                if diff["summary"]:
                    for line in diff["summary"]:
                        # Color-code by change type
                        if line.startswith("Added"):
                            st.markdown(f":green[{line}]")
                        elif line.startswith("Removed"):
                            st.markdown(f":red[{line}]")
                        elif line.startswith("Modified"):
                            st.markdown(f":orange[{line}]")
                        else:
                            st.write(line)
                else:
                    st.write("No changes detected.")

            # Conflicts (for merge modes)
            if selected_strategy != IMPORT_REPLACE:
                conflicts = preview.get("conflicts", [])
                if conflicts:
                    st.warning(f"{len(conflicts)} conflict(s) detected")
                    conflict_data = {
                        "Subject": [c["subject"] for c in conflicts],
                        "Predicate": [c["predicate"] for c in conflicts],
                        "Current Value": [
                            ", ".join(c["current_values"]) for c in conflicts
                        ],
                        "Incoming Value": [c["incoming_value"] for c in conflicts],
                    }
                    st.dataframe(conflict_data, width="stretch", hide_index=True)

            # Prefix conflicts
            prefix_conflicts = preview.get("prefix_conflicts", [])
            if prefix_conflicts:
                with st.expander(f"Prefix Changes ({len(prefix_conflicts)} conflicts)"):
                    pfx_data = {
                        "Prefix": [c["prefix"] for c in prefix_conflicts],
                        "Current Namespace": [
                            c["current_namespace"] for c in prefix_conflicts
                        ],
                        "Incoming Namespace": [
                            c["incoming_namespace"] for c in prefix_conflicts
                        ],
                    }
                    st.dataframe(pfx_data, width="stretch", hide_index=True)

            # Change report download
            report = ont.format_diff_report(diff, report_format="markdown")
            _download_or_save(
                "Download Change Report",
                report,
                "change_report.md",
                mime="text/markdown",
                key="change_report",
            )

    if _ie_tab == "Export":
        st.subheader("Export Ontology")

        format_options = {
            "Turtle (.ttl)": "turtle",
            "RDF/XML (.owl)": "xml",
            "N-Triples (.nt)": "nt",
            "N3 (.n3)": "n3",
            "JSON-LD (.jsonld)": "json-ld",
        }

        selected_format = st.selectbox(
            "Export Format", options=list(format_options.keys())
        )
        format_ = format_options[selected_format]

        file_extensions = {
            "turtle": "ttl",
            "xml": "owl",
            "nt": "nt",
            "n3": "n3",
            "json-ld": "jsonld",
        }

        ext = file_extensions[format_]
        if st.button("Generate Export"):
            try:
                st.session_state["_export_content"] = ont.export_to_string(
                    format=format_
                )
                st.session_state["_export_ext"] = ext
            except Exception as e:  # noqa: BLE001 - export failure must show as a message, not a traceback
                st.session_state.pop("_export_content", None)
                show_message(f"Error exporting ontology: {e!s}", "error")

        # Kept in session_state so the save/download controls (which each cause a
        # rerun) still have the generated content.
        content = st.session_state.get("_export_content")
        if content is not None:
            ext = st.session_state.get("_export_ext", ext)
            st.text_area("Exported Content", value=content, height=400)
            _download_or_save(
                f"Download .{ext} file",
                content,
                f"ontology.{ext}",
                key="export",
            )

    if _ie_tab == "New Ontology":
        st.subheader("Create New Ontology")

        st.warning(
            "This will clear the current ontology. Make sure to export first if needed."
        )

        with st.form("new_ontology_form"):
            base_uri = st.text_input(
                "Base URI *",
                value="http://example.org/ontology#",
                help="The base namespace URI for your ontology",
            )
            label = st.text_input("Label (rdfs:label)")
            comment = st.text_area("Comment (rdfs:comment)")
            creator = st.text_input("Creator")

            submitted = st.form_submit_button("Create New Ontology")
            if submitted:
                if not base_uri:
                    show_message("Base URI is required!", "error")
                else:
                    st.session_state.ontology = get_ontology_manager_class()(
                        base_uri=base_uri
                    )
                    st.session_state.ontology.set_ontology_metadata(
                        label=label, comment=comment, creator=creator
                    )
                    from .ontology_manager import UndoManager

                    st.session_state.undo_manager = UndoManager(
                        st.session_state.ontology
                    )
                    # Replacing the graph is a deliberate change; bump the
                    # revision and flush it to disk immediately.
                    st.session_state["_ont_mutation_count"] = (
                        st.session_state.get("_ont_mutation_count", 0) + 1
                    )
                    request_autosave_flush()
                    show_message("New ontology created!", "success")
                    st.rerun()

    if _ie_tab == "Templates":
        from .templates import get_template, get_template_names, render_template

        def _on_apply_template():
            selected = st.session_state.template_select
            mode = st.session_state.template_apply_mode
            tmpl = get_template(selected)
            base_uri = str(ont.namespace)
            rendered = render_template(tmpl, base_uri)
            if mode == "Replace current":
                ont.load_from_string(rendered, "turtle")
            else:
                ont.merge_from_string(rendered, "turtle")
            save_checkpoint(f"Apply template: {selected}")
            request_autosave_flush()
            s = ont.get_statistics()
            st.session_state["_template_msg"] = (
                f"Template '{selected}' applied! "
                f"— {s['classes']} classes, {s['object_properties']} obj props, "
                f"{s['data_properties']} data props, {s['content_triples']} triples"
            )

        st.subheader("Apply Template")
        st.caption("Bootstrap your ontology from a built-in template.")

        if "_template_msg" in st.session_state:
            st.success(st.session_state.pop("_template_msg"))

        template_names = get_template_names()
        selected_template = clearable_selectbox(
            "Select Template",
            template_names,
            key="template_select",
            current_display=template_names[0] if template_names else None,
        )

        if selected_template:
            tmpl = get_template(selected_template)
            st.write(f"**Description:** {tmpl['description']}")

            with st.expander("Preview Turtle"):
                base_uri = str(ont.namespace)
                rendered = render_template(tmpl, base_uri)
                st.code(rendered, language="turtle")

            st.radio(
                "Apply Mode",
                ["Merge into current", "Replace current"],
                horizontal=True,
                key="template_apply_mode",
            )

            st.button(
                "Apply Template",
                type="primary",
                key="apply_template_btn",
                on_click=_on_apply_template,
            )

    if _ie_tab == "Upper Ontologies":
        from .templates import (
            get_upper_ontology,
            get_upper_ontology_names,
            load_upper_ontology_module,
        )

        def _on_load_upper_ontology(upper):
            selected_modules = []
            for mod in upper["modules"]:
                if st.session_state.get(f"upper_mod_{mod['name']}", False):
                    selected_modules.append(mod)

            if not selected_modules:
                st.session_state["_upper_onto_err"] = "Select at least one module."
                return

            try:
                mode = st.session_state.upper_apply_mode
                first = True
                for mod in selected_modules:
                    content = load_upper_ontology_module(mod)
                    if first and mode == "Replace current":
                        ont.load_from_string(content, "turtle")
                        first = False
                    else:
                        ont.merge_from_string(content, "turtle")
                mod_names = ", ".join(m["name"] for m in selected_modules)
                save_checkpoint(f"Load upper ontology: {upper['name']} ({mod_names})")
                request_autosave_flush()
                s = ont.get_statistics()
                st.session_state["_upper_onto_msg"] = (
                    f"Loaded {upper['name']} ({mod_names})! "
                    f"— {s['classes']} classes, {s['object_properties']} obj props, "
                    f"{s['data_properties']} data props, {s['content_triples']} triples"
                )
            except Exception as e:  # noqa: BLE001 - a bad upper ontology must show as a message
                st.session_state["_upper_onto_err"] = (
                    f"Error loading upper ontology: {e!s}"
                )

        st.subheader("Upper Ontologies")
        st.caption(
            "Start from a professionally built upper ontology as a foundation. "
            "Your domain classes extend these foundational concepts."
        )

        if "_upper_onto_msg" in st.session_state:
            st.success(st.session_state.pop("_upper_onto_msg"))
        if "_upper_onto_err" in st.session_state:
            st.error(st.session_state.pop("_upper_onto_err"))

        upper_names = get_upper_ontology_names()
        selected_upper = clearable_selectbox(
            "Select Upper Ontology",
            upper_names,
            key="upper_ontology_select",
            current_display=upper_names[0] if upper_names else None,
        )

        if selected_upper:
            upper = get_upper_ontology(selected_upper)
            st.write(f"**{upper['name']}** v{upper['version']}")
            st.write(upper["description"])
            st.caption(
                f"License: {upper['license']} — Attribution: {upper['attribution']}"
            )
            if upper.get("url"):
                st.caption(f"More info: {upper['url']}")

            st.write("**Modules:**")
            for mod in upper["modules"]:
                default_on = mod.get("required", False) or mod.get("default", False)
                st.checkbox(
                    f"**{mod['name']}** — {mod['description']}",
                    value=default_on,
                    disabled=mod.get("required", False),
                    key=f"upper_mod_{mod['name']}",
                )

            st.radio(
                "Apply Mode",
                ["Merge into current", "Replace current"],
                horizontal=True,
                key="upper_apply_mode",
            )

            st.button(
                "Load Upper Ontology",
                type="primary",
                key="apply_upper_ontology_btn",
                on_click=_on_load_upper_ontology,
                args=(upper,),
            )

    if _ie_tab == "Reference Ontologies":
        from .templates import (
            get_reference_ontology,
            get_reference_ontology_names,
            load_reference_ontology_module,
        )

        def _on_load_reference_ontology(ref):
            selected_modules = []
            for mod in ref["modules"]:
                if st.session_state.get(f"ref_mod_{mod['name']}", False):
                    selected_modules.append(mod)

            if not selected_modules:
                st.session_state["_ref_onto_err"] = "Select at least one module."
                return

            try:
                mode = st.session_state.ref_apply_mode
                with st.spinner(f"Loading {ref['name']}…"):
                    first = True
                    for mod in selected_modules:
                        fmt = mod.get("format", "turtle")
                        content = load_reference_ontology_module(mod)
                        if first and mode == "Replace current":
                            ont.load_from_string(content, fmt)
                            first = False
                        else:
                            ont.merge_from_string(content, fmt)
                mod_names = ", ".join(m["name"] for m in selected_modules)
                save_checkpoint(f"Load reference ontology: {ref['name']} ({mod_names})")
                request_autosave_flush()
                s = ont.get_statistics()
                st.session_state["_ref_onto_msg"] = (
                    f"Loaded {ref['name']} ({mod_names})! "
                    f"— {s['classes']} classes, {s['object_properties']} obj props, "
                    f"{s['data_properties']} data props, {s['content_triples']} triples"
                )
            except Exception as e:  # noqa: BLE001 - a bad reference ontology must show as a message
                st.session_state["_ref_onto_err"] = (
                    f"Error loading reference ontology: {e!s}"
                )

        st.subheader("Reference Ontologies")
        st.caption(
            "Import widely-used domain and reference vocabularies into the "
            "current ontology. Bundled vocabularies load instantly; remote "
            "vocabularies are downloaded once on first use and cached locally."
        )

        if "_ref_onto_msg" in st.session_state:
            st.success(st.session_state.pop("_ref_onto_msg"))
        if "_ref_onto_err" in st.session_state:
            st.error(st.session_state.pop("_ref_onto_err"))

        ref_names = get_reference_ontology_names()
        selected_ref = clearable_selectbox(
            "Select Reference Ontology",
            ref_names,
            key="reference_ontology_select",
            current_display=ref_names[0] if ref_names else None,
        )

        if selected_ref:
            ref = get_reference_ontology(selected_ref)
            st.write(f"**{ref['name']}** v{ref['version']}")
            st.write(ref["description"])
            st.caption(f"License: {ref['license']} — Attribution: {ref['attribution']}")
            if ref.get("url"):
                st.caption(f"More info: {ref['url']}")

            has_remote = any("url" in m for m in ref["modules"])
            if has_remote:
                st.caption(
                    "📡 Source: downloaded on first use, cached locally. "
                    "Requires network access on first load."
                )
            else:
                st.caption("💾 Source: bundled with the application (offline-ready).")

            st.write("**Modules:**")
            for mod in ref["modules"]:
                default_on = mod.get("required", False) or mod.get("default", False)
                st.checkbox(
                    f"**{mod['name']}** — {mod['description']}",
                    value=default_on,
                    disabled=mod.get("required", False),
                    key=f"ref_mod_{mod['name']}",
                )

            st.radio(
                "Apply Mode",
                ["Merge into current", "Replace current"],
                horizontal=True,
                key="ref_apply_mode",
            )

            st.button(
                "Load Reference Ontology",
                type="primary",
                key="apply_reference_ontology_btn",
                on_click=_on_load_reference_ontology,
                args=(ref,),
            )


def render_advanced():
    """Render the advanced OWL features page."""
    st.header("Advanced OWL Features")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    class_names = [c["name"] for c in classes]
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    all_prop_names = [p["name"] for p in object_props] + [p["name"] for p in data_props]
    individuals = ont.get_individuals()
    ind_names = [i["name"] for i in individuals]

    _adv_tab = st.segmented_control(
        "Section",
        [
            "Class Expressions",
            "Property Chains",
            "Disjoint Union",
            "All Different",
            "Has Key",
        ],
        default="Class Expressions",
        key="adv_active_tab",
        label_visibility="collapsed",
    )
    if not _adv_tab:
        _adv_tab = "Class Expressions"

    if _adv_tab == "Class Expressions":
        st.subheader("Class Expressions")
        st.caption("Define complex class expressions using set operations")

        # View existing expressions
        expressions = ont.get_class_expressions()
        if expressions:
            st.write("**Existing Expressions:**")
            for expr in expressions:
                st.write(
                    f"- **{expr['class']}** {expr['type']}: {', '.join(expr['members'])}"
                )
        else:
            st.info("No class expressions defined yet.")

        st.divider()

        if len(class_names) < 2:
            st.warning("Need at least 2 classes to create expressions.")
        else:
            with st.form("add_class_expression_form"):
                target_class = required_selectbox(
                    "Target Class",
                    class_names,
                    key="adv_expr_target",
                    current_display=class_names[0] if class_names else None,
                    help="The class to define with this expression",
                )

                expr_type = st.selectbox(
                    "Expression Type",
                    options=["unionOf", "intersectionOf", "complementOf", "oneOf"],
                )

                st.write("**Select members:**")
                if expr_type == "complementOf":
                    complement_class = required_selectbox(
                        "Complement of Class",
                        class_names,
                        key="adv_expr_complement",
                        current_display=class_names[0] if class_names else None,
                    )
                    selected_classes = [complement_class] if complement_class else []
                    selected_individuals = []
                elif expr_type == "oneOf":
                    selected_individuals = st.multiselect(
                        "Individuals (enumeration)", options=ind_names
                    )
                    selected_classes = []
                else:
                    selected_classes = st.multiselect("Classes", options=class_names)
                    selected_individuals = []

                submitted = st.form_submit_button("Add Expression")
                if submitted:
                    if _missing := missing_required(**{"Target Class": target_class}):
                        show_message(_missing, "error")
                    elif expr_type == "oneOf" and selected_individuals:
                        ont.add_class_expression(
                            target_class, expr_type, individuals=selected_individuals
                        )
                        save_checkpoint("Add class expression")
                        show_message(f"Expression added to {target_class}", "success")
                        st.rerun()
                    elif selected_classes:
                        ont.add_class_expression(
                            target_class, expr_type, classes=selected_classes
                        )
                        save_checkpoint("Add class expression")
                        show_message(f"Expression added to {target_class}", "success")
                        st.rerun()
                    else:
                        show_message("Please select at least one member!", "error")

    if _adv_tab == "Property Chains":
        st.subheader("Property Chains")
        st.caption(
            "Define property chain axioms (e.g., hasParent o hasBrother = hasUncle)"
        )

        # View existing chains
        chains = ont.get_property_chains()
        if chains:
            st.write("**Existing Property Chains:**")
            for chain in chains:
                st.write(f"- **{chain['property']}** = {' o '.join(chain['chain'])}")
        else:
            st.info("No property chains defined yet.")

        st.divider()

        obj_prop_names = [p["name"] for p in object_props]
        if len(obj_prop_names) < 2:
            st.warning("Need at least 2 object properties to create chains.")
        else:
            with st.form("add_property_chain_form"):
                result_prop = required_selectbox(
                    "Result Property",
                    obj_prop_names,
                    key="adv_chain_result",
                    current_display=obj_prop_names[0] if obj_prop_names else None,
                    help="The property that results from following the chain",
                )

                chain_props = st.multiselect(
                    "Chain Properties (in order)",
                    options=obj_prop_names,
                    help="Select properties in the order they should be followed",
                )

                submitted = st.form_submit_button("Add Property Chain")
                if submitted:
                    if _missing := missing_required(**{"Result Property": result_prop}):
                        show_message(_missing, "error")
                    elif len(chain_props) < 2:
                        show_message("Chain must have at least 2 properties!", "error")
                    else:
                        ont.add_property_chain(result_prop, chain_props)
                        save_checkpoint("Add property chain")
                        show_message(
                            f"Property chain added for {result_prop}", "success"
                        )
                        st.rerun()

    if _adv_tab == "Disjoint Union":
        st.subheader("Disjoint Union")
        st.caption("Define a class as the disjoint union of other classes")

        # View existing disjoint unions
        unions = ont.get_disjoint_unions()
        if unions:
            st.write("**Existing Disjoint Unions:**")
            for union in unions:
                st.write(
                    f"- **{union['class']}** = disjointUnionOf({', '.join(union['members'])})"
                )
        else:
            st.info("No disjoint unions defined yet.")

        st.divider()

        if len(class_names) < 3:
            st.warning(
                "Need at least 3 classes (1 parent + 2 children) for disjoint union."
            )
        else:
            with st.form("add_disjoint_union_form"):
                parent_class = required_selectbox(
                    "Parent Class",
                    class_names,
                    key="adv_union_parent",
                    current_display=class_names[0] if class_names else None,
                    help="The class that is the disjoint union",
                )

                member_classes = st.multiselect(
                    "Member Classes",
                    options=class_names,
                    help="Classes that make up the disjoint union",
                )

                submitted = st.form_submit_button("Add Disjoint Union")
                if submitted:
                    if _missing := missing_required(**{"Parent Class": parent_class}):
                        show_message(_missing, "error")
                    elif len(member_classes) < 2:
                        show_message("Need at least 2 member classes!", "error")
                    elif parent_class in member_classes:
                        show_message("Parent class cannot be a member!", "error")
                    else:
                        ont.add_disjoint_union(parent_class, member_classes)
                        save_checkpoint("Add disjoint union")
                        show_message(
                            f"Disjoint union added for {parent_class}", "success"
                        )
                        st.rerun()

    if _adv_tab == "All Different":
        st.subheader("All Different")
        st.caption("Declare that a set of individuals are all mutually different")

        # View existing AllDifferent declarations
        all_diffs = ont.get_all_different()
        if all_diffs:
            st.write("**Existing AllDifferent Declarations:**")
            for i, diff in enumerate(all_diffs):
                st.write(f"- AllDifferent: {', '.join(diff)}")
        else:
            st.info("No AllDifferent declarations yet.")

        st.divider()

        if len(ind_names) < 2:
            st.warning("Need at least 2 individuals for AllDifferent.")
        else:
            with st.form("add_all_different_form"):
                selected_inds = st.multiselect(
                    "Select Individuals",
                    options=ind_names,
                    help="All selected individuals will be declared mutually different",
                )

                submitted = st.form_submit_button("Add AllDifferent")
                if submitted:
                    if len(selected_inds) < 2:
                        show_message("Select at least 2 individuals!", "error")
                    else:
                        ont.add_all_different(selected_inds)
                        save_checkpoint("Add all different")
                        show_message("AllDifferent declaration added!", "success")
                        st.rerun()

    if _adv_tab == "Has Key":
        st.subheader("Has Key")
        st.caption("Define key properties that uniquely identify instances of a class")

        # View existing hasKey declarations
        keys = ont.get_has_keys()
        if keys:
            st.write("**Existing hasKey Declarations:**")
            for key in keys:
                st.write(f"- **{key['class']}** hasKey: {', '.join(key['properties'])}")
        else:
            st.info("No hasKey declarations yet.")

        st.divider()

        if not class_names:
            st.warning("Need at least 1 class.")
        elif not all_prop_names:
            st.warning("Need at least 1 property.")
        else:
            with st.form("add_has_key_form"):
                target_class = required_selectbox(
                    "Class",
                    class_names,
                    key="adv_haskey_class",
                    current_display=class_names[0] if class_names else None,
                )

                key_props = st.multiselect(
                    "Key Properties",
                    options=all_prop_names,
                    help="Properties that together uniquely identify instances",
                )

                submitted = st.form_submit_button("Add hasKey")
                if submitted:
                    if _missing := missing_required(Class=target_class):
                        show_message(_missing, "error")
                    elif not key_props:
                        show_message("Select at least 1 property!", "error")
                    else:
                        ont.add_has_key(target_class, key_props)
                        save_checkpoint("Add has key")
                        show_message(f"hasKey added for {target_class}", "success")
                        st.rerun()


def render_validation():
    """Render the validation and reasoning page."""
    st.header("Validation & Reasoning")

    ont = st.session_state.ontology

    _val_tab = st.segmented_control(
        "Section",
        ["Validation", "Reasoning"],
        default="Validation",
        key="val_active_tab",
        label_visibility="collapsed",
    )
    if not _val_tab:
        _val_tab = "Validation"

    if _val_tab == "Validation":
        st.subheader("Ontology Validation")

        check_domain_range = st.checkbox(
            "Check for missing domain/range",
            value=False,
            help="Report properties without rdfs:domain/rdfs:range (or schema:domainIncludes/gist:domainIncludes). Off by default since many ontologies intentionally omit these.",
        )

        if st.button("Run Validation"):
            issues = ont.validate(check_missing_domain_range=check_domain_range)

            if not issues:
                show_message("No issues found! The ontology looks good.", "success")
            else:
                st.write(f"Found {len(issues)} issue(s):")

                # Group by severity
                errors = [i for i in issues if i["severity"] == "error"]
                warnings = [i for i in issues if i["severity"] == "warning"]
                infos = [i for i in issues if i["severity"] == "info"]

                if errors:
                    st.error(f"**Errors ({len(errors)}):**")
                    for issue in errors:
                        st.write(f"  - {issue['message']}")

                if warnings:
                    st.warning(f"**Warnings ({len(warnings)}):**")
                    for issue in warnings:
                        st.write(f"  - {issue['message']}")

                if infos:
                    st.info(f"**Information ({len(infos)}):**")
                    for issue in infos:
                        st.write(f"  - {issue['message']}")

    if _val_tab == "Reasoning":
        st.subheader("Apply Reasoning")

        st.write("""
        Reasoning can infer new triples based on the ontology structure.
        This uses OWL-RL (Rule Language) reasoning.
        """)

        profile = st.selectbox(
            "Reasoning Profile",
            [("RDFS", "rdfs"), ("OWL-RL", "owl-rl"), ("OWL-RL Extended", "owl-rl-ext")],
            format_func=lambda x: x[0],
        )

        current_triples = len(ont.graph)
        st.write(f"Current triple count: {current_triples}")

        if st.button("Apply Reasoning"):
            try:
                new_triples = ont.apply_reasoning(profile=profile[1])
                save_checkpoint("Apply reasoning")
                request_autosave_flush()
                show_message(
                    f"Reasoning complete! {new_triples} new triples inferred.",
                    "success",
                )
                st.write(f"New triple count: {len(ont.graph)}")
            except Exception as e:  # noqa: BLE001 - reasoner failure must show as a message, not a traceback
                show_message(f"Error during reasoning: {e!s}", "error")


def render_visualization():
    """Render the visualization page."""
    st.header("Visualization")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    individuals = ont.get_individuals()

    stats = ont.get_statistics()

    if stats["content_triples"] == 0:
        st.info(
            "No content to visualize. Add classes, properties, individuals, or SKOS concepts first."
        )
        return

    # Seeded in session_state rather than passed as ``default=``, the way the
    # Classes, Relations and Restrictions pages do it.
    if "viz_active_tab" not in st.session_state:
        st.session_state["viz_active_tab"] = "Interactive Graph"
    _viz_tab = st.segmented_control(
        "Section",
        ["Interactive Graph", "Class Hierarchy", "Statistics"],
        key="viz_active_tab",
        label_visibility="collapsed",
    )
    if not _viz_tab:
        _viz_tab = "Interactive Graph"

    if _viz_tab == "Interactive Graph":
        # Row 1: entity type checkboxes + ind. edges + triples
        _has_skos = stats.get("concepts", 0) > 0
        _has_owl = (
            stats["classes"] > 0
            or stats["object_properties"] > 0
            or stats["data_properties"] > 0
        )

        # Persist viz settings across page switches.
        # Widget keys are removed from session_state when the page is not rendered,
        # so we store settings in separate "_viz_cfg_*" keys and sync on each visit.
        _viz_cfg = {
            "show_classes": _has_owl,
            "show_obj_props": _has_owl,
            "show_data_props": False,
            "show_annotations": False,
            "show_individuals": False,
            "show_skos": True,
            "show_ind_edges": False,
            "show_triples": False,
            "graph_height": 670,
            "node_spacing": 150,
            "fit": True,
            "details_panel": False,
            "highlight_issues": False,
            "focus_mode": False,
            "focus_depth": 1,
            "options_open": True,
        }
        # Bring back settings saved in a previous session before applying
        # defaults, so a returning user opens with their own preferences (#142).
        _restore_viz_settings(_viz_cfg)
        for _k, _v in _viz_cfg.items():
            cfg_key = f"_viz_cfg_{_k}"
            wid_key = f"viz_{_k}"
            if cfg_key not in st.session_state:
                st.session_state[cfg_key] = _v
            # Restore widget key from persisted config
            st.session_state[wid_key] = st.session_state[cfg_key]

        # The display options are a band of controls above the canvas that is
        # set once and then left alone, so it collapses to give the graph the
        # room. A toggle rather than an expander: an expander's open state is
        # client-side only and resets on reload, while this rides the same
        # persisted viz settings, so a band you collapsed stays collapsed.
        # Render sits outside it, since redrawing is the one thing still worth
        # doing while the rest is out of the way.
        _opt_col, _render_col = st.columns([5, 1])
        with _opt_col:
            options_open = st.toggle(
                "Display options",
                key="viz_options_open",
                on_change=viz_sync,
                args=("_viz_cfg_options_open", "viz_options_open"),
                help="Which node types to draw, the graph height and the "
                "layout spacing.",
            )
        with _render_col:
            render_graph = st.button(
                "Render",
                type="primary",
                use_container_width=True,
                help="Redraw the graph and re-run the layout. Also re-centres on "
                "the current Find selection.",
            )

        if options_open:
            _cols = (
                st.columns([1, 1, 1, 1, 1, 1, 1, 1])
                if _has_skos
                else st.columns([1, 1, 1, 1, 1, 1, 1])
            )
            with _cols[0]:
                st.checkbox(
                    "Classes",
                    key="viz_show_classes",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_classes", "viz_show_classes"),
                )
            with _cols[1]:
                st.checkbox(
                    "Obj Props",
                    key="viz_show_obj_props",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_obj_props", "viz_show_obj_props"),
                )
            with _cols[2]:
                st.checkbox(
                    "Data Props",
                    key="viz_show_data_props",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_data_props", "viz_show_data_props"),
                )
            with _cols[3]:
                st.checkbox(
                    "Annotations",
                    key="viz_show_annotations",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_annotations", "viz_show_annotations"),
                )
            with _cols[4]:
                st.checkbox(
                    "Individuals",
                    key="viz_show_individuals",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_individuals", "viz_show_individuals"),
                )
            _ind_edge_col, _triple_col = (
                (_cols[6], _cols[7]) if _has_skos else (_cols[5], _cols[6])
            )
            if _has_skos:
                with _cols[5]:
                    st.checkbox(
                        "SKOS",
                        key="viz_show_skos",
                        on_change=viz_sync,
                        args=("_viz_cfg_show_skos", "viz_show_skos"),
                    )
            with _ind_edge_col:
                st.checkbox(
                    "Ind. Edges",
                    key="viz_show_ind_edges",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_ind_edges", "viz_show_ind_edges"),
                    help="Show property edges between individuals",
                )
            with _triple_col:
                st.checkbox(
                    "Triples",
                    key="viz_show_triples",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_triples", "viz_show_triples"),
                    help="Show all RDF triples for visible nodes",
                )

            # Row 2: sliders + fit-to-window + highlight issues
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
            with col1:
                st.slider(
                    "Graph Height",
                    300,
                    1200,
                    step=10,
                    key="viz_graph_height",
                    on_change=viz_sync,
                    args=("_viz_cfg_graph_height", "viz_graph_height"),
                    disabled=st.session_state.get("_viz_cfg_fit", True),
                    help="Used when 'Fit to window' is off.",
                )
            with col2:
                st.slider(
                    "Node Spacing",
                    50,
                    300,
                    help="Distance between nodes. Increase for less overlap.",
                    key="viz_node_spacing",
                    on_change=viz_sync,
                    args=("_viz_cfg_node_spacing", "viz_node_spacing"),
                )
            with col3:
                st.checkbox(
                    "Fit to window",
                    help="Resize the graph to fill the window height. "
                    "Turn off to use the Graph Height slider.",
                    key="viz_fit",
                    on_change=viz_sync,
                    args=("_viz_cfg_fit", "viz_fit"),
                )
            with col4:
                st.checkbox(
                    "Highlight Issues",
                    key="viz_highlight_issues",
                    on_change=viz_sync,
                    args=("_viz_cfg_highlight_issues", "viz_highlight_issues"),
                )

        # Read the settings from the persisted config rather than from the
        # widgets' return values: collapsed, the widgets do not render at all,
        # and the config is what they write into either way.
        _cfg = st.session_state
        show_classes = _cfg["_viz_cfg_show_classes"]
        show_properties = _cfg["_viz_cfg_show_obj_props"]
        show_data_props = _cfg["_viz_cfg_show_data_props"]
        show_annotations = _cfg["_viz_cfg_show_annotations"]
        show_individuals = _cfg["_viz_cfg_show_individuals"]
        # SKOS has no toggle without concepts to draw, so it stays off rather
        # than reading a stale True from a previous ontology.
        show_skos = _has_skos and _cfg["_viz_cfg_show_skos"]
        show_ind_edges = _cfg["_viz_cfg_show_ind_edges"]
        show_triples = _cfg["_viz_cfg_show_triples"]
        height = _cfg["_viz_cfg_graph_height"]
        node_spacing = _cfg["_viz_cfg_node_spacing"]
        fit = _cfg["_viz_cfg_fit"]
        highlight_issues = _cfg["_viz_cfg_highlight_issues"]

        validation_subjects = set()
        if highlight_issues:
            issues = ont.validate()
            validation_subjects = {i["subject"] for i in issues}

        # Class filter — reconcile the selection with the current class set
        # instead of resetting it on every ontology mutation, which used to wipe
        # a narrowed filter whenever a class or restriction was added (#180).
        # A mutation-counter jump not matched by the edit counter means the whole
        # ontology was replaced (load/import/new/undo), so reset to "all" rather
        # than diffing against a now-unrelated ontology that may reuse URIs.
        #
        # The widget lists the namespace-tagged display names, so two classes
        # sharing a local name are separately selectable rather than showing as
        # one duplicated entry that toggles both (issue #179). The *state* is
        # keyed by URI: a display label grows its namespace tag the moment a
        # second class takes the same local name, so a selection stored by label
        # would read as "these classes just appeared" and re-show a hidden one.
        # Every filterable kind is reconciled the same way, so the per-kind state
        # lives in one dict keyed by the kind's key rather than a parallel set of
        # variables per kind (issue #196).
        _kind_items = {"class": classes, "ind": individuals}
        # Filters and focus seeds the user left behind for this linked file
        # (issue #164). Empty on the cloud, and after the first render. Runs
        # before the replacement check below, which reads counters it clears.
        _file_state = _restore_viz_file_state()
        replaced = viz_ontology_was_replaced()
        _saved_seed_ids = _str_list(_file_state.get("focus_seed_ids"))
        if _saved_seed_ids and "_viz_cfg_focus_seeds" not in st.session_state:
            # Held until focus_targets exists further down — that's the map from
            # node id back to the label the multiselect shows.
            st.session_state["_viz_pending_focus_seed_ids"] = _saved_seed_ids
        filters: dict[str, dict] = {}
        for _kind in _FILTER_KINDS:
            _key = _kind["key"]
            _entries = build_filter_entries(_kind_items.get(_key) or [])
            _all_uris = [e["uri"] for e in _entries]
            _prev_sel, _prev_known = seed_filter_from_saved(
                _all_uris,
                set(_str_list(_file_state.get(f"hidden_{_key}_uris"))),
                st.session_state.get(f"_viz_cfg_selected_{_key}_uris"),
                st.session_state.get(f"_viz_cfg_known_{_key}_uris"),
            )
            _sel_uris, _known_uris = reconcile_filter_selection(
                _all_uris,
                _prev_sel,
                _prev_known,
                replaced=replaced,
            )
            st.session_state[f"_viz_cfg_selected_{_key}_uris"] = _sel_uris
            st.session_state[f"_viz_cfg_known_{_key}_uris"] = _known_uris
            _display_by_uri = {e["uri"]: e["display"] for e in _entries}
            _selected_displays = [_display_by_uri[u] for u in _sel_uris]
            # The multiselect holds display labels; seed its widget value here so
            # the reconciled selection is what it renders.
            st.session_state[f"viz_selected_{_key}"] = _selected_displays
            filters[_key] = {
                "kind": _kind,
                "entries": _entries,
                "displays": [e["display"] for e in _entries],
                "uris": [e["uri"] for e in _entries],
                "display_by_uri": _display_by_uri,
                "uri_by_display": {e["display"]: e["uri"] for e in _entries},
                "selected_uris": _sel_uris,
                "selected_displays": _selected_displays,
            }
        viz_mark_ontology_seen()

        class_entries = filters["class"]["entries"]
        all_class_names = filters["class"]["displays"]
        selected_classes_list = filters["class"]["selected_displays"]
        ind_entries = filters["ind"]["entries"]
        selected_ind_uris = set(filters["ind"]["selected_uris"])
        # Display mirror of the class selection, refreshed here on every render
        # and never written to elsewhere. The focus-mode controls below read it
        # to seed themselves from the current selection. The total rides along so
        # they can tell a real narrowing from the everything-selected default
        # (see focus_seeds_from_selection); neither is a persisted setting.
        st.session_state["_viz_cfg_selected_classes"] = selected_classes_list
        st.session_state["_viz_cfg_class_count"] = len(all_class_names)

        # Focus mode: centre the view on one node (class, individual or SKOS
        # concept) and show only its neighbourhood within N hops. The pruning
        # runs after the full graph is built (see below), so "depth" counts real
        # links of every type — not just subclass chains. Seed options are keyed
        # to the same node ids the graph builder assigns.
        focus_targets: dict[str, str] = {}
        if show_classes:
            for e in class_entries:
                focus_targets[f"Class: {e['display']}"] = _uid(e["uri"])
        if show_individuals:
            for e in ind_entries:
                focus_targets[f"Individual: {e['display']}"] = f"ind_{_uid(e['uri'])}"
        if show_data_props:
            for prop in data_props:
                focus_targets[f"Data Property: {prop['name']}"] = (
                    f"dprop_{_uid(prop['uri'])}"
                )
        if show_skos and _has_skos:
            for concept in ont.get_concepts():
                focus_targets[f"Concept: {concept['name']}"] = f"skos_{concept['name']}"

        # Seeds whose label now names a *different* entity than it did last
        # render belong to an ontology that has since been swapped out, so drop
        # them before anything reads or persists them.
        if "_viz_cfg_focus_seeds" in st.session_state:
            st.session_state["_viz_cfg_focus_seeds"] = prune_reused_focus_seeds(
                st.session_state["_viz_cfg_focus_seeds"],
                st.session_state.get("_viz_cfg_focus_seed_ids_by_label"),
                focus_targets,
            )

        # Seeds saved for this linked file are stored as node ids (#164); turn
        # them back into the labels the multiselect works in. An id whose entity
        # is gone — or whose type is toggled off, and so isn't in focus_targets —
        # simply drops out, the same pruning the focus block does below.
        _pending_seed_ids = st.session_state.pop("_viz_pending_focus_seed_ids", None)
        if _pending_seed_ids and "_viz_cfg_focus_seeds" not in st.session_state:
            _label_by_id = {node_id: label for label, node_id in focus_targets.items()}
            _restored_seeds = [
                _label_by_id[i] for i in _pending_seed_ids if i in _label_by_id
            ]
            if _restored_seeds:
                st.session_state["_viz_cfg_focus_seeds"] = _restored_seeds

        # Find & centre on a specific entity (issue #144). Independent of focus
        # mode: picking an entity here selects and camera-centres it in the graph
        # via vis-network focus(), so it's easy to locate in a large graph. The
        # options reuse the focus_targets label -> node-id map built above. It
        # sits beside the Filter Classes expander so it doesn't cost the graph a
        # whole row; the empty state is a placeholder (clearable), not a "—" row.
        _find_id: str | None = None
        # Whether that target is a class. Class node ids carry no prefix, so the
        # kind cannot be read back off the id the way the others can, and the
        # class loop's own guard needs it: an emptied filter would otherwise skip
        # the loop before the per-node bypass could run (issue #234 review).
        _find_is_class = False
        focus_seed_ids: list = []
        # Declared with the rest, not left to the branch that draws the picker:
        # with focus mode on and every focusable type switched off, that branch
        # does not run and the page crashed reading this further down (P1).
        focus_seeds: list = []
        focus_depth = 0
        _find_col, _filter_col = st.columns([1, 3])
        with _find_col:
            if focus_targets:
                _find_choice = st.selectbox(
                    "Find entity in graph",
                    options=sorted(focus_targets),
                    index=None,
                    placeholder="🔍 Find and centre on an entity…",
                    label_visibility="collapsed",
                    key="viz_find_entity",
                    on_change=viz_find_changed,
                    help="Jump to and highlight an entity so it's easy to spot "
                    "in a large graph. Lists the entity types enabled above.",
                )
                if _find_choice:
                    _find_id = focus_targets.get(_find_choice)
                    _find_is_class = bool(_find_id) and _find_choice.startswith(
                        "Class: "
                    )
                    # The target may currently be hidden — by one of the display
                    # filters, or pruned away in focus mode — in which case its
                    # node isn't in the graph and the JS focus() would silently
                    # no-op (PR #144 review P2). On a fresh pick, reveal it:
                    # restore a filtered-out entity and, in focus mode, add it as
                    # a seed so the prune keeps it. Guarded by the find seq so
                    # this runs once per pick.
                    _cur_seq = st.session_state.get("_viz_find_seq", 0)
                    if st.session_state.get("_viz_find_revealed_seq") != _cur_seq:
                        st.session_state["_viz_find_revealed_seq"] = _cur_seq
                        _reveal_rerun = False
                        # A node filter hiding the target is handled where the
                        # graph is built, against the live filter, so nothing is
                        # written back here. Un-hiding it once per pick both
                        # rewrote a filter the user had set and went stale the
                        # moment a later filter change hid it again (issue #234).
                        if st.session_state.get("_viz_cfg_focus_mode"):
                            _seeds = list(
                                st.session_state.get("_viz_cfg_focus_seeds") or []
                            )
                            if _find_choice not in _seeds:
                                st.session_state["_viz_cfg_focus_seeds"] = _seeds + [
                                    _find_choice
                                ]
                                _reveal_rerun = True
                        if _reveal_rerun:
                            st.rerun()
        # What the view is holding back, on the expander's own label: it costs
        # no vertical space there, and it sits on the control that causes it.
        # Written by the run that built the graph (below), because the numbers
        # come from the focus controls inside this very expander and from the
        # prune, neither of which has happened yet. Italic, which the CSS hides
        # while the expander is open — the controls then say it in full.
        _hidden_note = st.session_state.get("_viz_hidden_note") or ""
        _filter_label = "Filter Nodes"
        if _hidden_note:
            _filter_label += f" &nbsp; *{_hidden_note}*"
        with (
            _filter_col.container(key="viz_filter_nodes"),
            st.expander(_filter_label, expanded=False),
        ):
            focus_mode = st.checkbox(
                "Focus on one node",
                key="viz_focus_mode",
                on_change=viz_focus_toggle,
                help=(
                    "Show only a chosen node plus everything linked to it within "
                    "N hops, across all node types — handy for large ontologies "
                    "where showing everything at once is overwhelming."
                ),
            )
            if focus_mode and focus_targets:
                focus_labels = list(focus_targets.keys())
                label_set = set(focus_labels)
                # Default the focus seeds to the classes selected in the
                # multiselect, so the neighbourhood grows from exactly what the
                # user had narrowed to — or from one class when they had narrowed
                # to nothing (see focus_seeds_from_selection).
                saved_seeds = st.session_state.get("_viz_cfg_focus_seeds")
                if saved_seeds is None:
                    saved_seeds = focus_seeds_from_selection(
                        st.session_state.get("_viz_cfg_selected_classes") or [],
                        len(all_class_names),
                    )
                saved_seeds = [s for s in saved_seeds if s in label_set]
                if not saved_seeds:
                    saved_seeds = [focus_labels[0]]
                st.session_state["_viz_cfg_focus_seeds"] = saved_seeds
                st.session_state["viz_focus_seeds"] = saved_seeds
                # Remember what each label resolved to, so the next render can
                # tell a label that has come to name a different entity from one
                # that still names the same (see prune_reused_focus_seeds).
                st.session_state["_viz_cfg_focus_seed_ids_by_label"] = {
                    s: focus_targets.get(s) for s in saved_seeds
                }
                fcol1, fcol2 = st.columns([3, 1])
                with fcol1:
                    focus_seeds = st.multiselect(
                        "Focus node(s)",
                        options=focus_labels,
                        key="viz_focus_seeds",
                        on_change=viz_sync,
                        args=("_viz_cfg_focus_seeds", "viz_focus_seeds"),
                        help="Classes, individuals or SKOS concepts to centre on. "
                        "The neighbourhood grows from all of them. Starts from "
                        "the classes you had filtered down to, or from one when "
                        "you hadn't filtered. Toggle the entity-type checkboxes "
                        "above to list more.",
                    )
                with fcol2:
                    focus_depth = st.slider(
                        "Depth (hops)",
                        1,
                        5,
                        key="viz_focus_depth",
                        on_change=viz_sync,
                        args=("_viz_cfg_focus_depth", "viz_focus_depth"),
                        help="1 = direct neighbours only; higher pulls in further links.",
                    )
                focus_seed_ids = [
                    focus_targets[s] for s in focus_seeds if s in focus_targets
                ]
                # Build the full graph so the neighbourhood isn't pre-limited;
                # the post-build prune narrows it to the seeds' links.
                selected_classes = all_class_names
            elif focus_mode:
                st.info(
                    "Enable Classes, Individuals or SKOS above to pick focus nodes."
                )
                selected_classes = []
            else:
                # One kind is edited at a time, chosen by a segmented control, so
                # the panel stays the same height however many filterable kinds
                # exist (issue #196). Each segment carries a "shown/total" count
                # so a narrowing applied to a kind you're not looking at is still
                # visible. Only kinds whose entity-type checkbox is on are
                # offered — filtering something that isn't drawn is meaningless.
                _toggles = {
                    "show_classes": show_classes,
                    "show_individuals": show_individuals,
                }
                _live = [
                    f
                    for f in filters.values()
                    if _toggles.get(f["kind"]["toggle"]) and f["entries"]
                ]
                _by_key = {f["kind"]["key"]: f for f in _live}

                def _seg_text(key):
                    f = _by_key[key]
                    shown, total = len(f["selected_uris"]), len(f["entries"])
                    label = f["kind"]["label"]
                    return label if shown == total else f"{label} {shown}/{total}"

                if not _live:
                    st.info("Enable Classes or Individuals above to filter them.")
                    active = None
                else:
                    # Options are the stable kind keys and the count lives in
                    # format_func, so a narrowing that rewrites the caption never
                    # invalidates the widget's stored value.
                    _prev = st.session_state.get("_viz_cfg_filter_kind")
                    # A kind can vanish under the selector — its entity-type
                    # checkbox is turned off, or its last entity is deleted. The
                    # widget's own stored value is validated against the options
                    # too, so a stale one raises rather than falling back to the
                    # default; drop it and let `default` re-seed the control.
                    if st.session_state.get("viz_filter_kind") not in _by_key:
                        st.session_state.pop("viz_filter_kind", None)
                    _picked = st.segmented_control(
                        "Filter kind",
                        options=list(_by_key),
                        format_func=_seg_text,
                        default=_prev if _prev in _by_key else next(iter(_by_key)),
                        label_visibility="collapsed",
                        key="viz_filter_kind",
                    )
                    active = _by_key.get(_picked) or _live[0]
                    st.session_state["_viz_cfg_filter_kind"] = active["kind"]["key"]

                if active is not None:
                    _key = active["kind"]["key"]
                    _noun = active["kind"]["noun"]
                    _plural = active["kind"]["plural"]
                    _entries = active["entries"]
                    st.multiselect(
                        f"Select {_plural} to display",
                        options=active["displays"],
                        help=f"Choose which {_plural} to show in the graph. Empty "
                        f"shows none; use 'Select all' to bring them back.",
                        key=f"viz_selected_{_key}",
                        on_change=viz_filter_changed,
                        args=(_key, active["uri_by_display"]),
                        label_visibility="collapsed",
                        placeholder=f"No {_plural} shown — pick some, or Select all",
                    )
                    _picked_uris = (
                        st.session_state.get(f"_viz_cfg_selected_{_key}_uris") or []
                    )
                    _narrowed = len(_picked_uris) != len(_entries)
                    _bcol1, _bcol2 = st.columns([1, 1])
                    # An empty (or narrowed) filter hides nodes and there is no
                    # native way back — offer a one-click restore (issue B3).
                    with _bcol1:
                        # The count says what the button would restore you to, so
                        # its greyed-out state reads as "you already have all 4"
                        # rather than as an arbitrary disable. Its only other
                        # signal is the shown/total on the segmented control
                        # above, which is easy to miss and sits on a different
                        # widget.
                        if st.button(
                            f"Select all ({len(_entries)})",
                            key=f"viz_select_all_{_key}",
                            disabled=not _narrowed,
                            use_container_width=True,
                            help=f"Show every {_noun} in the graph again.",
                        ):
                            st.session_state[f"_viz_cfg_selected_{_key}_uris"] = list(
                                active["uris"]
                            )
                            st.rerun()
                    # Picking a handful out of a long multiselect is slow, and the
                    # selection is worth keeping — so the filter can also be driven
                    # by a pasted list, and prints the current one back in the same
                    # syntax to copy and restore later (issue #179). It lives in a
                    # popover so it costs one button rather than five rows.
                    with _bcol2.popover("Paste / copy", use_container_width=True):
                        _paste_text = st.text_area(
                            f"Paste a list of {_plural}",
                            key=f"viz_paste_{_key}",
                            height=80,
                            placeholder="Person Organization fn:zero",
                            help="Separate names with spaces, commas or line "
                            "breaks. Applying replaces the selection. Names "
                            "shared by several namespaces select all of them — "
                            "write 'fn:zero' (or paste the full URI) to pick "
                            "just one.",
                        )
                        if st.button(
                            "Apply pasted list",
                            key=f"viz_apply_paste_{_key}",
                            help=f"Show exactly the pasted {_plural}.",
                        ):
                            _pasted, _unknown = parse_filter_text(_paste_text, _entries)
                            if _pasted:
                                # The warning has to outlive the rerun that
                                # applies the selection, so a partly matching
                                # paste still reports what it dropped.
                                st.session_state["_viz_paste_unknown"] = _unknown
                                st.session_state[f"_viz_cfg_selected_{_key}_uris"] = (
                                    _pasted
                                )
                                st.rerun()
                            elif _unknown:
                                st.warning(
                                    f"No {_noun} matched: {_fmt_unknown(_unknown)}"
                                )
                            else:
                                st.info(f"Paste one or more {_noun} names first.")
                        _unknown_last = st.session_state.pop("_viz_paste_unknown", None)
                        if _unknown_last:
                            st.warning(
                                f"Ignored, no such {_noun}: "
                                f"{_fmt_unknown(_unknown_last)}"
                            )
                        if _picked_uris:
                            _sel_set = set(_picked_uris)
                            st.caption("Current selection — copy to restore it later:")
                            st.code(
                                " ".join(
                                    filter_entry_token(e)
                                    for e in _entries
                                    if e["uri"] in _sel_set
                                ),
                                language=None,
                                wrap_lines=True,
                            )
                # Authoritative regardless of which segment is on screen: the
                # class filter still applies while you are editing another kind.
                selected_classes = selected_classes_list

        # Persist the display preferences (entity toggles, spacing, fit, ...) so
        # they survive a reload (#142). Runs after every control has synced its
        # value; no-ops when nothing changed.
        _persist_viz_settings()
        # The entity-naming state (node filters, focus seeds) is saved separately,
        # against the linked working file it belongs to (#164).
        _persist_viz_file_state(filters, focus_targets)

        # Store graph settings in session state for caching
        selected_classes_key = (
            "_".join(sorted(selected_classes)) if selected_classes else "none"
        )
        # Narrowing the individuals filter has to invalidate the cached graph too.
        selected_inds_key = (
            "_".join(sorted(selected_ind_uris)) if selected_ind_uris else "none"
        )
        # Bump to invalidate cached graph data after code changes. 19: annotation
        # nodes gained a stable id, ntype and ename (issue #223), and a session
        # holding a pre-#223 payload would otherwise keep serving nodes a click
        # cannot resolve until some unrelated change happened to evict it.
        _graph_ver = 19
        # Include a mutation counter that bumps on every checkpoint / undo / redo,
        # so any change to the ontology — even one that preserves triple count —
        # invalidates the cached graph data and the iframe re-renders.
        ont_mutation = st.session_state.get("_ont_mutation_count", 0)
        # The Find target belongs in the key because it decides which nodes get
        # built: it is drawn even when the cap would otherwise have dropped it
        # (issue #234). Without it the usual order of events defeats the whole
        # thing — the page builds and caches a graph with no target, then picking
        # one changes nothing the key can see, so no rebuild happens and the
        # cached payload still lacks the entity that was asked for.
        graph_key = f"v{_graph_ver}_m{ont_mutation}_{show_classes}_{show_properties}_{show_data_props}_{show_annotations}_{show_individuals}_{show_ind_edges}_{show_skos}_{show_triples}_{height}_{node_spacing}_{highlight_issues}_{hash(selected_classes_key)}_{hash(selected_inds_key)}_{focus_mode}_{'-'.join(sorted(focus_seed_ids))}_{focus_depth}_{_find_id or ''}"
        if "last_graph_key" not in st.session_state:
            st.session_state.last_graph_key = None
            st.session_state.last_graph_data = None
        if "viz_render_seq" not in st.session_state:
            st.session_state.viz_render_seq = 0

        # Bump the layout generation only when a fresh re-layout is actually
        # wanted: an explicit Render click, or a node-spacing change (which
        # alters the physics and should spread the graph out rather than freeze
        # the old spread). Every other rebuild reuses cached positions so the
        # graph stays put (issue #141).
        if render_graph:
            st.session_state.viz_render_seq += 1
            # Render also re-centres on the current Find selection, so a user who
            # panned away can recentre on it without clearing and re-picking
            # (PR #144 review P3 — reuses the existing button, no new control).
            if _find_id:
                st.session_state["_viz_find_seq"] = (
                    st.session_state.get("_viz_find_seq", 0) + 1
                )
        if (
            "_viz_last_node_spacing" in st.session_state
            and st.session_state["_viz_last_node_spacing"] != node_spacing
        ):
            st.session_state.viz_render_seq += 1
        st.session_state["_viz_last_node_spacing"] = node_spacing

        # Rebuild graph data when settings change or on first visit
        needs_rebuild = (
            st.session_state.last_graph_key != graph_key
            or st.session_state.last_graph_data is None
        )

        # Reserve the status slot on every render, not only when rebuilding: this
        # placeholder sits above the graph component, so an element that comes and
        # goes shifts the component's position in Streamlit's element tree and
        # makes Streamlit re-create its iframe — which drops graph fullscreen and
        # reloads the viewer (issue #189).
        status = st.empty()

        if needs_rebuild:
            # Build the graph using lightweight dicts (no pyvis overhead)
            status.info("Building graph...")

            class _GraphBuilder:
                """Minimal replacement for pyvis.Network — just collects nodes/edges."""

                __slots__ = ("_node_ids", "edges", "nodes", "options")

                def __init__(self):
                    self.nodes = []
                    self.edges = []
                    self._node_ids = set()
                    self.options = {}

                def add_node(self, node_id, **kwargs):
                    if node_id in self._node_ids:
                        return
                    self._node_ids.add(node_id)
                    kwargs["id"] = node_id
                    self.nodes.append(kwargs)

                def add_edge(self, source, target, **kwargs):
                    kwargs["from"] = source
                    kwargs["to"] = target
                    self.edges.append(kwargs)

            net = _GraphBuilder()
            net.options = {
                # Pin the layout's initial-placement RNG so a given graph always
                # stabilizes to the same arrangement instead of a fresh random
                # one each time it is rebuilt (issue #141). Combined with the
                # cached positions, this keeps the picture consistent across
                # renders, Render clicks, and fresh sessions.
                "layout": {"randomSeed": 191021},
                "physics": {
                    "enabled": True,
                    "barnesHut": {
                        "gravitationalConstant": -5000,
                        "centralGravity": 0.3,
                        "springLength": node_spacing,
                        "springConstant": 0.04,
                        "avoidOverlap": 0.3,
                    },
                    "stabilization": {"enabled": True, "iterations": 80},
                },
                "nodes": {"font": {"color": "#f0f0f0", "size": 12}},
                "edges": {
                    "font": {
                        "color": "#cccccc",
                        "size": 10,
                        "strokeWidth": 2,
                        "strokeColor": "#ffffff",
                    },
                    "smooth": {"enabled": True, "type": "curvedCW", "roundness": 0.2},
                },
            }

            # Focus mode assembles the whole graph and prunes it to the seeds'
            # neighbourhood afterwards, so the browser only ever sees the prune —
            # only that has to respect the render cap. Assembling under it
            # instead cut the very nodes a focus needs: a class past the cap
            # could not be focused on at all, and the graph came out empty with
            # nothing said about why (issue #216).
            #
            # One flag drives both the allowance and the prune, so the two can't
            # drift apart — see :func:`graph_node_cap` for why that matters.
            focus_pruning = bool(focus_mode and focus_seed_ids)
            max_nodes = graph_node_cap(focus_pruning)
            node_count = 0

            def _find_kind_is(prefix: str, _fid=_find_id) -> bool:
                """Is the Find target one of *this* kind of node? (issue #234)

                Ordering the target first only helps if its loop runs at all, and
                the kinds after classes are skipped outright once the budget is
                spent. Node ids carry their kind as a prefix, so the guard can
                let a block through for the one entity the user asked for.
                """
                return bool(_fid) and _fid.startswith(prefix)

            # Why the graph is smaller than the ontology, shown above it. Empty
            # when nothing was left out.
            graph_notice = ""

            # Build sets for node existence checks (URI-keyed for cross-namespace safety)
            cls_collisions = _build_name_collision_set(classes)
            # What to draw comes from `selected_classes` (display labels, and in
            # focus mode deliberately every class) rather than the stored URI
            # selection; resolve it to URIs so hiding one of two same-named
            # classes hides only that one (issue #179).
            _selected_displays = set(selected_classes) if selected_classes else set()
            visible_class_uris = {
                e["uri"] for e in class_entries if e["display"] in _selected_displays
            }
            # Which nodes actually made it into the graph. Every edge endpoint
            # has to be one of these: the builder does not validate endpoints, so
            # an edge naming a node that was never emitted is silently dropped by
            # vis-network and the relation just never draws (issue #200). Nodes
            # go missing both because a filter excluded them and because the
            # max_nodes cap cut the loop short.
            displayed_class_uris: set = set()
            displayed_ind_ids: set = set()
            skos_node_ids: set = set()

            # Add classes as nodes (only selected classes)
            if show_classes and (selected_classes or _find_is_class):
                for cls in prioritise_find_target(
                    classes, lambda c: _uid(c["uri"]), _find_id
                ):
                    if node_count >= max_nodes:
                        break
                    # The entity picked in Find is drawn even when the node
                    # filter hides it: you asked to see it, and a graph that
                    # silently omits it looks broken rather than filtered.
                    #
                    # Checked here, against the live filter, rather than by
                    # un-hiding it in the filter when the pick happens. That
                    # un-hiding ran once per pick, so an entity that was visible
                    # when picked and hidden by a *later* filter change was never
                    # revealed again: the pick had not changed, so nothing
                    # re-ran, and the app went on telling the viewer to centre on
                    # a node it had not sent (issue #234).
                    if (
                        cls["uri"] not in visible_class_uris
                        and _uid(cls["uri"]) != _find_id
                    ):
                        continue
                    cls_node_id = _uid(cls["uri"])
                    disp_cls_name = _disambiguated_name(cls, cls_collisions)
                    label = cls["label"] if cls["label"] else disp_cls_name
                    title = f"Class: {disp_cls_name}"
                    if cls["label"]:
                        title += f"\nLabel: {cls['label']}"
                    if cls["comment"]:
                        title += f"\nComment: {cls['comment'][:100]}"

                    has_issue = cls["name"] in validation_subjects
                    node_color = (
                        {
                            "background": "#4CAF50",
                            "border": "#F44336",
                            "highlight": {"border": "#F44336"},
                        }
                        if has_issue
                        else {"background": "#4CAF50", "border": "#388E3C"}
                    )
                    border_width = 3 if has_issue else 1
                    if has_issue:
                        title += "\n⚠ Has validation issues"
                    net.add_node(
                        cls_node_id,
                        label=label,
                        title=title,
                        color=node_color,
                        borderWidth=border_width,
                        shape="box",
                        size=25,
                        ntype="Class",
                        ename=cls_node_id,
                    )
                    displayed_class_uris.add(cls["uri"])
                    node_count += 1

                # Add class hierarchy edges (URI-based so cross-namespace collisions don't merge)
                for cls in classes:
                    if cls["uri"] not in displayed_class_uris:
                        continue
                    cls_node_id = _uid(cls["uri"])
                    for parent_uri in cls.get("parent_uris", []):
                        if parent_uri in displayed_class_uris:
                            parent_node_id = _uid(parent_uri)
                            net.add_edge(
                                cls_node_id,
                                parent_node_id,
                                label="subClassOf",
                                title=f"Subclass relation:\n{cls['name']} is a subclass of {parent_uri.rsplit('#', 1)[-1].rsplit('/', 1)[-1]}",
                                color="#81C784",
                                arrows="to",
                                ntype="Class Relation",
                                ename=_edge_id(cls["uri"], "subClassOf", parent_uri),
                            )

            # Add object properties as labeled edges between domain and range
            if show_properties and object_props and show_classes:
                for prop in object_props:
                    # Only show if both domain and range exist as class nodes (URI-keyed)
                    dom_uri = prop.get("domain_uri", "")
                    rng_uri = prop.get("range_uri", "")
                    if (
                        dom_uri
                        and rng_uri
                        and dom_uri in displayed_class_uris
                        and rng_uri in displayed_class_uris
                    ):
                        prop_node_id = _uid(prop["uri"])
                        label = prop["label"] if prop["label"] else prop["name"]
                        title = f"Object Property: {prop['name']}"
                        if prop["label"]:
                            title += f"\nLabel: {prop['label']}"
                        net.add_edge(
                            _uid(dom_uri),
                            _uid(rng_uri),
                            label=label,
                            title=title,
                            color="#2196F3",
                            arrows="to",
                            ntype="Object Property",
                            ename=prop_node_id,
                        )

            # Add reused-property links (link_classes) as edges. These live as
            # someValuesFrom/allValuesFrom restrictions on the source class, so
            # they are not covered by the global domain/range edges above. Drawn
            # dashed to distinguish a per-class link from a global axiom.
            if show_properties and show_classes:
                for rest in ont.get_restrictions():
                    if rest["type"] not in ("someValuesFrom", "allValuesFrom"):
                        continue
                    value_uri = rest.get("value_uri")
                    if not value_uri or value_uri not in displayed_class_uris:
                        continue
                    for src_uri in rest.get("applied_to_uris", []):
                        if src_uri not in displayed_class_uris:
                            continue
                        # Typed as the restriction it stands for, not as the
                        # property it uses: clicking it used to open the property
                        # definition rather than the axiom on screen (issue #152).
                        net.add_edge(
                            _uid(src_uri),
                            _uid(value_uri),
                            label=rest["property"],
                            title=(
                                f"Restriction: {rest['type']}"
                                f"\nProperty: {rest['property']}"
                                f"\nValue: {rest['value']}"
                            ),
                            color="#2196F3",
                            arrows="to",
                            dashes=True,
                            ntype="Restriction",
                            ename=_edge_id(
                                src_uri,
                                rest.get("property_uri") or rest["property"],
                                rest["type"],
                                value_uri,
                            ),
                        )

            # Add data properties (connected to displayed classes, or standalone if no domain)
            if (
                show_data_props
                and data_props
                and (node_count < max_nodes or _find_kind_is("dprop_"))
            ):
                for prop in prioritise_find_target(
                    data_props, lambda p: f"dprop_{_uid(p['uri'])}", _find_id
                ):
                    if node_count >= max_nodes and (
                        f"dprop_{_uid(prop['uri'])}" != _find_id
                    ):
                        break
                    # Skip if domain is set but the class node isn't displayed.
                    # Not for the Find target though: its domain is exactly the
                    # kind of class the cap drops, so this guard would put back
                    # the silent no-result the prioritising exists to prevent.
                    # It is drawn standalone, without the domain edge it cannot
                    # have (issue #234 review).
                    prop_node_id = f"dprop_{_uid(prop['uri'])}"
                    dom_uri = prop.get("domain_uri", "")
                    if (
                        dom_uri
                        and show_classes
                        and dom_uri not in displayed_class_uris
                        and prop_node_id != _find_id
                    ):
                        continue

                    label = prop["label"] if prop["label"] else prop["name"]
                    title = f"Data Property: {prop['name']}"
                    if prop["domain"]:
                        title += f"\nDomain: {prop['domain']}"
                    if prop["range"]:
                        title += f"\nRange: {prop['range']}"
                    if prop["functional"]:
                        title += "\nFunctional: Yes"

                    net.add_node(
                        prop_node_id,
                        label=label,
                        title=title,
                        color={"background": "#9C27B0", "border": "#7B1FA2"},
                        shape="box",
                        size=12,
                        font={"color": "#f0f0f0"},
                        ntype="Data Property",
                        ename=_uid(prop["uri"]),
                    )
                    node_count += 1

                    # Connect to domain class
                    if dom_uri and dom_uri in displayed_class_uris:
                        net.add_edge(
                            _uid(dom_uri),
                            prop_node_id,
                            title=f"Domain:\n{prop['name']} has domain {prop['domain']}",
                            color="#CE93D8",
                            arrows="to",
                            dashes=True,
                        )

            # Add individuals
            if (
                show_individuals
                and individuals
                and (node_count < max_nodes or _find_kind_is("ind_"))
            ):
                ind_collisions = _build_name_collision_set(individuals)
                for ind in prioritise_find_target(
                    individuals, lambda i: f"ind_{_uid(i['uri'])}", _find_id
                ):
                    if (
                        node_count >= max_nodes
                        and f"ind_{_uid(ind['uri'])}" != _find_id
                    ):
                        break
                    # Individuals filter (issue #196). Focus mode builds the full
                    # graph and prunes afterwards, so it ignores the filter the
                    # same way the class one does.
                    if (
                        not focus_mode
                        and ind["uri"] not in selected_ind_uris
                        and f"ind_{_uid(ind['uri'])}" != _find_id
                    ):
                        continue
                    ind_node_id = f"ind_{_uid(ind['uri'])}"
                    disp_ind_name = _disambiguated_name(ind, ind_collisions)
                    label = ind["label"] if ind["label"] else disp_ind_name
                    title = f"Individual: {disp_ind_name}"
                    if ind["classes"]:
                        title += f"\nType: {', '.join(ind['classes'])}"

                    has_issue = ind["name"] in validation_subjects
                    ind_color = (
                        {
                            "background": "#FF9800",
                            "border": "#F44336",
                            "highlight": {"border": "#F44336"},
                        }
                        if has_issue
                        else {"background": "#FF9800", "border": "#F57C00"}
                    )
                    border_width = 3 if has_issue else 1
                    if has_issue:
                        title += "\n⚠ Has validation issues"
                    net.add_node(
                        ind_node_id,
                        label=label,
                        title=title,
                        color=ind_color,
                        borderWidth=border_width,
                        shape="box",
                        size=20,
                        ntype="Individual",
                        ename=_uid(ind["uri"]),
                    )
                    displayed_ind_ids.add(ind_node_id)
                    node_count += 1

                    # Connect to classes via URI so the edge points to the
                    # exact class node, even when the same local name appears
                    # in multiple namespaces.
                    if show_classes:
                        class_uris = ind.get("class_uris") or []
                        cls_names = ind.get("classes") or []
                        for idx, cls_uri in enumerate(class_uris):
                            if cls_uri in displayed_class_uris:
                                cls_name = (
                                    cls_names[idx] if idx < len(cls_names) else cls_uri
                                )
                                net.add_edge(
                                    ind_node_id,
                                    _uid(cls_uri),
                                    label="type",
                                    title=f"Instance of:\n{ind['name']} is an instance of {cls_name}",
                                    color="#FFB74D",
                                    arrows="to",
                                )

                # Add edges between individuals (object property assertions).
                # Keyed on the assertion's target URI, not its local name: two
                # individuals in different namespaces can share a name, and a
                # name lookup would draw the edge to whichever of them happened
                # to be seen last (PR #202 review).
                if show_ind_edges:
                    for ind in individuals:
                        src_node = f"ind_{_uid(ind['uri'])}"
                        if src_node not in displayed_ind_ids:
                            continue
                        for prop in ind.get("properties", []):
                            target_uri = prop.get("value_uri")
                            tgt_node = f"ind_{_uid(target_uri)}" if target_uri else ""
                            if tgt_node in displayed_ind_ids:
                                net.add_edge(
                                    src_node,
                                    tgt_node,
                                    label=prop["property"],
                                    title=f"{prop['property']}:\n{ind['name']} → {prop['value']}",
                                    color="#FF9800",
                                    arrows="to",
                                )

            # Add class relations (only if both nodes exist) — URI-keyed
            class_relations = ont.get_class_relations()
            if show_classes and classes:
                for rel in class_relations:
                    subj_uri = rel.get("subject_uri", "")
                    obj_uri = rel.get("object_uri", "")
                    if (
                        subj_uri in displayed_class_uris
                        and obj_uri in displayed_class_uris
                    ):
                        subj_node = _uid(subj_uri)
                        obj_node = _uid(obj_uri)
                        # Tagged so a click resolves back to this exact triple and
                        # opens its editor (issue #152).
                        rel_ename = _edge_id(subj_uri, rel["relation"], obj_uri)
                        if rel["relation"] == "equivalentClass":
                            net.add_edge(
                                subj_node,
                                obj_node,
                                label="equivalentClass",
                                title=f"Equivalent classes:\n{rel['subject']} and {rel['object']} represent the same concept",
                                color="#9C27B0",
                                arrows="to",
                                ntype="Class Relation",
                                ename=rel_ename,
                            )
                        elif rel["relation"] == "disjointWith":
                            net.add_edge(
                                subj_node,
                                obj_node,
                                label="disjointWith",
                                title=f"Disjoint classes:\n{rel['subject']} and {rel['object']} cannot share instances",
                                color="#F44336",
                                arrows="to",
                                ntype="Class Relation",
                                ename=rel_ename,
                            )

            # Add annotations for classes and individuals
            if show_annotations and node_count < max_nodes:
                # Annotations for classes
                if show_classes and classes:
                    for cls in classes:
                        if node_count >= max_nodes:
                            break
                        # Annotating a class the filter hid (or the node cap cut)
                        # would hang the annotation off a node that isn't there.
                        if cls["uri"] not in displayed_class_uris:
                            continue
                        try:
                            # By URI, not local name: two classes sharing a name
                            # would otherwise each show the other's annotations.
                            annotations = ont.get_annotations(cls["uri"])
                            for ann in annotations:
                                if node_count >= max_nodes:
                                    break
                                # Skip label and comment as they're already shown in tooltip
                                if ann["predicate"] in ["label", "comment"]:
                                    continue
                                ann_ename = annotation_ename(cls["uri"], ann)
                                ann_id = f"ann_{_uid(ann_ename)}"
                                # Use prefixed predicate name
                                pred_display = ann.get(
                                    "predicate_prefixed", ann["predicate"]
                                )
                                # Truncate long values
                                value_display = (
                                    ann["value"][:30] + "..."
                                    if len(ann["value"]) > 30
                                    else ann["value"]
                                )
                                net.add_node(
                                    ann_id,
                                    label=value_display,
                                    title=f"{pred_display}: {ann['value']}",
                                    color={
                                        "background": "#795548",
                                        "border": "#5D4037",
                                    },
                                    shape="box",
                                    size=8,
                                    font={"size": 10, "color": "#f0f0f0"},
                                    ntype="Annotation",
                                    ename=ann_ename,
                                )
                                node_count += 1
                                net.add_edge(
                                    _uid(cls["uri"]),
                                    ann_id,
                                    title=f"Annotation: {pred_display}",
                                    color="#A1887F",
                                    arrows="to",
                                    dashes=True,
                                )
                        except Exception:
                            logger.debug(
                                "Skipping a class annotation node", exc_info=True
                            )

                # Annotations for individuals
                if show_individuals and individuals:
                    for ind in individuals:
                        if node_count >= max_nodes:
                            break
                        ind_node_id = f"ind_{_uid(ind['uri'])}"
                        if ind_node_id not in displayed_ind_ids:
                            continue
                        try:
                            annotations = ont.get_annotations(ind["uri"])
                            for ann in annotations:
                                if node_count >= max_nodes:
                                    break
                                if ann["predicate"] in ["label", "comment"]:
                                    continue
                                ann_ename = annotation_ename(ind["uri"], ann)
                                ann_id = f"ann_{_uid(ann_ename)}"
                                pred_display = ann.get(
                                    "predicate_prefixed", ann["predicate"]
                                )
                                value_display = (
                                    ann["value"][:30] + "..."
                                    if len(ann["value"]) > 30
                                    else ann["value"]
                                )
                                net.add_node(
                                    ann_id,
                                    label=value_display,
                                    title=f"{pred_display}: {ann['value']}",
                                    color={
                                        "background": "#795548",
                                        "border": "#5D4037",
                                    },
                                    shape="box",
                                    size=8,
                                    font={"size": 10, "color": "#f0f0f0"},
                                    ntype="Annotation",
                                    ename=ann_ename,
                                )
                                node_count += 1
                                net.add_edge(
                                    ind_node_id,
                                    ann_id,
                                    title=f"Annotation: {pred_display}",
                                    color="#A1887F",
                                    arrows="to",
                                    dashes=True,
                                )
                        except Exception:
                            logger.debug(
                                "Skipping an individual annotation node", exc_info=True
                            )

            # Add SKOS concepts and relations
            if show_skos and (node_count < max_nodes or _find_kind_is("skos_")):
                concepts = ont.get_concepts()
                for concept in prioritise_find_target(
                    concepts, lambda c: f"skos_{c['name']}", _find_id
                ):
                    if (
                        node_count >= max_nodes
                        and f"skos_{concept['name']}" != _find_id
                    ):
                        break
                    c_id = f"skos_{concept['name']}"
                    label = concept.get("pref_label") or concept["name"]
                    title = f"SKOS Concept: {concept['name']}"
                    if concept.get("pref_label"):
                        title += f"\nprefLabel: {concept['pref_label']}"
                    if concept.get("definition"):
                        title += f"\nDefinition: {concept['definition'][:100]}"
                    if concept.get("scheme"):
                        title += f"\nScheme: {concept['scheme']}"
                    net.add_node(
                        c_id,
                        label=label,
                        title=title,
                        color={"background": "#00897B", "border": "#00695C"},
                        shape="box",
                        size=20,
                        ntype="SKOS Concept",
                        ename=concept.get("uri", concept["name"]),
                    )
                    skos_node_ids.add(c_id)
                    node_count += 1

                # Add broader/narrower/related edges
                for concept in concepts:
                    c_id = f"skos_{concept['name']}"
                    if c_id not in skos_node_ids:
                        continue
                    for broader in concept.get("broader", []):
                        b_id = f"skos_{broader}"
                        if b_id in skos_node_ids:
                            net.add_edge(
                                c_id,
                                b_id,
                                label="broader",
                                title=f"Broader: {concept['name']} → {broader}",
                                color="#26A69A",
                                arrows="to",
                            )
                    for related in concept.get("related", []):
                        r_id = f"skos_{related}"
                        if r_id in skos_node_ids:
                            net.add_edge(
                                c_id,
                                r_id,
                                label="related",
                                title=f"Related: {concept['name']} ↔ {related}",
                                color="#80CBC4",
                                arrows="",
                                dashes=True,
                            )

            # Add raw RDF triples for visible nodes
            if show_triples and node_count < max_nodes:
                from rdflib import Literal as _Literal
                from rdflib import URIRef as _URIRef

                # Build URI → node_id mapping over the nodes actually emitted,
                # so a triple edge always has a real subject to hang off.
                _uri_to_node = {}
                if show_classes:
                    for cls in classes:
                        if cls["uri"] in displayed_class_uris:
                            _uri_to_node[cls["uri"]] = _uid(cls["uri"])
                if show_individuals and individuals:
                    for ind in individuals:
                        _ind_node = f"ind_{_uid(ind['uri'])}"
                        if _ind_node in displayed_ind_ids:
                            _uri_to_node[ind["uri"]] = _ind_node
                if show_skos:
                    for concept in ont.get_concepts():
                        _skos_node = f"skos_{concept['name']}"
                        if concept.get("uri") and _skos_node in skos_node_ids:
                            _uri_to_node[concept["uri"]] = _skos_node

                # Query only triples with visible subjects (avoid full graph scan)
                _triple_new = 0
                _max_triple_new = 200
                _local = ont._local_name
                _triple_node_color = {"background": "#90A4AE", "border": "#607D8B"}
                _literal_node_color = {"background": "#B0BEC5", "border": "#78909C"}
                for s_uri_str, s_node in list(_uri_to_node.items()):
                    s_uri = _URIRef(s_uri_str)
                    s_local = _local(s_uri)
                    for p, o in ont.graph.predicate_objects(s_uri):
                        p_label = _local(p)

                        if isinstance(o, _URIRef):
                            o_str = str(o)
                            if o_str in _uri_to_node:
                                o_node = _uri_to_node[o_str]
                            else:
                                if _triple_new >= _max_triple_new:
                                    continue
                                o_node = f"triple_{abs(hash(o_str)) % 10**8}"
                                net.add_node(
                                    o_node,
                                    label=_local(o),
                                    title=f"URI: {o_str}",
                                    color=_triple_node_color,
                                    shape="box",
                                    size=10,
                                    font={"size": 10, "color": "#f0f0f0"},
                                )
                                _uri_to_node[o_str] = o_node
                                _triple_new += 1
                                node_count += 1

                            net.add_edge(
                                s_node,
                                o_node,
                                label=p_label,
                                title=f"{s_local} → {p_label} → {_local(o)}",
                                color="#90A4AE",
                                arrows="to",
                            )

                        elif isinstance(o, _Literal):
                            if _triple_new >= _max_triple_new:
                                continue
                            o_str = str(o)
                            o_display = o_str[:30] + "..." if len(o_str) > 30 else o_str
                            o_node = (
                                f"lit_{abs(hash(s_uri_str + str(p) + o_str)) % 10**8}"
                            )
                            dt = (
                                str(o.datatype).split("#")[-1]
                                if o.datatype
                                else "string"
                            )
                            net.add_node(
                                o_node,
                                label=o_display,
                                title=f"Literal: {o_str}\nDatatype: {dt}",
                                color=_literal_node_color,
                                shape="box",
                                size=8,
                                font={"size": 9, "color": "#333333"},
                            )
                            _triple_new += 1
                            node_count += 1

                            net.add_edge(
                                s_node,
                                o_node,
                                label=p_label,
                                title=f"{s_local} → {p_label} → {o_display}",
                                color="#B0BEC5",
                                arrows="to",
                            )

            # Classes that passed the filter but never got a node: the cap cut
            # the loop short. This used to be silent, so a class simply went
            # missing — along with every edge that needed it, which reads as
            # unrelated classes losing their connections (issue #216). The focus
            # block below replaces this with something more specific when it has
            # it, since a focus that finds nothing is the sharper symptom.
            _cut_classes = len(visible_class_uris) - len(displayed_class_uris)
            if show_classes and _cut_classes > 0:
                graph_notice = (
                    f"{_cut_classes} of {len(visible_class_uris)} classes are not "
                    f"drawn: the graph stops at {max_nodes} nodes. Hide some in "
                    f"Filter Nodes, or focus on one node, to see the rest."
                )

            # Focus mode: keep only the seed nodes' neighbourhood within
            # focus_depth hops over the assembled edges (BFS over all node
            # types, so depth counts real graph links rather than class hops).
            # Several seeds grow the neighbourhood from all of them at once.
            focus_hidden = 0
            if focus_pruning:
                _before_prune = len(net.nodes)
                present_ids = {n["id"] for n in net.nodes}
                seeds = {sid for sid in focus_seed_ids if sid in present_ids}
                if seeds:
                    adj: dict = {}
                    for edge in net.edges:
                        adj.setdefault(edge["from"], set()).add(edge["to"])
                        adj.setdefault(edge["to"], set()).add(edge["from"])
                    # Ring by ring, starting with the seeds themselves, and never
                    # past what can be drawn — the assembly was allowed over that
                    # only because this holds the line. The seeds alone can
                    # already overflow it: they default to every selected class.
                    # Truncating mid-ring keeps the nearer hops, which are the
                    # ones that were asked for.
                    keep: set = set()
                    ring = set(seeds)
                    for _ in range(focus_depth + 1):
                        if not ring:
                            break
                        room = GRAPH_MAX_NODES - len(keep)
                        if len(ring) > room:
                            keep |= set(sorted(ring)[:room])
                            graph_notice = (
                                f"This focus covers more than the "
                                f"{GRAPH_MAX_NODES} nodes the graph can draw, so "
                                f"only part of it is shown. Pick fewer focus "
                                f"nodes, or a lower depth, to see it in full."
                            )
                            break
                        keep |= ring
                        nxt: set = set()
                        for nid in ring:
                            nxt |= adj.get(nid, set())
                        ring = nxt - keep
                    net.nodes = [n for n in net.nodes if n["id"] in keep]
                    net.edges = [
                        e for e in net.edges if e["from"] in keep and e["to"] in keep
                    ]
                    focus_hidden = _before_prune - len(net.nodes)
                else:
                    # No seed was built (past the assembly cap, or its type
                    # toggled off) — show nothing rather than the whole graph,
                    # which would be misleading. Say why, or the empty graph
                    # looks like the focus itself is broken (issue #216).
                    net.nodes = []
                    net.edges = []
                    graph_notice = (
                        f"Nothing to focus on: this ontology is past the "
                        f"{max_nodes} nodes the graph builds at once, and the "
                        f"node you picked is not among them. Hide some classes "
                        f"or individuals in Filter Nodes to bring it into range."
                    )

            # Spread parallel edges so they don't overlap
            from collections import defaultdict as _defaultdict

            _edge_groups = _defaultdict(list)
            for edge in net.edges:
                key = tuple(sorted((edge["from"], edge["to"])))
                _edge_groups[key].append(edge)
            for (_first, _second), group in _edge_groups.items():
                if len(group) < 2:
                    continue
                # Alternate sides, widening every second edge, so each edge of a
                # pair gets a distinct curve. Two things this has to get right:
                #
                # The step. `(i + 1) // 2` was 1 for both i=1 and i=2, so from
                # three parallel edges upwards the third lay exactly on top of
                # the first.
                #
                # The direction. curvedCW is clockwise *along the edge's own*
                # from-to, so two edges pointing opposite ways cancel out: give
                # one CW and the other CCW, as plain alternation does, and they
                # land on the same side of the pair rather than either side of
                # it. Flipping the label for an edge that runs against the
                # group's canonical order makes the side absolute, so
                # `A disjointWith B` and `B nextItem A` bow apart (issue #245).
                for i, edge in enumerate(group):
                    _runs_backwards = edge["from"] != _first
                    _clockwise = (i % 2 == 0) != _runs_backwards
                    edge["smooth"] = {
                        "enabled": True,
                        "type": "curvedCW" if _clockwise else "curvedCCW",
                        "roundness": 0.2 * (i // 2 + 1),
                    }

            # Generate and display the graph using custom component
            try:
                import json as _json

                nodes_json = _json.dumps(net.nodes)
                edges_json = _json.dumps(net.edges)
                options_json = _json.dumps(net.options)

                # Cache graph data for reuse on rerun
                st.session_state.last_graph_key = graph_key
                st.session_state.last_graph_data = {
                    "nodes": nodes_json,
                    "edges": edges_json,
                    "options": options_json,
                    # Cached with the graph so it survives the reruns that reuse
                    # it, rather than flashing once on the build that found it.
                    "notice": graph_notice,
                    # What the focus prune took out, cached with the graph it
                    # produced so the caption below survives the reruns that
                    # reuse it (issue #222 follow-up).
                    "focus_hidden": focus_hidden,
                }
                # NB: don't bump viz_render_seq here. The component re-renders on
                # its own whenever nodes/edges change, and seq is the layout-cache
                # generation: bumping it on every rebuild invalidated the cache so
                # a node-set change (e.g. a focus expand) always re-ran physics
                # from scratch instead of freezing the existing nodes (issue #141,
                # PR review). seq is now bumped only for a real re-layout below.
                status.empty()

            except Exception as e:  # noqa: BLE001 - a graph build failure must not break the page
                status.empty()
                st.error(f"Error building graph: {e!s}")

        # Always display the graph component (even on rerun after selection)
        gdata = st.session_state.get("last_graph_data")
        # Why the graph is smaller than the ontology, in the slot the build
        # status used. Written on every render, not only on a rebuild: the slot
        # is reserved either way (issue #189), and the reason still holds while
        # the cached graph is reused.
        if gdata and gdata.get("notice"):
            status.warning(gdata["notice"], icon="⚠️")
        # Recompute the note for the Filter Nodes label now that the focus
        # controls have rendered and the prune has run. One rerun when it
        # actually changes, so the label is never a step behind what the graph
        # is showing; it converges because the note is derived from settings,
        # not from the rerun.
        _note_now = viz_hidden_caption(
            focus_mode,
            list(focus_seeds) if focus_mode else [],
            focus_depth,
            (gdata or {}).get("focus_hidden", 0),
            (len(filters["class"]["uris"]) - len(filters["class"]["selected_uris"]))
            + (len(filters["ind"]["uris"]) - len(filters["ind"]["selected_uris"])),
        )
        if _note_now != st.session_state.get("_viz_hidden_note", ""):
            st.session_state["_viz_hidden_note"] = _note_now
            st.rerun()
        # Say what is being held back, small, right above the canvas: a focus or
        # a narrowed filter is otherwise invisible, and an entity that isn't
        # drawn looks lost rather than filtered (issue #222 follow-up).
        if gdata:
            import os as _os

            _component_path = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "lib", "graph_viewer"
            )
            # Version the component name by a hash of its source, so any change to
            # index.html serves under a fresh URL and browsers / the desktop
            # webview can't run a stale cached copy (the webview's cache persists
            # across launches via the storage_path added for #70).
            import hashlib as _hashlib

            try:
                with open(
                    _os.path.join(_component_path, "index.html"), encoding="utf-8"
                ) as _gv_fh:
                    _gv_src = _gv_fh.read()
                _gv_ver = _hashlib.md5(_gv_src.encode("utf-8")).hexdigest()[:8]
            except OSError:
                _gv_ver = "0"
            _graph_component = st.components.v1.declare_component(
                f"graph_viewer_{_gv_ver}", path=_component_path
            )

            # Theme the graph (canvas + legend) to match the app, so it isn't a
            # white box in dark mode. Standard Streamlit dark/light colours are
            # used, derived from the active theme type (issue #62).
            _gv_dark = False
            try:
                _gv_dark = st.context.theme.get("type") == "dark"
            except Exception:
                logger.debug(
                    "Graph theme defaulting to light: st.context.theme unavailable",
                    exc_info=True,
                )
            _gv_theme = (
                {"bg": "#0e1117", "panel": "#262730", "text": "#fafafa"}
                if _gv_dark
                else {
                    "bg": "#ffffff",
                    "panel": "rgba(255,255,255,0.92)",
                    "text": "#333333",
                }
            )

            # Track the selection across reruns so a component re-mount (panel
            # toggle, or a re-mount right after a click) can restore the right
            # node. Seed from the component's *current* value first: a click sets
            # it before the rerun, so this reflects the just-clicked node with no
            # one-rerun lag (which previously caused a first-click node to
            # deactivate after a re-mount). Fall back to the last persisted value
            # when the component returned nothing (a fresh re-mount).
            _live_sel = st.session_state.get("graph_viewer")
            if isinstance(_live_sel, dict) and "selected" in _live_sel:
                _kept, _dropped = _viz_live_selection(
                    _live_sel,
                    st.session_state.get("_viz_dropped_selection"),
                    st.session_state.get("_ont_mutation_count", 0),
                )
                st.session_state["_viz_last_selection"] = _kept
                if _dropped is None:
                    st.session_state.pop("_viz_dropped_selection", None)
            _prev_sel = st.session_state.get("_viz_last_selection")
            _prev_has_sel = isinstance(_prev_sel, dict) and _prev_sel.get("selected")

            _panel_on = bool(st.session_state.get("_viz_cfg_details_panel", True))
            if _panel_on:
                _col_graph, _col_panel = st.columns([3, 1])
                _col_toggle = None
            else:
                # Collapsed: a thin reopen toggle on the right edge, IDE-style.
                # It turns primary (coloured) when a node is selected, since the
                # toggle is otherwise easy to miss.
                _col_graph, _col_toggle = st.columns([30, 1])
                _col_panel = None

            if _col_toggle is not None:
                with _col_toggle:
                    if st.button(
                        "‹",
                        key="viz_show_panel",
                        help="Show details panel",
                        type="primary" if _prev_has_sel else "secondary",
                    ):
                        st.session_state["_viz_cfg_details_panel"] = True
                        st.session_state["_viz_settings_dirty"] = True
                        st.rerun()

            with _col_graph:
                selection = _graph_component(
                    nodes=gdata["nodes"],
                    edges=gdata["edges"],
                    options=gdata["options"],
                    height=height,
                    autofit=fit,
                    theme=_gv_theme,
                    selected_node=(_prev_sel.get("nodeId") if _prev_has_sel else None),
                    # Find & centre target + a change-seq, so the component
                    # re-centres only on a fresh pick (issue #144).
                    focus_node=_find_id,
                    focus_seq=st.session_state.get("_viz_find_seq", 0),
                    # On desktop the webview can't download; the component sends
                    # the PNG back for us to save instead (#86).
                    web_download=not local_store.local_persist_enabled(),
                    seq=st.session_state.viz_render_seq,
                    key="graph_viewer",
                    default=None,
                )

            # Desktop "Download PNG": the component hands us the image data URL to
            # save to disk (the webview can't download). Guard by reqId so it's
            # written once.
            if isinstance(selection, dict) and selection.get("pngData"):
                _png_req = selection.get("reqId")
                if _png_req and _png_req != st.session_state.get("_viz_last_png_req"):
                    st.session_state["_viz_last_png_req"] = _png_req
                    try:
                        import base64

                        _b64 = selection["pngData"].split(",", 1)[-1]
                        _png_path = _Path.home() / "Downloads" / "ontology-graph.png"
                        _png_path.parent.mkdir(parents=True, exist_ok=True)
                        _png_path.write_bytes(base64.b64decode(_b64))
                        st.toast(f"Saved graph image to {_png_path}", icon="💾")
                    except (OSError, ValueError) as e:
                        st.toast(f"Could not save image: {e}", icon="⚠️")

            # Ctrl/Cmd-click in the graph requests focusing on a node: add it to
            # the "Focus on one node" seeds and enable focus mode (issue #56). The
            # reqId guard ensures each click is applied once (the component value
            # persists across reruns).
            if isinstance(selection, dict) and selection.get("focusRequest"):
                _req_id = selection.get("reqId")
                if _req_id and _req_id != st.session_state.get("_viz_last_focus_req"):
                    st.session_state["_viz_last_focus_req"] = _req_id
                    _id_to_label = {v: k for k, v in focus_targets.items()}
                    _focus_label = _id_to_label.get(selection.get("nodeId"))
                    if _focus_label:
                        st.session_state["_viz_cfg_focus_mode"] = True
                        _seeds = list(
                            st.session_state.get("_viz_cfg_focus_seeds") or []
                        )
                        if _focus_label not in _seeds:
                            _seeds.append(_focus_label)
                        st.session_state["_viz_cfg_focus_seeds"] = _seeds
                        st.toast(f"Focusing on {_focus_label}", icon="🎯")
                        st.rerun()
                    else:
                        st.toast(
                            "Focus is available for classes, individuals, and "
                            "SKOS concepts.",
                            icon="ℹ️",
                        )

            # Status bar outside iframe — dark styled
            # The selection was already captured (from the component's current
            # value) before the component call above, so just read it here.
            _sel = st.session_state.get("_viz_last_selection")

            # Selection details, shared by the side panel and the status bar.
            has_selection = isinstance(_sel, dict) and _sel.get("selected")
            ntype = _sel.get("ntype") if has_selection else None
            ename = _sel.get("ename") if has_selection else None
            show_view = has_selection and ntype and ename and ntype in _PAGE_BY_TYPE

            def _open_full_editor(_ntype, _ename):
                """Open the entity in its editor. Classes land directly in the
                Edit/Delete tab with the entity preselected (no scrolling);
                relations and restrictions hand their list the edge's identity so
                it opens that row (issue #152); other types fall back to the
                inline-view jump for now (issue #80)."""
                st.session_state["_back_to_viz"] = True
                st.session_state.search_navigate_to = _PAGE_BY_TYPE[_ntype]
                if _ntype == "Class":
                    _target = next(
                        (c for c in classes if _uid(c["uri"]) == _ename), None
                    )
                    if _target:
                        _, _lookup = build_class_options(classes)
                        _disp = {v: k for k, v in _lookup.items()}.get(_target["uri"])
                        if _disp:
                            st.session_state["cls_active_tab"] = "Edit/Delete Class"
                            st.session_state["edit_class_select"] = _disp
                            st.rerun()
                if _ntype == "Class Relation":
                    # The search is cleared so the row is in the list the page
                    # searches for it in — a leftover filter would hide it.
                    st.session_state["_rel_open_edge"] = _edge_id_parts(_ename, 3)
                    st.session_state["rel_search"] = ""
                    st.session_state["rel_active_tab"] = "View Relations"
                    st.rerun()
                if _ntype == "Restriction":
                    st.session_state["_rest_open_edge"] = _edge_id_parts(_ename, 4)
                    st.session_state["rest_search"] = ""
                    st.session_state["rest_active_tab"] = "View Restrictions"
                    st.rerun()
                _nav_open_entity(_ntype, _ename)
                if _ntype == "SKOS Concept":
                    st.session_state["_skos_navigate_to_concept"] = True
                st.rerun()

            if _panel_on:
                with _col_panel:
                    _h1, _h2 = st.columns([3, 1])
                    with _h1:
                        st.markdown("##### Details")
                    with _h2:
                        if st.button("›", key="viz_hide_panel", help="Hide panel"):
                            st.session_state["_viz_cfg_details_panel"] = False
                            st.session_state["_viz_settings_dirty"] = True
                            st.rerun()
                    _sel_ntype = ntype if has_selection else None
                    _sel_ename = ename if has_selection else None
                    _add_kind = _panel_add_kind()
                    if _add_kind == "class":
                        # The add form owns the whole panel while it is open, so
                        # its fields can't be confused with the editor's.
                        _render_panel_add_class_form(
                            ont, classes, _sel_ntype, _sel_ename
                        )
                    elif _add_kind == "crel":
                        # Owns the panel for the same reason, and because while
                        # the pick is armed a graph click means "this is the
                        # object", not "show me this node".
                        _render_panel_add_relation_form(
                            ont, classes, _sel_ntype, _sel_ename
                        )
                    elif _add_kind == "rest":
                        # Object properties only: every restriction this flow can
                        # build points at a class, which a data property cannot.
                        _render_panel_add_restriction_form(
                            ont, classes, object_props, _sel_ntype, _sel_ename
                        )
                    elif _add_kind == "ind":
                        _render_panel_add_individual_form(
                            ont, classes, individuals, _sel_ntype, _sel_ename
                        )
                    elif _add_kind == "ann":
                        _render_panel_add_annotation_form(
                            ont,
                            panel_subject_uri(
                                _sel_ntype,
                                _sel_ename,
                                classes,
                                object_props,
                                data_props,
                                individuals,
                            ),
                            _sel.get("label", "") if has_selection else "",
                        )
                    elif not has_selection:
                        st.caption(
                            "Click a node to see details. Ctrl/Cmd-click focuses on it."
                        )
                        _render_panel_add_buttons(classes, None, None, None)
                    else:
                        st.markdown(f"**{_sel.get('label', '')}**")
                        # What was selected, not merely that it was an edge:
                        # relations, restrictions and object properties are all
                        # drawn as edges and want telling apart (issue #152).
                        st.caption(ntype or ("Edge" if _sel.get("isEdge") else "Node"))
                        _render_panel_entity_editor(
                            ont,
                            ntype,
                            ename,
                            _sel,
                            classes,
                            object_props,
                            data_props,
                            individuals,
                        )
                        if show_view and st.button(
                            "Open full editor"
                            if ntype in _PRECISE_NAV_TYPES
                            else "Open",
                            key="panel_open_editor",
                            use_container_width=True,
                        ):
                            _open_full_editor(ntype, ename)
                        _render_panel_add_buttons(
                            classes,
                            ntype,
                            ename,
                            panel_subject_uri(
                                ntype,
                                ename,
                                classes,
                                object_props,
                                data_props,
                                individuals,
                            ),
                        )
            else:
                # Status bar under the graph (shown when the panel is hidden).
                if has_selection:
                    title_text = (_sel.get("title") or "").replace("\n", " | ")
                    prefix = "Edge: " if _sel.get("isEdge") else ""
                    sel_html = f"<b>{prefix}{_sel.get('label', '')}</b> — {title_text}"
                else:
                    sel_html = (
                        "Click a node or edge to see details · "
                        "Ctrl/Cmd-click a node to focus on it"
                    )

                # Inject CSS to remove gap between status bar columns
                st.markdown(
                    """<style>
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) { gap: 0 !important; }
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) [data-testid="stBaseButton-secondary"] button,
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) button[kind] ,
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) button {
                background: #4CAF50 !important; color: white !important;
                border: none !important; border-radius: 0 4px 4px 0 !important;
                height: 36px !important; min-height: 36px !important; max-height: 36px !important;
                padding: 0 16px !important; line-height: 36px !important;
                margin: 0 !important;
            }
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) [data-testid="stVerticalBlockBorderWrapper"] {
                height: 36px !important; overflow: hidden;
            }
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar) button:hover {
                background: #388E3C !important;
            }
            </style>""",
                    unsafe_allow_html=True,
                )

                if show_view:
                    col_info, col_btn = st.columns([7, 2])
                    with col_info:
                        st.markdown(
                            f'<div id="graph-status-bar" style="background:#1e1e1e;color:#fff;padding:6px 12px;'
                            f"border-radius:4px 0 0 4px;font-size:14px;display:flex;align-items:center;gap:8px;"
                            f'height:36px;">'
                            f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sel_html}</span>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    with col_btn:
                        _btn_label = (
                            "Open full editor"
                            if ntype in _PRECISE_NAV_TYPES
                            else "View"
                        )
                        if st.button(
                            _btn_label, key="graph_view_btn", use_container_width=True
                        ):
                            _open_full_editor(ntype, ename)
                else:
                    st.markdown(
                        f'<div id="graph-status-bar" style="background:#1e1e1e;color:#fff;padding:6px 12px;'
                        f"border-radius:4px;font-size:14px;display:flex;align-items:center;gap:8px;"
                        f'height:36px;">'
                        f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sel_html}</span>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    if _viz_tab == "Class Hierarchy":
        st.subheader("Class Hierarchy (Text)")

        if not classes:
            st.info("No classes defined.")
        else:
            tree_text = build_class_hierarchy_text(classes)
            st.code(tree_text, language=None)

    if _viz_tab == "Statistics":
        st.subheader("Ontology Statistics")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Element Distribution:**")
            chart_data = {
                "Element": ["Classes", "Object Props", "Data Props", "Individuals"],
                "Count": [
                    stats["classes"],
                    stats["object_properties"],
                    stats["data_properties"],
                    stats["individuals"],
                ],
            }
            st.bar_chart(chart_data, x="Element", y="Count")

        with col2:
            st.write("**Quick Stats:**")
            st.write(f"- Total Classes: {stats['classes']}")
            st.write(f"- Total Object Properties: {stats['object_properties']}")
            st.write(f"- Total Data Properties: {stats['data_properties']}")
            st.write(f"- Total Individuals: {stats['individuals']}")
            st.write(f"- Total Restrictions: {stats['restrictions']}")
            st.write(f"- Content Triples: {stats['content_triples']}")


def render_source():
    """Render the source view page."""
    st.header("Source (Turtle)")
    ont = st.session_state.ontology
    try:
        turtle_src = ont.export_to_string(format="turtle")
        st.code(turtle_src, language="turtle", line_numbers=True)
    except Exception as e:  # noqa: BLE001 - serialization failure must show as a message
        st.error(f"Error serializing ontology: {e}")


def main():
    """Main application entry point."""
    _configure_page()
    init_session_state()
    maybe_restore_autosave()

    # Sidebar navigation — asset path resolved relative to this module so it
    # works under both `streamlit run` and `pip install` deployments.
    # Use the white logo in dark mode so it stays legible (the colour logo is
    # dark on transparent). st.context.theme reflects the active theme on recent
    # Streamlit; older versions fall back to the colour logo.
    _theme_type = None
    try:
        _theme_type = st.context.theme.type
    except Exception:
        logger.debug(
            "Sidebar logo defaulting to colour: st.context.theme unavailable",
            exc_info=True,
        )
    # st.context.theme is stale on the first render of a session — it reports the
    # default ("light") until the browser tells the server the active theme, so
    # only trust it from the second render on (issues #70, #78).
    _theme_settled = st.session_state.get("_theme_settled", False)
    st.session_state["_theme_settled"] = True
    if local_store.local_persist_enabled():
        # Detect the OS appearance once per session (cached) — calling darkdetect
        # every render shells out to the OS and made the UI lag.
        if "_system_base" not in st.session_state:
            st.session_state["_system_base"] = local_store.detect_system_base()
        _system_base = st.session_state["_system_base"]
        _pinned = local_store.get_theme_base()
        # Persist a pin only when the user actually changes the theme: while
        # following the OS (no pin), store only a deviation from the OS theme; a
        # match is left unstored so it keeps following the system. Once pinned,
        # keep it in sync with the toolbar Settings menu. To return to "follow
        # system", clear the saved setting. Skip the stale first render.
        if _theme_settled and _theme_type in ("light", "dark"):
            if _pinned is None:
                if _system_base in ("light", "dark") and _theme_type != _system_base:
                    local_store.set_theme_base(_theme_type)
                    _pinned = _theme_type
            elif _theme_type != _pinned:
                local_store.set_theme_base(_theme_type)
                _pinned = _theme_type
        # Logo: use the live theme once the client reports it; on the first
        # render fall back to what the launcher opened the app with (pin, else
        # detected OS), so the dark logo doesn't flash the light/blue variant.
        if _theme_settled and _theme_type in ("light", "dark"):
            _dark_mode = _theme_type == "dark"
        else:
            _dark_mode = (_pinned or _system_base) == "dark"
    else:
        _dark_mode = _theme_type == "dark"
    _logo_file = "ORIONBELT Logo w.png" if _dark_mode else "ORIONBELT_Logo.png"
    _logo_path = _Path(__file__).parent / "assets" / _logo_file
    st.sidebar.image(str(_logo_path), width=200)
    st.sidebar.markdown("# Ontology Builder")
    st.sidebar.markdown(
        "\u00a9 2025\u20132026 [RALFORION d.o.o.](https://ralforion.com)"
    )
    _gh_repo = GITHUB_ISSUES_URL.rsplit("/", 1)[0]
    st.sidebar.markdown(
        f"<small>v{APP_VERSION} · "
        f'<a href="{_gh_repo}" title="GitHub"><svg height="13" width="13" viewBox="0 0 16 16" style="vertical-align:middle;fill:currentColor;"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a> · '
        f'<a href="{GITHUB_ISSUES_URL}/new">Report Issue</a></small>',
        unsafe_allow_html=True,
    )

    pages = {
        "Dashboard": render_dashboard,
        "Classes": render_classes,
        "Properties": render_properties,
        "Individuals": render_individuals,
        "Relations": render_relations,
        "Restrictions": render_restrictions,
        "Advanced": render_advanced,
        "Annotations": render_annotations,
        "SKOS Vocabulary": render_skos_vocabulary,
        "Import / Export": render_import_export,
        "Source": render_source,
        "Validation": render_validation,
        "Visualization": render_visualization,
    }

    # Handle graph view navigation (from visualization click)
    _qp = st.query_params
    if "graph_view_type" in _qp and "graph_view_name" in _qp:
        _gv_type = _qp["graph_view_type"]
        _gv_name = _qp["graph_view_name"]
        _nav_page = _PAGE_BY_TYPE.get(_gv_type)
        if _nav_page:
            st.session_state.search_navigate_to = _nav_page
            _nav_open_entity(_gv_type, _gv_name)
            if _gv_type == "SKOS Concept":
                st.session_state["_skos_navigate_to_concept"] = True
        st.query_params.clear()
        st.rerun()

    # Handle search navigation
    nav_override = None
    if "search_navigate_to" in st.session_state:
        nav_override = st.session_state.search_navigate_to
        del st.session_state.search_navigate_to
    if nav_override and nav_override in pages:
        st.session_state["nav_radio"] = nav_override
    # Land a fresh empty session on Import/Export via the radio's `index` so the
    # highlight and value agree (a pre-set session_state value diverged them and
    # swallowed the first nav click). Once the user navigates, nav_radio exists
    # in session_state and drives the selection, so index is ignored.
    _page_names = list(pages.keys())
    _default_idx = 0
    if "nav_radio" not in st.session_state and _ontology_is_empty(
        st.session_state.ontology
    ):
        _default_idx = _page_names.index("Import / Export")
    selection = st.sidebar.radio(
        "Navigation", _page_names, index=_default_idx, key="nav_radio"
    )

    # An add form in the graph panel belongs to the Visualization page. Leaving
    # abandons it, so a half-armed "now click the object" state can't be waiting
    # when you come back and read a later, unrelated click as the second end
    # (issue #221).
    if selection != "Visualization":
        _panel_close_add()

    # Undo / Redo controls
    um = st.session_state.undo_manager
    if um:
        undo_col, redo_col = st.sidebar.columns(2)
        with undo_col:
            if st.button(
                "Undo",
                disabled=not um.can_undo(),
                use_container_width=True,
                key="btn_undo",
            ):
                label = um.undo()
                st.session_state["_ont_mutation_count"] = (
                    st.session_state.get("_ont_mutation_count", 0) + 1
                )
                set_flash_message(f"Undid: {label}", "info")
                st.rerun()
        with redo_col:
            if st.button(
                "Redo",
                disabled=not um.can_redo(),
                use_container_width=True,
                key="btn_redo",
            ):
                label = um.redo()
                st.session_state["_ont_mutation_count"] = (
                    st.session_state.get("_ont_mutation_count", 0) + 1
                )
                set_flash_message(f"Redid: {label}", "info")
                st.rerun()

    render_autosave_sidebar()

    st.sidebar.divider()

    # Global search
    type_to_page = {
        "Class": "Classes",
        "Object Property": "Properties",
        "Data Property": "Properties",
        "Individual": "Individuals",
        "SKOS Concept": "SKOS Vocabulary",
    }
    search_query = st.sidebar.text_input(
        "Search", placeholder="Search resources...", key="global_search"
    )
    if search_query:
        results = st.session_state.ontology.search(search_query)
        if results:
            # Group by type
            grouped: dict[str, list] = {}
            for r in results[:20]:
                grouped.setdefault(r["type"], []).append(r)
            for type_label, items in grouped.items():
                st.sidebar.caption(type_label)
                page = type_to_page.get(type_label, "Dashboard")
                # Tag the namespace when the same local name appears under more
                # than one URI in these results, so duplicates don't render as
                # identical entries (e.g. `Dog` and `Dog (other)`). This is the
                # same disambiguation the rest of the UI and the graph already
                # use (issue #119).
                collisions = _build_name_collision_set(items)
                for r in items:
                    disp_name = _disambiguated_name(r, collisions)
                    label_str = (
                        f" ({r['label']})"
                        if r["label"] and r["label"] != r["name"]
                        else ""
                    )
                    # Key the search button by URI hash so duplicate local
                    # names in different namespaces produce distinct buttons.
                    r_uri = r.get("uri", r["name"])
                    r_uid = _uid(r_uri)
                    if st.sidebar.button(
                        f"{disp_name}{label_str}",
                        key=f"search_{type_label}_{r_uid}",
                        use_container_width=True,
                    ):
                        st.session_state.search_navigate_to = page
                        # Open the view pane keyed by URI hash so we navigate
                        # to the *exact* resource, not whichever shares the
                        # same local name.
                        _nav_open_entity(type_label, r_uid, r_uri)
                        st.rerun()
        else:
            st.sidebar.caption("No results found.")

    st.sidebar.divider()

    # Quick stats in sidebar
    stats = st.session_state.ontology.get_statistics()
    st.sidebar.caption("Quick Stats")
    # One block rather than a write() per line: each was its own element, and
    # the gap between elements cost more than the lines themselves. Two trailing
    # spaces are markdown for a line break.
    _stat_lines = [
        f"📦 Classes: {stats['classes']}",
        f"🔗 Object Props: {stats['object_properties']}",
        f"📝 Data Props: {stats['data_properties']}",
        f"👤 Individuals: {stats['individuals']}",
    ]
    if stats.get("concepts", 0) > 0:
        _stat_lines.append(f"🏷️ SKOS Concepts: {stats['concepts']}")
    _stat_lines.append(f"📊 Triples: {stats['content_triples']}")
    st.sidebar.markdown("  \n".join(_stat_lines))

    # Say what the app is, but only to someone who has nothing loaded yet. The
    # name otherwise lives in the sidebar and the tab title, and a permanent
    # banner would push every page's real content down for the whole session.
    # It sits above the page dispatch rather than on the Dashboard because a
    # fresh session lands on Import / Export, so a Dashboard-only intro would be
    # seen by returning users and missed by the newcomers it is written for.
    if _ontology_is_empty(st.session_state.ontology):
        # ® to match the trademark notice in the README; this is the one place
        # in the UI that prints the full product name.
        st.title("OrionBelt® Ontology Builder")
        st.markdown(
            "### Build and explore OWL ontologies in your browser\n\n"
            "Create, visualize and validate ontologies without installing "
            "Protégé."
        )

    # Show ontology name in main area
    ont = st.session_state.ontology
    meta = ont.get_ontology_metadata()
    ont_label = meta.get("label", "")
    ont_uri = str(ont.namespace)
    if not ont_label:
        import re

        parts = [p for p in ont_uri.rstrip("#/").split("/") if p and ":" not in p]
        name_parts = [p for p in parts if not re.match(r"^v?\d+[\d.]*$", p)]
        ont_label = name_parts[-1] if name_parts else (parts[-1] if parts else ont_uri)
    if ont_uri.startswith("http://example.org/"):
        st.markdown(
            f'<p style="color:gray;font-size:0.9rem;margin:0"><b>{ont_label}</b> — '
            f"{ont_uri.replace('http://', 'http&#58;//')}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<p style="color:gray;font-size:0.9rem;margin:0"><b>{ont_label}</b> — '
            f'<a href="{ont_uri}" target="_blank" style="color:gray">{ont_uri}</a></p>',
            unsafe_allow_html=True,
        )

    # "Back to graph" affordance after jumping to an editor from the
    # Visualization panel / status bar (issue #80).
    if selection == "Visualization":
        st.session_state.pop("_back_to_viz", None)
    elif st.session_state.get("_back_to_viz") and st.button(
        "← Back to graph", key="back_to_viz"
    ):
        st.session_state.pop("_back_to_viz", None)
        st.session_state.search_navigate_to = "Visualization"
        st.rerun()

    # Show any flash message from a previous action (set_flash_message), for
    # every page rather than only Import/Export, so bulk-add results and delete
    # confirmations aren't lost after their rerun (issue #114).
    display_flash_message()

    # Render selected page
    try:
        pages[selection]()
    except Exception as e:  # noqa: BLE001 - a crash in any page must not kill the app
        log_error(e, context=f"Page: {selection}")
        st.error(f"An error occurred: {e}")
        st.caption(f"[Report this issue on GitHub]({GITHUB_ISSUES_URL}/new)")

    # Sidebar: error log and GitHub link
    st.sidebar.divider()
    error_log = st.session_state.error_log
    if error_log:
        with st.sidebar.expander(f"Errors ({len(error_log)})", expanded=False):
            for i, entry in enumerate(reversed(error_log)):
                st.markdown(f"**{entry['time']}** — {entry['context']}")
                st.code(entry["error"], language=None)
                with st.expander("Traceback", expanded=False):
                    st.code(entry["traceback"], language="python")
            if st.button("Clear errors", key="btn_clear_errors"):
                st.session_state.error_log = []
                st.rerun()
            st.markdown(f"[Report on GitHub]({GITHUB_ISSUES_URL}/new)")

    # Mirror the current ontology to browser localStorage (after all edits for
    # this rerun have been applied) so a refresh can restore it.
    persist_autosave()


if __name__ == "__main__":
    main()

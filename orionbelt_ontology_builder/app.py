"""
OrionBelt Ontology Builder - A Streamlit application for building, editing,
and managing OWL ontologies.
"""

import logging

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
    ACTIVE_LANG_PACK_KEY,
    APP_NAME,
    APP_VERSION,
    AUTOSAVE_DEBOUNCE_SECONDS,
    AUTOSAVE_KEY,
    AUTOSAVE_MAX_BYTES,
    CUSTOM_LANG_PACKS_KEY,
    FOCUS_BUILD_MAX_NODES,
    GITHUB_ISSUES_URL,
    GRAPH_MAX_NODES,
    LABEL_NAME_SEPARATOR,
    LANG_PACKS_KEY,
    LIST_PAGE_SIZE,
    PKG_DIR,
    SEARCH_PAD_WIDTH,
    VIZ_FILE_STATE_KEY,
    VIZ_FILE_STATE_MAX_FILES,
    VIZ_SETTINGS_KEY,
    _apply_annotation_edit,
    _apply_class_edit,
    _apply_class_relation_add,
    _apply_individual_edit,
    _apply_language_packs,
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
    _mark_language_packs_dirty,
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
    active_language_pack,
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
    custom_language_packs,
    delete_custom_language_pack,
    display_flash_message,
    filter_entry_token,
    focus_seeds_after_request,
    focus_seeds_from_selection,
    follow_focus_seed_renames,
    follow_renamed_node_ids,
    format_label_name,
    get_ontology_manager_class,
    graph_node_cap,
    init_session_state,
    language_pack_entries,
    language_pack_names,
    language_selectbox,
    language_tag_error,
    log_error,
    maybe_restore_autosave,
    missing_required,
    panel_subject_uri,
    parent_option_index,
    parse_filter_text,
    parse_search_query,
    persist_autosave,
    persist_language_packs,
    prioritise_find_target,
    prune_reused_focus_seeds,
    reconcile_filter_selection,
    render_add_annotation,
    render_add_class_form,
    render_add_restriction,
    render_annotation_form,
    render_language_pack_sidebar,
    render_relation_form,
    render_relation_rows,
    render_restriction_editor,
    render_restriction_form,
    render_restriction_row,
    request_autosave_flush,
    required_selectbox,
    resolve_annotation_predicate_choice,
    resolve_picked_object,
    restore_language_packs,
    restriction_references_class,
    restriction_takes_on_class,
    restriction_value_is_class,
    save_checkpoint,
    save_custom_language_pack,
    seed_filter_from_saved,
    set_flash_message,
    show_message,
    viz_drop_focus_seeds,
    viz_filter_changed,
    viz_find_changed,
    viz_focus_toggle,
    viz_hidden_caption,
    viz_hidden_note_style,
    viz_mark_ontology_seen,
    viz_node_id,
    viz_note_rename,
    viz_ontology_was_replaced,
    viz_sync,
)

# The pages, re-exported so ``app.render_classes`` and friends still resolve.
# They live in ``views`` rather than ``pages`` because Streamlit reads a
# ``pages`` directory next to an entry script as a legacy multipage app (#269).
from .views.advanced import render_advanced
from .views.annotations import (  # noqa: F401 - the tabs are re-exported like the ui block's
    bulk_annotation_updates,
    render_annotation_types,
    render_annotations,
    render_language_packs,
    render_view_annotations,
)
from .views.classes import render_classes
from .views.dashboard import render_dashboard
from .views.import_export import render_import_export
from .views.individuals import render_individuals
from .views.properties import render_properties
from .views.relations import render_relations
from .views.restrictions import render_restrictions
from .views.skos import render_skos_vocabulary
from .views.source import render_source
from .views.validation import render_validation
from .views.visualization import render_visualization


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
    _logo_path = PKG_DIR / "assets" / _logo_file
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

    # Which language codes every Language field offers (issue #252). It sits in
    # the sidebar because those fields are on three pages and in the graph
    # panel, and one pack is meant to hold for all of them.
    render_language_pack_sidebar()

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

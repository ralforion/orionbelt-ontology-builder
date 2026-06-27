"""
OrionBelt Ontology Builder - A Streamlit application for building, editing,
and managing OWL ontologies.
"""

import hashlib
import logging
import streamlit as st
import traceback
from datetime import datetime
from pathlib import Path as _Path

APP_NAME = "OrionBelt Ontology Builder"
APP_VERSION = "1.8.0"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GITHUB_ISSUES_URL = "https://github.com/ralforion/orionbelt-ontology-builder/issues"

# Browser-localStorage autosave: the working ontology lives only in Streamlit's
# in-memory session state, so a page refresh starts a fresh session and would
# otherwise discard all unsaved work. We mirror the graph into the browser's
# localStorage and restore it automatically when a new session starts.
AUTOSAVE_KEY = "orionbelt_ontology_builder_autosave"
# localStorage is ~5 MB per origin; stay well under to leave headroom.
AUTOSAVE_MAX_BYTES = 4_000_000

_FAVICON = _Path(__file__).parent / "favicon.png"

_CUSTOM_CSS = """
<style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    .success-message {
        padding: 10px;
        background-color: #d4edda;
        border-radius: 4px;
        color: #155724;
    }
    .warning-message {
        padding: 10px;
        background-color: #fff3cd;
        border-radius: 4px;
        color: #856404;
    }
    .error-message {
        padding: 10px;
        background-color: #f8d7da;
        border-radius: 4px;
        color: #721c24;
    }
    /* Reduce margin/padding */
    .block-container, .stMainBlockContainer,
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 2.5rem !important;
        padding-bottom: 0 !important;
    }
    footer, [data-testid="stBottom"] {
        display: none !important;
    }
    .main .block-container { min-height: 0 !important; }
    /* Reduce iframe and element spacing */
    iframe {
        margin-bottom: 0 !important;
    }
    [data-testid="stCustomComponentV1"] {
        margin-bottom: -1rem !important;
    }
</style>
"""


def _configure_page() -> None:
    """Apply page config and custom CSS. Called from main() so it fires on
    every Streamlit rerun (CSS markdown only persists for the rerun in which
    it was emitted; set_page_config is idempotent across reruns)."""
    if not st.session_state.get("_page_configured"):
        st.set_page_config(
            page_title=APP_NAME,
            page_icon=str(_FAVICON) if _FAVICON.exists() else None,
            layout="wide",
            initial_sidebar_state="expanded",
        )
        st.session_state["_page_configured"] = True
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    if "app_started" not in st.session_state:
        st.session_state.app_started = True
        logger.info(f"{APP_NAME} v{APP_VERSION}")


@st.cache_resource
def get_ontology_manager_class():
    """Lazy load the OntologyManager class."""
    from .ontology_manager import OntologyManager

    return OntologyManager


def init_session_state():
    """Initialize session state variables."""
    if "ontology" not in st.session_state:
        with st.spinner("Loading ontology engine..."):
            OntologyManager = get_ontology_manager_class()
            st.session_state.ontology = OntologyManager()
    if "undo_manager" not in st.session_state:
        try:
            from .ontology_manager import UndoManager

            st.session_state.undo_manager = UndoManager(st.session_state.ontology)
        except ImportError as e:
            st.error(f"Failed to load UndoManager: {e}")
            st.session_state.undo_manager = None
    if "flash_message" not in st.session_state:
        st.session_state.flash_message = None
    if "error_log" not in st.session_state:
        st.session_state.error_log = []
    # On first run with empty ontology, start on Import/Export page.
    if "nav_radio" not in st.session_state:
        ont = st.session_state.ontology
        _s = ont.get_statistics()
        if (
            _s["classes"] == 0
            and _s["object_properties"] == 0
            and _s["data_properties"] == 0
            and _s.get("concepts", 0) == 0
        ):
            st.session_state["nav_radio"] = "Import / Export"


def _content_hash(text: str) -> str:
    """Stable hash of a serialized ontology, used to skip redundant autosaves."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _ontology_is_empty(ont) -> bool:
    """True when the ontology has no user content (only metadata, if any)."""
    s = ont.get_statistics()
    return (
        s["classes"] == 0
        and s["object_properties"] == 0
        and s["data_properties"] == 0
        and s["individuals"] == 0
        and s.get("concepts", 0) == 0
    )


def _get_local_storage():
    """Return a browser-localStorage handle, or None if unavailable.

    The component instance is constructed once per session (mounting the reader
    component twice in one rerun would collide on its Streamlit key). On a fresh
    page load the browser hands its stored items back on a *later* rerun, so we
    refresh the cached handle's items from the component's latest value on every
    call. If the optional dependency is missing or the component fails, autosave
    is silently disabled so the rest of the app keeps working.
    """
    if "_local_storage" not in st.session_state:
        try:
            from streamlit_local_storage import LocalStorage

            st.session_state["_local_storage"] = LocalStorage()
        except Exception as e:  # pragma: no cover - depends on browser/runtime
            logger.warning(f"localStorage autosave unavailable: {e}")
            st.session_state["_local_storage"] = None
    ls = st.session_state["_local_storage"]
    if ls is not None:
        latest = st.session_state.get(getattr(ls, "storedKey", None))
        if isinstance(latest, dict):
            ls.storedItems = latest
    return ls


def maybe_restore_autosave():
    """Restore the ontology from browser localStorage when a session starts.

    Runs after init_session_state(), while the freshly created ontology is still
    empty. The localStorage component returns its empty default on the first
    script run of a fresh page load and only delivers the real data on a
    follow-up rerun, so this keeps retrying (no premature "restored" flag) until
    either data arrives or the session already has content. The empty-session
    guard makes it safe to run repeatedly — a loaded sample is never clobbered.
    """
    if st.session_state.get("_autosave_restored"):
        return
    ont = st.session_state.ontology
    # Once the session has content (restored, imported, or freshly authored),
    # there is nothing left to restore.
    if not _ontology_is_empty(ont):
        st.session_state["_autosave_restored"] = True
        return

    ls = _get_local_storage()
    if ls is None:
        st.session_state["_autosave_restored"] = True
        return
    saved = ls.getItem(AUTOSAVE_KEY)
    # The localStorage component occasionally hands the value back wrapped in a
    # {key: value} dict instead of the raw string; unwrap defensively.
    if isinstance(saved, dict):
        saved = saved.get(AUTOSAVE_KEY) or next(
            (v for v in saved.values() if isinstance(v, str)), None
        )
    if not isinstance(saved, str) or not saved.strip():
        # Data may not have arrived from the browser yet; try again next rerun.
        return

    try:
        ont.load_from_string(saved, format="turtle")
    except Exception as e:
        log_error(e, context="Autosave restore")
        st.session_state["_autosave_restored"] = True
        return

    st.session_state["_autosave_restored"] = True
    st.session_state["_autosave_last_hash"] = _content_hash(saved)
    # An empty-but-valid saved graph (e.g. after a discard) is loaded silently;
    # there is no work to announce or navigate to.
    if _ontology_is_empty(ont):
        return
    # Rebuild undo history so the restored graph becomes the baseline state.
    try:
        from .ontology_manager import UndoManager

        st.session_state.undo_manager = UndoManager(ont)
    except ImportError:
        pass
    st.session_state["_ont_mutation_count"] = (
        st.session_state.get("_ont_mutation_count", 0) + 1
    )
    # init_session_state parks empty sessions on Import/Export; with content
    # restored, the Dashboard is the more useful landing page.
    if st.session_state.get("nav_radio") == "Import / Export":
        st.session_state["nav_radio"] = "Dashboard"
    st.toast("Restored your previous session from this browser's autosave.", icon="💾")


def persist_autosave():
    """Mirror the current ontology into browser localStorage when it changed.

    Called at the end of each rerun. Skips when autosave is disabled, unchanged
    since the last save, or too large for localStorage.
    """
    if not st.session_state.get("_autosave_enabled", True):
        return
    # Don't persist until restore has resolved, or the empty starting graph
    # would overwrite saved data before it can be read back on a later rerun.
    if not st.session_state.get("_autosave_restored"):
        return
    ls = _get_local_storage()
    if ls is None:
        return
    try:
        ttl = st.session_state.ontology.export_to_string(format="turtle")
    except Exception as e:
        log_error(e, context="Autosave export")
        return

    if len(ttl.encode("utf-8")) > AUTOSAVE_MAX_BYTES:
        if not st.session_state.get("_autosave_too_big_warned"):
            st.session_state["_autosave_too_big_warned"] = True
            st.sidebar.warning(
                "Ontology is too large to autosave to this browser. "
                "Export it manually so you don't lose work."
            )
        return

    h = _content_hash(ttl)
    if h == st.session_state.get("_autosave_last_hash"):
        return
    # Key the write by content hash so each distinct save mounts a fresh
    # component instance — reusing one key across reruns can leave the component
    # writing a stale/wrapped value.
    ls.setItem(AUTOSAVE_KEY, ttl, key=f"orionbelt_autosave_set_{h[:12]}")
    st.session_state["_autosave_last_hash"] = h


def render_autosave_sidebar():
    """Sidebar controls: toggle autosave and discard the saved session."""
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
        and st.session_state.get("_autosave_last_hash")
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
        st.session_state["_autosave_last_hash"] = None
        st.session_state["_ont_mutation_count"] = (
            st.session_state.get("_ont_mutation_count", 0) + 1
        )
        st.toast("Cleared this browser's autosave and reset the workspace.", icon="🗑️")
        st.rerun()


def save_checkpoint(label: str = "Edit"):
    """Save a snapshot to the undo history after a mutation."""
    if st.session_state.get("undo_manager"):
        st.session_state.undo_manager.checkpoint(label)
    # Bump mutation counter so derived UI caches (e.g. graph viz) invalidate
    st.session_state["_ont_mutation_count"] = (
        st.session_state.get("_ont_mutation_count", 0) + 1
    )


def log_error(error: Exception, context: str = ""):
    """Log a runtime error to session state for display."""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "context": context,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }
    st.session_state.error_log.append(entry)


def show_message(message: str, type: str = "info"):
    """Display a message to the user."""
    if type == "success":
        st.success(message)
    elif type == "warning":
        st.warning(message)
    elif type == "error":
        st.error(message)
    else:
        st.info(message)


def set_flash_message(message: str, type: str = "info"):
    """Set a flash message to be displayed after rerun."""
    st.session_state.flash_message = {"message": message, "type": type}


def display_flash_message():
    """Display and clear any pending flash message."""
    if st.session_state.get("flash_message"):
        msg = st.session_state.flash_message
        show_message(msg["message"], msg["type"])
        st.session_state.flash_message = None


def confirm_delete(resource_name: str, resource_type: str, key_suffix: str) -> bool:
    """Show delete impact and confirmation UI. Returns True when confirmed."""
    ont = st.session_state.ontology
    confirm_key = f"confirm_delete_{key_suffix}"

    if st.session_state.get(confirm_key):
        impact = ont.get_delete_impact(resource_name, resource_type)
        summary = ont.format_delete_impact(impact)
        st.warning(summary)
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Confirm Delete", key=f"yes_{confirm_key}", type="primary"):
                st.session_state[confirm_key] = False
                return True
        with col_no:
            if st.button("Cancel", key=f"no_{confirm_key}"):
                st.session_state[confirm_key] = False
                st.rerun()
    return False


def format_label_name(name: str, label: str) -> str:
    """Format display string as 'Label (name)' if label exists and differs from name."""
    if label and label != name:
        return f"{label} ({name})"
    return name


def _uid(uri: str) -> str:
    """Stable short identifier for a URI — used as Streamlit key suffix.

    The local name of an imported resource may collide across namespaces
    (e.g., gist:Organization and foaf:Organization both have local name
    'Organization'). Using a hash of the full URI guarantees a unique key
    per resource regardless of name collisions.
    """
    return hashlib.md5(uri.encode("utf-8")).hexdigest()[:12]


def _prefix_for_uri(uri: str) -> str:
    """Return the prefix bound to the namespace of a URI, or empty string.

    Used by display disambiguation to surface the namespace when a local
    name appears in more than one namespace.
    """
    ont = st.session_state.get("ontology")
    if ont is None:
        return ""
    # Find the longest namespace whose URI is a prefix of the resource URI
    best_prefix = ""
    best_ns_len = 0
    for prefix, ns in ont.graph.namespaces():
        ns_str = str(ns)
        if uri.startswith(ns_str) and len(ns_str) > best_ns_len:
            best_prefix = prefix
            best_ns_len = len(ns_str)
    return best_prefix


def _build_name_collision_set(items: list) -> set:
    """Return the set of local names that appear under more than one URI.

    `items` is a list of dicts each with 'name' and 'uri' fields. Result is
    used by `_disambiguated_name` so single-namespace names render as just
    the name and ambiguous names render with a namespace tag.
    """
    seen: dict[str, str] = {}
    collisions: set[str] = set()
    for it in items:
        name = it.get("name")
        uri = it.get("uri")
        if not name or not uri:
            continue
        if name in seen:
            if seen[name] != uri:
                collisions.add(name)
        else:
            seen[name] = uri
    return collisions


def _disambiguated_name(item: dict, collisions: set) -> str:
    """Return a display name that includes a namespace prefix when ambiguous.

    `Organization` stays `Organization` if it's the only one; otherwise it
    becomes `Organization (foaf)` / `Organization (gist)` etc.
    """
    name = item.get("name", "")
    if name in collisions:
        prefix = _prefix_for_uri(item.get("uri", ""))
        if prefix:
            return f"{name} ({prefix})"
    return name


def _cb_toggle_view(prefix, uid):
    """Callback: open view panel, close edit. `uid` must be unique per resource."""
    st.session_state[f"view_{prefix}_{uid}"] = True
    st.session_state[f"edit_{prefix}_{uid}"] = False


def _cb_toggle_edit(prefix, uid):
    """Callback: open edit panel, close view. `uid` must be unique per resource."""
    st.session_state[f"edit_{prefix}_{uid}"] = True
    st.session_state[f"view_{prefix}_{uid}"] = False


def _cb_view_to_edit(prefix, uid):
    """Callback: switch from view to edit. `uid` must be unique per resource."""
    st.session_state[f"view_{prefix}_{uid}"] = False
    st.session_state[f"edit_{prefix}_{uid}"] = True


def _cb_confirm_delete(key_suffix):
    """Callback: trigger delete confirmation."""
    st.session_state[f"confirm_delete_{key_suffix}"] = True


def build_uri_options(items: list, include_none: bool = False) -> tuple:
    """Build dropdown options for any entity list (classes / properties /
    individuals) where each item is a dict with at least 'name' and 'uri'.

    Display strings include a namespace tag when local names collide across
    namespaces (e.g. 'Organization (foaf)' / 'Organization (gist)'), so the
    dropdown never shows two visually identical entries. The lookup maps
    each display string to the resource's full URI — pass this URI to
    OntologyManager methods (which already accept URIs via `_uri()`) so a
    cross-namespace duplicate is never silently rewritten into the user's
    base namespace.

    Returns:
        tuple: (display_options, uri_lookup_dict). For the 'None' entry the
        lookup value is None.
    """
    options = []
    lookup = {}
    collisions = _build_name_collision_set(items)

    rows = []
    for it in items:
        disp_name = _disambiguated_name(it, collisions)
        display = format_label_name(disp_name, it.get("label"))
        rows.append(display)
        lookup[display] = it["uri"]

    rows.sort(key=lambda x: x.lower())

    if include_none:
        options.append("None")
        lookup["None"] = None

    options.extend(rows)
    return options, lookup


def build_class_options(classes: list, include_none: bool = False) -> tuple:
    """Build class dropdown options with 'Label (disambiguated name)' format.

    Thin wrapper around :func:`build_uri_options` kept for clarity at call
    sites that work specifically with classes.
    """
    options = []
    lookup = {}
    collisions = _build_name_collision_set(classes)

    # Build display strings and sort
    items = []
    for c in classes:
        disp_name = _disambiguated_name(c, collisions)
        display = format_label_name(disp_name, c.get("label"))
        items.append(display)
        lookup[display] = c["uri"]

    # Sort alphabetically by display text (case-insensitive)
    items.sort(key=lambda x: x.lower())

    if include_none:
        options.append("None")
        lookup["None"] = None

    options.extend(items)
    return options, lookup


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
                    st.rerun()

    with st.expander("Add Import"):
        new_import = st.text_input(
            "Import URI", placeholder="http://example.org/other-ontology"
        )
        if st.button("Add Import"):
            if new_import:
                ont.add_import(new_import)
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
            if new_prefix and new_ns:
                ont.add_prefix(new_prefix, new_ns)
                save_checkpoint("Add prefix")
                set_flash_message(f"Added prefix '{new_prefix}'", "success")
                st.rerun()
            else:
                show_message("Both prefix and namespace URI are required.", "warning")

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

    _cls_tab = st.segmented_control(
        "Section",
        ["View Classes", "Add Class", "Edit/Delete Class", "Bulk Operations"],
        default="View Classes",
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
            _active_cls = next(
                (
                    c
                    for c in sorted_classes
                    if st.session_state.get(f"view_class_{_uid(c['uri'])}", False)
                    or st.session_state.get(f"edit_class_{_uid(c['uri'])}", False)
                ),
                None,
            )
            if _active_cls:
                _active_uid = _uid(_active_cls["uri"])
                for c in sorted_classes:
                    c_uid = _uid(c["uri"])
                    if c_uid != _active_uid:
                        st.session_state.pop(f"view_class_{c_uid}", None)
                        st.session_state.pop(f"edit_class_{c_uid}", None)

            for cls in sorted_classes:
                cls_uid = _uid(cls["uri"])
                disp_name = _disambiguated_name(cls, collisions)
                display_name = format_label_name(disp_name, cls.get("label"))
                _cls_expanded = st.session_state.get(
                    f"view_class_{cls_uid}", False
                ) or st.session_state.get(f"edit_class_{cls_uid}", False)
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
                    if st.session_state.get(f"view_class_{cls_uid}", False):
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
                    if st.session_state.get(f"edit_class_{cls_uid}", False):
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
                            new_parent = st.selectbox(
                                "Parent Class",
                                options=["None"] + other_classes,
                                index=0
                                if current_parent == "None"
                                else (
                                    other_classes.index(current_parent) + 1
                                    if current_parent in other_classes
                                    else 0
                                ),
                                key=f"par_{cls_uid}",
                            )

                            if st.form_submit_button("Save Changes"):
                                # Handle rename first — pass URI so cross-namespace duplicates resolve correctly
                                current_ref = cls["uri"]
                                if new_name and new_name != cls["name"]:
                                    if ont.rename_class(cls["uri"], new_name):
                                        current_ref = new_name  # post-rename, the resource lives in the base namespace
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
                                st.session_state[f"edit_class_{cls_uid}"] = False
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

        with st.form("add_class_form"):
            name = st.text_input(
                "Class Name *", help="Local name for the class (e.g., 'Person')"
            )
            label = st.text_input("Label", help="Human-readable label")
            comment = st.text_area("Comment", help="Description of the class")
            parent_options, parent_lookup = build_class_options(
                classes, include_none=True
            )
            parent_display = st.selectbox(
                "Parent Class",
                options=parent_options,
                help="Select a parent class for hierarchy",
            )

            submitted = st.form_submit_button("Add Class")
            if submitted:
                if not name:
                    show_message("Class name is required!", "error")
                elif name in [c["name"] for c in classes]:
                    show_message(f"Class '{name}' already exists!", "error")
                else:
                    parent_val = parent_lookup.get(parent_display)
                    ont.add_class(name, parent=parent_val, label=label, comment=comment)
                    save_checkpoint("Add class")
                    show_message(f"Class '{name}' added successfully!", "success")
                    st.rerun()

    if _cls_tab == "Edit/Delete Class":
        st.subheader("Edit or Delete Class")

        if not classes:
            st.info("No classes to edit.")
        else:
            # Build options with Label (disambiguated name) format; lookup is by URI
            class_options, class_lookup = build_class_options(classes)
            selected_display = st.selectbox(
                "Select Class", options=class_options, key="edit_class_select"
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
                    new_label = st.text_input("Label", value=class_info["label"])
                    new_comment = st.text_area("Comment", value=class_info["comment"])

                    other_classes = [c for c in class_names if c != selected_class]
                    current_parent = (
                        class_info["parents"][0] if class_info["parents"] else "None"
                    )
                    new_parent = st.selectbox(
                        "Parent Class",
                        options=["None"] + other_classes,
                        index=0
                        if current_parent == "None"
                        else (
                            other_classes.index(current_parent) + 1
                            if current_parent in other_classes
                            else 0
                        ),
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        update_btn = st.form_submit_button("Update Class")
                    with col2:
                        delete_btn = st.form_submit_button(
                            "Delete Class", type="secondary"
                        )

                    if update_btn:
                        # Rename first (updates all references) so the rest of
                        # the update targets the renamed class.
                        current_ref = class_info["uri"]
                        if new_name and new_name != class_info["name"]:
                            if ont.rename_class(class_info["uri"], new_name):
                                current_ref = new_name
                            else:
                                show_message(
                                    f"Cannot rename: '{new_name}' already exists!",
                                    "error",
                                )
                                st.rerun()

                        # Remove old parent if changed
                        if (
                            class_info["parents"]
                            and new_parent != class_info["parents"][0]
                        ):
                            ont.update_class(
                                current_ref,
                                remove_parent=class_info["parents"][0],
                            )

                        ont.update_class(
                            current_ref,
                            new_label=new_label,
                            new_comment=new_comment,
                            new_parent=new_parent if new_parent != "None" else None,
                        )
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
                "Enter one class name per line, or use CSV format: Name, Label, Parent"
            )
            bulk_text = st.text_area(
                "Class entries",
                height=200,
                key="bulk_classes_text",
                placeholder="Dog\nCat\nBird\n\nor CSV:\nName, Label, Parent\nDog, A Dog, Animal\nCat, A Cat, Animal",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(bulk_text)
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    if st.button(
                        "Create All Classes", type="primary", key="bulk_create_classes"
                    ):
                        result = ont.bulk_add_classes(entries)
                        save_checkpoint("Bulk add classes")
                        parts = []
                        if result["created"]:
                            parts.append(f"Created {len(result['created'])} class(es)")
                        if result["skipped"]:
                            parts.append(f"Skipped {len(result['skipped'])} existing")
                        if result["errors"]:
                            parts.append(f"{len(result['errors'])} error(s)")
                        show_message(
                            ". ".join(parts),
                            "success" if result["created"] else "warning",
                        )
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
            _active_op = next(
                (
                    p
                    for p in filtered_obj_props
                    if st.session_state.get(f"view_objprop_{_uid(p['uri'])}", False)
                    or st.session_state.get(f"edit_objprop_{_uid(p['uri'])}", False)
                ),
                None,
            )
            if _active_op:
                _active_op_uid = _uid(_active_op["uri"])
                for p in filtered_obj_props:
                    p_uid = _uid(p["uri"])
                    if p_uid != _active_op_uid:
                        st.session_state.pop(f"view_objprop_{p_uid}", None)
                        st.session_state.pop(f"edit_objprop_{p_uid}", None)

            for prop in filtered_obj_props:
                prop_uid = _uid(prop["uri"])
                disp_name = _disambiguated_name(prop, op_collisions)
                _op_expanded = st.session_state.get(
                    f"view_objprop_{prop_uid}", False
                ) or st.session_state.get(f"edit_objprop_{prop_uid}", False)
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
                    if st.session_state.get(f"view_objprop_{prop_uid}", False):
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
                    if st.session_state.get(f"edit_objprop_{prop_uid}", False):
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
                                dom_disp = st.selectbox(
                                    "Domain",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_dom_disp)
                                    if cur_dom_disp in cls_opts
                                    else 0,
                                    key=f"objp_dom_{prop_uid}",
                                )
                            with col2:
                                rng_disp = st.selectbox(
                                    "Range",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_rng_disp)
                                    if cur_rng_disp in cls_opts
                                    else 0,
                                    key=f"objp_rng_{prop_uid}",
                                )

                            if st.form_submit_button("Save Changes"):
                                # Handle rename first — pass URI for cross-namespace safety
                                current_ref = prop["uri"]
                                if new_name and new_name != prop["name"]:
                                    if ont.rename_property(prop["uri"], new_name):
                                        current_ref = new_name
                                        save_checkpoint("Rename property")
                                        show_message(
                                            f"Property renamed to '{new_name}'",
                                            "success",
                                        )
                                    else:
                                        show_message(
                                            f"Cannot rename: '{new_name}' already exists!",
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
                                st.session_state[f"edit_objprop_{prop_uid}"] = False
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
            _active_dp = next(
                (
                    p
                    for p in filtered_data_props
                    if st.session_state.get(f"view_dataprop_{_uid(p['uri'])}", False)
                    or st.session_state.get(f"edit_dataprop_{_uid(p['uri'])}", False)
                ),
                None,
            )
            if _active_dp:
                _active_dp_uid = _uid(_active_dp["uri"])
                for p in filtered_data_props:
                    p_uid = _uid(p["uri"])
                    if p_uid != _active_dp_uid:
                        st.session_state.pop(f"view_dataprop_{p_uid}", None)
                        st.session_state.pop(f"edit_dataprop_{p_uid}", None)

            for prop in filtered_data_props:
                prop_uid = _uid(prop["uri"])
                disp_name = _disambiguated_name(prop, dp_collisions)
                _dp_expanded = st.session_state.get(
                    f"view_dataprop_{prop_uid}", False
                ) or st.session_state.get(f"edit_dataprop_{prop_uid}", False)
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
                    if st.session_state.get(f"view_dataprop_{prop_uid}", False):
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
                    if st.session_state.get(f"edit_dataprop_{prop_uid}", False):
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
                                dom_disp = st.selectbox(
                                    "Domain",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_dom_disp)
                                    if cur_dom_disp in cls_opts
                                    else 0,
                                    key=f"dp_dom_{prop_uid}",
                                )
                            with col2:
                                current_range = (
                                    prop["range"]
                                    if prop["range"] in datatypes
                                    else "string"
                                )
                                new_range = st.selectbox(
                                    "Range (Datatype)",
                                    options=datatypes,
                                    index=datatypes.index(current_range)
                                    if current_range in datatypes
                                    else 0,
                                    key=f"dp_rng_{prop_uid}",
                                )

                            if st.form_submit_button("Save Changes"):
                                # Handle rename first — pass URI for cross-namespace safety
                                current_ref = prop["uri"]
                                if new_name and new_name != prop["name"]:
                                    if ont.rename_property(prop["uri"], new_name):
                                        current_ref = new_name
                                        save_checkpoint("Rename property")
                                        show_message(
                                            f"Property renamed to '{new_name}'",
                                            "success",
                                        )
                                    else:
                                        show_message(
                                            f"Cannot rename: '{new_name}' already exists!",
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
                                st.session_state[f"edit_dataprop_{prop_uid}"] = False
                                show_message("Property updated!", "success")
                                st.rerun()

    if _prop_tab == "Add Object Property":
        st.subheader("Add Object Property")

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
                domain_disp = st.selectbox("Domain (Class)", options=cls_opts)
            with col2:
                range_disp = st.selectbox("Range (Class)", options=cls_opts)

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

            inverse_disp = st.selectbox("Inverse Of", options=obj_prop_opts)

            submitted = st.form_submit_button("Add Object Property")
            if submitted:
                if not name:
                    show_message("Property name is required!", "error")
                elif name in obj_prop_names or name in data_prop_names:
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
                domain_disp = st.selectbox(
                    "Domain (Class)", options=cls_opts, key="data_prop_domain"
                )
            with col2:
                datatypes = list(get_ontology_manager_class().XSD_DATATYPES.keys())
                range_ = st.selectbox(
                    "Range (Datatype)", options=datatypes, key="data_prop_range"
                )

            functional = st.checkbox("Functional", key="data_prop_functional")

            submitted = st.form_submit_button("Add Data Property")
            if submitted:
                if not name:
                    show_message("Property name is required!", "error")
                elif name in obj_prop_names or name in data_prop_names:
                    show_message(f"Property '{name}' already exists!", "error")
                else:
                    ont.add_data_property(
                        name,
                        domain=cls_lookup.get(domain_disp),
                        range_=range_,
                        label=label,
                        comment=comment,
                        functional=functional,
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
                "Enter one property per line, or CSV: Name, Domain, Range, Label"
            )
            bulk_text = st.text_area(
                "Property entries",
                height=200,
                key="bulk_props_text",
                placeholder="hasFriend\nhasEnemy\n\nor CSV:\nName, Domain, Range, Label\nhasFriend, Person, Person, has friend",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(bulk_text)
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    ptype = "object" if prop_type == "Object Property" else "data"
                    if st.button(
                        "Create All Properties", type="primary", key="bulk_create_props"
                    ):
                        result = ont.bulk_add_properties(entries, property_type=ptype)
                        save_checkpoint("Bulk add properties")
                        parts = []
                        if result["created"]:
                            parts.append(
                                f"Created {len(result['created'])} propert(ies)"
                            )
                        if result["skipped"]:
                            parts.append(f"Skipped {len(result['skipped'])} existing")
                        if result["errors"]:
                            parts.append(f"{len(result['errors'])} error(s)")
                        show_message(
                            ". ".join(parts),
                            "success" if result["created"] else "warning",
                        )
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

            _active_ind = next(
                (
                    i
                    for i in individuals
                    if st.session_state.get(f"view_ind_{_uid(i['uri'])}", False)
                    or st.session_state.get(f"edit_ind_{_uid(i['uri'])}", False)
                ),
                None,
            )
            if _active_ind:
                _active_ind_uid = _uid(_active_ind["uri"])
                for i in individuals:
                    i_uid = _uid(i["uri"])
                    if i_uid != _active_ind_uid:
                        st.session_state.pop(f"view_ind_{i_uid}", None)
                        st.session_state.pop(f"edit_ind_{i_uid}", None)

            for ind in individuals:
                classes_str = (
                    ", ".join(ind["classes"]) if ind["classes"] else "No class"
                )
                _ik = _uid(ind["uri"])
                disp_ind_name = _disambiguated_name(ind, ind_collisions)
                _ind_expanded = st.session_state.get(
                    f"view_ind_{_ik}", False
                ) or st.session_state.get(f"edit_ind_{_ik}", False)
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
                    if st.session_state.get(f"view_ind_{_ik}", False):
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
                    if st.session_state.get(f"edit_ind_{_ik}", False):
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
                                add_class = st.selectbox(
                                    "Add to Class",
                                    options=["None"] + available_classes,
                                    key=f"ind_add_cls_{_ik}",
                                )
                            with col2:
                                remove_class = st.selectbox(
                                    "Remove from Class",
                                    options=["None"] + current_classes,
                                    key=f"ind_rem_cls_{_ik}",
                                )

                            if st.form_submit_button("Save Changes"):
                                # Handle rename first — pass URI for cross-namespace safety
                                current_ref = ind["uri"]
                                if new_name and new_name != ind["name"]:
                                    if ont.rename_individual(ind["uri"], new_name):
                                        current_ref = new_name
                                        save_checkpoint("Rename individual")
                                        show_message(
                                            f"Individual renamed to '{new_name}'",
                                            "success",
                                        )
                                    else:
                                        show_message(
                                            f"Cannot rename: '{new_name}' already exists!",
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
                                st.session_state[f"edit_ind_{_ik}"] = False
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
                class_type = st.selectbox("Class Type *", options=class_names)

                submitted = st.form_submit_button("Add Individual")
                if submitted:
                    if not name:
                        show_message("Individual name is required!", "error")
                    elif name in ind_names:
                        show_message(f"Individual '{name}' already exists!", "error")
                    else:
                        ont.add_individual(
                            name, class_type, label=label, comment=comment
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
                individual = st.selectbox("Select Individual", options=ind_names)

                prop_type = st.radio(
                    "Property Type", ["Object Property", "Data Property"]
                )

                if prop_type == "Object Property":
                    prop_options = [p["name"] for p in object_props]
                    property_name = st.selectbox(
                        "Property",
                        options=prop_options if prop_options else ["No properties"],
                    )
                    value = st.selectbox("Value (Individual)", options=ind_names)
                    is_object = True
                else:
                    prop_options = [p["name"] for p in data_props]
                    property_name = st.selectbox(
                        "Property",
                        options=prop_options if prop_options else ["No properties"],
                    )
                    value = st.text_input("Value")
                    is_object = False

                submitted = st.form_submit_button("Add Property Value")
                if submitted:
                    if not property_name or property_name == "No properties":
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
                "Enter one individual per line (Name, Class) or CSV: Name, Class, Label"
            )
            bulk_text = st.text_area(
                "Individual entries",
                height=200,
                key="bulk_individuals_text",
                placeholder="Name, Class, Label\nalice, Person, Alice\nbob, Person, Bob",
            )
            if bulk_text:
                entries = ont.parse_bulk_text(bulk_text)
                if entries:
                    st.dataframe(pd.DataFrame(entries), width="stretch")
                    if st.button(
                        "Create All Individuals",
                        type="primary",
                        key="bulk_create_individuals",
                    ):
                        result = ont.bulk_add_individuals(entries)
                        save_checkpoint("Bulk add individuals")
                        parts = []
                        if result["created"]:
                            parts.append(
                                f"Created {len(result['created'])} individual(s)"
                            )
                        if result["skipped"]:
                            parts.append(f"Skipped {len(result['skipped'])} existing")
                        if result["errors"]:
                            parts.append(f"{len(result['errors'])} error(s)")
                        show_message(
                            ". ".join(parts),
                            "success" if result["created"] else "warning",
                        )
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
    class_names = [c["name"] for c in classes]
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    all_props = [p["name"] for p in object_props] + [p["name"] for p in data_props]
    restrictions = ont.get_restrictions()

    _rest_tab = st.segmented_control(
        "Section",
        ["View Restrictions", "Add Restriction"],
        default="View Restrictions",
        key="rest_active_tab",
        label_visibility="collapsed",
    )
    if not _rest_tab:
        _rest_tab = "View Restrictions"

    if _rest_tab == "View Restrictions":
        if not restrictions:
            st.info("No restrictions defined yet.")
        else:
            for i, rest in enumerate(restrictions):
                with st.expander(f"🔒 {rest['type']} on {rest['property']}"):
                    st.write(f"**Property:** {rest['property']}")
                    st.write(f"**Restriction Type:** {rest['type']}")
                    st.write(f"**Value:** {rest['value']}")
                    if rest["on_class"]:
                        st.write(f"**Qualified on Class:** {rest['on_class']}")
                    st.write(f"**Applied to Classes:** {', '.join(rest['applied_to'])}")

                    if rest["applied_to"]:
                        if st.button("Delete", key=f"del_rest_{i}"):
                            ont.delete_restriction(
                                rest["applied_to"][0], rest["property"], rest["type"]
                            )
                            save_checkpoint("Delete restriction")
                            show_message("Restriction deleted!", "success")
                            st.rerun()

    if _rest_tab == "Add Restriction":
        st.subheader("Add Restriction")

        if not class_names:
            st.warning("Please create at least one class first.")
        elif not all_props:
            st.warning("Please create at least one property first.")
        else:
            with st.form("add_restriction_form"):
                target_class = st.selectbox("Apply to Class", options=class_names)
                property_name = st.selectbox("On Property", options=all_props)

                restriction_types = [
                    "someValuesFrom",
                    "allValuesFrom",
                    "hasValue",
                    "minCardinality",
                    "maxCardinality",
                    "exactCardinality",
                    "minQualifiedCardinality",
                    "maxQualifiedCardinality",
                    "qualifiedCardinality",
                ]
                restriction_type = st.selectbox(
                    "Restriction Type", options=restriction_types
                )

                st.write("**Restriction Value:**")
                if restriction_type in ["someValuesFrom", "allValuesFrom"]:
                    value = st.selectbox(
                        "Value (Class)", options=class_names, key="rest_class_value"
                    )
                elif restriction_type == "hasValue":
                    value_type = st.radio("Value Type", ["Literal", "Individual"])
                    if value_type == "Literal":
                        value = st.text_input("Literal Value")
                    else:
                        ind_names = [i["name"] for i in ont.get_individuals()]
                        value = st.selectbox(
                            "Individual",
                            options=ind_names if ind_names else ["No individuals"],
                        )
                else:
                    value = st.number_input("Cardinality", min_value=0, value=1)

                on_class = None
                if "Qualified" in restriction_type:
                    on_class = st.selectbox(
                        "Qualified on Class", options=class_names, key="qualified_class"
                    )

                submitted = st.form_submit_button("Add Restriction")
                if submitted:
                    try:
                        ont.add_restriction(
                            target_class,
                            property_name,
                            restriction_type,
                            value,
                            on_class=on_class,
                        )
                        save_checkpoint("Add restriction")
                        show_message("Restriction added!", "success")
                        st.rerun()
                    except Exception as e:
                        show_message(f"Error adding restriction: {str(e)}", "error")


def render_relations():
    """Render the relations management page."""
    st.header("Relations")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    individuals = ont.get_individuals()

    _rel_tab = st.segmented_control(
        "Section",
        [
            "View Relations",
            "Class Relations",
            "Property Relations",
            "Individual Relations",
        ],
        default="View Relations",
        key="rel_active_tab",
        label_visibility="collapsed",
    )
    if not _rel_tab:
        _rel_tab = "View Relations"

    if _rel_tab == "View Relations":
        st.subheader("All Relations")

        # Class relations
        class_relations = ont.get_class_relations()
        if class_relations:
            st.write("**Class Relations:**")
            for rel in class_relations:
                subj_uri = rel.get("subject_uri", rel["subject"])
                obj_uri = rel.get("object_uri", rel["object"])
                rel_uid = _uid(f"{subj_uri}|{rel['relation']}|{obj_uri}")
                col1, col2, col3, col4 = st.columns([3, 2, 3, 1])
                with col1:
                    st.write(f"📦 {rel['subject']}")
                with col2:
                    st.write(f"➡️ {rel['relation']}")
                with col3:
                    st.write(f"📦 {rel['object']}")
                with col4:
                    if st.button("🗑️", key=f"del_crel_{rel_uid}"):
                        ont.remove_class_relation(subj_uri, rel["relation"], obj_uri)
                        save_checkpoint("Delete class relation")
                        show_message("Relation deleted!", "success")
                        st.rerun()
        else:
            st.info("No class relations defined.")

        st.divider()

        # Property relations
        prop_relations = ont.get_property_relations()
        if prop_relations:
            st.write("**Property Relations:**")
            for rel in prop_relations:
                col1, col2, col3, col4 = st.columns([3, 2, 3, 1])
                with col1:
                    st.write(f"🔗 {rel['subject']}")
                with col2:
                    st.write(f"➡️ {rel['relation']}")
                with col3:
                    st.write(f"🔗 {rel['object']}")
                with col4:
                    subj_uri = rel.get("subject_uri", rel["subject"])
                    obj_uri = rel.get("object_uri", rel["object"])
                    rel_uid = _uid(f"{subj_uri}|{rel['relation']}|{obj_uri}")
                    if st.button("🗑️", key=f"del_prel_{rel_uid}"):
                        ont.remove_property_relation(subj_uri, rel["relation"], obj_uri)
                        save_checkpoint("Delete property relation")
                        show_message("Relation deleted!", "success")
                        st.rerun()
        else:
            st.info("No property relations defined.")

        st.divider()

        # Individual relations
        ind_relations = ont.get_individual_relations()
        if ind_relations:
            st.write("**Individual Relations:**")
            for rel in ind_relations:
                col1, col2, col3, col4 = st.columns([3, 2, 3, 1])
                with col1:
                    st.write(f"👤 {rel['subject']}")
                with col2:
                    st.write(f"➡️ {rel['relation']}")
                with col3:
                    st.write(f"👤 {rel['object']}")
                with col4:
                    subj_uri = rel.get("subject_uri", rel["subject"])
                    obj_uri = rel.get("object_uri", rel["object"])
                    rel_uid = _uid(f"{subj_uri}|{rel['relation']}|{obj_uri}")
                    if st.button("🗑️", key=f"del_irel_{rel_uid}"):
                        ont.remove_individual_relation(
                            subj_uri, rel["relation"], obj_uri
                        )
                        save_checkpoint("Delete individual relation")
                        show_message("Relation deleted!", "success")
                        st.rerun()
        else:
            st.info("No individual relations defined.")

    if _rel_tab == "Class Relations":
        st.subheader("Add Class Relation")

        if len(classes) < 2:
            st.warning("Need at least 2 classes to create relations.")
        else:
            with st.form("add_class_relation_form"):
                cls_opts, cls_lookup = build_class_options(classes)
                col1, col2, col3 = st.columns(3)

                with col1:
                    class1_disp = st.selectbox(
                        "Class 1", options=cls_opts, key="crel_class1"
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=["subClassOf", "equivalentClass", "disjointWith"],
                        key="crel_type",
                    )
                with col3:
                    class2_disp = st.selectbox(
                        "Class 2", options=cls_opts, key="crel_class2"
                    )

                st.caption("""
                - **subClassOf**: Class 1 is a subclass of Class 2
                - **equivalentClass**: Class 1 and Class 2 have the same instances
                - **disjointWith**: Class 1 and Class 2 have no common instances
                """)

                submitted = st.form_submit_button("Add Class Relation")
                if submitted:
                    class1_uri = cls_lookup.get(class1_disp)
                    class2_uri = cls_lookup.get(class2_disp)
                    if class1_uri == class2_uri:
                        show_message("Please select two different classes!", "error")
                    else:
                        ont.add_class_relation(class1_uri, relation_type, class2_uri)
                        save_checkpoint("Add class relation")
                        show_message(
                            f"Relation added: {class1_disp} {relation_type} {class2_disp}",
                            "success",
                        )
                        st.rerun()

    if _rel_tab == "Property Relations":
        st.subheader("Add Property Relation")

        all_props = object_props + data_props
        if len(all_props) < 2:
            st.warning("Need at least 2 properties to create relations.")
        else:
            with st.form("add_property_relation_form"):
                prop_opts, prop_lookup = build_uri_options(all_props)
                col1, col2, col3 = st.columns(3)

                with col1:
                    prop1_disp = st.selectbox(
                        "Property 1", options=prop_opts, key="prel_prop1"
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=["subPropertyOf", "equivalentProperty", "inverseOf"],
                        key="prel_type",
                    )
                with col3:
                    prop2_disp = st.selectbox(
                        "Property 2", options=prop_opts, key="prel_prop2"
                    )

                st.caption("""
                - **subPropertyOf**: Property 1 is a sub-property of Property 2
                - **equivalentProperty**: Property 1 and Property 2 have the same meaning
                - **inverseOf**: Property 1 is the inverse of Property 2 (e.g., hasParent / hasChild)
                """)

                submitted = st.form_submit_button("Add Property Relation")
                if submitted:
                    prop1_uri = prop_lookup.get(prop1_disp)
                    prop2_uri = prop_lookup.get(prop2_disp)
                    if prop1_uri == prop2_uri:
                        show_message("Please select two different properties!", "error")
                    else:
                        ont.add_property_relation(prop1_uri, relation_type, prop2_uri)
                        save_checkpoint("Add property relation")
                        show_message(
                            f"Relation added: {prop1_disp} {relation_type} {prop2_disp}",
                            "success",
                        )
                        st.rerun()

    if _rel_tab == "Individual Relations":
        st.subheader("Add Individual Relation")

        if len(individuals) < 2:
            st.warning("Need at least 2 individuals to create relations.")
        else:
            with st.form("add_individual_relation_form"):
                ind_opts, ind_lookup = build_uri_options(individuals)
                col1, col2, col3 = st.columns(3)

                with col1:
                    ind1_disp = st.selectbox(
                        "Individual 1", options=ind_opts, key="irel_ind1"
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=["sameAs", "differentFrom"],
                        key="irel_type",
                    )
                with col3:
                    ind2_disp = st.selectbox(
                        "Individual 2", options=ind_opts, key="irel_ind2"
                    )

                st.caption("""
                - **sameAs**: Individual 1 and Individual 2 refer to the same entity
                - **differentFrom**: Individual 1 and Individual 2 are definitely different entities
                """)

                submitted = st.form_submit_button("Add Individual Relation")
                if submitted:
                    ind1_uri = ind_lookup.get(ind1_disp)
                    ind2_uri = ind_lookup.get(ind2_disp)
                    if ind1_uri == ind2_uri:
                        show_message(
                            "Please select two different individuals!", "error"
                        )
                    else:
                        ont.add_individual_relation(ind1_uri, relation_type, ind2_uri)
                        save_checkpoint("Add individual relation")
                        show_message(
                            f"Relation added: {ind1_disp} {relation_type} {ind2_disp}",
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

    # Build resources with labels for display: "Label (name)" format
    def format_resource(name, label, res_type):
        if label and label != name:
            return f"{label} ({name})"
        return name

    # Combine all resources with their labels
    all_resources = []
    for c in classes:
        display = format_resource(c["name"], c.get("label"), "Class")
        all_resources.append(
            {
                "name": c["name"],
                "label": c.get("label"),
                "type": "Class",
                "display": display,
            }
        )
    for p in object_props:
        display = format_resource(p["name"], p.get("label"), "Object Property")
        all_resources.append(
            {
                "name": p["name"],
                "label": p.get("label"),
                "type": "Object Property",
                "display": display,
            }
        )
    for p in data_props:
        display = format_resource(p["name"], p.get("label"), "Data Property")
        all_resources.append(
            {
                "name": p["name"],
                "label": p.get("label"),
                "type": "Data Property",
                "display": display,
            }
        )
    for i in individuals:
        display = format_resource(i["name"], i.get("label"), "Individual")
        all_resources.append(
            {
                "name": i["name"],
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
                filter_types = ["All"] + list(set(r["type"] for r in all_resources))
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
                    selected = st.selectbox(
                        "Select Resource",
                        options=[r["display"] for r in filtered_resources],
                        key="view_annotations_select",
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
                        for ann in annotations:
                            col1, col2, col3 = st.columns([2, 4, 1])
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
                                if st.button(
                                    "🗑️",
                                    key=f"del_ann_{resource_name}_{ann['predicate']}_{hash(ann['value'])}",
                                ):
                                    ont.delete_annotation(
                                        resource_name,
                                        ann.get("predicate_uri", ann["predicate"]),
                                        ann["value"],
                                        lang=ann.get("language"),
                                        datatype=ann.get("datatype"),
                                    )
                                    save_checkpoint("Delete annotation")
                                    show_message("Annotation deleted!", "success")
                                    st.rerun()

    if _ann_tab == "Add Annotation":
        st.subheader("Add Annotation")

        if not all_resources:
            st.warning("Please create at least one resource first.")
        else:
            # Get predicates used in the ontology
            used_predicates = ont.get_used_annotation_predicates()

            # Build predicate options: standard ones + used from ontology
            standard_predicates = [
                {"local_name": "label", "uri": "label", "prefix": "rdfs"},
                {"local_name": "comment", "uri": "comment", "prefix": "rdfs"},
                {"local_name": "seeAlso", "uri": "seeAlso", "prefix": "rdfs"},
                {"local_name": "isDefinedBy", "uri": "isDefinedBy", "prefix": "rdfs"},
                {"local_name": "prefLabel", "uri": "prefLabel", "prefix": "skos"},
                {"local_name": "altLabel", "uri": "altLabel", "prefix": "skos"},
                {"local_name": "definition", "uri": "definition", "prefix": "skos"},
                {"local_name": "example", "uri": "example", "prefix": "skos"},
                {"local_name": "note", "uri": "note", "prefix": "skos"},
                {"local_name": "title", "uri": "title", "prefix": "dcterms"},
                {
                    "local_name": "description",
                    "uri": "description",
                    "prefix": "dcterms",
                },
                {"local_name": "creator", "uri": "creator", "prefix": "dcterms"},
                {
                    "local_name": "contributor",
                    "uri": "contributor",
                    "prefix": "dcterms",
                },
                {"local_name": "date", "uri": "date", "prefix": "dcterms"},
                {"local_name": "deprecated", "uri": "deprecated", "prefix": "owl"},
            ]

            # Combine and deduplicate (used predicates take priority as they have full URIs)
            predicate_options = []
            predicate_lookup = {}  # display -> uri

            # Add used predicates first (from ontology)
            seen_names = set()
            for p in used_predicates:
                display = (
                    f"{p['prefix']}:{p['local_name']}"
                    if p["prefix"]
                    else p["local_name"]
                )
                if display not in seen_names:
                    predicate_options.append(display)
                    predicate_lookup[display] = p["uri"]
                    seen_names.add(display)
                    seen_names.add(p["local_name"])  # Also mark local name as seen

            # Add standard predicates that aren't already included
            for p in standard_predicates:
                display = f"{p['prefix']}:{p['local_name']}"
                if p["local_name"] not in seen_names and display not in seen_names:
                    predicate_options.append(display)
                    predicate_lookup[display] = p[
                        "uri"
                    ]  # Use short name for standard ones

            # Sort options
            predicate_options.sort(key=lambda x: x.lower())

            with st.form("add_annotation_form"):
                # Use display format with label
                resource_options = [
                    f"{r['display']} [{r['type']}]" for r in all_resources
                ]
                selected = st.selectbox("Select Resource", options=resource_options)

                predicate_display = st.selectbox(
                    "Annotation Type", options=predicate_options
                )

                value = st.text_area("Value")

                language = st.text_input(
                    "Language Tag (optional)", placeholder="en, de, fr..."
                )

                submitted = st.form_submit_button("Add Annotation")
                if submitted:
                    if not value:
                        show_message("Value is required!", "error")
                    else:
                        # Find the resource by matching the option string
                        idx = resource_options.index(selected)
                        resource_name = all_resources[idx]["name"]
                        predicate_uri = predicate_lookup.get(
                            predicate_display, predicate_display
                        )
                        ont.add_annotation(
                            resource_name,
                            predicate_uri,
                            value,
                            lang=language if language else None,
                        )
                        save_checkpoint("Add annotation")
                        show_message("Annotation added!", "success")
                        st.rerun()

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
                show_message(msg, "success" if not result["errors"] else "warning")
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
    scheme_names = [s["name"] for s in schemes]
    concept_names = [c["name"] for c in concepts]

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
                _scheme_expanded = st.session_state.get(
                    f"view_scheme_{scheme['name']}", False
                ) or st.session_state.get(f"edit_scheme_{scheme['name']}", False)
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
                            key=f"btn_view_scheme_{scheme['name']}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("scheme", scheme["name"]),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_scheme_{scheme['name']}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("scheme", scheme["name"]),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_scheme_{scheme['name']}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"scheme_{scheme['name']}",),
                        )

                    if st.session_state.get(f"view_scheme_{scheme['name']}", False):
                        st.divider()
                        st.write(f"**Name:** {scheme['name']}")
                        st.write(f"**Label:** {scheme['label'] or '—'}")
                        st.write(f"**Comment:** {scheme['comment'] or '—'}")
                        st.write(f"**Concepts:** {scheme['concept_count']}")

                    if confirm_delete(
                        scheme["name"], "concept", f"scheme_{scheme['name']}"
                    ):
                        ont.delete_concept_scheme(scheme["name"])
                        save_checkpoint("Delete concept scheme")
                        set_flash_message(
                            f"Scheme '{scheme['name']}' deleted!", "success"
                        )
                        st.rerun()

                    if st.session_state.get(f"edit_scheme_{scheme['name']}", False):
                        st.divider()
                        with st.form(f"edit_scheme_form_{scheme['name']}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=scheme["name"],
                                key=f"scheme_name_{scheme['name']}",
                                help="Renaming updates every reference, including "
                                "the inScheme links from its concepts — no "
                                "membership is lost.",
                            )
                            new_label = st.text_input(
                                "Label",
                                value=scheme["label"] or "",
                                key=f"scheme_lbl_{scheme['name']}",
                            )
                            new_comment = st.text_area(
                                "Comment",
                                value=scheme["comment"] or "",
                                key=f"scheme_cmt_{scheme['name']}",
                            )
                            if st.form_submit_button("Save Changes"):
                                renamed = bool(new_name and new_name != scheme["name"])
                                if renamed and not ont.rename_concept_scheme(
                                    scheme["name"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = new_name if renamed else scheme["name"]
                                    ont.update_concept_scheme(
                                        target,
                                        new_label=new_label,
                                        new_comment=new_comment,
                                    )
                                    save_checkpoint("Update concept scheme")
                                    st.session_state[
                                        f"edit_scheme_{scheme['name']}"
                                    ] = False
                                    st.session_state[f"view_scheme_{target}"] = True
                                    show_message(
                                        f"Scheme '{target}' updated!", "success"
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
                elif s_name in scheme_names:
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
                "Filter by Scheme", ["All"] + scheme_names, key="concept_filter_scheme"
            )
            filtered = (
                concepts
                if filter_scheme == "All"
                else ont.get_concepts(scheme=filter_scheme)
            )

            # Collapse other concepts when one is active
            def _concept_key(c):
                return str(abs(hash(c["uri"])))[:8]

            _active_concept = next(
                (
                    c
                    for c in filtered
                    if st.session_state.get(f"view_skos_{_concept_key(c)}", False)
                    or st.session_state.get(f"edit_skos_{_concept_key(c)}", False)
                ),
                None,
            )
            if _active_concept:
                _active_ck = _concept_key(_active_concept)
                for c in filtered:
                    ck = _concept_key(c)
                    if ck != _active_ck:
                        st.session_state.pop(f"view_skos_{ck}", None)
                        st.session_state.pop(f"edit_skos_{ck}", None)

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
                _sk = f"view_skos_{_ck}"
                _ek = f"edit_skos_{_ck}"

                _skos_expanded = st.session_state.get(
                    _sk, False
                ) or st.session_state.get(_ek, False)
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
                    if st.session_state.get(_sk, False):
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
                            other_concepts = [
                                c for c in concept_names if c != concept["name"]
                            ]
                            rel_target = st.selectbox(
                                "Target Concept",
                                other_concepts,
                                key=f"rel_target_{_ck}",
                            )
                            if st.button("Add", key=f"add_rel_{_ck}"):
                                ont.add_concept_relation(
                                    concept["name"], rel_type, rel_target
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

                    if confirm_delete(concept["name"], "concept", f"c_{_ck}"):
                        ont.delete_concept(concept["name"])
                        save_checkpoint("Delete concept")
                        set_flash_message(
                            f"Concept '{concept['name']}' deleted!", "success"
                        )
                        st.rerun()

                    # Inline edit form
                    if st.session_state.get(_ek, False):
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

                            # Broader concept
                            other_concepts = [
                                c for c in concept_names if c != concept["name"]
                            ]
                            current_broader = (
                                concept["broader"][0] if concept["broader"] else "None"
                            )
                            broader_options = ["None"] + other_concepts
                            broader_idx = (
                                broader_options.index(current_broader)
                                if current_broader in broader_options
                                else 0
                            )
                            new_broader = st.selectbox(
                                "Broader Concept",
                                broader_options,
                                index=broader_idx,
                                key=f"broader_{_ck}",
                            )

                            # Scheme
                            current_scheme = (
                                concept["schemes"][0]
                                if concept.get("schemes")
                                else "None"
                            )
                            scheme_options = ["None"] + scheme_names
                            scheme_idx = (
                                scheme_options.index(current_scheme)
                                if current_scheme in scheme_options
                                else 0
                            )
                            new_scheme = st.selectbox(
                                "Scheme",
                                scheme_options,
                                index=scheme_idx,
                                key=f"scheme_{_ck}",
                            )

                            if st.form_submit_button("Save Changes"):
                                # Rename first (updates all references) so the
                                # rest of the update targets the new name.
                                renamed = bool(new_name and new_name != concept["name"])
                                if renamed and not ont.rename_concept(
                                    concept["name"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = new_name if renamed else concept["name"]
                                    # Handle broader change
                                    broader_val = (
                                        new_broader if new_broader != "None" else ""
                                    )
                                    old_broader = (
                                        concept["broader"][0]
                                        if concept["broader"]
                                        else ""
                                    )
                                    broader_changed = broader_val != old_broader

                                    # Handle scheme change
                                    old_scheme = (
                                        concept["schemes"][0]
                                        if concept.get("schemes")
                                        else ""
                                    )
                                    new_scheme_val = (
                                        new_scheme if new_scheme != "None" else ""
                                    )
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

                                    _update_kwargs = dict(
                                        new_pref_label=new_pref,
                                        new_definition=new_def,
                                        add_scheme=add_s,
                                        remove_scheme=remove_s,
                                    )
                                    if broader_changed:
                                        _update_kwargs["new_broader"] = broader_val
                                    ont.update_concept(target, **_update_kwargs)
                                    save_checkpoint("Update concept")
                                    st.session_state[_ek] = False
                                    if renamed:
                                        _new_ck = str(
                                            abs(hash(str(ont._uri(new_name))))
                                        )[:8]
                                        st.session_state[f"view_skos_{_new_ck}"] = True
                                    else:
                                        st.session_state[_sk] = True
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
            c_scheme = st.selectbox(
                "Scheme", ["None"] + scheme_names, key="concept_scheme_select"
            )
            c_broader = st.selectbox(
                "Broader Concept",
                ["None"] + concept_names,
                key="concept_broader_select",
            )
            c_lang = st.text_input("Language Tag (e.g., en, de)", key="concept_lang")
            if st.form_submit_button("Add Concept"):
                if not c_name:
                    show_message("Concept name is required!", "error")
                elif c_name in concept_names:
                    show_message(f"Concept '{c_name}' already exists!", "error")
                else:
                    ont.add_concept(
                        c_name,
                        scheme=c_scheme if c_scheme != "None" else None,
                        pref_label=c_pref or None,
                        definition=c_def or None,
                        broader=c_broader if c_broader != "None" else None,
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
                "Scheme", ["All"] + scheme_names, key="hierarchy_scheme_select"
            )
            hierarchy = ont.get_concept_hierarchy(
                scheme=h_scheme if h_scheme != "All" else None
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

    # Display any flash messages from previous actions
    display_flash_message()

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
                st.session_state["_ontology_cleared"] = "Ontology cleared!"
                st.rerun()

        def _direct_import(content, format_):
            """Import directly without preview (for empty ontologies)."""
            try:
                ont.load_from_string(content, format=format_)
                st.session_state.ontology = ont
                save_checkpoint("Import ontology")
                set_flash_message(
                    f"Ontology imported successfully! ({len(ont.graph)} triples)",
                    "success",
                )
                # Clear file uploader by incrementing its key
                st.session_state["import_uploader_key"] = (
                    st.session_state.get("import_uploader_key", 0) + 1
                )
                st.rerun()
            except Exception as e:
                show_message(f"Error importing ontology: {str(e)}", "error")

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
                        except Exception as e:
                            show_message(f"Error parsing file: {str(e)}", "error")

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
                        except Exception as e:
                            show_message(f"Error parsing content: {str(e)}", "error")

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
                IMPORT_REPLACE,
                IMPORT_MERGE,
                IMPORT_MERGE_OVERWRITE,
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
                        st.session_state.import_preview = None
                        st.session_state.import_content = None
                        st.session_state.import_format = None
                        triples = len(ont.graph)
                        set_flash_message(
                            f"Ontology imported successfully! ({triples} triples)",
                            "success",
                        )
                        st.rerun()
                    except Exception as e:
                        show_message(f"Error applying import: {str(e)}", "error")
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
            st.download_button(
                "Download Change Report",
                data=report,
                file_name="change_report.md",
                mime="text/markdown",
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

        if st.button("Generate Export"):
            try:
                content = ont.export_to_string(format=format_)
                st.text_area("Exported Content", value=content, height=400)

                ext = file_extensions[format_]
                st.download_button(
                    label=f"Download .{ext} file",
                    data=content,
                    file_name=f"ontology.{ext}",
                    mime="text/plain",
                )
            except Exception as e:
                show_message(f"Error exporting ontology: {str(e)}", "error")

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
                    show_message("New ontology created!", "success")
                    st.rerun()

    if _ie_tab == "Templates":
        from .templates import get_template_names, get_template, render_template

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
        selected_template = st.selectbox(
            "Select Template", template_names, key="template_select"
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
            get_upper_ontology_names,
            get_upper_ontology,
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
                s = ont.get_statistics()
                st.session_state["_upper_onto_msg"] = (
                    f"Loaded {upper['name']} ({mod_names})! "
                    f"— {s['classes']} classes, {s['object_properties']} obj props, "
                    f"{s['data_properties']} data props, {s['content_triples']} triples"
                )
            except Exception as e:
                st.session_state["_upper_onto_err"] = (
                    f"Error loading upper ontology: {str(e)}"
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
        selected_upper = st.selectbox(
            "Select Upper Ontology", upper_names, key="upper_ontology_select"
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
            get_reference_ontology_names,
            get_reference_ontology,
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
                s = ont.get_statistics()
                st.session_state["_ref_onto_msg"] = (
                    f"Loaded {ref['name']} ({mod_names})! "
                    f"— {s['classes']} classes, {s['object_properties']} obj props, "
                    f"{s['data_properties']} data props, {s['content_triples']} triples"
                )
            except Exception as e:
                st.session_state["_ref_onto_err"] = (
                    f"Error loading reference ontology: {str(e)}"
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
        selected_ref = st.selectbox(
            "Select Reference Ontology", ref_names, key="reference_ontology_select"
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
                target_class = st.selectbox(
                    "Target Class",
                    options=class_names,
                    help="The class to define with this expression",
                )

                expr_type = st.selectbox(
                    "Expression Type",
                    options=["unionOf", "intersectionOf", "complementOf", "oneOf"],
                )

                st.write("**Select members:**")
                if expr_type == "complementOf":
                    complement_class = st.selectbox(
                        "Complement of Class", options=class_names
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
                    if expr_type == "oneOf" and selected_individuals:
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
                result_prop = st.selectbox(
                    "Result Property",
                    options=obj_prop_names,
                    help="The property that results from following the chain",
                )

                chain_props = st.multiselect(
                    "Chain Properties (in order)",
                    options=obj_prop_names,
                    help="Select properties in the order they should be followed",
                )

                submitted = st.form_submit_button("Add Property Chain")
                if submitted:
                    if len(chain_props) < 2:
                        show_message("Chain must have at least 2 properties!", "error")
                    else:
                        ont.add_property_chain(result_prop, chain_props)
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
                parent_class = st.selectbox(
                    "Parent Class",
                    options=class_names,
                    help="The class that is the disjoint union",
                )

                member_classes = st.multiselect(
                    "Member Classes",
                    options=class_names,
                    help="Classes that make up the disjoint union",
                )

                submitted = st.form_submit_button("Add Disjoint Union")
                if submitted:
                    if len(member_classes) < 2:
                        show_message("Need at least 2 member classes!", "error")
                    elif parent_class in member_classes:
                        show_message("Parent class cannot be a member!", "error")
                    else:
                        ont.add_disjoint_union(parent_class, member_classes)
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
                target_class = st.selectbox("Class", options=class_names)

                key_props = st.multiselect(
                    "Key Properties",
                    options=all_prop_names,
                    help="Properties that together uniquely identify instances",
                )

                submitted = st.form_submit_button("Add hasKey")
                if submitted:
                    if not key_props:
                        show_message("Select at least 1 property!", "error")
                    else:
                        ont.add_has_key(target_class, key_props)
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
                show_message(
                    f"Reasoning complete! {new_triples} new triples inferred.",
                    "success",
                )
                st.write(f"New triple count: {len(ont.graph)}")
            except Exception as e:
                show_message(f"Error during reasoning: {str(e)}", "error")


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

    _viz_tab = st.segmented_control(
        "Section",
        ["Interactive Graph", "Class Hierarchy", "Statistics"],
        default="Interactive Graph",
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
            "maximize": False,
            "highlight_issues": False,
            "focus_mode": False,
            "focus_depth": 1,
        }
        for _k, _v in _viz_cfg.items():
            cfg_key = f"_viz_cfg_{_k}"
            wid_key = f"viz_{_k}"
            if cfg_key not in st.session_state:
                st.session_state[cfg_key] = _v
            # Restore widget key from persisted config
            st.session_state[wid_key] = st.session_state[cfg_key]

        def _viz_sync(cfg_key, wid_key):
            """Callback to persist widget value when changed."""
            st.session_state[cfg_key] = st.session_state[wid_key]

        def _viz_focus_toggle():
            """Persist the focus toggle and, when it turns on, seed the focus
            nodes from the classes selected in the multiselect — so the
            neighbourhood grows from exactly what the user had picked (one class
            or several). An empty selection falls back to the first node."""
            on = st.session_state["viz_focus_mode"]
            st.session_state["_viz_cfg_focus_mode"] = on
            if on:
                sel = st.session_state.get("_viz_cfg_selected_classes") or []
                st.session_state["_viz_cfg_focus_seeds"] = [f"Class: {c}" for c in sel]

        _cols = (
            st.columns([1, 1, 1, 1, 1, 1, 1, 1])
            if _has_skos
            else st.columns([1, 1, 1, 1, 1, 1, 1])
        )
        with _cols[0]:
            show_classes = st.checkbox(
                "Classes",
                key="viz_show_classes",
                on_change=_viz_sync,
                args=("_viz_cfg_show_classes", "viz_show_classes"),
            )
        with _cols[1]:
            show_properties = st.checkbox(
                "Obj Props",
                key="viz_show_obj_props",
                on_change=_viz_sync,
                args=("_viz_cfg_show_obj_props", "viz_show_obj_props"),
            )
        with _cols[2]:
            show_data_props = st.checkbox(
                "Data Props",
                key="viz_show_data_props",
                on_change=_viz_sync,
                args=("_viz_cfg_show_data_props", "viz_show_data_props"),
            )
        with _cols[3]:
            show_annotations = st.checkbox(
                "Annotations",
                key="viz_show_annotations",
                on_change=_viz_sync,
                args=("_viz_cfg_show_annotations", "viz_show_annotations"),
            )
        with _cols[4]:
            show_individuals = st.checkbox(
                "Individuals",
                key="viz_show_individuals",
                on_change=_viz_sync,
                args=("_viz_cfg_show_individuals", "viz_show_individuals"),
            )
        if _has_skos:
            with _cols[5]:
                show_skos = st.checkbox(
                    "SKOS",
                    key="viz_show_skos",
                    on_change=_viz_sync,
                    args=("_viz_cfg_show_skos", "viz_show_skos"),
                )
            with _cols[6]:
                show_ind_edges = st.checkbox(
                    "Ind. Edges",
                    key="viz_show_ind_edges",
                    on_change=_viz_sync,
                    args=("_viz_cfg_show_ind_edges", "viz_show_ind_edges"),
                    help="Show property edges between individuals",
                )
            with _cols[7]:
                show_triples = st.checkbox(
                    "Triples",
                    key="viz_show_triples",
                    on_change=_viz_sync,
                    args=("_viz_cfg_show_triples", "viz_show_triples"),
                    help="Show all RDF triples for visible nodes",
                )
        else:
            show_skos = False
            with _cols[5]:
                show_ind_edges = st.checkbox(
                    "Ind. Edges",
                    key="viz_show_ind_edges",
                    on_change=_viz_sync,
                    args=("_viz_cfg_show_ind_edges", "viz_show_ind_edges"),
                    help="Show property edges between individuals",
                )
            with _cols[6]:
                show_triples = st.checkbox(
                    "Triples",
                    key="viz_show_triples",
                    on_change=_viz_sync,
                    args=("_viz_cfg_show_triples", "viz_show_triples"),
                    help="Show all RDF triples for visible nodes",
                )

        # Row 2: sliders + maximize + highlight issues + render button
        col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
        with col1:
            height = st.slider(
                "Graph Height",
                300,
                1200,
                step=10,
                key="viz_graph_height",
                on_change=_viz_sync,
                args=("_viz_cfg_graph_height", "viz_graph_height"),
            )
        with col2:
            node_spacing = st.slider(
                "Node Spacing",
                50,
                300,
                help="Distance between nodes. Increase for less overlap.",
                key="viz_node_spacing",
                on_change=_viz_sync,
                args=("_viz_cfg_node_spacing", "viz_node_spacing"),
            )
        with col3:
            maximize = st.checkbox(
                "Maximize",
                help="Expand graph to full height",
                key="viz_maximize",
                on_change=_viz_sync,
                args=("_viz_cfg_maximize", "viz_maximize"),
            )
            if maximize:
                height = 1200
        with col4:
            highlight_issues = st.checkbox(
                "Highlight Issues",
                key="viz_highlight_issues",
                on_change=_viz_sync,
                args=("_viz_cfg_highlight_issues", "viz_highlight_issues"),
            )
        with col5:
            render_graph = st.button("Render", type="primary", use_container_width=True)

        validation_subjects = set()
        if highlight_issues:
            issues = ont.validate()
            validation_subjects = {i["subject"] for i in issues}

        # Class filter — reset to "all selected" whenever the ontology mutates
        # (load, import, replace, undo) so a previously narrowed filter doesn't
        # silently hide most of the newly loaded content.
        all_class_names = [c["name"] for c in classes] if classes else []
        all_class_set = set(all_class_names)
        current_mutation = st.session_state.get("_ont_mutation_count", 0)
        last_seen_mutation = st.session_state.get("_viz_cfg_classes_at_mutation")
        if (
            "_viz_cfg_selected_classes" not in st.session_state
            or last_seen_mutation != current_mutation
        ):
            st.session_state["_viz_cfg_selected_classes"] = all_class_names
            st.session_state["_viz_cfg_classes_at_mutation"] = current_mutation
        else:
            # Drop names that no longer exist, but keep an intentionally empty
            # selection empty — repopulating here would make "Clear all" (the
            # multiselect's ✕) snap straight back to every class. The mutation
            # branch above is what resets to "all" when the ontology changes.
            st.session_state["_viz_cfg_selected_classes"] = [
                c
                for c in st.session_state["_viz_cfg_selected_classes"]
                if c in all_class_set
            ]
        st.session_state["viz_selected_classes"] = st.session_state[
            "_viz_cfg_selected_classes"
        ]

        # Focus mode: centre the view on one node (class, individual or SKOS
        # concept) and show only its neighbourhood within N hops. The pruning
        # runs after the full graph is built (see below), so "depth" counts real
        # links of every type — not just subclass chains. Seed options are keyed
        # to the same node ids the graph builder assigns.
        focus_targets: dict[str, str] = {}
        if show_classes:
            for c in classes:
                focus_targets[f"Class: {c['name']}"] = _uid(c["uri"])
        if show_individuals:
            for ind in individuals:
                focus_targets[f"Individual: {ind['name']}"] = f"ind_{_uid(ind['uri'])}"
        if show_skos and _has_skos:
            for concept in ont.get_concepts():
                focus_targets[f"Concept: {concept['name']}"] = f"skos_{concept['name']}"

        focus_seed_ids: list = []
        focus_depth = 0
        with st.expander("Filter Classes", expanded=False):
            focus_mode = st.checkbox(
                "Focus on one node",
                key="viz_focus_mode",
                on_change=_viz_focus_toggle,
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
                # user had picked (one class or several).
                saved_seeds = st.session_state.get("_viz_cfg_focus_seeds")
                if saved_seeds is None:
                    saved_seeds = [
                        f"Class: {c}"
                        for c in (
                            st.session_state.get("_viz_cfg_selected_classes") or []
                        )
                        if f"Class: {c}" in label_set
                    ]
                saved_seeds = [s for s in saved_seeds if s in label_set]
                if not saved_seeds:
                    saved_seeds = [focus_labels[0]]
                st.session_state["_viz_cfg_focus_seeds"] = saved_seeds
                st.session_state["viz_focus_seeds"] = saved_seeds
                fcol1, fcol2 = st.columns([3, 1])
                with fcol1:
                    focus_seeds = st.multiselect(
                        "Focus node(s)",
                        options=focus_labels,
                        key="viz_focus_seeds",
                        on_change=_viz_sync,
                        args=("_viz_cfg_focus_seeds", "viz_focus_seeds"),
                        help="Classes, individuals or SKOS concepts to centre on. "
                        "The neighbourhood grows from all of them. Toggle the "
                        "entity-type checkboxes above to list more.",
                    )
                with fcol2:
                    focus_depth = st.slider(
                        "Depth (hops)",
                        1,
                        5,
                        key="viz_focus_depth",
                        on_change=_viz_sync,
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
                selected_classes = st.multiselect(
                    "Select classes to display",
                    options=all_class_names,
                    help="Choose which classes to show in the graph",
                    key="viz_selected_classes",
                    on_change=_viz_sync,
                    args=("_viz_cfg_selected_classes", "viz_selected_classes"),
                )

        # Store graph settings in session state for caching
        selected_classes_key = (
            "_".join(sorted(selected_classes)) if selected_classes else "none"
        )
        _graph_ver = 15  # Bump to invalidate cached graph data after code changes
        # Include a mutation counter that bumps on every checkpoint / undo / redo,
        # so any change to the ontology — even one that preserves triple count —
        # invalidates the cached graph data and the iframe re-renders.
        ont_mutation = st.session_state.get("_ont_mutation_count", 0)
        graph_key = f"v{_graph_ver}_m{ont_mutation}_{show_classes}_{show_properties}_{show_data_props}_{show_annotations}_{show_individuals}_{show_ind_edges}_{show_skos}_{show_triples}_{height}_{node_spacing}_{highlight_issues}_{hash(selected_classes_key)}_{focus_mode}_{'-'.join(sorted(focus_seed_ids))}_{focus_depth}"
        if "last_graph_key" not in st.session_state:
            st.session_state.last_graph_key = None
            st.session_state.last_graph_data = None
        if "viz_render_seq" not in st.session_state:
            st.session_state.viz_render_seq = 0

        # Bump sequence on Render click to force component re-init (re-runs layout)
        if render_graph:
            st.session_state.viz_render_seq += 1

        # Rebuild graph data when settings change or on first visit
        needs_rebuild = (
            st.session_state.last_graph_key != graph_key
            or st.session_state.last_graph_data is None
        )

        if needs_rebuild:
            # Build the graph using lightweight dicts (no pyvis overhead)
            status = st.empty()
            status.info("Building graph...")

            class _GraphBuilder:
                """Minimal replacement for pyvis.Network — just collects nodes/edges."""

                __slots__ = ("nodes", "edges", "_node_ids", "options")

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

            # Limit total nodes to prevent browser hanging
            max_nodes = 500
            node_count = 0

            # Build sets for node existence checks (URI-keyed for cross-namespace safety)
            cls_collisions = _build_name_collision_set(classes)
            selected_class_names = set(selected_classes) if selected_classes else set()
            displayed_class_uris: set = set()

            # Add classes as nodes (only selected classes)
            if show_classes and selected_classes:
                for cls in classes:
                    if node_count >= max_nodes:
                        break
                    if cls["name"] not in selected_class_names:
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

            # Add data properties (connected to displayed classes, or standalone if no domain)
            if show_data_props and data_props and node_count < max_nodes:
                for prop in data_props:
                    if node_count >= max_nodes:
                        break
                    # Skip if domain is set but the class node isn't displayed
                    dom_uri = prop.get("domain_uri", "")
                    if dom_uri and show_classes and dom_uri not in displayed_class_uris:
                        continue

                    prop_node_id = f"dprop_{_uid(prop['uri'])}"
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
            if show_individuals and individuals and node_count < max_nodes:
                for ind in individuals:
                    if node_count >= max_nodes:
                        break
                    ind_node_id = f"ind_{_uid(ind['uri'])}"
                    label = ind["label"] if ind["label"] else ind["name"]
                    title = f"Individual: {ind['name']}"
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

                # Add edges between individuals (object property assertions)
                if show_ind_edges:
                    ind_uri_by_name: dict[str, str] = {
                        ind["name"]: ind["uri"] for ind in individuals
                    }
                    for ind in individuals:
                        for prop in ind.get("properties", []):
                            target_uri = ind_uri_by_name.get(prop["value"])
                            if target_uri:
                                net.add_edge(
                                    f"ind_{_uid(ind['uri'])}",
                                    f"ind_{_uid(target_uri)}",
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
                        if rel["relation"] == "equivalentClass":
                            net.add_edge(
                                subj_node,
                                obj_node,
                                label="equivalentClass",
                                title=f"Equivalent classes:\n{rel['subject']} and {rel['object']} represent the same concept",
                                color="#9C27B0",
                                arrows="to",
                            )
                        elif rel["relation"] == "disjointWith":
                            net.add_edge(
                                subj_node,
                                obj_node,
                                label="disjointWith",
                                title=f"Disjoint classes:\n{rel['subject']} and {rel['object']} cannot share instances",
                                color="#F44336",
                                arrows="to",
                            )

            # Add annotations for classes and individuals
            if show_annotations and node_count < max_nodes:
                annotation_counter = 0
                # Annotations for classes
                if show_classes and classes:
                    for cls in classes:
                        if node_count >= max_nodes:
                            break
                        try:
                            annotations = ont.get_annotations(cls["name"])
                            for ann in annotations:
                                if node_count >= max_nodes:
                                    break
                                # Skip label and comment as they're already shown in tooltip
                                if ann["predicate"] in ["label", "comment"]:
                                    continue
                                annotation_counter += 1
                                ann_id = f"ann_{annotation_counter}"
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
                                )
                                node_count += 1
                                net.add_edge(
                                    cls["name"],
                                    ann_id,
                                    title=f"Annotation: {pred_display}",
                                    color="#A1887F",
                                    arrows="to",
                                    dashes=True,
                                )
                        except Exception:
                            pass  # Skip problematic annotations

                # Annotations for individuals
                if show_individuals and individuals:
                    for ind in individuals:
                        if node_count >= max_nodes:
                            break
                        try:
                            annotations = ont.get_annotations(ind["name"])
                            for ann in annotations:
                                if node_count >= max_nodes:
                                    break
                                if ann["predicate"] in ["label", "comment"]:
                                    continue
                                annotation_counter += 1
                                ann_id = f"ann_{annotation_counter}"
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
                                )
                                node_count += 1
                                net.add_edge(
                                    f"ind_{ind['name']}",
                                    ann_id,
                                    title=f"Annotation: {pred_display}",
                                    color="#A1887F",
                                    arrows="to",
                                    dashes=True,
                                )
                        except Exception:
                            pass  # Skip problematic annotations

            # Add SKOS concepts and relations
            if show_skos and node_count < max_nodes:
                concepts = ont.get_concepts()
                skos_node_ids = set()
                for concept in concepts:
                    if node_count >= max_nodes:
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
                from rdflib import URIRef as _URIRef, Literal as _Literal

                # Build URI → node_id mapping from all visible nodes
                _uri_to_node = {}
                if show_classes and selected_classes:
                    for cls in classes:
                        if cls["name"] in selected_classes:
                            _uri_to_node[cls["uri"]] = cls["name"]
                if show_individuals and individuals:
                    for ind in individuals:
                        _uri_to_node[ind["uri"]] = f"ind_{ind['name']}"
                if show_skos:
                    for concept in ont.get_concepts():
                        if concept.get("uri"):
                            _uri_to_node[concept["uri"]] = f"skos_{concept['name']}"

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

            # Focus mode: keep only the seed nodes' neighbourhood within
            # focus_depth hops over the assembled edges (BFS over all node
            # types, so depth counts real graph links rather than class hops).
            # Several seeds grow the neighbourhood from all of them at once.
            if focus_mode and focus_seed_ids:
                present_ids = {n["id"] for n in net.nodes}
                seeds = {sid for sid in focus_seed_ids if sid in present_ids}
                if seeds:
                    adj: dict = {}
                    for edge in net.edges:
                        adj.setdefault(edge["from"], set()).add(edge["to"])
                        adj.setdefault(edge["to"], set()).add(edge["from"])
                    keep = set(seeds)
                    frontier = set(seeds)
                    for _ in range(focus_depth):
                        nxt = set()
                        for nid in frontier:
                            nxt |= adj.get(nid, set()) - keep
                        if not nxt:
                            break
                        keep |= nxt
                        frontier = nxt
                    net.nodes = [n for n in net.nodes if n["id"] in keep]
                    net.edges = [
                        e for e in net.edges if e["from"] in keep and e["to"] in keep
                    ]
                else:
                    # No seed was built (e.g. beyond the node cap) — show nothing
                    # rather than the whole graph, which would be misleading.
                    net.nodes = []
                    net.edges = []

            # Spread parallel edges so they don't overlap
            from collections import defaultdict as _defaultdict

            _edge_groups = _defaultdict(list)
            for edge in net.edges:
                key = tuple(sorted((edge["from"], edge["to"])))
                _edge_groups[key].append(edge)
            for group in _edge_groups.values():
                if len(group) < 2:
                    continue
                for i, edge in enumerate(group):
                    if i == 0:
                        edge["smooth"] = {
                            "enabled": True,
                            "type": "curvedCW",
                            "roundness": 0.2,
                        }
                    elif i % 2 == 1:
                        edge["smooth"] = {
                            "enabled": True,
                            "type": "curvedCCW",
                            "roundness": 0.2 * ((i + 1) // 2),
                        }
                    else:
                        edge["smooth"] = {
                            "enabled": True,
                            "type": "curvedCW",
                            "roundness": 0.2 * ((i + 1) // 2),
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
                }
                # Bump seq so the iframe component re-initialises with the new data
                st.session_state.viz_render_seq += 1
                status.empty()

            except Exception as e:
                status.empty()
                st.error(f"Error building graph: {str(e)}")

        # Always display the graph component (even on rerun after selection)
        gdata = st.session_state.get("last_graph_data")
        if gdata:
            import os as _os

            _component_path = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "lib", "graph_viewer"
            )
            _graph_component = st.components.v1.declare_component(
                "graph_viewer", path=_component_path
            )

            selection = _graph_component(
                nodes=gdata["nodes"],
                edges=gdata["edges"],
                options=gdata["options"],
                height=height,
                seq=st.session_state.viz_render_seq,
                key="graph_viewer",
                default=None,
            )

            # Status bar outside iframe — dark styled
            _type_to_page = {
                "Class": "Classes",
                "Object Property": "Properties",
                "Data Property": "Properties",
                "Individual": "Individuals",
                "SKOS Concept": "SKOS Vocabulary",
            }
            _view_key_map = {
                "Class": lambda n: f"view_class_{n}",
                "Object Property": lambda n: f"view_objprop_{n}",
                "Data Property": lambda n: f"view_dataprop_{n}",
                "Individual": lambda n: f"view_ind_{n}",
                "SKOS Concept": lambda n: f"view_skos_{str(abs(hash(n)))[:8]}",
            }

            # Status bar with View button
            has_selection = (
                selection and isinstance(selection, dict) and selection.get("selected")
            )
            ntype = selection.get("ntype") if has_selection else None
            ename = selection.get("ename") if has_selection else None
            show_view = has_selection and ntype and ename and ntype in _type_to_page

            if has_selection:
                title_text = (selection.get("title") or "").replace("\n", " | ")
                prefix = "Edge: " if selection.get("isEdge") else ""
                sel_html = f"<b>{prefix}{selection.get('label', '')}</b> — {title_text}"
            else:
                sel_html = "Click a node or edge to see details"

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
                col_info, col_btn = st.columns([20, 1])
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
                    if st.button(
                        "View", key="graph_view_btn", use_container_width=True
                    ):
                        page = _type_to_page[ntype]
                        vk = _view_key_map[ntype](ename)
                        st.session_state.search_navigate_to = page
                        st.session_state[vk] = True
                        if ntype == "SKOS Concept":
                            st.session_state["_skos_navigate_to_concept"] = True
                        st.rerun()
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
            # Build hierarchy text
            def build_tree_text(classes):
                roots = [c for c in classes if not c["parents"]]
                if not roots:
                    roots = classes[:1]

                lines = []

                def add_class(cls_name, level=0):
                    cls = next((c for c in classes if c["name"] == cls_name), None)
                    if cls:
                        prefix = "  " * level + ("└── " if level > 0 else "")
                        label = f" ({cls['label']})" if cls["label"] else ""
                        lines.append(f"{prefix}{cls['name']}{label}")
                        for child in cls["children"]:
                            add_class(child, level + 1)

                for root in roots:
                    add_class(root["name"])

                return "\n".join(lines)

            tree_text = build_tree_text(classes)
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
    except Exception as e:
        st.error(f"Error serializing ontology: {e}")


def main():
    """Main application entry point."""
    _configure_page()
    init_session_state()
    maybe_restore_autosave()

    # Sidebar navigation — asset path resolved relative to this module so it
    # works under both `streamlit run` and `pip install` deployments.
    _logo_path = _Path(__file__).parent / "assets" / "ORIONBELT_Logo.png"
    st.sidebar.image(str(_logo_path), width=200)
    st.sidebar.markdown("# Ontology Builder")
    st.sidebar.markdown("\u00a9 2025 [RALFORION d.o.o.](https://ralforion.com)")
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
        _type_to_page = {
            "Class": "Classes",
            "Object Property": "Properties",
            "Data Property": "Properties",
            "Individual": "Individuals",
            "SKOS Concept": "SKOS Vocabulary",
        }
        _view_key_map = {
            "Class": f"view_class_{_gv_name}",
            "Object Property": f"view_objprop_{_gv_name}",
            "Data Property": f"view_dataprop_{_gv_name}",
            "Individual": f"view_ind_{_gv_name}",
            "SKOS Concept": f"view_skos_{str(abs(hash(_gv_name)))[:8]}",
        }
        _nav_page = _type_to_page.get(_gv_type)
        if _nav_page:
            st.session_state.search_navigate_to = _nav_page
            _vk = _view_key_map.get(_gv_type)
            if _vk:
                st.session_state[_vk] = True
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
    selection = st.sidebar.radio("Navigation", list(pages.keys()), key="nav_radio")

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
                for r in items:
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
                        f"{r['name']}{label_str}",
                        key=f"search_{type_label}_{r_uid}",
                        use_container_width=True,
                    ):
                        st.session_state.search_navigate_to = page
                        # Open the view pane keyed by URI hash so we navigate
                        # to the *exact* resource, not whichever shares the
                        # same local name.
                        view_key_map = {
                            "Class": f"view_class_{r_uid}",
                            "Object Property": f"view_objprop_{r_uid}",
                            "Data Property": f"view_dataprop_{r_uid}",
                            "Individual": f"view_ind_{r_uid}",
                            "SKOS Concept": f"view_skos_{str(abs(hash(r_uri)))[:8]}",
                        }
                        view_key = view_key_map.get(type_label)
                        if view_key:
                            st.session_state[view_key] = True
                        st.rerun()
        else:
            st.sidebar.caption("No results found.")

    st.sidebar.divider()

    # Quick stats in sidebar
    stats = st.session_state.ontology.get_statistics()
    st.sidebar.caption("Quick Stats")
    st.sidebar.write(f"📦 Classes: {stats['classes']}")
    st.sidebar.write(f"🔗 Object Props: {stats['object_properties']}")
    st.sidebar.write(f"📝 Data Props: {stats['data_properties']}")
    st.sidebar.write(f"👤 Individuals: {stats['individuals']}")
    if stats.get("concepts", 0) > 0:
        st.sidebar.write(f"🏷️ SKOS Concepts: {stats['concepts']}")
    st.sidebar.write(f"📊 Triples: {stats['content_triples']}")

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

    # Render selected page
    try:
        pages[selection]()
    except Exception as e:
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

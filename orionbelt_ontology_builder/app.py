"""
OrionBelt Ontology Builder - A Streamlit application for building, editing,
and managing OWL ontologies.
"""

import hashlib
import json
import logging
import re
import time
import traceback
from datetime import datetime
from pathlib import Path as _Path

import streamlit as st

from . import local_store

APP_NAME = "OrionBelt Ontology Builder"
APP_VERSION = "1.18.0"

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

# Visualization display preferences persisted across sessions (issue #142), so a
# user's Fit-to-window / entity-type / spacing etc. choices survive a reload.
# Stored in the same backends as the ontology autosave (browser localStorage on
# the cloud, config.json on desktop). Only ontology-INDEPENDENT settings belong
# here; the node filters and focus seeds reference entity names, so they are
# saved per linked file instead (see VIZ_FILE_STATE_KEY, issue #164).
VIZ_SETTINGS_KEY = "orionbelt_viz_settings"
_VIZ_PERSIST_KEYS = (
    "show_classes",
    "show_obj_props",
    "show_data_props",
    "show_annotations",
    "show_individuals",
    "show_skos",
    "show_ind_edges",
    "show_triples",
    "graph_height",
    "node_spacing",
    "fit",
    "highlight_issues",
    "details_panel",
    "focus_mode",
    "focus_depth",
)
# Clamp restored integer settings so a stale/tampered value can't crash a slider
# whose value must lie within its min/max.
_VIZ_INT_RANGES = {
    "graph_height": (300, 1200),
    "node_spacing": (50, 300),
    "focus_depth": (1, 5),
}
# Per-linked-file Visualization state (issue #164). The node filters and focus
# seeds name specific entities, which is why #142 left them out of the settings
# above: restoring "Class: Person" into a different ontology is meaningless. The
# desktop app's linked working file removes that objection, since it identifies
# the ontology and its path already lives in config.json. So this state is saved
# per linked path and only restored while that same file is still linked; a
# cloud session has no linked file and keeps resetting per session.
VIZ_FILE_STATE_KEY = "viz_file_state"
# Bound config.json's growth. Dicts keep insertion order, so the entry rewritten
# longest ago is the one evicted.
VIZ_FILE_STATE_MAX_FILES = 20
# Disk autosave (local/desktop) is gated on the mutation counter and debounced:
# the graph is only serialized when it actually changed and edits have settled,
# so normal UI reruns do no work even for large ontologies. Important actions
# (import, new ontology, linking a file) force an immediate flush.
AUTOSAVE_DEBOUNCE_SECONDS = 2.0

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

# Streamlit's built-in Light/Dark theme presets (the "⋮ → Settings → Theme"
# menu) replace the whole theme — including primaryColor — with Streamlit's
# default red, ignoring the configured brand colour. So we force the brand
# primary onto the key controls with CSS, applied in every theme. Scoped to
# stable data-testid / data-baseweb hooks (and :has(input:checked) for the
# checked state) so unchecked controls are untouched.
# NOTE: this targets Streamlit's internal DOM; re-verify on a Streamlit bump
# (the version is pinned in pyproject.toml for exactly this reason).
_BRAND = local_store.BRAND_PRIMARY_COLOR  # "#0D2B7A"
_BRAND_TINT = "rgba(13, 43, 122, 0.12)"
_BRAND_CSS = f"""
<style>
    /* Primary buttons */
    [data-testid="stBaseButton-primary"] {{
        background-color: {_BRAND} !important;
        border-color: {_BRAND} !important;
    }}
    /* Checked checkbox box */
    [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > span {{
        background-color: {_BRAND} !important;
        border-color: {_BRAND} !important;
    }}
    /* Selected radio (its control circle; not the label wrapper) */
    [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) > div:first-child {{
        background-color: {_BRAND} !important;
        border-color: {_BRAND} !important;
    }}
    /* Active segmented-control pill and tab */
    [data-testid="stBaseButton-segmented_controlActive"] {{
        color: {_BRAND} !important;
        border-color: {_BRAND} !important;
        background-color: {_BRAND_TINT} !important;
    }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        color: {_BRAND} !important;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{
        background-color: {_BRAND} !important;
    }}
    /* Slider thumb + its floating value label */
    [data-testid="stSlider"] [role="slider"] {{
        background-color: {_BRAND} !important;
    }}
    [data-testid="stSliderThumbValue"] {{
        color: {_BRAND} !important;
    }}
    /* Slider track: the filled portion's colour (red on a reset theme) is baked
       into a per-value class we can't recolour selectively, so neutralise the
       whole bar to Streamlit's unfilled tint — no red shows, and the navy thumb
       marks the position. Targets the track (the thumb's direct parent). */
    [data-testid="stSlider"] [data-baseweb="slider"] div:has(> [role="slider"]) {{
        background: rgba(151, 166, 195, 0.25) !important;
    }}
    /* Multiselect selected chips and their focus outline */
    [data-testid="stMultiSelect"] [data-baseweb="tag"] {{
        background-color: {_BRAND} !important;
    }}
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within {{
        border-color: {_BRAND} !important;
    }}
</style>
"""

# The brand navy is fine as a filled button/checkbox/radio but too dark as the
# *text/indicator* colour on the selected tab and pill against a dark backdrop.
# Injected only in dark mode, after _BRAND_CSS, so it wins for those accents.
_DARK_ACCENT = "#6EA8FE"
_DARK_TINT = "rgba(110, 168, 254, 0.15)"
_DARK_CSS = f"""
<style>
    [data-testid="stBaseButton-segmented_controlActive"] {{
        color: {_DARK_ACCENT} !important;
        border-color: {_DARK_ACCENT} !important;
        background-color: {_DARK_TINT} !important;
    }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        color: {_DARK_ACCENT} !important;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{
        background-color: {_DARK_ACCENT} !important;
    }}
    /* Text/indicator accents from _BRAND_CSS that are too dark on a dark
       backdrop: the slider value label and the multiselect focus outline.
       (The filled thumb and chips stay navy, like the checkboxes/buttons.) */
    [data-testid="stSliderThumbValue"] {{
        color: {_DARK_ACCENT} !important;
    }}
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within {{
        border-color: {_DARK_ACCENT} !important;
    }}
</style>
"""


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


def get_ontology_manager_class():
    """Lazy load the OntologyManager class.

    Not cached with ``st.cache_resource``: that would pin the class object
    captured at first import for the life of the server process. Streamlit
    Community Cloud reruns the script on a git push without always restarting
    the process, so a cached class survived across deploys and new instances
    were built from the *old* class definition, missing methods added in the
    new code (e.g. ``get_creatable_namespaces``) and raising ``AttributeError``
    until the app was rebooted. The import below is already cached by Python's
    module system, so re-importing each call is cheap and always current.
    """
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
    # Landing on Import/Export for a fresh empty session is handled at the
    # navigation radio via its `index` (see main), not by pre-setting the
    # widget's session_state value here: a pre-set value left the radio
    # highlighting Dashboard while the page showed Import/Export and swallowed
    # the first nav click.


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
        # Optional dependency; failure mode depends on browser/runtime.
        except Exception as e:  # noqa: BLE001  # pragma: no cover
            logger.warning(f"localStorage autosave unavailable: {e}")
            st.session_state["_local_storage"] = None
    ls = st.session_state["_local_storage"]
    if ls is not None:
        latest = st.session_state.get(getattr(ls, "storedKey", None))
        if isinstance(latest, dict):
            ls.storedItems = latest
    return ls


def _rdf_format_for_path(path):
    """rdflib format for a file path (Turtle if the extension is unknown)."""
    from .ontology_manager import rdf_format_for_path

    return rdf_format_for_path(path)


def _disk_restore_source():
    """Return ``(path, label)`` to restore from on a local run, else ``(None, None)``.

    Prefers the user's linked working file; falls back to the crash-recovery
    snapshot written by :func:`persist_autosave`.
    """
    linked = local_store.get_linked_path()
    if linked is not None and linked.exists():
        return linked, "linked file"
    rec = local_store.recovery_file()
    if rec.exists():
        return rec, "recovery file"
    return None, None


def _block_disk_persist(message: str) -> None:
    """Stop disk autosave for the session and record why.

    Used when an existing recovery/linked file can't be read or parsed, so the
    end-of-rerun persistence never overwrites a file we failed to load.
    """
    st.session_state["_disk_persist_blocked"] = True
    st.session_state["_disk_persist_block_msg"] = message


def _current_mutation_count() -> int:
    """The app's monotonic graph-change counter (bumped on every mutation)."""
    return st.session_state.get("_ont_mutation_count", 0)


# ---- Shared autosave scheduling (backend-agnostic) -----------------------
# Both backends (browser localStorage and local disk) use the same dirty +
# debounce gate so a no-mutation rerun does zero work — no serialization, no
# hashing — regardless of graph size. Each backend then implements its own
# write (string into localStorage, or stream-to-temp-file on disk).


def _autosave_tick() -> int:
    """Stamp the time when the graph changes; return the current revision.

    Idempotent within a rerun, so calling it from multiple targets is safe.
    """
    mc = _current_mutation_count()
    if mc != st.session_state.get("_autosave_seen_rev"):
        st.session_state["_autosave_seen_rev"] = mc
        st.session_state["_autosave_mutated_at"] = time.time()
    return mc


def _autosave_ready() -> bool:
    """True when a dirty target should be written now (forced or settled)."""
    if st.session_state.get("_force_autosave_flush"):
        return True
    idle = time.time() - st.session_state.get("_autosave_mutated_at", 0.0)
    return idle >= AUTOSAVE_DEBOUNCE_SECONDS


def request_autosave_flush() -> None:
    """Force the next autosave to write now, skipping the debounce window.

    Call after important actions (import, new ontology, linking a file) so a
    large, deliberate change is persisted immediately. Applies to whichever
    backend is active.
    """
    st.session_state["_force_autosave_flush"] = True


def _mark_disk_source_saved(label: str) -> None:
    """Record that the restored-from file is already current at this revision.

    Only the file we actually read is up to date; the other target is left
    behind so the next persist refreshes it from the restored graph.
    """
    mc = _current_mutation_count()
    if label == "linked file":
        st.session_state["_linked_saved_rev"] = mc
        st.session_state["_recovery_saved_rev"] = None
    else:
        st.session_state["_recovery_saved_rev"] = mc
        st.session_state["_linked_saved_rev"] = None


def _restore_autosave_from_disk(ont):
    """Restore the working ontology from disk on a local/desktop run.

    Disk reads are synchronous (unlike the browser component, which delivers
    data on a later rerun), so this resolves in a single pass and always marks
    the session restored. Parses straight from the file (no whole-file string in
    memory) and pauses disk autosave if the file can't be read or parsed, so a
    bad file is never overwritten.
    """
    st.session_state["_autosave_restored"] = True
    path, label = _disk_restore_source()
    if path is None:
        return
    fmt = "turtle" if label == "recovery file" else _rdf_format_for_path(path)
    try:
        ont.load_from_file(str(path), format=fmt)
    except Exception as e:  # noqa: BLE001 - autosave restore must never break startup
        log_error(e, context="Autosave restore (disk)")
        _block_disk_persist(
            f"The {label} couldn't be read or parsed. Disk autosave is paused so "
            "it isn't overwritten — fix or re-link it, then reload."
        )
        return
    _mark_disk_source_saved(label)
    # An empty-but-valid saved graph is loaded silently; nothing to announce.
    if _ontology_is_empty(ont):
        return
    try:
        from .ontology_manager import UndoManager

        st.session_state.undo_manager = UndoManager(ont)
    except ImportError:
        pass
    st.session_state["_ont_mutation_count"] = (
        st.session_state.get("_ont_mutation_count", 0) + 1
    )
    if st.session_state.get("nav_radio") == "Import / Export":
        st.session_state["nav_radio"] = "Dashboard"
    st.toast(f"Restored your previous session from the {label}.", icon="💾")


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

    # Local/desktop runs persist to disk instead of browser localStorage.
    if local_store.local_persist_enabled():
        _restore_autosave_from_disk(ont)
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
    except Exception as e:  # noqa: BLE001 - autosave restore must never break startup
        log_error(e, context="Autosave restore")
        st.session_state["_autosave_restored"] = True
        return

    st.session_state["_autosave_restored"] = True
    # An empty-but-valid saved graph (e.g. after a discard) is loaded silently;
    # there is no work to announce or navigate to.
    if _ontology_is_empty(ont):
        # localStorage already holds this content; don't rewrite it.
        st.session_state["_ls_saved_rev"] = _current_mutation_count()
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
    # localStorage already holds this content at the new revision.
    st.session_state["_ls_saved_rev"] = _current_mutation_count()
    # Deliberately do NOT redirect navigation here. The browser localStorage
    # component delivers the saved data on an arbitrary later rerun — usually the
    # first one the user triggers (e.g. clicking a tab). Forcing nav to Dashboard
    # then hijacked that interaction and yanked the user off the page they were
    # on. Leaving nav untouched keeps the restore silent apart from the toast;
    # the user stays wherever they are. (The synchronous disk-restore path can
    # still land on Dashboard safely because it resolves before any interaction.)
    st.toast("Restored your previous session from this browser's autosave.", icon="💾")


def _persist_autosave_to_disk():
    """Mirror the working ontology to disk on a local/desktop run.

    Gated on the mutation counter so normal UI reruns do *no* work (no
    serialization, no hashing) even for large ontologies: the graph is written
    only when it changed since the last save. Writes are debounced — once edits
    settle for AUTOSAVE_DEBOUNCE_SECONDS — and coalesce rapid edits, while
    important actions force an immediate flush via request_autosave_flush.

    One write per change, not two: when a linked file is set it *is* the
    persistent store (restore prefers it), so the recovery snapshot is only
    written as a fallback if the linked write fails (e.g. a synced folder is
    offline). With no linked file, the recovery snapshot is the store.

    Tradeoff: edits made in the last debounce window before a crash may be lost;
    the sidebar shows "Saved to disk" only once the flush has completed.
    """
    # A failed restore (unreadable/corrupt recovery or linked file) pauses disk
    # writes so we never overwrite a file we couldn't load.
    if st.session_state.get("_disk_persist_blocked"):
        return

    mc = _autosave_tick()
    ont = st.session_state.ontology
    linked = local_store.get_linked_path()

    if linked is not None:
        if mc == st.session_state.get("_linked_saved_rev"):
            return  # linked store already current
        if not _autosave_ready():
            return
        try:
            ont.save_to_file(linked, format=_rdf_format_for_path(linked))
            st.session_state["_linked_saved_rev"] = mc
            st.session_state["_linked_write_warned"] = False
            st.session_state.pop("_force_autosave_flush", None)
            return  # linked file is the store; no second write
        except OSError as e:
            log_error(e, context="Linked-file write")
            if not st.session_state.get("_linked_write_warned"):
                st.session_state["_linked_write_warned"] = True
                st.sidebar.warning(
                    f"Couldn't write the linked file: {e}. "
                    "Falling back to the local recovery snapshot."
                )
            # Fall through to write recovery as a safety net for these edits.

    if mc == st.session_state.get("_recovery_saved_rev"):
        return
    if not _autosave_ready():
        return
    try:
        ont.save_to_file(local_store.recovery_file(), format="turtle")
        st.session_state["_recovery_saved_rev"] = mc
        st.session_state.pop("_force_autosave_flush", None)
    except OSError as e:
        # Leave the revision unset so the next rerun retries.
        log_error(e, context="Recovery write")


def _persist_autosave_to_localstorage():
    """Mirror the working ontology into browser localStorage when it changed.

    Same dirty + debounce gate as the disk backend, so a no-mutation rerun does
    no work and a large ontology isn't re-serialized every rerun just to fail the
    size check. An over-quota graph disables browser autosave until the next
    mutation (e.g. the graph shrinks back under the cap).
    """
    ls = _get_local_storage()
    if ls is None:
        return

    mc = _autosave_tick()
    if mc == st.session_state.get("_ls_saved_rev"):
        return  # unchanged — no serialize, no hashing
    if st.session_state.get("_ls_oversized_rev") == mc:
        return  # already known too big at this revision; wait for a change
    if not _autosave_ready():
        return

    try:
        ttl = st.session_state.ontology.export_to_string(format="turtle")
    except Exception as e:  # noqa: BLE001 - autosave export must never break the session
        log_error(e, context="Autosave export")
        return

    if len(ttl.encode("utf-8")) > AUTOSAVE_MAX_BYTES:
        # Disable until the next mutation rather than re-serializing every rerun.
        st.session_state["_ls_oversized_rev"] = mc
        if not st.session_state.get("_autosave_too_big_warned"):
            st.session_state["_autosave_too_big_warned"] = True
            st.sidebar.warning(
                "Ontology is too large to autosave to this browser. "
                "Export it manually so you don't lose work."
            )
        return

    # Key the write by content hash so each distinct save mounts a fresh
    # component instance — reusing one key across reruns can leave the component
    # writing a stale/wrapped value.
    h = _content_hash(ttl)
    ls.setItem(AUTOSAVE_KEY, ttl, key=f"orionbelt_autosave_set_{h[:12]}")
    st.session_state["_ls_saved_rev"] = mc
    st.session_state["_autosave_too_big_warned"] = False
    st.session_state.pop("_force_autosave_flush", None)


def persist_autosave():
    """Persist the working ontology via the active backend (disk or browser).

    Called at the end of each rerun. Skips when autosave is disabled or before
    restore has resolved; the backend itself does nothing when nothing changed.
    """
    if not st.session_state.get("_autosave_enabled", True):
        return
    # Don't persist until restore has resolved, or the empty starting graph
    # would overwrite saved data before it can be read back on a later rerun.
    if not st.session_state.get("_autosave_restored"):
        return

    # Autosave is best-effort and must never take down the app. It runs at the
    # end of every rerun, outside main()'s error handling, and an important
    # action (e.g. linking a file) forces an immediate flush — so an unexpected
    # backend failure here would otherwise escape and stop the app on that very
    # action (issue #121). The disk backend already handles the expected
    # transient OSErrors; this catch-all is the safety net for anything else:
    # log it (surfacing the cause in the in-app error log) and, on disk runs,
    # pause further writes so it isn't retried every rerun until the user fixes
    # the file and reloads.
    try:
        if local_store.local_persist_enabled():
            _persist_autosave_to_disk()
        else:
            _persist_autosave_to_localstorage()
    except Exception as e:  # noqa: BLE001 - autosave must never break the session
        log_error(e, context="Autosave")
        if local_store.local_persist_enabled():
            _block_disk_persist(
                "Autosave hit an unexpected error and has been paused so it "
                "doesn't retry. Your work is still here — fix or re-link the "
                "file, then reload."
            )


def _apply_viz_settings(data, defaults) -> None:
    """Copy persisted viz settings into the ``_viz_cfg_*`` session keys.

    ``defaults`` is the ``_viz_cfg`` dict, used both to enumerate the settings
    and to validate types: a saved value is only applied when it matches the
    default's type (bools stay bools, ints stay ints), and ints are clamped to
    their widget range so a stale/tampered value can't crash a slider.
    """
    if not isinstance(data, dict):
        return
    for k, default in defaults.items():
        if k not in _VIZ_PERSIST_KEYS or k not in data:
            continue
        v = data[k]
        if isinstance(default, bool):
            if isinstance(v, bool):
                st.session_state[f"_viz_cfg_{k}"] = v
        elif (
            isinstance(default, int) and isinstance(v, int) and not isinstance(v, bool)
        ):
            lo, hi = _VIZ_INT_RANGES.get(k, (v, v))
            st.session_state[f"_viz_cfg_{k}"] = max(lo, min(hi, v))


def _viz_settings_payload() -> str:
    """Serialize the persisted viz settings for change detection and storage."""
    data = {
        k: st.session_state[f"_viz_cfg_{k}"]
        for k in _VIZ_PERSIST_KEYS
        if f"_viz_cfg_{k}" in st.session_state
    }
    return json.dumps(data, sort_keys=True)


def _restore_viz_settings(defaults) -> None:
    """Restore persisted viz display settings once per session (issue #142).

    On the cloud the localStorage value arrives on a *later* rerun, and the
    storage component's first render hands back an empty default — so this only
    resolves once a real value is read (disk and no-storage cases resolve
    immediately). Until then it retries. It also stops, without overriding, once
    the user has started changing settings this session, so a late-arriving
    saved set never clobbers what they are doing now (PR #142 review P1).
    """
    if st.session_state.get("_viz_settings_restored"):
        return
    if st.session_state.get("_viz_settings_dirty"):
        st.session_state["_viz_settings_restored"] = True
        return
    if local_store.local_persist_enabled():
        _apply_viz_settings(local_store.load_config().get("viz_settings"), defaults)
        st.session_state["_viz_settings_restored"] = True
        return
    ls = _get_local_storage()
    if ls is None:
        st.session_state["_viz_settings_restored"] = True
        return
    saved = ls.getItem(VIZ_SETTINGS_KEY)
    if isinstance(saved, dict):
        saved = saved.get(VIZ_SETTINGS_KEY) or next(
            (v for v in saved.values() if isinstance(v, str)), None
        )
    if isinstance(saved, str) and saved.strip():
        try:
            _apply_viz_settings(json.loads(saved), defaults)
        except (ValueError, TypeError):
            pass
        st.session_state["_viz_settings_restored"] = True
    # else: the real value hasn't arrived (or nothing was ever saved). Retry on
    # a later rerun; a brand-new user's first change lifts the save gate via the
    # dirty flag, so nothing is written until there is a real change to save.


def _persist_viz_settings() -> None:
    """Save the current viz display settings after the user changes one (#142).

    Gated on an explicit change (the dirty flag set by the settings callbacks),
    not merely on the page rendering: otherwise a cloud reload could write the
    starting defaults back over a saved set before localStorage had answered
    (PR #142 review P1). No-ops when nothing changed since the last write.
    """
    if not st.session_state.get("_viz_settings_dirty"):
        return
    payload = _viz_settings_payload()
    if payload == st.session_state.get("_viz_settings_saved_json"):
        return
    if local_store.local_persist_enabled():
        try:
            cfg = local_store.load_config()
            cfg["viz_settings"] = json.loads(payload)
            local_store.save_config(cfg)
        except OSError as e:
            log_error(e, context="Viz settings save")
            return
    else:
        ls = _get_local_storage()
        if ls is None:
            return
        h = _content_hash(payload)
        ls.setItem(
            VIZ_SETTINGS_KEY, payload, key=f"orionbelt_viz_settings_set_{h[:12]}"
        )
    st.session_state["_viz_settings_saved_json"] = payload


def _viz_file_state_id() -> str | None:
    """Identity of the ontology the per-file viz state belongs to, else ``None``.

    The linked working file's path (issue #164). Cloud sessions have no linked
    file and no disk, so they get ``None`` and keep the per-session reset.
    """
    if not local_store.local_persist_enabled():
        return None
    path = local_store.get_linked_path()
    return str(path) if path else None


def _str_list(value) -> list[str]:
    """Coerce a persisted value to a list of strings, dropping anything else."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def viz_drop_focus_seeds() -> None:
    """Forget the focus seeds so they re-derive from the current selection."""
    st.session_state.pop("_viz_cfg_focus_seeds", None)
    st.session_state.pop("_viz_cfg_focus_seed_ids_by_label", None)


# The Visualization page's widget callbacks. They live at module level so they
# can be exercised directly — as nested functions they were unreachable from a
# test, which is how the crash below went unnoticed.
#
# Streamlit runs an ``on_change`` callback *before* the script reruns, and a
# widget key is dropped from session_state once a run goes by without that
# widget being rendered. This page mounts and unmounts widgets constantly (tab
# switches, the Filter Nodes expander, focus mode swapping the filter controls
# for the seed picker), so a callback can fire for a key that is no longer
# there. Reading it outright killed the session with a KeyError (issue #219).
#
# A dropped widget has no value to persist, so these skip. The change is lost
# for that one interaction — the next render puts the widget back from the
# stored config — which is a glitch the user can simply repeat, rather than a
# dead page they have to reload.


def _viz_widget_missing(wid_key: str) -> bool:
    """Whether ``wid_key``'s widget is gone, so its callback has nothing to do.

    Presence, not truthiness: an unticked checkbox and an empty multiselect are
    values the user chose, and must not be mistaken for an absent widget.
    """
    return wid_key not in st.session_state


def viz_sync(cfg_key, wid_key):
    """Persist a viz display setting when its widget changes."""
    if _viz_widget_missing(wid_key):
        return
    st.session_state[cfg_key] = st.session_state[wid_key]
    # A change to a persisted setting lifts the cross-session save gate
    # (issue #142); changes to per-ontology filters do not.
    if cfg_key.removeprefix("_viz_cfg_") in _VIZ_PERSIST_KEYS:
        st.session_state["_viz_settings_dirty"] = True


def viz_filter_changed(kind_key, uri_by_display):
    """Persist a node filter by URI. The widget holds display labels, which gain
    a namespace tag as soon as a second entity takes the same local name —
    storing those would make the next render read the renamed entries as newly
    created and re-show hidden ones (#179)."""
    wid_key = f"viz_selected_{kind_key}"
    if _viz_widget_missing(wid_key):
        # Not merely a crash to avoid: reading the absent key as "nothing
        # picked" would store an empty filter, hiding every node of this kind
        # and persisting that (issue #219).
        return
    picked = st.session_state[wid_key] or []
    st.session_state[f"_viz_cfg_selected_{kind_key}_uris"] = [
        uri_by_display[d] for d in picked if d in uri_by_display
    ]


def focus_seeds_from_selection(selected_classes, class_count):
    """The focus seeds a fresh switch into focus mode should start from (#224).

    A class selection that is a genuine narrowing carries intent — the user
    filtered down to what they care about — so the neighbourhood grows from all
    of it. "Everything selected" is the default state and carries no intent at
    all, and seeding from *that* opened "Focus on one node" on every class at
    once: the post-build prune had nothing to narrow, so the mode did least on
    exactly the large ontologies it exists for. Start from a single class there
    instead, which is what the control is named after; the multiselect is right
    there to add more.
    """
    labels = [f"Class: {c}" for c in selected_classes]
    if class_count and len(labels) >= class_count:
        return labels[:1]
    return labels


def viz_focus_toggle():
    """Persist the focus toggle, seeding the focus nodes on first use.

    Turning focus on derives seeds from the class selection only when there are
    none to restore (see focus_seeds_from_selection). Deriving them on *every*
    switch-on threw away whatever you had picked the moment you toggled the mode
    off and on again, so narrowing "Focus node(s)" to the one class you wanted
    never survived (issue #235). The derived seeding is a starting point for the
    first use, not something reapplied over a choice you have already made.

    That also decouples the two controls: after you have expressed a preference,
    the focus seeds are their own list rather than a function of Filter Nodes.
    An empty selection still falls back to the first node, downstream.
    """
    if _viz_widget_missing("viz_focus_mode"):
        return
    on = st.session_state["viz_focus_mode"]
    st.session_state["_viz_cfg_focus_mode"] = on
    st.session_state["_viz_settings_dirty"] = True
    if on and not st.session_state.get("_viz_cfg_focus_seeds"):
        st.session_state["_viz_cfg_focus_seeds"] = focus_seeds_from_selection(
            st.session_state.get("_viz_cfg_selected_classes") or [],
            st.session_state.get("_viz_cfg_class_count") or 0,
        )


def viz_find_changed():
    """Bump a sequence so the graph re-centres on the picked entity only when the
    Find selection changes — not on every rerun or drag, which would keep yanking
    the camera back (issue #144)."""
    st.session_state["_viz_find_seq"] = st.session_state.get("_viz_find_seq", 0) + 1


def prune_reused_focus_seeds(seeds, seen_ids_by_label, focus_targets):
    """Drop seeds whose label has come to name a different entity.

    Seeds are held as the labels the multiselect shows, and the focus block
    prunes them by label alone — but a label does not identify anything. Import
    an ontology that also has a ``Person`` over one that had it and the stale
    seed passes that prune, silently re-pointing the focus at an unrelated class
    and (since #164) persisting it as that class.

    Comparing each label against the node id it resolved to last render catches
    that, whatever caused it. The replacement counters do not: an import goes
    through ``save_checkpoint``, which bumps the edit counter alongside the
    mutation counter, so it is deliberately *not* a "replacement" (issue #180).

    A label with no recorded id is one the user just picked, so it is kept.
    """
    if not seeds or not seen_ids_by_label:
        return list(seeds or [])
    return [
        s
        for s in seeds
        if s not in seen_ids_by_label or seen_ids_by_label[s] == focus_targets.get(s)
    ]


def _clear_viz_file_session_state() -> None:
    """Drop the session keys that belong to one specific ontology.

    The filter selections and focus seeds name entities of the file they were
    made against, so they must not survive a switch to another one: they would
    both suppress the new file's saved state (a selection already in session
    wins over it) and then be written back out under the new file's key.
    """
    for kind in _FILTER_KINDS:
        st.session_state.pop(f"_viz_cfg_selected_{kind['key']}_uris", None)
        st.session_state.pop(f"_viz_cfg_known_{kind['key']}_uris", None)
    viz_drop_focus_seeds()
    st.session_state.pop("_viz_pending_focus_seed_ids", None)
    # The mutation counters seen on the last render belong to the file we just
    # left, and loading the new one bumps the ontology's counter without a
    # matching edit. Left in place they would read as "the ontology was
    # replaced", which resets the filter to everything shown and so discards the
    # state we are about to restore. Nothing can leak across the switch anyway:
    # the selection itself was just cleared, so the only thing the reconcile has
    # to diff against is the new file's own saved state.
    st.session_state.pop("_viz_cfg_seen_mutation", None)
    st.session_state.pop("_viz_cfg_seen_edits", None)


def _restore_viz_file_state() -> dict:
    """Return the linked file's saved viz state, once per file (issue #164).

    Yields the saved entry on the first Visualization render for a given linked
    path and ``{}`` afterwards, since session state then holds the reconciled
    selection. Linking a different file mid-session clears the previous file's
    per-ontology state first, so the new file's own state is what applies.
    """
    file_id = _viz_file_state_id()
    marker = "_viz_file_state_for"
    if marker in st.session_state:
        if st.session_state[marker] == file_id:
            return {}
        # A switch, not the first render: the state in session belongs to the
        # file we just left.
        _clear_viz_file_session_state()
    st.session_state[marker] = file_id
    if file_id is None:
        return {}
    store = local_store.load_config().get(VIZ_FILE_STATE_KEY)
    entry = store.get(file_id) if isinstance(store, dict) else None
    return entry if isinstance(entry, dict) else {}


def viz_ontology_was_replaced() -> bool:
    """Whether the whole ontology was swapped since the last graph render.

    A mutation-counter jump not matched by the edit counter means a
    load/import/new/undo rather than an incremental edit, so the node filters
    reset to "everything shown" instead of diffing against an ontology that may
    reuse URIs for unrelated entities.

    Must be evaluated *after* :func:`_restore_viz_file_state`, which clears the
    counters when the linked file changed: loading the new file bumps the
    ontology counter, and treating that as a replacement would throw away the
    state being restored for it (issue #164).
    """
    mutation = st.session_state.get("_ont_mutation_count", 0)
    edits = st.session_state.get("_ont_edit_count", 0)
    prev_mutation = st.session_state.get("_viz_cfg_seen_mutation")
    prev_edits = st.session_state.get("_viz_cfg_seen_edits", 0)
    return prev_mutation is not None and (mutation - prev_mutation) != (
        edits - prev_edits
    )


def viz_mark_ontology_seen() -> None:
    """Record the counters this render reconciled against.

    The counterpart to :func:`viz_ontology_was_replaced`, which compares the
    next render's counters with these.
    """
    st.session_state["_viz_cfg_seen_mutation"] = st.session_state.get(
        "_ont_mutation_count", 0
    )
    st.session_state["_viz_cfg_seen_edits"] = st.session_state.get("_ont_edit_count", 0)


def seed_filter_from_saved(all_uris, hidden, selected, known):
    """Reconcile inputs for a node filter, seeded from saved per-file state.

    Returns ``(selected, known)`` unchanged once the session has a selection of
    its own. On the first render of a linked file it turns the saved hidden set
    into the equivalent pair, so the saved state goes *through*
    :func:`reconcile_filter_selection` rather than around it: an entity added to
    the file since the last session is absent from the hidden set and therefore
    shows up, the way new content always does.
    """
    if not hidden or selected is not None:
        return selected, known
    return [uri for uri in all_uris if uri not in hidden], set(all_uris)


def _viz_file_state_payload(filters: dict, focus_targets: dict) -> dict:
    """The per-file viz state worth saving: hidden entities and focus seeds.

    Stores what the user *hid* rather than what is selected. Everything is shown
    by default, so the hidden set is normally empty or tiny, which keeps
    config.json small for an ontology with thousands of entities. It also
    restores identically: an entity added to the file since the last session is
    absent from the hidden set and so shows up, exactly as
    :func:`reconcile_filter_selection` would have decided.
    """
    data: dict[str, list[str]] = {}
    for key, entry in filters.items():
        selected = set(entry["selected_uris"])
        hidden = [uri for uri in entry["uris"] if uri not in selected]
        if hidden:
            data[f"hidden_{key}_uris"] = hidden
    # Seeds are stored as the graph's node ids, not the labels the multiselect
    # shows. A label picks up a namespace tag the moment a second entity takes
    # the same local name, so a saved label would stop matching a file that
    # gained one while the app was closed (the lesson of issue #179). Node ids
    # for classes, individuals and data properties derive from the URI instead.
    seeds = st.session_state.get("_viz_cfg_focus_seeds") or []
    seed_ids = [focus_targets[s] for s in seeds if s in focus_targets]
    if seed_ids:
        data["focus_seed_ids"] = seed_ids
    return data


def _persist_viz_file_state(filters: dict, focus_targets: dict) -> None:
    """Save the linked file's node filters and focus seeds (issue #164).

    No-ops when nothing changed since the last render, and when the state
    already on disk matches, so ordinary reruns don't rewrite config.json.
    """
    file_id = _viz_file_state_id()
    if file_id is None:
        return
    payload = _viz_file_state_payload(filters, focus_targets)
    fingerprint = json.dumps([file_id, payload], sort_keys=True)
    if fingerprint == st.session_state.get("_viz_file_state_fingerprint"):
        return
    try:
        cfg = local_store.load_config()
        store = cfg.get(VIZ_FILE_STATE_KEY)
        if not isinstance(store, dict):
            store = {}
        existing = store.get(file_id)
        if payload != existing and (payload or existing is not None):
            # Re-insert so this file counts as the most recently changed: dicts
            # keep insertion order and JSON preserves it, so eviction drops the
            # stalest.
            store.pop(file_id, None)
            if payload:
                store[file_id] = payload
            while len(store) > VIZ_FILE_STATE_MAX_FILES:
                store.pop(next(iter(store)))
            cfg[VIZ_FILE_STATE_KEY] = store
            local_store.save_config(cfg)
    except OSError as e:
        # Leave the fingerprint unset so an unwritable config.json is retried on
        # a later rerun instead of being silently given up on.
        log_error(e, context="Viz per-file state save")
        return
    st.session_state["_viz_file_state_fingerprint"] = fingerprint


def _load_linked_file(target) -> bool:
    """Replace the working ontology with the contents of ``target``.

    Returns True on success. Used when linking to an existing file so "point at
    my Nextcloud ontology" opens that file instead of overwriting it. Parses
    straight from the path, in the format implied by its extension.
    """
    try:
        OntologyManager = get_ontology_manager_class()
        new_ont = OntologyManager()
        new_ont.load_from_file(str(target), format=_rdf_format_for_path(target))
    except Exception as e:  # noqa: BLE001 - a bad linked file must not break the session
        log_error(e, context="Linked file load")
        return False
    st.session_state.ontology = new_ont
    st.session_state["_ont_mutation_count"] = (
        st.session_state.get("_ont_mutation_count", 0) + 1
    )
    # The linked file already holds this content at the new revision, so it
    # won't be rewritten on the next flush. (Recovery is a fallback only, so it
    # isn't refreshed while a healthy linked file is the store.)
    st.session_state["_linked_saved_rev"] = _current_mutation_count()
    try:
        from .ontology_manager import UndoManager

        st.session_state.undo_manager = UndoManager(new_ont)
    except ImportError:
        pass
    return True


def _render_disk_autosave_sidebar():
    """Sidebar controls for the local disk-backed autosave and linked file."""
    if st.session_state.get("_disk_persist_blocked"):
        st.sidebar.warning(
            st.session_state.get("_disk_persist_block_msg", "Disk autosave is paused.")
        )
    st.sidebar.checkbox(
        "Autosave to disk",
        value=st.session_state.get("_autosave_enabled", True),
        key="_autosave_enabled",
        help=(
            "Saves your ontology to a linked file if you set one below, "
            "otherwise to a recovery file on this machine so an unexpected "
            "close can be recovered."
        ),
    )
    if st.session_state.get("_autosave_enabled", True) and not _ontology_is_empty(
        st.session_state.ontology
    ):
        # Track the active store: the linked file when set, else recovery. Report
        # "saved" only once the debounced flush has caught up to the revision.
        mc = _current_mutation_count()
        active_key = (
            "_linked_saved_rev"
            if local_store.get_linked_path() is not None
            else "_recovery_saved_rev"
        )
        saved_rev = st.session_state.get(active_key)
        if saved_rev == mc:
            st.sidebar.caption("✓ Saved to disk")
        elif saved_rev is not None:
            # The disk write is debounced and only runs on a rerun, so a pending
            # write lands on the next edit/interaction rather than immediately. Say
            # so honestly instead of "Autosaving…", which looked stuck when the
            # session went idle even though the work is safe in memory (issue #145).
            st.sidebar.caption("• Saved in memory; writing to disk shortly…")

    linked = local_store.get_linked_path()
    with st.sidebar.expander("Linked working file", expanded=linked is not None):
        st.caption(
            "Point this at a file in a synced folder (Nextcloud, Dropbox, ...) "
            "for automatic off-machine backups. It tracks your working ontology "
            "and is loaded again on startup."
        )
        path_str = st.text_input(
            "File path",
            value=str(linked) if linked else "",
            key="_linked_path_input",
            placeholder="/path/to/my-ontology.ttl",
        )

        # Decide up front whether the chosen path is an existing, non-empty file.
        # If so, default to LOADING it (the issue's "open my ontology" workflow)
        # rather than silently overwriting it with the current graph.
        typed = path_str.strip()
        target = _Path(typed).expanduser() if typed else None
        file_has_content = bool(
            target
            and target.exists()
            and target.is_file()
            and (local_store.read_text(target) or "").strip()
        )
        existing_action = None
        if file_has_content:
            existing_action = st.radio(
                "That file already exists:",
                [
                    "Load it into the workspace",
                    "Overwrite it with the current ontology",
                ],
                key="_linked_existing_action",
            )

        set_col, clear_col = st.columns(2)
        with set_col:
            if st.button("Link", use_container_width=True, key="_linked_set"):
                p = path_str.strip()
                if p:
                    load_it = (
                        file_has_content
                        and existing_action == "Load it into the workspace"
                    )
                    local_store.set_linked_path(p)
                    st.session_state["_linked_write_warned"] = False
                    # A fresh link clears any earlier restore-failure pause.
                    st.session_state["_disk_persist_blocked"] = False
                    st.session_state.pop("_disk_persist_block_msg", None)
                    # Linking a file is an important action: flush immediately
                    # rather than waiting out the debounce window.
                    st.session_state["_force_autosave_flush"] = True
                    if load_it:
                        if _load_linked_file(_Path(p).expanduser()):
                            st.toast(f"Linked and loaded {p}", icon="🔗")
                        else:
                            # Couldn't load it; don't overwrite either.
                            _block_disk_persist(
                                "Couldn't load the linked file. Disk autosave is "
                                "paused so it isn't overwritten."
                            )
                            st.toast(f"Linked {p}, but couldn't load it", icon="⚠️")
                    else:
                        # New file or an explicit overwrite: write current state.
                        st.session_state["_linked_saved_rev"] = None
                        st.toast(f"Linked working file: {p}", icon="🔗")
                    st.rerun()
        with clear_col:
            if st.button(
                "Unlink",
                use_container_width=True,
                key="_linked_clear",
                disabled=linked is None,
            ):
                local_store.set_linked_path(None)
                st.toast("Unlinked working file.", icon="🔗")
                st.rerun()
        if linked is not None:
            st.caption(f"Linked: `{linked}`")


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


def save_checkpoint(label: str = "Edit"):
    """Save a snapshot to the undo history after a mutation."""
    if st.session_state.get("undo_manager"):
        st.session_state.undo_manager.checkpoint(label)
    # Bump mutation counter so derived UI caches (e.g. graph viz) invalidate
    st.session_state["_ont_mutation_count"] = (
        st.session_state.get("_ont_mutation_count", 0) + 1
    )
    # A separate counter tracking only incremental edits (not ontology
    # replacements like load/import/new, which bump the mutation counter
    # directly). The Visualization class filter uses the gap between the two to
    # tell an edit apart from a replacement (issue #180).
    st.session_state["_ont_edit_count"] = st.session_state.get("_ont_edit_count", 0) + 1


def log_error(error: Exception, context: str = ""):
    """Log a runtime error to session state for display."""
    entry = {
        # Local wall-clock time: the log is read by whoever is at the app.
        "time": datetime.now().astimezone().strftime("%H:%M:%S"),
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


def _bulk_result_message(result: dict, label: str) -> tuple[str, str]:
    """Summarize a bulk-add result for a flash message, naming each entry that
    failed and why, so a rejected row (e.g. an invalid name) is not a silent
    failure (issue #114). ``label`` is the noun with its plural suffix, e.g.
    "class(es)". Returns ``(message, type)`` for :func:`set_flash_message`.
    """
    parts = []
    if result["created"]:
        parts.append(f"Created {len(result['created'])} {label}")
    if result.get("updated"):
        parts.append(f"Updated {len(result['updated'])} existing")
    if result["skipped"]:
        parts.append(f"Skipped {len(result['skipped'])} existing")
    errors = result["errors"]
    if errors:
        # "row(s) failed" rather than "could not be created": a bulk class run
        # can now fail while *updating* an existing class (e.g. adding an
        # invalid parent), not only while creating one (issue #157 review).
        parts.append(f"{len(errors)} row{'s' if len(errors) != 1 else ''} failed")
    summary = ". ".join(parts) if parts else "Nothing to create"
    if errors:
        shown = errors[:10]
        lines = "\n".join(
            f"- **{e.get('name') or '(empty name)'}**: "
            f"{e.get('error') or 'unknown error'}"
            for e in shown
        )
        if len(errors) > len(shown):
            lines += f"\n- ...and {len(errors) - len(shown)} more"
        summary = f"{summary}:\n\n{lines}"
    succeeded = result["created"] or result.get("updated")
    if errors and not succeeded:
        msg_type = "error"
    elif errors:
        msg_type = "warning"
    elif succeeded:
        msg_type = "success"
    else:
        msg_type = "info"
    return summary, msg_type


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


# Separates the local name from the label in display strings. Neither the order
# nor the separator is cosmetic.
#
# Streamlit filters selectboxes client-side with fzy, which awards a match a
# word-boundary bonus taken from the character *preceding* it: 0.9 after '/',
# 0.8 after a space (or '-', '_'), 0.7 for a camelCase hump, and 0.0 after '('.
# The old 'Label (name)' format gave the local name no bonus at all, so an
# unrelated camelCase compound could outscore an exact match — searching
# 'HamTopping' in pizza.owl ranked 'ParmaHamTopping' first (issue #210). Leading
# with the name, behind a separator that ends in a space, restores the bonus.
#
# Name-first also keeps the option list sorted consistently: a resource whose
# label matches its name renders as the bare name, so a label-first format would
# sort part of the list by label and the rest by name.
LABEL_NAME_SEPARATOR = " · "


def format_label_name(name: str, label: str) -> str:
    """Format display string as 'name · Label' if label exists and differs from name."""
    if label and label != name:
        return f"{name}{LABEL_NAME_SEPARATOR}{label}"
    return name


# fzy also subtracts 0.005 for every character *after* the last matched one, so
# a longer option scores lower purely for being longer. A resource with a short
# name therefore lost to a longer one whenever its own label pushed the display
# string past the competitor's: searching 'n' ranked 'node' above 'n · number'
# (issue #214), because both matched at position 0 with the same 0.9 bonus and
# only length separated them.
#
# Padding every option to one width makes that trailing penalty identical for
# all of them, so length stops counting and the score reflects the match alone.
# Equal scores keep the order the app supplied (Streamlit sorts with a stable
# lodash sortBy), which is the builders' alphabetical sort — and for a prefix
# query that puts the shortest name first.
#
# The width is a constant rather than the longest option in the list: padding is
# applied through ``format_func``, so it never touches the option values the
# rest of the app stores and looks up, but a width that moved with the option
# set would still change a rendered label under a selection. 120 covers every
# display string in the bundled ontologies (the longest is 103); anything past
# it simply keeps today's behaviour. Well under fzy's 1024-character cutoff,
# beyond which it stops scoring entirely.
SEARCH_PAD_WIDTH = 120


def _pad_option(display: object) -> str:
    """Pad a dropdown option to :data:`SEARCH_PAD_WIDTH` for search ranking.

    Pass as ``format_func`` to any selectbox fed by :func:`build_uri_options` or
    :func:`build_class_options`. The padding is invisible (HTML collapses the
    trailing spaces) and stays out of the widget's value, which remains the
    unpadded display string every lookup is keyed by.
    """
    return str(display).ljust(SEARCH_PAD_WIDTH)


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
        uri = item.get("uri", "")
        prefix = _prefix_for_uri(uri)
        if prefix:
            return f"{name} ({prefix})"
        # No bound prefix (e.g. an arbitrary custom URI entered for issue #87
        # part B): fall back to the namespace so two distinct URIs sharing a
        # local name still render — and key — distinctly. The namespace alone is
        # unique here: same namespace plus same local name would be the same URI,
        # not a collision.
        ns = uri[: len(uri) - len(name)] if uri.endswith(name) else uri
        if ns:
            return f"{name} ({ns})"
    return name


# Which card is open on a per-item list page is a single source of truth:
# ``active_{kind}`` holds ``(key, mode)`` where ``mode`` is ``"view"`` or
# ``"edit"`` (absent means nothing is open). One value per kind means opening a
# card overwrites any previously open one, so single-active is inherent — no
# per-item boolean flags to scan or clean up. ``kind`` is the page's flag
# segment: ``class``, ``objprop``, ``dataprop``, ``ind``, ``skos``, ``scheme``.


def _cb_toggle_view(prefix, uid):
    """Callback: open `uid`'s view panel. `uid` must be unique per resource."""
    st.session_state[f"active_{prefix}"] = (uid, "view")


def _cb_toggle_edit(prefix, uid):
    """Callback: open `uid`'s edit panel. `uid` must be unique per resource."""
    st.session_state[f"active_{prefix}"] = (uid, "edit")


def _cb_view_to_edit(prefix, uid):
    """Callback: switch `uid`'s open card from view to edit."""
    st.session_state[f"active_{prefix}"] = (uid, "edit")


def _open_entity(kind: str, key: str, mode: str = "view") -> None:
    """Open a card from a navigation path (search, graph-click, "Open full
    editor"). These open a card directly rather than through the View/Edit
    button callbacks. Because there is a single ``active_{kind}`` value, the
    freshly requested card always wins — no card left open elsewhere can shadow
    it (issue #146 review).
    """
    st.session_state[f"active_{kind}"] = (key, mode)


def _close_entity(kind: str) -> None:
    """Close whatever card of ``kind`` is open (Cancel, or a finished save)."""
    st.session_state.pop(f"active_{kind}", None)


def _get_active(kind: str):
    """Return ``(key, mode)`` for the open card of ``kind``, or ``None``."""
    value = st.session_state.get(f"active_{kind}")
    if isinstance(value, tuple) and len(value) == 2 and value[1] in ("view", "edit"):
        return value
    return None


def _is_open(kind: str, key: str, mode: str | None = None) -> bool:
    """True if ``key`` is the open card for ``kind`` (in ``mode`` if given)."""
    active = _get_active(kind)
    if active is None or active[0] != key:
        return False
    return mode is None or active[1] == mode


# Maps a graph/search/editor entity's display type to its active-card kind.
_NAV_KIND_BY_TYPE = {
    "Class": "class",
    "Object Property": "objprop",
    "Data Property": "dataprop",
    "Individual": "ind",
    "SKOS Concept": "skos",
}

# Which page holds the editor for a graph selection. Relations and restrictions
# are edges rather than nodes, so they have no URI of their own — see
# ``_edge_id`` for how the graph names them (issue #152).
_PAGE_BY_TYPE = {
    "Class": "Classes",
    "Object Property": "Properties",
    "Data Property": "Properties",
    "Individual": "Individuals",
    "SKOS Concept": "SKOS Vocabulary",
    "Class Relation": "Relations",
    "Restriction": "Restrictions",
}

# Types whose "Open" lands on the row's own editor rather than just the page.
_PRECISE_NAV_TYPES = {"Class", "Class Relation", "Restriction"}

# A relation or restriction edge carries its whole identity in ``ename``, since
# there is no URI to look it up by. The unit separator cannot occur in a URI or
# a local name, so the parts are unambiguous however they are spelled.
_EDGE_ID_SEP = "\x1f"


def _edge_id(*parts) -> str:
    """Name a graph edge that stands for a relation or restriction (issue #152)."""
    return _EDGE_ID_SEP.join("" if p is None else str(p) for p in parts)


def _edge_id_parts(ename: str, count: int) -> tuple | None:
    """Split an edge id back into its ``count`` parts, or None if it isn't one.

    A selection can outlive the graph payload that produced it (a settings
    change rebuilds the graph while the panel still holds the last click), so a
    name that doesn't decode reads as "gone" rather than resolving to something
    else.
    """
    parts = tuple((ename or "").split(_EDGE_ID_SEP))
    return parts if len(parts) == count else None


def _restriction_matches_edge(rest: dict, parts: tuple) -> bool:
    """Whether ``rest`` is the restriction a graph edge stands for (issue #152).

    Matched on the class the edge starts at, plus the property, type and value —
    the same fields that identify a row on the Restrictions page, so a class
    carrying several restrictions on one property resolves to the clicked one.
    """
    src_uri, prop_uri, rtype, value_uri = parts
    return (
        src_uri in (rest.get("applied_to_uris") or [])
        and (rest.get("property_uri") or rest.get("property")) == prop_uri
        and rest.get("type") == rtype
        and (rest.get("value_uri") or "") == value_uri
    )


def _nav_open_entity(display_type: str, uid: str, uri: str | None = None) -> None:
    """Open the card for a navigation target (graph-click, search, "Open full
    editor") named by its display type. SKOS concepts key by URI hash — local
    names collide across schemes — so pass ``uri`` for them; every other kind
    keys by ``uid`` (already URI-derived at the call sites). No-op for unknown
    types.
    """
    kind = _NAV_KIND_BY_TYPE.get(display_type)
    if not kind:
        return
    key = str(abs(hash(uri if uri is not None else uid)))[:8] if kind == "skos" else uid
    _open_entity(kind, key)


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
    """Build class dropdown options with 'disambiguated name · Label' format.

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


def build_namespace_options(ont) -> tuple:
    """Build namespace dropdown options for creating an entity in a chosen
    namespace.

    Offers the base (default) namespace first, then any namespace already used
    by an entity or explicitly bound by the user (see
    :meth:`OntologyManager.get_creatable_namespaces`). Each option is labelled
    with its bound prefix when one exists.

    Returns:
        tuple: (display_options, namespace_lookup). The lookup maps each display
        string to a namespace URI, or ``None`` for the default (base) namespace
        so callers can pass it straight to ``add_*(namespace=...)``.
    """
    options = []
    lookup: dict[str, str | None] = {}

    for i, ns in enumerate(ont.get_creatable_namespaces()):
        if i == 0:
            display = f"(default) {ns}"
            lookup[display] = None
        else:
            prefix = _prefix_for_uri(ns)
            display = f"{prefix}: {ns}" if prefix else ns
            lookup[display] = ns
        options.append(display)

    return options, lookup


def _renamed_ref(ont, old_uri, new_name):
    """Full URI a rename produces for ``new_name``, preserving ``old_uri``'s
    namespace (mirrors the engine's rename logic). Used so post-rename updates
    target the resource in its own namespace rather than the base namespace."""
    return str(ont._uri(new_name, ont._namespace_of(old_uri)))


def _namespace_option_index(ont, ns_options, ns_lookup, uri):
    """Index of the :func:`build_namespace_options` entry matching ``uri``'s
    current namespace, so an edit form pre-selects where the resource already
    lives. Falls back to 0 (the default/base namespace)."""
    ns = ont._namespace_of(uri)
    current = None if ns == ont.base_uri else ns
    for i, opt in enumerate(ns_options):
        if ns_lookup.get(opt) == current:
            return i
    return 0


_KEEP_NAMESPACE = object()  # sentinel: leave a resource in its current namespace


def _rename_or_move(ont, rename_fn, old_uri, old_local, new_name, new_namespace):
    """Resolve the target URI from the (possibly changed) local name and
    namespace and rename via ``rename_fn`` if it differs from ``old_uri``.

    A namespace change is just a rename to a full URI in the new namespace, so
    ``rename_fn`` re-points every reference and no links are lost. Returns
    ``(ok, current_ref)``: ``ok`` is False only when ``rename_fn`` refuses
    because the target URI already exists. ``new_namespace`` is ``None`` (base),
    a namespace URI, or the ``_KEEP_NAMESPACE`` sentinel to keep the current
    namespace.
    """
    target_ns = (
        ont._namespace_of(old_uri)
        if new_namespace is _KEEP_NAMESPACE
        else new_namespace
    )
    target_uri = str(ont._uri(new_name or old_local, target_ns))
    if target_uri == old_uri:
        return True, old_uri
    if rename_fn(old_uri, target_uri):
        return True, target_uri
    return False, old_uri


def _custom_uri_field(current_uri, new_name, key):
    """Render an "Advanced: set a custom URI" expander inside an edit form and
    return the effective name to rename to (issue #87 part B).

    A full ``http(s)`` URI entered here overrides the Name (local part) and any
    Namespace selector, so the entity is renamed to that exact IRI everywhere it
    appears — used to give an entity an arbitrary identifier or to match an
    entity in another ontology. The engine already accepts a full URI as a rename
    target (``_uri`` passes it through, ``invalid_name_reason`` allows it), so the
    returned value flows through the form's existing validate-and-rename path
    unchanged. Returns ``new_name`` untouched when the field is blank or equal to
    the current URI, so nothing renames on a no-op.

    Must be called inside the ``st.form(...)`` body, before the submit button, so
    the text input is submitted with the form.
    """
    with st.expander("Advanced: set a custom URI"):
        custom = st.text_input(
            "Full URI (overrides Name and Namespace)",
            value="",
            key=key,
            placeholder=str(current_uri),
            help="Enter a full http(s) URI to give this entity an arbitrary "
            "identifier, e.g. to match an entity in another ontology. Every "
            "reference is re-pointed, so no links are lost. Leave blank to use "
            "the Name and Namespace above.",
        )
    custom = custom.strip()
    if custom and custom != str(current_uri):
        return custom
    return new_name


def _external_uri_target(ont, default_uri, key, label):
    """Optional "external URI" input for a relation target (issue #87 part B).

    Lets a relation (equivalentClass / equivalentProperty / sameAs, or any other
    type) point at an entity in another ontology that has not been imported, by
    typing its full ``http(s)`` URI instead of picking an existing entity from
    the dropdown. The engine's ``add_*_relation`` already passes a full URI
    through ``_uri`` unchanged, so the returned target flows straight into it.

    Returns ``(target_uri, error)``: when the field holds a valid full URI that
    becomes the target (overriding ``default_uri``, the dropdown pick); when it
    is blank, ``default_uri`` is returned; when it is present but not a valid full
    URI, ``error`` is a message string (and ``default_uri`` is returned). Must be
    called inside the ``st.form(...)`` body, before the submit button.
    """
    ext = st.text_input(
        f"…or link {label} to an external URI (optional)",
        value="",
        key=key,
        placeholder="http://other.example.org/ns#Entity",
        help="Link to an entity in another ontology that has not been imported. "
        "Enter its full http(s) URI. Overrides the dropdown above.",
    ).strip()
    if not ext:
        return default_uri, None
    if not ext.startswith(("http://", "https://")):
        return default_uri, "External URI must be a full http(s) URI."
    if reason := ont.invalid_name_reason(ext):
        return default_uri, reason
    return ext, None


def _apply_class_edit(
    ont,
    class_info,
    new_name,
    new_label,
    new_comment,
    new_parent,
    new_namespace=_KEEP_NAMESPACE,
):
    """Apply a class edit (rename + label/comment/parent). Returns True on success.

    Shared by the Edit/Delete form and the Visualization side panel. A change to
    the local name and/or ``new_namespace`` is applied as a single rename to the
    new full URI (every reference is re-pointed, so no links are lost); the
    remaining updates then target the class at its new URI. ``new_namespace`` is
    ``None`` for the base namespace, a namespace URI string, or the
    ``_KEEP_NAMESPACE`` sentinel to leave the class where it is (used by callers
    without a namespace selector). Shows an error and returns False if the target
    URI is already taken. The caller owns the undo checkpoint and rerun.
    """
    if (
        new_name
        and new_name != class_info["name"]
        and (reason := ont.invalid_name_reason(new_name))
    ):
        show_message(reason, "error")
        return False
    ok, current_ref = _rename_or_move(
        ont,
        ont.rename_class,
        class_info["uri"],
        class_info["name"],
        new_name,
        new_namespace,
    )
    if not ok:
        show_message(
            f"Cannot move/rename: '{new_name or class_info['name']}' already exists!",
            "error",
        )
        return False
    if class_info["parents"] and new_parent != class_info["parents"][0]:
        ont.update_class(current_ref, remove_parent=class_info["parents"][0])
    ont.update_class(
        current_ref,
        new_label=new_label,
        new_comment=new_comment,
        new_parent=new_parent if new_parent != "None" else None,
    )
    return True


def _apply_class_relation_add(ont, subj_uri, rel_type, obj_uri, subj_show, obj_show):
    """Write one class relation. Returns True on success.

    Shared by the Relations page and the Visualization panel (issue #221), so
    both refuse the same nonsense triple. The caller owns the rerun.
    """
    if not subj_uri or not obj_uri:
        show_message("Pick both classes first!", "error")
        return False
    if subj_uri == obj_uri:
        show_message("Please select two different classes!", "error")
        return False
    ont.add_class_relation(subj_uri, rel_type, obj_uri)
    save_checkpoint("Add class relation")
    show_message(f"Relation added: {subj_show} {rel_type} {obj_show}", "success")
    return True


def parent_option_index(parent_options, parent_lookup, parent_uri) -> int:
    """Where ``parent_uri`` sits in a class dropdown, or 0 ("None") (issue #221).

    The preselection is addressed by URI, not by name, since local names collide
    across namespaces and picking by name could parent a new class onto the wrong
    one. A URI that is no longer in the list falls back to "None" rather than to
    whatever now sits at that index: the panel seeds this from the graph
    selection, and that class can be deleted or filtered out from under it.
    """
    if not parent_uri:
        return 0
    display = next((d for d, u in parent_lookup.items() if u == parent_uri), None)
    if display is not None and display in parent_options:
        return parent_options.index(display)
    return 0


def render_add_class_form(ont, classes, form_key, parent_uri=None, on_close=None):
    """Render the "add a class" form. Returns True when a class was created.

    Shared by the Classes page and the Visualization details panel, so both
    create through the same guards (issue #221). ``form_key`` makes the widget
    keys unique. ``parent_uri`` preselects the parent, which is how the panel
    seeds a new class from the class you had selected on the graph; the field
    stays editable, so the graph offers a starting point rather than deciding
    for you. ``on_close`` is what dismissing the form means; the page has no such
    thing (the tab is the form) so it passes None and gets no Cancel button.

    The caller owns the rerun: the panel has to drop its open flag first.
    """
    parent_options, parent_lookup = build_class_options(classes, include_none=True)
    parent_index = parent_option_index(parent_options, parent_lookup, parent_uri)

    with st.form(form_key):
        name = st.text_input(
            "Class Name *", help="Local name for the class (e.g., 'Person')"
        )
        label = st.text_input("Label", help="Human-readable label")
        comment = st.text_area("Comment", help="Description of the class")
        parent_display = st.selectbox(
            "Parent Class",
            options=parent_options,
            index=parent_index,
            help="Select a parent class for hierarchy",
            format_func=_pad_option,
        )
        ns_options, ns_lookup = build_namespace_options(ont)
        ns_display = st.selectbox(
            "Namespace",
            options=ns_options,
            help="Namespace the class is created in (default is the base URI)",
        )

        cancelled = False
        if on_close is None:
            submitted = st.form_submit_button("Add Class")
        else:
            add_col, cancel_col = st.columns(2)
            with add_col:
                submitted = st.form_submit_button("Add Class", use_container_width=True)
            with cancel_col:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if cancelled:
            on_close()
            st.rerun()
        if submitted:
            ns_val = ns_lookup.get(ns_display)
            if not name:
                show_message("Class name is required!", "error")
            elif reason := ont.invalid_name_reason(name):
                show_message(reason, "error")
            elif str(ont._uri(name, ns_val)) in {c["uri"] for c in classes}:
                show_message(f"Class '{name}' already exists!", "error")
            else:
                ont.add_class(
                    name,
                    parent=parent_lookup.get(parent_display),
                    label=label,
                    comment=comment,
                    namespace=ns_val,
                )
                save_checkpoint("Add class")
                show_message(f"Class '{name}' added successfully!", "success")
                return True
    return False


def _apply_property_edit(
    ont, prop, new_name, new_label, new_comment, new_domain, new_range
):
    """Apply a property edit (rename + label/comment/domain/range).

    Returns True on success, False (with an error message) on a rename clash.
    Shared by the property edit forms and the Visualization side panel. The
    caller handles the undo checkpoint and rerun. ``new_domain``/``new_range``
    are passed straight to ``update_property`` (a class URI, a datatype name, or
    "" to clear).
    """
    current_ref = prop["uri"]
    if new_name and new_name != prop["name"]:
        if reason := ont.invalid_name_reason(new_name):
            show_message(reason, "error")
            return False
        if ont.rename_property(prop["uri"], new_name):
            current_ref = _renamed_ref(ont, prop["uri"], new_name)
        else:
            show_message(f"Cannot rename: '{new_name}' already exists!", "error")
            return False
    ont.update_property(
        current_ref,
        new_label=new_label,
        new_comment=new_comment,
        new_domain=new_domain,
        new_range=new_range,
    )
    return True


def _apply_individual_edit(
    ont, ind, new_name, new_label, new_comment, add_class, remove_class
):
    """Apply an individual edit (rename + label/comment/class membership).

    Returns True on success, False (with an error message) on a rename clash.
    Shared by the individual edit form and the Visualization side panel.
    """
    current_ref = ind["uri"]
    if new_name and new_name != ind["name"]:
        if reason := ont.invalid_name_reason(new_name):
            show_message(reason, "error")
            return False
        if ont.rename_individual(ind["uri"], new_name):
            current_ref = _renamed_ref(ont, ind["uri"], new_name)
        else:
            show_message(f"Cannot rename: '{new_name}' already exists!", "error")
            return False
    ont.update_individual(
        current_ref,
        new_label=new_label,
        new_comment=new_comment,
        add_class=add_class if add_class and add_class != "None" else None,
        remove_class=remove_class if remove_class and remove_class != "None" else None,
    )
    return True


def _render_panel_relation_editor(ont, ename, classes):
    """Edit the class relation behind a graph edge, in the Details panel (#152).

    The edge names the whole triple, which is looked up in the live ontology: a
    selection can outlive the axiom it points at (deleted here, undone, edited on
    the Relations page, or edited in this very panel — a triple that changes is a
    different edge), and that has to say so rather than rewrite whatever is at
    hand.
    """
    parts = _edge_id_parts(ename, 3)
    rel = None
    if parts is not None:
        rel = next(
            (
                r
                for r in ont.get_class_relations()
                if (r.get("subject_uri"), r["relation"], r.get("object_uri")) == parts
            ),
            None,
        )
    if rel is None:
        st.caption("This relation was edited or removed. Click an edge to pick one up.")
        return
    # Keyed by the edge, so switching selections doesn't hand the new relation
    # the widget state of the one edited before it.
    render_relation_form(
        ont, rel, f"panel_{_uid(ename)}", _relation_spec("crel", ont, classes)
    )


def _render_panel_restriction_editor(ont, ename, classes, properties):
    """Edit the restriction behind a graph edge, in the Details panel (#152).

    Only restrictions drawn as their own edge (someValuesFrom / allValuesFrom
    onto a visible class) can be selected here; the rest of them have no element
    in the graph to click. Resolved from the live ontology for the same reason as
    the relation editor above.
    """
    parts = _edge_id_parts(ename, 4)
    rest = None
    if parts is not None:
        rest = next(
            (r for r in ont.get_restrictions() if _restriction_matches_edge(r, parts)),
            None,
        )
    if rest is None:
        st.caption(
            "This restriction was edited or removed. Click an edge to pick one up."
        )
        return
    # One restriction node can hang off several classes, and the editor acts on
    # the first of them — narrow it to the class whose edge was clicked.
    src_uri = parts[0]
    index = list(rest["applied_to_uris"]).index(src_uri)
    row = {
        **rest,
        "applied_to": [rest["applied_to"][index]],
        "applied_to_uris": [src_uri],
    }
    render_restriction_form(ont, row, f"panel_{_uid(ename)}", classes, properties)


def _panel_add_kind():
    """Which add form the Visualization panel is showing, or None (issue #221).

    One ``_viz_add_kind`` value rather than a flag per kind, so the class and
    relation forms (and the individual one this grows to host) cannot end up open
    at the same time.
    """
    return st.session_state.get("_viz_add_kind")


def _panel_close_add() -> None:
    """Close whatever add form is open, and disarm any pending pick."""
    for key in ("_viz_add_kind", "_viz_crel_subject", "_viz_crel_object"):
        st.session_state.pop(key, None)


def resolve_picked_object(subject_id, selected_ntype, selected_ename):
    """What an armed "pick the object" click means (issue #221).

    Returns ``("pick", node_id)`` to take it as the object, ``("cancel", None)``
    to abandon the add, or ``("wait", None)`` to keep waiting.

    The subject stays selected on the graph when the pick is armed, so its own id
    has to read as "still waiting" rather than as a relation from a class to
    itself. Losing the selection is the cancel: clicking empty canvas clears it,
    and so does clicking the subject again, which is the gesture people reach for
    to undo a click. Anything that is not a class keeps waiting instead of
    cancelling, since misclicking a property should not throw the pairing away.
    """
    if not selected_ename:
        return ("cancel", None)
    if selected_ename == subject_id:
        return ("wait", None)
    if selected_ntype != "Class":
        return ("wait", None)
    return ("pick", selected_ename)


def _panel_add_parent(classes, ntype, ename):
    """The class a new one should hang under: the selected node, if it is a class."""
    if ntype == "Class" and ename:
        return next((c["uri"] for c in classes if _uid(c["uri"]) == ename), None)
    return None


def _render_panel_add_class_button(classes, ntype, ename):
    """The button that opens the add form, at the foot of the panel (issue #221)."""
    parent_uri = _panel_add_parent(classes, ntype, ename)
    parent_name = next((c["name"] for c in classes if c["uri"] == parent_uri), None)
    if st.button(
        "Add subclass" if parent_uri else "Add class",
        key="panel_add_class_open",
        use_container_width=True,
        help=(
            f"Add a class under '{parent_name}'."
            if parent_uri
            else "Add a class. Select a class first to make it the parent."
        ),
    ):
        st.session_state["_viz_add_kind"] = "class"
        st.rerun()


def _render_panel_add_class_form(ont, classes, ntype, ename):
    """The add-a-class form, shown *instead of* the panel's usual contents.

    It replaces them rather than joining them: the entity editor already has its
    own Name, Label and Comment fields, and two sets of those stacked in a narrow
    column is a good way to fill in the wrong one. Replacing also keeps the form
    at the top of the panel, where it is visible without scrolling.

    A selected class becomes the new class's parent, which is the point of adding
    from the graph at all: you hang a class where it belongs by clicking there,
    instead of finding the parent again in a dropdown of every class. With
    anything else selected, or nothing, it still adds a class, just parentless.
    """
    parent_uri = _panel_add_parent(classes, ntype, ename)
    parent_name = next((c["name"] for c in classes if c["uri"] == parent_uri), None)
    st.markdown(
        f"**New subclass of {parent_name}**" if parent_name else "**New class**"
    )
    if parent_name:
        st.caption("Change the parent below to hang it somewhere else.")
    if render_add_class_form(
        ont,
        classes,
        "panel_add_class_form",
        parent_uri=parent_uri,
        on_close=_panel_close_add,
    ):
        _panel_close_add()
        st.rerun()


def _render_panel_add_relation_button(classes, ntype, ename):
    """The button that arms a relation add, at the foot of the panel (issue #221).

    Only offered with a class selected: a relation needs a subject, and pressing
    this is what fixes the selected class as one.
    """
    if _panel_add_parent(classes, ntype, ename) is None:
        return
    if st.button(
        "Add relation",
        key="panel_add_rel_open",
        use_container_width=True,
        help="Then click the class this one points at.",
    ):
        st.session_state["_viz_add_kind"] = "crel"
        st.session_state["_viz_crel_subject"] = ename
        st.rerun()


def _render_panel_add_relation_form(ont, classes, ntype, ename):
    """Add a class relation by clicking its two ends on the graph (issue #221).

    Pressing "Add relation" fixes the selected class as the subject and waits for
    the next class click to be the object, which keeps the direction explicit:
    these are arrows, not lines, so the order the two ends are given in is the
    content of the triple, not a detail. Both ends stay editable in the form
    afterwards, so a misclick is corrected here rather than by starting over.
    """
    by_id = {_uid(c["uri"]): c for c in classes}
    subject = by_id.get(st.session_state.get("_viz_crel_subject"))
    if subject is None:
        # The subject was deleted or renamed while the pick was armed.
        _panel_close_add()
        st.rerun()

    obj_id = st.session_state.get("_viz_crel_object")
    if not obj_id:
        st.markdown(f"**Relation from {subject['name']}**")
        st.info("Now click the class it points at.")
        action, picked = resolve_picked_object(
            st.session_state["_viz_crel_subject"], ntype, ename
        )
        if action == "pick":
            st.session_state["_viz_crel_object"] = picked
            st.rerun()
        if action == "cancel":
            _panel_close_add()
            st.rerun()
        if st.button("Cancel", key="panel_add_rel_cancel", use_container_width=True):
            _panel_close_add()
            st.rerun()
        return

    obj = by_id.get(obj_id)
    if obj is None:
        st.session_state.pop("_viz_crel_object", None)
        st.rerun()

    st.markdown("**New relation**")
    options, lookup = build_class_options(classes)
    # Not parent_option_index: that falls back to index 0 for a URI it cannot
    # find, which is "None" in a parent dropdown but a real class here. Both ends
    # were just resolved out of `classes`, so both are present.
    display_by_uri = {u: d for d, u in lookup.items()}
    with st.form("panel_add_rel_form"):
        subj_disp = st.selectbox(
            "Subject",
            options=options,
            index=options.index(display_by_uri[subject["uri"]]),
            format_func=_pad_option,
        )
        rel_type = st.selectbox("Relation Type", options=list(ont.CLASS_RELATIONS))
        obj_disp = st.selectbox(
            "Object",
            options=options,
            index=options.index(display_by_uri[obj["uri"]]),
            format_func=_pad_option,
        )
        st.caption(f"Reads as: {subject['name']} → {obj['name']}")
        add_col, cancel_col = st.columns(2)
        with add_col:
            submitted = st.form_submit_button("Add relation", use_container_width=True)
        with cancel_col:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)
    if cancelled:
        _panel_close_add()
        st.rerun()
    if submitted and _apply_class_relation_add(
        ont,
        lookup.get(subj_disp),
        rel_type,
        lookup.get(obj_disp),
        subj_disp,
        obj_disp,
    ):
        _panel_close_add()
        st.rerun()


def _render_panel_entity_editor(
    ont, ntype, ename, sel, classes, object_props, data_props, individuals
):
    """Render the inline editor (or read-only details) for the selected graph
    node in the Visualization side panel (issue #80).

    Resolves the entity from its node id (``_uid(uri)``) and shows a compact edit
    form for classes, object/data properties and individuals; class relations and
    restrictions are edges with no URI of their own and resolve from the edge id
    instead (issue #152). Anything else falls back to the tooltip text. Returns
    the entity dict, or None for the edge-borne kinds and unresolved selections.
    """
    if ntype == "Class Relation":
        _render_panel_relation_editor(ont, ename, classes)
        return None
    if ntype == "Restriction":
        _render_panel_restriction_editor(ont, ename, classes, object_props + data_props)
        return None

    # Object properties are drawn as edges (so selecting one is a selectEdge with
    # isEdge=True), but they're still editable — resolve by type, not by node vs
    # edge. Structural edges (type, domain, ...) have no entry in the pool and
    # fall through to the read-only tooltip.
    entity = None
    if ename:
        pool = {
            "Class": classes,
            "Object Property": object_props,
            "Data Property": data_props,
            "Individual": individuals,
        }.get(ntype)
        if pool:
            entity = next((e for e in pool if _uid(e["uri"]) == ename), None)

    if entity is None:
        for line in (sel.get("title") or "").split("\n"):
            if line.strip():
                st.write(line.strip())
        return None

    if ntype == "Class":
        with st.form("panel_edit_class"):
            name = st.text_input("Name", value=entity["name"])
            label = st.text_input("Label", value=entity["label"])
            comment = st.text_area("Comment", value=entity["comment"])
            others = [c["name"] for c in classes if c["name"] != entity["name"]]
            cur = entity["parents"][0] if entity["parents"] else "None"
            parent = st.selectbox(
                "Parent",
                ["None"] + others,
                index=others.index(cur) + 1 if cur in others else 0,
            )
            if st.form_submit_button("Save", use_container_width=True):
                if _apply_class_edit(ont, entity, name, label, comment, parent):
                    save_checkpoint("Update class")
                    show_message("Class updated!", "success")
                st.rerun()
    elif ntype in ("Object Property", "Data Property"):
        with st.form("panel_edit_prop"):
            name = st.text_input("Name", value=entity["name"])
            label = st.text_input("Label", value=entity["label"])
            comment = st.text_area("Comment", value=entity["comment"])
            cls_opts, cls_lookup = build_class_options(classes, include_none=True)
            cur_dom = next(
                (d for d, u in cls_lookup.items() if u == entity.get("domain_uri", "")),
                "None",
            )
            dom = st.selectbox(
                "Domain",
                cls_opts,
                index=cls_opts.index(cur_dom) if cur_dom in cls_opts else 0,
                format_func=_pad_option,
            )
            if ntype == "Object Property":
                cur_rng = next(
                    (
                        d
                        for d, u in cls_lookup.items()
                        if u == entity.get("range_uri", "")
                    ),
                    "None",
                )
                rng = st.selectbox(
                    "Range",
                    cls_opts,
                    index=cls_opts.index(cur_rng) if cur_rng in cls_opts else 0,
                    format_func=_pad_option,
                )
                # Only apply when changed, so a range/domain that can't be shown
                # in the dropdown (e.g. a class outside this ontology) isn't
                # cleared on save; None tells update_property to leave it as-is.
                new_range = (cls_lookup.get(rng) or "") if rng != cur_rng else None
            else:
                dts = list(get_ontology_manager_class().XSD_DATATYPES.keys())
                # The selectbox shows the first datatype when the current range
                # isn't a known one; compare against that shown default so an
                # unknown range isn't silently rewritten on save.
                default_rng = (
                    entity["range"]
                    if entity["range"] in dts
                    else (dts[0] if dts else None)
                )
                rng = st.selectbox(
                    "Range (datatype)",
                    dts,
                    index=dts.index(default_rng) if default_rng in dts else 0,
                )
                new_range = rng if rng != default_rng else None
            new_domain = (cls_lookup.get(dom) or "") if dom != cur_dom else None
            if st.form_submit_button("Save", use_container_width=True):
                if _apply_property_edit(
                    ont, entity, name, label, comment, new_domain, new_range
                ):
                    save_checkpoint("Update property")
                    show_message("Property updated!", "success")
                st.rerun()
    elif ntype == "Individual":
        with st.form("panel_edit_ind"):
            name = st.text_input("Name", value=entity["name"])
            label = st.text_input("Label", value=entity["label"])
            comment = st.text_area("Comment", value=entity["comment"])
            cur_classes = entity["classes"]
            avail = [c["name"] for c in classes if c["name"] not in cur_classes]
            add_cls = st.selectbox("Add to class", ["None"] + avail)
            rem_cls = st.selectbox("Remove from class", ["None"] + cur_classes)
            if st.form_submit_button("Save", use_container_width=True):
                if _apply_individual_edit(
                    ont, entity, name, label, comment, add_cls, rem_cls
                ):
                    save_checkpoint("Update individual")
                    show_message("Individual updated!", "success")
                st.rerun()

    st.caption("IRI")
    st.code(entity["uri"], language=None)
    return entity


def _download_or_save(label, data, file_name, mime="text/plain", key=None):
    """Offer a file to the user, working in both the web and desktop apps.

    The web shows a normal download button. The desktop / local app's embedded
    webview can't perform browser downloads (#86), so there we instead show a
    Save-to-disk control (path input defaulting to Downloads) that writes the
    file directly. The dead download button is not shown on the desktop.
    """
    _k = key or file_name
    if not local_store.local_persist_enabled():
        st.download_button(
            label=label, data=data, file_name=file_name, mime=mime, key=f"dl_{_k}"
        )
        return
    path = st.text_input(
        "Save to file",
        value=str(_Path.home() / "Downloads" / file_name),
        key=f"savepath_{_k}",
    )
    save_label = label.replace("Download", "Save") if "Download" in label else label
    if st.button(f"💾 {save_label}", key=f"savebtn_{_k}"):
        try:
            local_store.atomic_write(_Path(path).expanduser(), data)
            # Use a toast (floating popup) rather than an inline banner, which can
            # render below the fold where it isn't visible.
            st.toast(f"Saved to {path}", icon="💾")
        except OSError as e:
            st.toast(f"Could not save: {e}", icon="⚠️")


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


# Cap how many item cards a "view" list renders at once. Each card is an expander
# plus several buttons (and a form when expanded), so an ontology with hundreds of
# classes / properties / individuals / concepts would otherwise emit thousands of
# widgets in one render — enough to overwhelm the embedded desktop webview and take
# the app down (issue #140). Paginating bounds the payload regardless of size, and
# every per-item list view shares this cap (issue #146).
LIST_PAGE_SIZE = 50

# How many nodes the Visualization graph may draw. vis-network (and the desktop
# webview especially) bogs down well before a large ontology's worth of them.
GRAPH_MAX_NODES = 500

# How many it may *assemble* in focus mode, where the drawn graph is the pruned
# neighbourhood of the seeds rather than everything built. Assembly is cheap —
# plain dicts — so this can be far larger than what is drawn, which is what lets
# a class deep into a big ontology be focused on at all (issue #216).
FOCUS_BUILD_MAX_NODES = 5000


def graph_node_cap(focus_pruning: bool) -> int:
    """How many nodes a graph build may assemble (issue #216).

    Going past what can be drawn is only safe because focus mode prunes back to
    the seeds' neighbourhood afterwards, so the allowance is tied to that prune
    actually running — not to focus mode being on. With the mode on but every
    seed cleared nothing prunes, and the browser would be handed the lot.
    """
    return FOCUS_BUILD_MAX_NODES if focus_pruning else GRAPH_MAX_NODES


def _page_bounds(total: int, page: int, page_size: int) -> tuple[int, int, int, int]:
    """Resolve a 1-based ``page`` over ``total`` items into slice bounds.

    Returns ``(num_pages, page, start, end)`` where ``page`` is clamped into
    ``[1, num_pages]`` and ``start``/``end`` are 0-based slice indices. Pure, so
    it is unit-tested directly.
    """
    num_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(int(page), 1), num_pages)
    start = (page - 1) * page_size
    return num_pages, page, start, min(start + page_size, total)


def _paginate_rows(items: list, page_key: str, noun: str) -> list:
    """Paginate a flat list of rows (no open/active state) at LIST_PAGE_SIZE.

    Renders a page selector and a range caption when there is more than one
    page, and returns the slice of ``items`` to render. ``page_key`` is the
    session-state key backing the selector (unique per list). Used for the
    Relations lists, which are plain rows rather than expandable cards.
    """
    total = len(items)
    if total <= LIST_PAGE_SIZE:
        return items
    num_pages, page, _, _ = _page_bounds(
        total, st.session_state.get(page_key, 1), LIST_PAGE_SIZE
    )
    st.session_state[page_key] = page  # clamp before the widget reads the key
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=num_pages,
        step=1,
        key=page_key,
        help=f"{total} {noun}; {LIST_PAGE_SIZE} shown per page.",
    )
    _, _, start, end = _page_bounds(total, page, LIST_PAGE_SIZE)
    st.caption(f"Showing {noun} {start + 1}–{end} of {total}.")
    return items[start:end]


def _resolve_list_view(items, kind, key_of, page_key, noun):
    """Shared logic for a per-item "view" list (classes, properties, ...).

    Given the already sorted/filtered display list, this:

      * reads the open item directly from the single ``active_{kind}`` value —
        no scan over per-item flags, no cleanup loop, since only one card can be
        open per kind by construction (issue #147);
      * paginates at LIST_PAGE_SIZE with a page selector, jumping to the active
        item's page once when it becomes active — not every render, so a manual
        page change sticks while a card stays open (issues #140 / #143 / #146).

    ``kind`` is the active-value segment (``active_{kind}`` holds
    ``(key, mode)``) and ``key_of`` maps an item to its unique key string. An
    open item that is not in ``items`` (e.g. filtered out by search) simply
    reads as "nothing open" this render, leaving the value intact so the card
    reappears when the filter clears.

    Returns ``(page_items, active_item)``.
    """

    active_state = _get_active(kind)
    active = None
    if active_state is not None:
        active = next((it for it in items if key_of(it) == active_state[0]), None)

    total = len(items)
    if total <= LIST_PAGE_SIZE:
        return items, active

    jump_key = f"{page_key}__active_key"
    if active is not None:
        _akey = key_of(active)
        if st.session_state.get(jump_key) != _akey:
            st.session_state[page_key] = items.index(active) // LIST_PAGE_SIZE + 1
            st.session_state[jump_key] = _akey
    else:
        # No card open: forget the last jump so reopening one jumps again.
        st.session_state.pop(jump_key, None)

    num_pages, page, _, _ = _page_bounds(
        total, st.session_state.get(page_key, 1), LIST_PAGE_SIZE
    )
    st.session_state[page_key] = page  # clamp before the widget reads the key
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=num_pages,
        step=1,
        key=page_key,
        help=f"{total} {noun}; {LIST_PAGE_SIZE} shown per page.",
    )
    _, _, start, end = _page_bounds(total, page, LIST_PAGE_SIZE)
    st.caption(f"Showing {noun} {start + 1}–{end} of {total}.")
    return items[start:end], active


# Stands for "anything" in a slot of a pasted triple, so two of the three parts
# can be pinned: "* disjointWith inductor".
_SEARCH_ANY = {"*", "?", "_", "-"}


def parse_search_query(query: str) -> tuple:
    """Split a search box's text into ``(slots, terms)``.

    ``slots`` is a three-item tuple when the text reads like a pasted triple —
    ``capacitor disjointWith inductor`` — so each word can be matched against its
    own column, with ``*`` standing for anything (issue #170). It is None
    otherwise, and then ``terms`` are the words that must each appear somewhere
    in the row. Local names never contain whitespace (the name validation
    rejects it), so splitting on whitespace is unambiguous.
    """
    words = (query or "").strip().lower().split()
    if not words:
        return None, []
    if len(words) == 3:
        slots = tuple(None if w in _SEARCH_ANY else w for w in words)
        return slots, []
    return None, words


def _matches_slots(slots: tuple, fields: tuple) -> bool:
    """Whether each non-wildcard slot is a substring of its field.

    A field may be a tuple of alternatives, in which case any of them can carry
    the match (a restriction's middle column is its property *or* its type).
    """
    for slot, field in zip(slots, fields):
        if slot is None:
            continue
        candidates = field if isinstance(field, tuple) else (field,)
        if not any(slot in (c or "").lower() for c in candidates):
            return False
    return True


def _filter_relations(relations: list, query: str) -> list:
    """Filter relation rows by subject, relation and object local names.

    A pasted triple matches column by column, so ``capacitor disjointWith
    inductor`` finds exactly that relation (issue #170). Anything else is
    matched as separate words that must each appear in the row, which keeps the
    single-word search from issue #148 working. An empty query returns the list
    unchanged.
    """
    slots, terms = parse_search_query(query)
    if slots is None and not terms:
        return relations

    def _fields(r):
        return (r["subject"], r["relation"], r["object"])

    if slots:
        return [r for r in relations if _matches_slots(slots, _fields(r))]
    return [
        r
        for r in relations
        if all(any(t in f.lower() for f in _fields(r)) for t in terms)
    ]


def _sort_relations(relations: list) -> list:
    """Sort relation rows by (subject, relation, object), case-insensitively."""
    return sorted(
        relations,
        key=lambda r: (
            r["subject"].lower(),
            r["relation"].lower(),
            r["object"].lower(),
        ),
    )


def _filter_restrictions(restrictions: list, query: str) -> list:
    """Case-insensitive substring filter over a restriction's property, type,
    value, qualified class, and the classes it applies to (issue #148).

    A restriction is not a triple, but it reads like one: the class it applies to,
    the property, and the value. So a pasted ``Bicycle hasPart Wheel`` matches
    those three columns (issue #170). The middle word also matches the
    restriction type and the last one the qualified class, so ``Bicycle
    someValuesFrom Wheel`` finds it too.
    """
    slots, terms = parse_search_query(query)
    if slots is None and not terms:
        return restrictions

    def _haystack(r):
        # Fields can be None for valid OWL restrictions the manager doesn't map
        # (e.g. owl:hasSelf), so coerce before joining.
        val = r.get("value")
        parts = [
            r.get("property") or "",
            r.get("type") or "",
            "" if val is None else str(val),
            r.get("on_class") or "",
            " ".join(str(c) for c in (r.get("applied_to") or [])),
        ]
        return " ".join(parts).lower()

    def _fields(r):
        val = r.get("value")
        return (
            " ".join(str(c) for c in (r.get("applied_to") or [])),
            (r.get("property") or "", r.get("type") or ""),
            ("" if val is None else str(val), r.get("on_class") or ""),
        )

    if slots:
        return [r for r in restrictions if _matches_slots(slots, _fields(r))]
    return [r for r in restrictions if all(t in _haystack(r) for t in terms)]


def _sort_restrictions(restrictions: list) -> list:
    """Sort restrictions by (property, type), case-insensitively.

    Fields can be None (e.g. an unmapped owl:hasSelf), so coerce before ``.lower()``.
    """
    return sorted(
        restrictions,
        key=lambda r: (
            (r.get("property") or "").lower(),
            (r.get("type") or "").lower(),
        ),
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
            selected_display = st.selectbox(
                "Select Class",
                options=class_options,
                key="edit_class_select",
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
                    new_ns_display = st.selectbox(
                        "Namespace",
                        options=ns_options,
                        index=ns_index,
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
                            new_namespace = ns_lookup.get(
                                st.selectbox(
                                    "Namespace",
                                    options=ns_opts,
                                    index=_namespace_option_index(
                                        ont, ns_opts, ns_lookup, prop["uri"]
                                    ),
                                    key=f"objp_ns_{prop_uid}",
                                    help="Moving to another namespace re-points "
                                    "every reference to this property.",
                                )
                            )
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
                                dom_disp = st.selectbox(
                                    "Domain",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_dom_disp)
                                    if cur_dom_disp in cls_opts
                                    else 0,
                                    key=f"objp_dom_{prop_uid}",
                                    format_func=_pad_option,
                                )
                            with col2:
                                rng_disp = st.selectbox(
                                    "Range",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_rng_disp)
                                    if cur_rng_disp in cls_opts
                                    else 0,
                                    key=f"objp_rng_{prop_uid}",
                                    format_func=_pad_option,
                                )

                            if st.form_submit_button("Save Changes"):
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
                            new_namespace = ns_lookup.get(
                                st.selectbox(
                                    "Namespace",
                                    options=ns_opts,
                                    index=_namespace_option_index(
                                        ont, ns_opts, ns_lookup, prop["uri"]
                                    ),
                                    key=f"dp_ns_{prop_uid}",
                                    help="Moving to another namespace re-points "
                                    "every reference to this property.",
                                )
                            )
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
                                dom_disp = st.selectbox(
                                    "Domain",
                                    options=cls_opts,
                                    index=cls_opts.index(cur_dom_disp)
                                    if cur_dom_disp in cls_opts
                                    else 0,
                                    key=f"dp_dom_{prop_uid}",
                                    format_func=_pad_option,
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
                    prop_disp = st.selectbox(
                        "Existing property *",
                        options=reuse_opts,
                        format_func=_pad_option,
                    )

                    cls_opts, cls_lookup = build_class_options(classes)
                    col1, col2 = st.columns(2)
                    with col1:
                        source_disp = st.selectbox(
                            "Source class *", options=cls_opts, format_func=_pad_option
                        )
                    with col2:
                        target_disp = st.selectbox(
                            "Target class *", options=cls_opts, format_func=_pad_option
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
                        if not (prop_name and source and target):
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
                    domain_disp = st.selectbox(
                        "Domain (Class)", options=cls_opts, format_func=_pad_option
                    )
                with col2:
                    range_disp = st.selectbox(
                        "Range (Class)", options=cls_opts, format_func=_pad_option
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

                inverse_disp = st.selectbox(
                    "Inverse Of", options=obj_prop_opts, format_func=_pad_option
                )
                ns_options, ns_lookup = build_namespace_options(ont)
                ns_display = st.selectbox(
                    "Namespace",
                    options=ns_options,
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
                domain_disp = st.selectbox(
                    "Domain (Class)",
                    options=cls_opts,
                    key="data_prop_domain",
                    format_func=_pad_option,
                )
            with col2:
                datatypes = list(get_ontology_manager_class().XSD_DATATYPES.keys())
                range_ = st.selectbox(
                    "Range (Datatype)", options=datatypes, key="data_prop_range"
                )

            functional = st.checkbox("Functional", key="data_prop_functional")
            ns_options, ns_lookup = build_namespace_options(ont)
            ns_display = st.selectbox(
                "Namespace",
                options=ns_options,
                help="Namespace the property is created in (default is the base URI)",
                key="data_prop_namespace",
            )

            submitted = st.form_submit_button("Add Data Property")
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
                            new_namespace = ns_lookup.get(
                                st.selectbox(
                                    "Namespace",
                                    options=ns_opts,
                                    index=_namespace_option_index(
                                        ont, ns_opts, ns_lookup, ind["uri"]
                                    ),
                                    key=f"ind_ns_{_ik}",
                                    help="Moving to another namespace re-points "
                                    "every reference to this individual.",
                                )
                            )
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
                class_type = st.selectbox("Class Type *", options=class_names)
                ns_options, ns_lookup = build_namespace_options(ont)
                ns_display = st.selectbox(
                    "Namespace",
                    options=ns_options,
                    help="Namespace the individual is created in (default is the base URI)",
                )

                submitted = st.form_submit_button("Add Individual")
                if submitted:
                    ns_val = ns_lookup.get(ns_display)
                    if not name:
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


def _slot_options(entities: list, current_uri) -> tuple:
    """Build ``(options, lookup)`` for an editor slot, keeping ``current_uri``.

    Selecting by local name would resolve into the base namespace and rewrite an
    imported entity (``other:Foo`` saved back as ``:Foo``), so options map to
    full URIs and the row's own value is offered as itself when nothing local
    holds it (review P2).
    """
    options, lookup = build_uri_options(entities)
    if current_uri and current_uri not in lookup.values():
        options = options + [str(current_uri)]
        lookup = {**lookup, str(current_uri): str(current_uri)}
    return options, lookup


def render_restriction_row(ont, rest, row_key, classes, properties):
    """Render one restriction as a row, with edit and delete (issue #152).

    Mirrors the Relations lists: class, property, type and value across the row,
    so a page of restrictions can be scanned at a glance. The editor opens
    underneath the row it belongs to.
    """
    value_text = "—" if rest["value"] is None else str(rest["value"])
    if rest["on_class"]:
        value_text = f"{value_text} (on {rest['on_class']})"

    col_cls, col_prop, col_type, col_val, col_edit, col_del = st.columns(
        [3, 2, 2, 3, 0.7, 0.7]
    )
    with col_cls:
        st.write(f"📦 {', '.join(rest['applied_to']) or '—'}")
    with col_prop:
        st.write(f"🔗 {rest['property']}")
    with col_type:
        st.write(f"🔒 {rest['type'] or '—'}")
    with col_val:
        st.write(value_text)

    # An orphaned restriction (applied to nothing) has no class to edit or
    # delete against, so it is shown but not actionable.
    if not rest["applied_to"]:
        return

    with col_edit:
        st.button(
            "✏️",
            key=f"edit_rest_{row_key}",
            help="Edit this restriction",
            on_click=_cb_toggle_edit,
            args=("rest", row_key),
        )
    with col_del:
        if st.button("🗑️", key=f"del_rest_{row_key}", help="Delete this restriction"):
            # Use full URIs so restrictions on external/imported properties or
            # classes delete correctly, and the value (with the qualified class)
            # so a sibling on the same property and type is not deleted instead
            # of this row (issue #152).
            applied_uri = rest.get("applied_to_uris") or rest["applied_to"]
            removed = ont.delete_restriction(
                applied_uri[0],
                rest.get("property_uri") or rest["property"],
                rest["type"],
                value=rest.get("value_uri") or rest.get("value"),
                on_class=rest.get("on_class_uri") or rest.get("on_class"),
            )
            if removed:
                save_checkpoint("Delete restriction")
                show_message("Restriction deleted!", "success")
                st.rerun()
            else:
                show_message("Could not delete this restriction.", "error")

    render_restriction_editor(ont, rest, row_key, classes, properties)


def render_restriction_editor(ont, rest, row_key, classes, properties):
    """Edit one restriction in place, inside its expander (issue #152).

    The row is identified by its whole spec, so a class carrying several
    restrictions on the same property and type edits the one on screen rather
    than whichever the graph yields first. Keyed by the row's position in the
    rendered list, which is what the delete button already does: two identical
    restrictions would otherwise share a key.
    """
    if not _is_open("rest", row_key, "edit"):
        return
    render_restriction_form(
        ont, rest, row_key, classes, properties, on_close=lambda: _close_entity("rest")
    )


def render_restriction_form(ont, rest, form_key, classes, properties, on_close=None):
    """Render the edit form for one restriction (issue #152).

    Shared by the Restrictions page rows and the Visualization details panel, so
    both rewrite the axiom through the same guards. ``form_key`` makes the widget
    keys unique — the page passes the row's position, the panel the selected
    edge's id. ``on_close`` is what dismissing the editor means; the panel has no
    such thing (it follows the graph selection), so it passes None and gets no
    Cancel button.
    """
    types = list(ont.RESTRICTION_TYPES)
    applied_uris = rest.get("applied_to_uris") or rest["applied_to"]
    cls_options, cls_lookup = _slot_options(classes, applied_uris[0])
    prop_options, prop_lookup = _slot_options(
        properties, rest.get("property_uri") or rest["property"]
    )
    on_options, on_lookup = _slot_options(classes, rest.get("on_class_uri"))

    # The value stays free text: it can be a class, a cardinality or a literal,
    # and a form cannot swap the widget when the type picker changes. It is
    # pre-filled as a full URI in the two cases where a bare local name would
    # not round-trip (review P2):
    #   * an imported entity, since a local name resolves into the base
    #     namespace and would point at a different thing;
    #   * any resource-valued hasValue, since add_restriction stores a
    #     non-http value as a literal — so saving an unchanged row would turn
    #     owl:hasValue :alice into owl:hasValue "alice".
    # A hasValue that already holds a literal has no value_uri and stays as it is.
    value_default = "" if rest["value"] is None else str(rest["value"])
    _value_uri = rest.get("value_uri")
    if _value_uri and (
        rest["type"] == "hasValue" or not str(_value_uri).startswith(str(ont.namespace))
    ):
        value_default = str(_value_uri)

    with st.form(f"edit_rest_form_{form_key}"):
        new_class = st.selectbox(
            "Applies to Class",
            cls_options,
            index=_uri_option_index(cls_options, cls_lookup, applied_uris[0]),
            key=f"er_cls_{form_key}",
            format_func=_pad_option,
        )
        new_property = st.selectbox(
            "Property",
            prop_options,
            index=_uri_option_index(
                prop_options, prop_lookup, rest.get("property_uri") or rest["property"]
            ),
            key=f"er_prop_{form_key}",
            format_func=_pad_option,
        )
        new_type = st.selectbox(
            "Restriction Type",
            types,
            index=types.index(rest["type"]) if rest["type"] in types else 0,
            key=f"er_type_{form_key}",
        )
        new_value = st.text_input(
            "Value",
            value=value_default,
            key=f"er_val_{form_key}",
            help="A class name for someValuesFrom/allValuesFrom, a number for a "
            "cardinality, or a literal for hasValue. A full URI is kept as it is.",
        )
        new_on_class = None
        if "Qualified" in new_type:
            new_on_class = st.selectbox(
                "Qualified on Class",
                on_options,
                index=(
                    _uri_option_index(on_options, on_lookup, rest["on_class_uri"])
                    if rest.get("on_class_uri")
                    else 0
                ),
                key=f"er_onclass_{form_key}",
                format_func=_pad_option,
            )

        cancelled = False
        if on_close is None:
            saved = st.form_submit_button("💾 Save", use_container_width=True)
        else:
            save_col, cancel_col = st.columns(2)
            with save_col:
                saved = st.form_submit_button("💾 Save", use_container_width=True)
            with cancel_col:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if cancelled:
            on_close()
            st.rerun()
        if saved:
            try:
                changed = ont.update_restriction(
                    {
                        "class_name": applied_uris[0],
                        "property_name": rest.get("property_uri") or rest["property"],
                        "restriction_type": rest["type"],
                        "value": rest.get("value_uri") or rest.get("value"),
                        "on_class": rest.get("on_class_uri") or rest.get("on_class"),
                    },
                    {
                        "class_name": cls_lookup.get(new_class, new_class),
                        "property_name": prop_lookup.get(new_property, new_property),
                        "restriction_type": new_type,
                        "value": new_value,
                        "on_class": (
                            on_lookup.get(new_on_class, new_on_class)
                            if new_on_class
                            else None
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - a rejected edit must show as a message, not a traceback
                # As wide as the Add form's handler: a rejected edit must show
                # up as a message, never as a page-breaking traceback.
                show_message(str(exc), "error")
                return
            if changed:
                save_checkpoint("Edit restriction")
                if on_close is not None:
                    on_close()
                set_flash_message("Restriction updated!", "success")
                st.rerun()
            else:
                show_message(
                    "This restriction is no longer in the ontology, so it "
                    "wasn't changed.",
                    "error",
                )


def render_add_restriction(ont, classes, properties):
    """Render the "Add Restriction" tab.

    Split out of :func:`render_restrictions` for the same reason as the row
    renderer: the page's tab picker is a ``segmented_control``, which
    Streamlit's AppTest mis-serializes, so the form cannot be driven through
    the page in tests.
    """
    st.subheader("Add Restriction")

    if not classes:
        st.warning("Please create at least one class first.")
        return
    if not properties:
        st.warning("Please create at least one property first.")
        return

    with st.form("add_restriction_form"):
        # Pick by URI, not by local name: a name resolves into the base
        # namespace, so a restriction meant for an imported other:Foo
        # was silently created on a base-namespace twin instead.
        cls_opts, cls_lookup = build_uri_options(classes)
        prop_opts, prop_lookup = build_uri_options(properties)
        target_disp = st.selectbox(
            "Apply to Class", options=cls_opts, format_func=_pad_option
        )
        property_disp = st.selectbox(
            "On Property", options=prop_opts, format_func=_pad_option
        )

        # Straight from the engine, so a type can never be offered here
        # that it doesn't understand, or omitted when it gains one.
        restriction_type = st.selectbox(
            "Restriction Type", options=list(ont.RESTRICTION_TYPES)
        )

        st.write("**Restriction Value:**")
        value = None
        if restriction_type in ["someValuesFrom", "allValuesFrom"]:
            value = cls_lookup[
                st.selectbox(
                    "Value (Class)",
                    options=cls_opts,
                    key="rest_class_value",
                    format_func=_pad_option,
                )
            ]
        elif restriction_type == "hasValue":
            ind_opts, ind_lookup = build_uri_options(ont.get_individuals())
            value_type = st.radio("Value Type", ["Literal", "Individual"])
            if value_type == "Literal":
                value = st.text_input("Literal Value")
            elif ind_opts:
                value = ind_lookup[
                    st.selectbox(
                        "Individual", options=ind_opts, format_func=_pad_option
                    )
                ]
            else:
                # Offering a "No individuals" placeholder let that string
                # be stored as the value.
                st.info("No individuals yet — create one, or use a literal.")
        else:
            value = st.number_input("Cardinality", min_value=0, value=1)

        on_class = None
        if "Qualified" in restriction_type:
            on_class = cls_lookup[
                st.selectbox(
                    "Qualified on Class",
                    options=cls_opts,
                    key="qualified_class",
                    format_func=_pad_option,
                )
            ]

        submitted = st.form_submit_button("Add Restriction")
        if submitted:
            try:
                ont.add_restriction(
                    cls_lookup[target_disp],
                    prop_lookup[property_disp],
                    restriction_type,
                    value,
                    on_class=on_class,
                )
                save_checkpoint("Add restriction")
                show_message("Restriction added!", "success")
                st.rerun()
            except Exception as e:  # noqa: BLE001 - a rejected edit must show as a message, not a traceback
                show_message(f"Error adding restriction: {e!s}", "error")


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
                    class1_disp = st.selectbox(
                        "Class 1",
                        options=cls_opts,
                        key="crel_class1",
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.CLASS_RELATIONS),
                        key="crel_type",
                    )
                with col3:
                    class2_disp = st.selectbox(
                        "Class 2",
                        options=cls_opts,
                        key="crel_class2",
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
                    if ext_err:
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
                    prop1_disp = st.selectbox(
                        "Property 1",
                        options=prop_opts,
                        key="prel_prop1",
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.PROPERTY_RELATIONS),
                        key="prel_type",
                    )
                with col3:
                    prop2_disp = st.selectbox(
                        "Property 2",
                        options=prop_opts,
                        key="prel_prop2",
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
                    if ext_err:
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
                    ind1_disp = st.selectbox(
                        "Individual 1",
                        options=ind_opts,
                        key="irel_ind1",
                        format_func=_pad_option,
                    )
                with col2:
                    relation_type = st.selectbox(
                        "Relation Type",
                        options=list(ont.INDIVIDUAL_RELATIONS),
                        key="irel_type",
                    )
                with col3:
                    ind2_disp = st.selectbox(
                        "Individual 2",
                        options=ind_opts,
                        key="irel_ind2",
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
                    if ext_err:
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


def resolve_annotation_predicate_choice(ont, choice, lookup) -> tuple:
    """Map the "Annotation Type" picker's value to a ``(predicate, error)`` pair.

    A listed type comes back through ``lookup`` as its URI and always resolves.
    Anything else was typed into the picker to create a new annotation type
    (issue #161), so it is validated first: an unbound prefix or an unusable name
    is reported rather than minted into a broken URI. ``error`` is None when the
    predicate is usable.
    """
    if choice in lookup:
        return lookup[choice], None
    text = (choice or "").strip()
    return text, ont.invalid_annotation_predicate_reason(text)


def _relation_spec(kind: str, ont, entities: list) -> dict:
    """Per-list settings for a relation row: the icon, the entities that can
    fill a slot, the relation types, the active-card kind and the engine calls.

    Keyed by the active-card kind — ``crel`` for class relations, ``prel`` for
    property ones, ``irel`` for individual ones. Built here rather than at each
    call site so the Visualization panel edits a class relation through exactly
    the settings the Relations page uses (issue #152).
    """
    return {
        "crel": {
            "icon": "📦",
            "kind": "crel",
            "noun": "classes",
            "label": "class relation",
            "entities": entities,
            "relation_types": ont.CLASS_RELATIONS,
            "remove": ont.remove_class_relation,
            "update": ont.update_class_relation,
        },
        "prel": {
            "icon": "🔗",
            "kind": "prel",
            "noun": "properties",
            "label": "property relation",
            "entities": entities,
            "relation_types": ont.PROPERTY_RELATIONS,
            "remove": ont.remove_property_relation,
            "update": ont.update_property_relation,
        },
        "irel": {
            "icon": "👤",
            "kind": "irel",
            "noun": "individuals",
            "label": "individual relation",
            "entities": entities,
            "relation_types": ont.INDIVIDUAL_RELATIONS,
            "remove": ont.remove_individual_relation,
            "update": ont.update_individual_relation,
        },
    }[kind]


def render_relation_rows(ont, rows, spec):
    """Render one relation section: a row each, with edit and delete.

    See :func:`_relation_spec` for what ``spec`` carries. Editing rewrites the
    triple in place rather than asking the user to delete and re-add it
    (issue #152).
    """
    for rel in rows:
        subj_uri = rel.get("subject_uri", rel["subject"])
        obj_uri = rel.get("object_uri", rel["object"])
        rel_uid = _uid(f"{subj_uri}|{rel['relation']}|{obj_uri}")
        icon = spec["icon"]

        col1, col2, col3, col_edit, col_del = st.columns([3, 2, 3, 0.7, 0.7])
        with col1:
            st.write(f"{icon} {rel['subject']}")
        with col2:
            st.write(f"➡️ {rel['relation']}")
        with col3:
            st.write(f"{icon} {rel['object']}")
        with col_edit:
            st.button(
                "✏️",
                key=f"edit_{spec['kind']}_{rel_uid}",
                help="Edit this relation",
                on_click=_cb_toggle_edit,
                args=(spec["kind"], rel_uid),
            )
        with col_del:
            if st.button(
                "🗑️", key=f"del_{spec['kind']}_{rel_uid}", help="Delete this relation"
            ):
                spec["remove"](subj_uri, rel["relation"], obj_uri)
                save_checkpoint(f"Delete {spec['label']}")
                show_message("Relation deleted!", "success")
                st.rerun()

        if not _is_open(spec["kind"], rel_uid, "edit"):
            continue

        render_relation_form(
            ont, rel, rel_uid, spec, on_close=lambda: _close_entity(spec["kind"])
        )


def render_relation_form(ont, rel, form_key, spec, on_close=None):
    """Render the edit form for one relation triple (issue #152).

    Shared by the Relations page rows and the Visualization details panel, so
    both write the same triple through the same guards. ``form_key`` makes the
    widget keys unique — the page passes the row's URI-derived id, the panel the
    selected edge's. ``on_close`` is what dismissing the editor means; the panel
    has no such thing (it follows the graph selection), so it passes None and
    gets no Cancel button.
    """
    subj_uri = rel.get("subject_uri", rel["subject"])
    obj_uri = rel.get("object_uri", rel["object"])

    # A relation may point at an entity this list doesn't hold — the add
    # forms accept an external URI. Offer it as its own option, or the
    # editor would silently rewrite it to the first local entity when the
    # user only meant to change the relation type (review P2).
    row_options, row_lookup = build_uri_options(spec["entities"])
    for endpoint in (subj_uri, obj_uri):
        if endpoint not in row_lookup.values():
            row_options.append(endpoint)
            row_lookup[endpoint] = endpoint

    with st.form(f"edit_form_{spec['kind']}_{form_key}"):
        # Slots are pre-set to the row's own values, so an edit that touches
        # one part leaves the rest exactly as asserted.
        subj_default = _uri_option_index(row_options, row_lookup, subj_uri)
        obj_default = _uri_option_index(row_options, row_lookup, obj_uri)
        types = list(spec["relation_types"])
        new_subject = st.selectbox(
            "Subject",
            row_options,
            index=subj_default,
            key=f"es_{form_key}",
            format_func=_pad_option,
        )
        new_type = st.selectbox(
            "Relation",
            types,
            index=types.index(rel["relation"]) if rel["relation"] in types else 0,
            key=f"et_{form_key}",
        )
        new_object = st.selectbox(
            "Object",
            row_options,
            index=obj_default,
            key=f"eo_{form_key}",
            format_func=_pad_option,
        )
        # The add forms can point an object at an entity in an ontology that
        # was never imported; without this the editor could keep such a
        # target but never set one.
        ext_obj_uri, ext_err = _external_uri_target(
            ont,
            row_lookup[new_object],
            key=f"eo_ext_{form_key}",
            label="the object",
        )
        cancelled = False
        if on_close is None:
            saved = st.form_submit_button("💾 Save", use_container_width=True)
        else:
            save_col, cancel_col = st.columns(2)
            with save_col:
                saved = st.form_submit_button("💾 Save", use_container_width=True)
            with cancel_col:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if cancelled:
            on_close()
            st.rerun()
        if saved:
            new_subj_uri = row_lookup[new_subject]
            new_obj_uri = ext_obj_uri
            if ext_err:
                show_message(ext_err, "error")
                return
            if new_subj_uri == new_obj_uri:
                # The add forms refuse this; the editor has to as well, or
                # it becomes the way to assert "A disjointWith A"
                # (review P2).
                show_message(f"Please select two different {spec['noun']}!", "error")
                return
            changed = spec["update"](
                (subj_uri, rel["relation"], obj_uri),
                (new_subj_uri, new_type, new_obj_uri),
            )
            if changed:
                save_checkpoint(f"Edit {spec['label']}")
                if on_close is not None:
                    on_close()
                set_flash_message("Relation updated!", "success")
                st.rerun()
            else:
                # The row was deleted or edited elsewhere since this list
                # was drawn; re-adding it under the new values would
                # resurrect a relation the user already removed.
                show_message(
                    "This relation is no longer in the ontology, so it "
                    "wasn't changed. Close the editor to refresh the list.",
                    "error",
                )


def _uri_option_index(options: list, lookup: dict, uri: str) -> int:
    """Index of the option standing for ``uri``, or 0 when it isn't listed
    (an external URI with no entity of its own)."""
    for i, option in enumerate(options):
        if lookup.get(option) == uri:
            return i
    return 0


def annotation_option_for_predicate(ont, predicate_lookup, predicate_uri):
    """Return the "Annotation Type" option that stands for ``predicate_uri``.

    Options are matched on the URI they resolve to, so one predicate written as
    a bare name, a CURIE or a full URI all find the same option (issue #161).
    Returns None when no option covers it.
    """
    for display, predicate in predicate_lookup.items():
        if ont.resolve_annotation_predicate(predicate) == predicate_uri:
            return display
    return None


def render_add_annotation(ont, all_resources):
    """Render the "Add Annotation" tab.

    Split out of :func:`render_annotations` so the form can be driven
    directly in tests: the page's tab picker is a ``segmented_control``, and
    Streamlit's AppTest mis-serializes a single-select one, so any
    interaction after switching tabs fails before reaching the form.
    """
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
                f"{p['prefix']}:{p['local_name']}" if p["prefix"] else p["local_name"]
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
                predicate_lookup[display] = p["uri"]  # Use short name for standard ones

        # Sort options
        predicate_options.sort(key=lambda x: x.lower())

        # Clear the value/language of the annotation just saved, on the run
        # after it was added: a widget's state can't be changed once it has
        # been instantiated, so the add flags it here instead. The type and
        # the resource are left alone, so the same type can be applied to one
        # resource after another without re-picking it.
        if st.session_state.pop("_ann_clear_value", False):
            st.session_state["ann_value"] = ""
            st.session_state["ann_lang"] = ""

        # Re-select the type just used. The picker holds whatever was typed
        # ("wikidataId"), but once the annotation exists the options carry that
        # predicate's canonical display ("ex:wikidataId") instead, and a value
        # that is not among the options cannot be held: the widget would snap
        # back to the first entry, and the stale typed value could reappear in a
        # different case.
        _ann_pending = st.session_state.pop("_ann_select_predicate", None)
        if _ann_pending:
            _ann_option = annotation_option_for_predicate(
                ont, predicate_lookup, _ann_pending
            )
            if _ann_option:
                st.session_state["ann_predicate"] = _ann_option

        with st.form("add_annotation_form"):
            # Use display format with label
            resource_options = [f"{r['display']} [{r['type']}]" for r in all_resources]
            selected = st.selectbox(
                "Select Resource",
                options=resource_options,
                key="ann_resource",
                format_func=_pad_option,
            )

            # Typing a type that isn't listed creates it, so an ID with no
            # standard predicate (a Wikidata item, an internal ticket) gets
            # its own annotation type instead of going into Comment
            # (issue #161). The explicit key matters: an unkeyed selectbox is
            # identified by its arguments, so adding an annotation — which
            # puts its type into the used-predicate options — would change
            # the widget's identity and snap the selection back to the first
            # entry.
            predicate_display = st.selectbox(
                "Annotation Type",
                options=predicate_options,
                accept_new_options=True,
                key="ann_predicate",
                help=(
                    "Pick a type, or type your own to create it: a name like "
                    "`wikidataId`, a bound prefix like `wdt:P31`, or a full "
                    "URI. A new name of your own is declared as an "
                    "annotation property in the ontology."
                ),
                format_func=_pad_option,
            )

            value = st.text_area("Value", key="ann_value")

            language = st.text_input(
                "Language Tag (optional)",
                placeholder="en, de, fr...",
                key="ann_lang",
            )

            submitted = st.form_submit_button("Add Annotation")
            if submitted:
                predicate_uri, predicate_reason = resolve_annotation_predicate_choice(
                    ont, predicate_display, predicate_lookup
                )
                if not value:
                    show_message("Value is required!", "error")
                elif predicate_reason:
                    show_message(predicate_reason, "error")
                else:
                    # Find the resource by matching the option string
                    idx = resource_options.index(selected)
                    resource_name = all_resources[idx]["name"]
                    ont.add_annotation(
                        resource_name,
                        predicate_uri,
                        value,
                        lang=language if language else None,
                    )
                    st.session_state["_ann_clear_value"] = True
                    st.session_state["_ann_select_predicate"] = (
                        ont.resolve_annotation_predicate(predicate_uri)
                    )
                    save_checkpoint("Add annotation")
                    show_message("Annotation added!", "success")
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
                            rel_target = st.selectbox(
                                "Target Concept",
                                _rel_opts,
                                key=f"rel_target_{_ck}",
                                format_func=_pad_option,
                            )
                            if st.button("Add", key=f"add_rel_{_ck}") and rel_target:
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
                            new_broader = st.selectbox(
                                "Broader Concept",
                                broader_options,
                                index=broader_options.index(_cur_broader_disp)
                                if _cur_broader_disp in broader_options
                                else 0,
                                key=f"broader_{_ck}",
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
                            new_scheme = st.selectbox(
                                "Scheme",
                                scheme_options,
                                index=scheme_options.index(_cur_scheme_disp)
                                if _cur_scheme_disp in scheme_options
                                else 0,
                                key=f"scheme_{_ck}",
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
            c_scheme = st.selectbox(
                "Scheme",
                ["None"] + scheme_opts,
                key="concept_scheme_select",
                format_func=_pad_option,
            )
            _add_broader_opts, _add_broader_lookup = build_uri_options(concepts)
            c_broader = st.selectbox(
                "Broader Concept",
                ["None"] + _add_broader_opts,
                key="concept_broader_select",
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


def build_class_hierarchy_text(classes):
    """Render the class list as an indented subClassOf tree.

    ``classes`` is the list returned by ``OntologyManager.get_classes()``.

    The traversal is iterative rather than recursive so a very deep hierarchy
    can't overflow the call stack and raise "maximum recursion depth exceeded"
    (issue #171). Each branch also tracks its ancestors and stops when it meets
    one again, marking it ``(cycle)`` instead of following the back-edge, so a
    subClassOf cycle (e.g. A ⊑ B and B ⊑ A) terminates too. After the normal
    roots are walked, any class not yet emitted is walked as an extra root, so
    disconnected or wholly-cyclic components are shown rather than dropped.
    """
    by_name = {}
    for c in classes:
        by_name.setdefault(c["name"], c)  # first wins, matching old lookup

    lines = []
    emitted = set()  # classes shown as a real node (not just a cycle back-edge)

    def walk(start):
        # Explicit stack of (name, level, ancestors-on-this-branch).
        stack = [(start, 0, frozenset())]
        while stack:
            cls_name, level, path = stack.pop()
            cls = by_name.get(cls_name)
            if not cls:
                continue
            prefix = "  " * level + ("└── " if level > 0 else "")
            label = f" ({cls['label']})" if cls["label"] else ""
            if cls_name in path:
                lines.append(f"{prefix}{cls['name']}{label}  (cycle)")
                continue
            lines.append(f"{prefix}{cls['name']}{label}")
            emitted.add(cls_name)
            child_path = path | {cls_name}
            # Push in reverse so children pop in their listed order.
            for child in reversed(cls["children"]):
                stack.append((child, level + 1, child_path))

    for c in classes:
        if not c["parents"]:
            walk(c["name"])
    # Cover components that no root reaches (disconnected trees, all-cyclic
    # ontologies, multiple detached cycles).
    for c in classes:
        if c["name"] not in emitted:
            walk(c["name"])

    return "\n".join(lines)


# The node kinds the Visualization filter can narrow. One entry per kind is all
# a new filter needs: the controls are rendered from this list, so adding a kind
# costs a segment in the selector rather than another block of UI (issue #196).
# ``toggle`` is the entity-type checkbox that has to be on for the kind to be in
# the graph at all; a kind whose toggle is off is not offered. ``singular`` is
# the prefix the Find-and-centre picker labels this kind with ("Class: Person").
_FILTER_KINDS = (
    {
        "key": "class",
        "toggle": "show_classes",
        "label": "Classes",
        "singular": "Class",
        "noun": "class",
        "plural": "classes",
    },
    {
        "key": "ind",
        "toggle": "show_individuals",
        "label": "Individuals",
        "singular": "Individual",
        "noun": "individual",
        "plural": "individuals",
    },
)


def reconcile_filter_selection(all_uris, selected, known, replaced=False):
    """Reconcile one Visualization filter's selection with the ontology.

    Diffs the current URIs against those seen on the previous render (``known``)
    rather than resetting on every edit, so adding an entity or a restriction no
    longer wipes a narrowed filter (issue #180):

    - entities deleted since last render drop out of the selection;
    - entities created since last render are added (new content is shown by
      default, matching the "everything selected" default);
    - the rest of the selection is left as-is, so a deliberately emptied filter
      stays empty (nothing is "new" when the user clears it).

    ``replaced`` marks that the whole ontology was swapped (load/import/new/undo)
    rather than incrementally edited. Diffing must not run then: an unrelated
    ontology that happens to reuse a URI could otherwise inherit its
    hidden/narrowed state and load with entities missing. On a replacement — or
    the first render, when ``selected``/``known`` is ``None`` — everything is
    shown. Returns ``(selected_list, known_set)`` where ``selected_list`` keeps
    the entity-list order.

    Entities are identified by URI, not by the label the filter displays: that
    label gains a namespace tag as soon as a second entity takes the same local
    name, and diffing on it would read every same-named entity as newly created
    and re-show a deliberately hidden one (issue #179 review).
    """
    all_set = set(all_uris)
    if replaced or selected is None or known is None:
        selected_set = set(all_uris)
    else:
        newly_added = all_set - known
        selected_set = (set(selected) | newly_added) & all_set
    ordered = [u for u in all_uris if u in selected_set]
    return ordered, all_set


# Pasted lists are split on whitespace, commas and semicolons, so any of the
# ways a list gets copied around (one per line, comma-separated, the token
# string the filter itself prints) parses the same way.
_CLASS_TOKEN_SEPARATORS = re.compile(r"[\s,;]+")
# Collapse "Person (foaf)" to "Person(foaf)" so the display form the multiselect
# shows survives whitespace splitting and stays one token.
_CLASS_DISPLAY_GAP = re.compile(r"\s+\(")


def build_filter_entries(items):
    """Describe entities for one Visualization filter's controls.

    ``items`` is any list of entity dicts carrying ``name`` and ``uri`` —
    classes or individuals today. Returns a list of dicts with the ``name`` and
    ``uri``, the ``prefix`` bound to its namespace, whether that local name is
    ``ambiguous`` (carried by more than one URI within this list), and the
    ``display`` string the filter lists — the same namespace-tagged form used
    everywhere else in the app, so two entities named ``zero`` show as
    ``zero (fn)`` / ``zero (ex)`` instead of two identical entries (issue #179).
    Order follows the input list.

    ``prefix`` is filled in for every entity, not only ambiguous ones, so
    ``foaf:Agent`` is accepted on paste even where ``Agent`` is unique.
    """
    collisions = _build_name_collision_set(items)
    entries = []
    for it in items:
        name = it.get("name") or ""
        uri = it.get("uri") or ""
        entries.append(
            {
                "name": name,
                "uri": uri,
                "ambiguous": name in collisions,
                "prefix": _prefix_for_uri(uri),
                "display": _disambiguated_name(it, collisions),
            }
        )
    return entries


def filter_entry_token(entry):
    """Round-trippable token for one filter entry.

    An unambiguous entity is just its local name; an ambiguous one is written
    ``prefix:Name`` (the syntax issue #179 asks for), falling back to the full
    URI when its namespace has no bound prefix. Tokens are what the filter
    prints for copying and what :func:`parse_filter_text` reads back.
    """
    if not entry["ambiguous"]:
        return entry["name"]
    if entry["prefix"]:
        return f"{entry['prefix']}:{entry['name']}"
    return entry["uri"] or entry["name"]


def parse_filter_text(text, entries):
    """Resolve pasted names against one filter's entries.

    Accepts whitespace-, comma- or semicolon-separated tokens in any of the
    forms the app shows an entity in: a plain local name (``Person``), a prefixed
    name (``fn:zero``), the disambiguated display form (``zero (fn)``) or a full
    URI, optionally wrapped in ``<>`` or quotes. Matching is exact first, then
    case-insensitive. A plain local name shared by several namespaces selects
    all of them — the prefixed form picks just one.

    Returns ``(uris, unmatched)``: the matched URIs in entry-list order
    without repeats, and the tokens nothing matched, in input order. URIs rather
    than display labels, because the selection is stored by URI.
    """
    if not text or not text.strip():
        return [], []

    exact: dict[str, list[str]] = {}
    lowered: dict[str, list[str]] = {}
    order: dict[str, int] = {}

    def _register(key, uri):
        for table, k in ((exact, key), (lowered, key.lower())):
            if not k:
                continue
            bucket = table.setdefault(k, [])
            if uri not in bucket:
                bucket.append(uri)

    for index, entry in enumerate(entries):
        uri = entry["uri"]
        if not uri:
            continue
        order.setdefault(uri, index)
        _register(entry["name"], uri)
        _register(entry["display"], uri)
        _register(_CLASS_DISPLAY_GAP.sub("(", entry["display"]), uri)
        _register(uri, uri)
        if entry["prefix"]:
            _register(f"{entry['prefix']}:{entry['name']}", uri)

    matched: list[str] = []
    unmatched: list[str] = []
    seen: set[str] = set()
    for raw in _CLASS_TOKEN_SEPARATORS.split(_CLASS_DISPLAY_GAP.sub("(", text)):
        token = raw.strip().strip("\"'")
        if token.startswith("<") and token.endswith(">"):
            token = token[1:-1]
        if not token:
            continue
        hits = exact.get(token) or lowered.get(token.lower())
        if not hits:
            if token not in unmatched:
                unmatched.append(token)
            continue
        for uri in hits:
            if uri not in seen:
                seen.add(uri)
                matched.append(uri)

    matched.sort(key=lambda u: order.get(u, 0))
    return matched, unmatched


def _fmt_unknown(tokens, limit=20):
    """Render unmatched paste tokens for a warning, capped so a wholly wrong
    paste doesn't fill the panel."""
    shown = ", ".join(tokens[:limit])
    return f"{shown} (+{len(tokens) - limit} more)" if len(tokens) > limit else shown


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

        _cols = (
            st.columns([1, 1, 1, 1, 1, 1, 1, 1])
            if _has_skos
            else st.columns([1, 1, 1, 1, 1, 1, 1])
        )
        with _cols[0]:
            show_classes = st.checkbox(
                "Classes",
                key="viz_show_classes",
                on_change=viz_sync,
                args=("_viz_cfg_show_classes", "viz_show_classes"),
            )
        with _cols[1]:
            show_properties = st.checkbox(
                "Obj Props",
                key="viz_show_obj_props",
                on_change=viz_sync,
                args=("_viz_cfg_show_obj_props", "viz_show_obj_props"),
            )
        with _cols[2]:
            show_data_props = st.checkbox(
                "Data Props",
                key="viz_show_data_props",
                on_change=viz_sync,
                args=("_viz_cfg_show_data_props", "viz_show_data_props"),
            )
        with _cols[3]:
            show_annotations = st.checkbox(
                "Annotations",
                key="viz_show_annotations",
                on_change=viz_sync,
                args=("_viz_cfg_show_annotations", "viz_show_annotations"),
            )
        with _cols[4]:
            show_individuals = st.checkbox(
                "Individuals",
                key="viz_show_individuals",
                on_change=viz_sync,
                args=("_viz_cfg_show_individuals", "viz_show_individuals"),
            )
        if _has_skos:
            with _cols[5]:
                show_skos = st.checkbox(
                    "SKOS",
                    key="viz_show_skos",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_skos", "viz_show_skos"),
                )
            with _cols[6]:
                show_ind_edges = st.checkbox(
                    "Ind. Edges",
                    key="viz_show_ind_edges",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_ind_edges", "viz_show_ind_edges"),
                    help="Show property edges between individuals",
                )
            with _cols[7]:
                show_triples = st.checkbox(
                    "Triples",
                    key="viz_show_triples",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_triples", "viz_show_triples"),
                    help="Show all RDF triples for visible nodes",
                )
        else:
            show_skos = False
            with _cols[5]:
                show_ind_edges = st.checkbox(
                    "Ind. Edges",
                    key="viz_show_ind_edges",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_ind_edges", "viz_show_ind_edges"),
                    help="Show property edges between individuals",
                )
            with _cols[6]:
                show_triples = st.checkbox(
                    "Triples",
                    key="viz_show_triples",
                    on_change=viz_sync,
                    args=("_viz_cfg_show_triples", "viz_show_triples"),
                    help="Show all RDF triples for visible nodes",
                )

        # Row 2: sliders + fit-to-window + highlight issues + render button
        col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
        with col1:
            height = st.slider(
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
            node_spacing = st.slider(
                "Node Spacing",
                50,
                300,
                help="Distance between nodes. Increase for less overlap.",
                key="viz_node_spacing",
                on_change=viz_sync,
                args=("_viz_cfg_node_spacing", "viz_node_spacing"),
            )
        with col3:
            fit = st.checkbox(
                "Fit to window",
                help="Resize the graph to fill the window height. "
                "Turn off to use the Graph Height slider.",
                key="viz_fit",
                on_change=viz_sync,
                args=("_viz_cfg_fit", "viz_fit"),
            )
        with col4:
            highlight_issues = st.checkbox(
                "Highlight Issues",
                key="viz_highlight_issues",
                on_change=viz_sync,
                args=("_viz_cfg_highlight_issues", "viz_highlight_issues"),
            )
        with col5:
            render_graph = st.button(
                "Render",
                type="primary",
                use_container_width=True,
                help="Redraw the graph and re-run the layout. Also re-centres on "
                "the current Find selection.",
            )

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
        focus_seed_ids: list = []
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
                        _label, _, _name = _find_choice.partition(": ")
                        _reveal_rerun = False
                        # Every filterable kind can hide its entity, so look the
                        # picked label up across them rather than only classes.
                        for _fk in _FILTER_KINDS:
                            if _label != _fk["singular"]:
                                continue
                            _key = _fk["key"]
                            _uri = filters[_key]["uri_by_display"].get(_name)
                            _sel = list(
                                st.session_state.get(f"_viz_cfg_selected_{_key}_uris")
                                or []
                            )
                            if _uri and _uri not in _sel:
                                st.session_state[f"_viz_cfg_selected_{_key}_uris"] = (
                                    _sel + [_uri]
                                )
                                _reveal_rerun = True
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
        with _filter_col.expander("Filter Nodes", expanded=False):
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
        _graph_ver = 18  # Bump to invalidate cached graph data after code changes
        # Include a mutation counter that bumps on every checkpoint / undo / redo,
        # so any change to the ontology — even one that preserves triple count —
        # invalidates the cached graph data and the iframe re-renders.
        ont_mutation = st.session_state.get("_ont_mutation_count", 0)
        graph_key = f"v{_graph_ver}_m{ont_mutation}_{show_classes}_{show_properties}_{show_data_props}_{show_annotations}_{show_individuals}_{show_ind_edges}_{show_skos}_{show_triples}_{height}_{node_spacing}_{highlight_issues}_{hash(selected_classes_key)}_{hash(selected_inds_key)}_{focus_mode}_{'-'.join(sorted(focus_seed_ids))}_{focus_depth}"
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
            if show_classes and selected_classes:
                for cls in classes:
                    if node_count >= max_nodes:
                        break
                    if cls["uri"] not in visible_class_uris:
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
                ind_collisions = _build_name_collision_set(individuals)
                for ind in individuals:
                    if node_count >= max_nodes:
                        break
                    # Individuals filter (issue #196). Focus mode builds the full
                    # graph and prunes afterwards, so it ignores the filter the
                    # same way the class one does.
                    if not focus_mode and ind["uri"] not in selected_ind_uris:
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
                annotation_counter = 0
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
            if show_skos and node_count < max_nodes:
                concepts = ont.get_concepts()
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
            if focus_pruning:
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
                    # Cached with the graph so it survives the reruns that reuse
                    # it, rather than flashing once on the build that found it.
                    "notice": graph_notice,
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
                st.session_state["_viz_last_selection"] = (
                    _live_sel if _live_sel.get("selected") else None
                )
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
                    elif not has_selection:
                        st.caption(
                            "Click a node to see details. Ctrl/Cmd-click focuses on it."
                        )
                        _render_panel_add_class_button(classes, None, None)
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
                        _render_panel_add_class_button(classes, ntype, ename)
                        _render_panel_add_relation_button(classes, ntype, ename)
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

"""Shared UI helpers for the Streamlit pages.

Everything the pages have in common: session and flash state, the undo
checkpoint, the option builders behind every dropdown, and the entity forms that
the pages and the Visualization details panel render through the same code.

Split out of ``app.py`` when that reached 11.5k lines. The layering is the point,
not the line count: this module knows nothing about the pages, the pages import
from here, and ``app.py`` is left with the shell that wires them together — so a
page can no longer quietly reach into another page's internals.

``app.py`` re-exports these names, which is what the tests and the top-level
compatibility shims address them by.
"""

import hashlib
import html
import json
import logging
import re
import time
import traceback
from datetime import datetime
from itertools import pairwise
from pathlib import Path as _Path

import streamlit as st

from . import languages, local_store

"""
OrionBelt Ontology Builder - A Streamlit application for building, editing,
and managing OWL ontologies.
"""
APP_NAME = "OrionBelt Ontology Builder"
APP_VERSION = "1.27.1"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
GITHUB_ISSUES_URL = "https://github.com/ralforion/orionbelt-ontology-builder/issues"
AUTOSAVE_KEY = "orionbelt_ontology_builder_autosave"
AUTOSAVE_MAX_BYTES = 4_000_000
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
    "node_spacing",
    "highlight_issues",
    "auto_show_new",
    "details_panel",
    "focus_mode",
    "focus_depth",
    "options_open",
    "path_panel",
    "find_row_open",
)
_VIZ_INT_RANGES = {
    "node_spacing": (50, 300),
    "focus_depth": (1, 5),
}
VIZ_FILE_STATE_KEY = "viz_file_state"
VIZ_FILE_STATE_MAX_FILES = 20
#: Where the chosen language pack and any custom ones are stored (issue #252) —
#: the local config file when the launcher allows disk, browser localStorage on
#: the cloud, the same two places the viz settings use.
LANG_PACKS_KEY = "orionbelt_language_packs"
#: Session key holding the active pack's name. Deliberately not a widget's key:
#: two pickers choose the pack (the sidebar's and the Language Packs tab's, which
#: are one choice, issue #293), and a widget's key cannot be assigned once its
#: widget is on the page — this one can be written from anywhere.
ACTIVE_LANG_PACK_KEY = "lang_pack_active"
#: The sidebar pack picker's own widget key, mirrored from the key above.
LANG_PACK_SIDEBAR_KEY = "lang_pack_sidebar_select"
#: The Language Packs tab's pack picker, the app's other view of the same choice.
LANG_PACK_TAB_KEY = "lang_pack_edit_select"
#: Session key holding ``{pack name: [{"code", "label"}, ...]}`` of the user's
#: own packs.
CUSTOM_LANG_PACKS_KEY = "lang_packs_custom"
#: Where the SPARQL page's editor state — the query and the plain-editor choice
#: — is kept (issue #388): the local config file when the launcher allows disk,
#: browser localStorage on the cloud, the same two places the viz settings and
#: the language packs use.
SPARQL_STATE_KEY = "orionbelt_sparql_state"
#: Session key holding the query being written. Deliberately not a widget's key:
#: two editors write one query (see ``views.sparql``), and a widget's state is
#: dropped the moment its widget stops being rendered.
SPARQL_QUERY_KEY = "sparql_query_text"
#: Session key holding the plain-editor choice, and for the same reason: the
#: toggle's own key went with the page, so coming back from another page put the
#: highlighted editor back whatever had been chosen (issue #388).
SPARQL_PLAIN_KEY = "_sparql_cfg_plain_editor"
#: Longest query kept. A query is a screen or two of text; the cap is here so a
#: pasted-in wall of SPARQL cannot crowd out the ontology's own autosave, which
#: shares the browser's storage.
SPARQL_QUERY_MAX_CHARS = 20_000
#: The page's two limits, stored alongside the query. Session keys are these
#: names under ``_sparql_cfg_``; see ``views.sparql`` for the widgets they seed.
SPARQL_LIMIT_KEYS = ("max_rows", "timeout_seconds")
AUTOSAVE_DEBOUNCE_SECONDS = 2.0
# The package directory, not this module's: assets are the package's, and a
# module that moves into a subpackage must not take their paths with it — the
# graph component broke exactly that way when the pages were split out.
PKG_DIR = _Path(__file__).resolve().parent
_FAVICON = PKG_DIR / "favicon.png"
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
    /* CSS injected through st.markdown leaves an empty element behind, which
       is invisible but still takes a slot in the page column's 16px gap grid.
       Four of them ride above the graph, so the canvas started ~64px lower than
       it had to. Nothing to show, so take them out of the flow.

       Descendant combinators, not the child chain this used to be written as:
       Streamlit put another wrapper div between the markdown element and its
       container, the chain stopped matching, and all four blocks quietly came
       back into the layout (measured: 0 elements matched, 4 in the page). The
       `style:only-child` test is what makes this safe — a markdown block with
       anything to show never matches. */
    [data-testid="stElementContainer"]:has(
        [data-testid="stMarkdownContainer"] > style:only-child
    ) {
        display: none !important;
    }
    /* The browser-storage component has nothing to show, but Streamlit still
       lays its iframe out — a 26px band, plus the column's 16px gap, wherever
       the write happens to be called (on the graph page, right above the
       canvas). Take it out of the flow rather than hiding it: a display:none
       or visibility:hidden iframe is a document that may never run, and this
       one has a write to localStorage to perform. */
    [data-testid="stElementContainer"]:has(
        iframe[src*="streamlit_local_storage"]
    ) {
        position: absolute !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        pointer-events: none;
    }
    /* Reduce margin/padding. The side gutters are Streamlit's own 80px, which
       on a wide screen is 160px the graph could be using; 2rem still keeps text
       pages off the window edge.

       The top has a floor: Streamlit's header is an opaque 60px bar painted at
       z-index 999990, so anything above 3.75rem is painted over rather than
       scrolled under. 4rem clears it with a little air. It used to be 2.5rem
       and looked fine only because the CSS blocks above the title were each
       taking a 16px slot in the column; once those went out of the flow, the
       first line of the page slid under the header. */
    .block-container, .stMainBlockContainer,
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 4rem !important;
        padding-bottom: 0 !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
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
    /* Sidebar density. Streamlit's defaults put 16px between every element,
       64px around each divider and 96px of padding under the last one, which
       together pushed Quick Stats off the bottom of a 1080p screen. Measured
       in the browser: this recovers ~270px, enough for the whole sidebar to
       fit without scrolling.
       NOTE: internal DOM again — re-verify on a Streamlit bump. */
    /* The "what is hidden" note, which rides on the Node options label as
       generated content — not as part of the label text, which would force the
       expander shut on every filter edit (see viz_hidden_note_style, #267).
       Quieter than the label it follows, and gone once the expander is open:
       the controls inside then say the same thing in full. Scoped by the
       container key so no other expander's label is touched.
       The text itself comes from --viz-hidden-note, set per render. */
    .st-key-viz_filter_nodes summary p::after {
        content: var(--viz-hidden-note, "");
        margin-left: 0.75rem;
        font-size: 0.8rem;
        opacity: 0.55;
    }
    .st-key-viz_filter_nodes details[open] summary p::after {
        content: "";
        margin-left: 0;
    }
    /* The SPARQL editor. A query is code: proportional type misaligns the
       indentation that shows how a WHERE block nests, and makes it hard to see
       that ?s and ?5 differ. Scoped by the container key so every other text
       area in the app keeps the UI font. */
    .st-key-sparql_editor textarea {
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
                     "Liberation Mono", monospace !important;
        font-size: 0.86rem !important;
        line-height: 1.55 !important;
        tab-size: 2;
    }
    [data-testid="stSidebarHeader"] [data-testid="stLogoSpacer"] {
        /* Reserves room for a st.logo() this app doesn't set: the mark is
           rendered as an image in the sidebar body instead. */
        display: none !important;
    }
    [data-testid="stSidebarHeader"] {
        /* 60px tall plus a 16px margin, to hold a 28px collapse button, all
           of it above the logo. Sized to the button instead, which keeps it
           clear of the logo underneath. */
        height: 2.5rem !important;
        min-height: 2.5rem !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        margin-bottom: 0 !important;
    }
    [data-testid="stSidebarUserContent"] {
        padding-bottom: 1.5rem !important;
    }
    [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
        gap: 0.5rem !important;
    }
    [data-testid="stSidebar"] hr {
        margin-top: 0.4rem !important;
        margin-bottom: 0.4rem !important;
    }
    [data-testid="stSidebar"] h1 {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        margin-bottom: 0.2rem !important;
    }
</style>
"""
_BRAND = local_store.BRAND_PRIMARY_COLOR  # "#0D2B7A"
_BRAND_TINT = "rgba(13, 43, 122, 0.12)"
_BRAND_CSS = f"""
<style>
    /* Every hook below names Streamlit's own DOM, which is internal and moves
       without notice: 1.62 rebuilt these widgets on react-aria, and every
       ``[data-baseweb=...]`` selector this file used stopped matching in
       silence (issue #368). Re-check them in the browser whenever the Streamlit
       pin moves — the check is to inspect a rendered widget and confirm the
       element carrying the accent is still the one named here. */

    /* Primary buttons */
    [data-testid="stBaseButton-primary"] {{
        background-color: {_BRAND} !important;
        border-color: {_BRAND} !important;
    }}
    /* The box of a checked checkbox, and the track of a toggle that is on:
       st.toggle reuses stCheckbox's testid, and in 1.62 both mark the state on
       the label, so one rule covers the pair.

       ``:not([data-testid])`` is what separates the mark from the words beside
       it. Both are plain divs directly under the label; only the label carries a
       testid (stWidgetLabel). Without it this paints the text's background too,
       and every checked checkbox reads as highlighted. The radio and slider
       rules below exclude their own labels the same way. */
    [data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid]) {{
        background-color: {_BRAND} !important;
        border-color: {_BRAND} !important;
    }}
    /* The dot inside a selected radio, not the label wrapper (which carries a
       hover/focus tint of its own). */
    label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:not([data-testid]) {{
        background-color: {_BRAND} !important;
    }}
    /* Active segmented-control pill (the page tab pickers). Selected by ARIA
       state rather than by a testid: the testid this used to name,
       ``stBaseButton-segmented_controlActive``, is not on the button in 1.62.
       No ``color`` here — Streamlit paints the active label with the configured
       primaryColor, which is the brand navy and reads at 12.8:1 on a light
       background. Dark backgrounds are where that fails, and _DARK_CSS
       overrides it there. */
    button[data-variant="segmented_control"][aria-checked="true"] {{
        border-color: {_BRAND} !important;
        background-color: {_BRAND_TINT} !important;
    }}
    /* Slider thumb and its floating value label. There is no [role=slider] in
       1.62; the thumb is an unlabelled div, told apart from the rail beside it
       by the value label it carries. */
    [data-testid="stSlider"] div:has(> [data-testid="stSliderThumbValue"]) {{
        background-color: {_BRAND} !important;
    }}
    [data-testid="stSliderThumbValue"] {{
        color: {_BRAND} !important;
    }}
    /* Slider rail: the filled portion's colour (red on a reset theme) is baked
       into a per-value class we cannot recolour selectively, so the whole bar is
       neutralised — no red shows, and the thumb marks the position. Painting the
       rail with the accent instead would colour the unfilled half too, which
       says the slider is at its maximum. It is the childless div; the thumb is
       the one with the value label inside. */
    [data-testid="stSlider"] > div > div > div:not([data-testid]):not(:has(*)) {{
        background: rgba(151, 166, 195, 0.25) !important;
    }}
    /* Multiselect selected chips */
    [data-testid="stMultiSelectTagsContainer"] > span > span {{
        background-color: {_BRAND} !important;
    }}
</style>
"""
#: Accent *text* on a dark backdrop: links, the slider value. The brand navy is
#: 1.48:1 against Streamlit's dark background and cannot be read there at all;
#: this is 4.35:1, which is as dark as text in this family can go and stay
#: near the 4.5:1 AA asks of body text.
_DARK_ACCENT = "#4275DE"
#: Filled controls: a button, a checkbox, a radio dot, a slider thumb, and the
#: active tab. One step darker than the text accent, which buys the white label
#: they all carry 5.8:1 instead of 4.35:1, while the control itself still clears
#: the 3:1 WCAG asks against its surroundings (3.26:1). The two are a step apart
#: on purpose and read as one family; going darker still would take the link
#: text down with it, since for a colour used both ways the two numbers move
#: together.
_DARK_FILL = "#3560C4"
_DARK_CSS = f"""
<style>
    /* The active pill is filled rather than written in the accent. Streamlit
       paints its label with primaryColor, and the brand navy is 1.48:1 on
       Streamlit's dark background — the single unreadable label on the page,
       which is issue #368. Writing it in the accent fixed that but left the
       selected tab dimmer than the two unselected ones beside it, which read at
       18:1 in the theme's own white: the selected item looked like the weakest.
       Filled, it is the strongest, it matches the button, and the accent is
       never dim text — the tint below is left to the light theme. */
    button[data-variant="segmented_control"][aria-checked="true"] {{
        color: #FFFFFF !important;
        border-color: {_DARK_FILL} !important;
        background-color: {_DARK_FILL} !important;
    }}
    [data-testid="stSliderThumbValue"] {{
        color: {_DARK_ACCENT} !important;
    }}
    /* Links, which Streamlit draws in a blue of its own (#3D9DF3) that belongs
       to no other accent on the page. On the accent they read at 7.8:1 and look
       like the rest of the theme. */
    a,
    a:visited {{
        color: {_DARK_ACCENT} !important;
    }}
    /* The filled controls take the same accent as the text above: one blue for
       the whole theme. They keep their white labels, which is half of what set
       the colour — see _DARK_ACCENT. */
    [data-testid="stBaseButton-primary"] {{
        background-color: {_DARK_FILL} !important;
        border-color: {_DARK_FILL} !important;
    }}
    [data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid]) {{
        background-color: {_DARK_FILL} !important;
        border-color: {_DARK_FILL} !important;
    }}
    label[data-testid="stRadioOption"][data-selected="true"] > div > div > div:not([data-testid]) {{
        background-color: {_DARK_FILL} !important;
    }}
    [data-testid="stSlider"] div:has(> [data-testid="stSliderThumbValue"]) {{
        background-color: {_DARK_FILL} !important;
    }}
    [data-testid="stMultiSelectTagsContainer"] > span > span {{
        background-color: {_DARK_FILL} !important;
    }}
</style>
"""


#: A background counts as dark when white text reads better on it than black
#: does. That is where the two contrast ratios cross, at a relative luminance of
#: 0.179 by the W3C formula.
_DARK_BACKGROUND_LUMINANCE = 0.179


def _relative_luminance(colour: str) -> float | None:
    """The W3C relative luminance of a CSS colour, or ``None`` if unreadable.

    Streamlit hands a configured theme colour to the browser untouched, so it
    can be any CSS colour at all: verified against 1.62, ``rgb(3,4,5)``,
    ``#030405ff`` and ``black`` all render. The hex forms and the ``rgb()``
    family are read here; a colour name, ``hsl()``, ``oklch()`` and the rest are
    not, and deliberately so — knowing them all means carrying CSS's 148 colour
    names and its colour spaces around. ``None`` is the "cannot say" answer, and
    :func:`theme_is_dark` falls back to the theme's reported type rather than
    guessing from a colour it did not understand.

    Alpha is accepted and ignored: what sits behind a translucent background is
    the browser's, not ours, and the opaque colour is the better guess of the
    two.
    """
    text = colour.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):  # #rgb, #rgba
            digits = "".join(digit * 2 for digit in digits[:3])
        elif len(digits) in (6, 8):  # #rrggbb, #rrggbbaa
            digits = digits[:6]
        else:
            return None
        try:
            channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        except ValueError:
            return None
    elif text.startswith(("rgb(", "rgba(")) and text.endswith(")"):
        # Commas or spaces, and a "/ alpha" tail: rgb(3, 4, 5), rgb(3 4 5) and
        # rgb(3 4 5 / 50%) are all the same colour. Percentages are not read.
        parts = (
            text[text.index("(") + 1 : -1].replace(",", " ").replace("/", " ").split()
        )
        if len(parts) < 3:
            return None
        try:
            channels = [float(part) / 255 for part in parts[:3]]
        except ValueError:
            return None
        if any(not 0.0 <= channel <= 1.0 for channel in channels):
            return None
    else:
        return None
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def theme_is_dark() -> bool:
    """Is the app being drawn on a dark background?

    ``st.context.theme`` reports the theme's *base*, and a config.toml that
    overrides only colours has no base — so an app themed to a near-black
    background still reports ``light``, the dark styling never loads, and the
    navy accents land on black (issue #368). Where the type says light, the
    configured background colour is the better witness, and it is a colour, so
    it can simply be measured.

    Both lookups are guarded: ``st.context`` is unavailable outside a script
    run, and the option is absent unless a theme sets it.
    """
    try:
        if st.context.theme.get("type") == "dark":
            return True
    except Exception:  # theme detection is cosmetic, never fatal
        logger.debug(
            "Theme type unavailable; reading the configured colour", exc_info=True
        )
    try:
        background = st.get_option("theme.backgroundColor")
    except Exception:  # as above
        logger.debug("Theme background unavailable; assuming light", exc_info=True)
        return False
    if not background:
        return False
    luminance = _relative_luminance(str(background))
    return luminance is not None and luminance < _DARK_BACKGROUND_LUMINANCE


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


def _content_hash(text: str) -> str:
    """Stable hash of a serialized ontology, used to skip redundant autosaves."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


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


def _persist_viz_settings() -> None:
    """Save the current viz display settings after the user changes one (#142).

    Gated on an explicit change (the dirty flag set by the settings callbacks),
    not merely on the page rendering: otherwise a cloud reload could write the
    starting defaults back over a saved set before localStorage had answered
    (PR #142 review P1).

    Only the disk write is finished by the time this returns, and only it is
    recorded as saved. The browser one is a component render, and a pass that
    ends in ``st.rerun()`` is discarded along with everything it drew — which
    is the usual pass here, because changing a setting often moves the
    hidden-note count and that recompute reruns the page. Recording it as saved
    there made the loss permanent: the next pass found the payload already
    saved and never rendered the component again, so the setting was gone on
    the next reload. So the browser path re-offers the payload until a pass
    survives to carry it. The component is keyed by the payload's hash, so
    those are all the same component writing the same value, not a queue of
    writes (issue #326: turning "Auto-show new" on takes in what was queued,
    which moves that count, so the very first use hit this every time).
    """
    if not st.session_state.get("_viz_settings_dirty"):
        return
    payload = _viz_settings_payload()
    if local_store.local_persist_enabled():
        if payload == st.session_state.get("_viz_settings_saved_json"):
            return
        try:
            cfg = local_store.load_config()
            cfg["viz_settings"] = json.loads(payload)
            local_store.save_config(cfg)
        except OSError as e:
            log_error(e, context="Viz settings save")
            return
        st.session_state["_viz_settings_saved_json"] = payload
        return
    ls = _get_local_storage()
    if ls is None:
        return
    h = _content_hash(payload)
    ls.setItem(VIZ_SETTINGS_KEY, payload, key=f"orionbelt_viz_settings_set_{h[:12]}")


def custom_language_packs() -> dict[str, list[dict]]:
    """The user's own language packs, ``{name: [{"code", "label"}, ...]}``."""
    packs = st.session_state.get(CUSTOM_LANG_PACKS_KEY)
    return packs if isinstance(packs, dict) else {}


def language_pack_names() -> list[str]:
    """Every pack the picker offers: the built-in ones, then the user's."""
    return [*languages.BUILTIN_PACKS, *sorted(custom_language_packs())]


def active_language_pack() -> str:
    """The pack the Language fields are currently drawing their codes from.

    Falls back to the default when the saved name names nothing — the choice
    outlives the session that made it, and a custom pack deleted since must not
    empty every Language dropdown in the app.
    """
    name = st.session_state.get(ACTIVE_LANG_PACK_KEY)
    if isinstance(name, str) and name in language_pack_names():
        return name
    return languages.DEFAULT_PACK


def language_pack_entries(pack: str | None = None) -> list[dict]:
    """``[{"code", "label"}, ...]`` for a pack, the active one by default."""
    name = pack or active_language_pack()
    custom = custom_language_packs()
    if name in custom:
        return [dict(e) for e in custom[name]]
    return languages.builtin_pack(name)


def _mark_language_packs_dirty() -> None:
    """Note that the packs or the choice of one changed, so it is worth saving.

    Same gate as the viz settings: writing on every run would let a cloud reload
    put the starting defaults back over the saved set before localStorage had
    answered.
    """
    st.session_state["_lang_packs_dirty"] = True


def set_active_language_pack(name: str) -> None:
    """Make ``name`` the pack every Language field draws from (issue #293).

    The one place the choice is made, whoever makes it: the sidebar picker, the
    Language Packs tab's picker, and creating or deleting a pack all come through
    here, so the pack being edited and the pack in use are never two things.

    A name no pack answers to is ignored rather than stored — the callers offer
    the pack names as options, so a name that is not one is a stale value, not a
    choice. The write goes to the plain session key rather than to either
    picker's widget key, which is what lets a page drawn *after* the sidebar set
    the pack: assigning a widget's key once its widget exists is an exception.
    """
    if name not in language_pack_names():
        return
    if name == st.session_state.get(ACTIVE_LANG_PACK_KEY):
        return
    st.session_state[ACTIVE_LANG_PACK_KEY] = name
    _mark_language_packs_dirty()


def seed_language_pack_picker(widget_key: str) -> str:
    """Point one pack picker at the active pack, returning that pack's name.

    Called by each picker before it is drawn, which is how the two of them stay
    one choice. A seed rather than an ``index``: a widget given both a default
    and a session-state value draws a warning above the page. It also resolves a
    pack deleted since it was chosen to a name the options actually include —
    a selectbox value with no matching option is an exception, not a fallback.
    """
    active = active_language_pack()
    if st.session_state.get(widget_key) != active:
        st.session_state[widget_key] = active
    return active


def _language_pack_picked(widget_key: str) -> None:
    """``on_change`` for a pack picker: what it now shows becomes the pack in use.

    Necessary rather than incidental: the seed above runs on every rerun, so
    without this the run that follows a pick would put the old pack straight
    back into the picker.
    """
    set_active_language_pack(st.session_state.get(widget_key, ""))


def save_custom_language_pack(name: str, entries) -> str | None:
    """Store one custom pack, returning the reason it was refused, or ``None``.

    Refuses a built-in's name rather than shadowing it: the built-ins are how
    you get back to a known list, and a pack that quietly replaced one would
    leave no way back.
    """
    name = (name or "").strip()
    if not name:
        return "A pack name is required."
    if name in languages.BUILTIN_PACKS:
        return f"'{name}' is a built-in pack. Choose another name."
    cleaned, errors = languages.normalize_pack(entries)
    if errors:
        return errors[0]
    # An empty pack is allowed: it is what starting one from scratch looks like
    # before the first row is typed, and a Language field with no options still
    # takes a typed tag.
    st.session_state[CUSTOM_LANG_PACKS_KEY] = {**custom_language_packs(), name: cleaned}
    _mark_language_packs_dirty()
    return None


def delete_custom_language_pack(name: str) -> None:
    """Drop one custom pack.

    Deleting the pack that is in use may leave its name in
    :data:`ACTIVE_LANG_PACK_KEY`; the caller is what points the choice somewhere
    else. Either way nothing is left dangling for a reader:
    :func:`active_language_pack` resolves a name no pack answers to back to the
    default, and both pickers re-seed from it on the next run.
    """
    packs = {k: v for k, v in custom_language_packs().items() if k != name}
    st.session_state[CUSTOM_LANG_PACKS_KEY] = packs
    _mark_language_packs_dirty()


def _language_packs_payload() -> str:
    """Serialize the packs and the active choice for change detection/storage."""
    return json.dumps(
        {"active": active_language_pack(), "packs": custom_language_packs()},
        sort_keys=True,
    )


def _apply_language_packs(data) -> None:
    """Seed the session from a stored payload, dropping anything malformed.

    Storage is a file or a browser the user can edit, so every pack is put back
    through the same validation an edited one goes through.
    """
    if not isinstance(data, dict):
        return
    raw = data.get("packs")
    packs: dict[str, list[dict]] = {}
    if isinstance(raw, dict):
        for name, entries in raw.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(entries, list):
                continue
            # The same refusal :func:`save_custom_language_pack` makes, applied
            # again on the way in: storage is a file the user can edit, and a
            # custom pack under a built-in's name would take that name's place
            # (entries are looked up in the custom packs first) while the tab
            # still showed it as a read-only built-in with no way back.
            if name in languages.BUILTIN_PACKS:
                continue
            cleaned, errors = languages.normalize_pack(entries)
            # An empty list is a pack that has been started and not filled in,
            # which is savable — dropping it here would also drop the choice of
            # it as the active pack on the next launch.
            if not errors:
                packs[name] = cleaned
    st.session_state[CUSTOM_LANG_PACKS_KEY] = packs
    active = data.get("active")
    if isinstance(active, str) and (
        active in languages.BUILTIN_PACKS or active in packs
    ):
        st.session_state[ACTIVE_LANG_PACK_KEY] = active


def restore_language_packs() -> None:
    """Restore the saved packs and pack choice once per session (issue #252).

    Mirrors :func:`_restore_viz_settings`, including its retry: on the cloud the
    localStorage value only arrives on a later rerun, so this is not finished
    until a real value is read. It must run before the sidebar picker is drawn —
    seeding a widget's key after the widget exists is an error, and the picker's
    key *is* the stored value.
    """
    if st.session_state.get("_lang_packs_restored"):
        return
    if st.session_state.get("_lang_packs_dirty"):
        st.session_state["_lang_packs_restored"] = True
        return
    if local_store.local_persist_enabled():
        _apply_language_packs(local_store.load_config().get(LANG_PACKS_KEY))
        st.session_state["_lang_packs_restored"] = True
        return
    ls = _get_local_storage()
    if ls is None:
        st.session_state["_lang_packs_restored"] = True
        return
    saved = ls.getItem(LANG_PACKS_KEY)
    if isinstance(saved, dict):
        saved = saved.get(LANG_PACKS_KEY) or next(
            (v for v in saved.values() if isinstance(v, str)), None
        )
    if isinstance(saved, str) and saved.strip():
        try:
            _apply_language_packs(json.loads(saved))
        except (ValueError, TypeError):
            pass
        st.session_state["_lang_packs_restored"] = True


def persist_language_packs() -> None:
    """Save the packs and the active choice after a change. No-op otherwise."""
    if not st.session_state.get("_lang_packs_dirty"):
        return
    payload = _language_packs_payload()
    if payload == st.session_state.get("_lang_packs_saved_json"):
        return
    if local_store.local_persist_enabled():
        try:
            cfg = local_store.load_config()
            cfg[LANG_PACKS_KEY] = json.loads(payload)
            local_store.save_config(cfg)
        except OSError as e:
            log_error(e, context="Language packs save")
            return
    else:
        ls = _get_local_storage()
        if ls is None:
            return
        h = _content_hash(payload)
        ls.setItem(LANG_PACKS_KEY, payload, key=f"orionbelt_lang_packs_set_{h[:12]}")
    st.session_state["_lang_packs_saved_json"] = payload


def _sparql_limit_ranges() -> dict[str, tuple[int, int]]:
    """What each stored limit may be, read off the engine that enforces them.

    Taken from there rather than written out again, so a stored value cannot
    outlive a change to either ceiling — and a value outside its widget's range
    is not merely stale, it stops the widget from rendering at all.
    """
    from . import sparql

    return {
        "max_rows": (1, sparql.MAX_ROWS_CEILING),
        "timeout_seconds": (
            int(sparql.MIN_TIMEOUT_SECONDS),
            int(sparql.MAX_TIMEOUT_SECONDS),
        ),
    }


def _apply_sparql_state(data) -> None:
    """Copy a saved SPARQL editor state into the session keys the page reads.

    Types are checked the way :func:`_apply_viz_settings` checks them: a saved
    value of the wrong type is left at its default rather than trusted, so a
    stale or hand-edited store cannot put a non-string in front of the editor,
    and the limits are clamped to the ranges their widgets accept.
    """
    if not isinstance(data, dict):
        return
    query = data.get("query")
    if isinstance(query, str):
        st.session_state[SPARQL_QUERY_KEY] = query[:SPARQL_QUERY_MAX_CHARS]
    plain = data.get("plain_editor")
    if isinstance(plain, bool):
        st.session_state[SPARQL_PLAIN_KEY] = plain
    for name, (lo, hi) in _sparql_limit_ranges().items():
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            st.session_state[f"_sparql_cfg_{name}"] = max(lo, min(hi, value))


def _sparql_state_payload() -> str:
    """Serialize the SPARQL editor state for change detection and storage."""
    query = st.session_state.get(SPARQL_QUERY_KEY, "")
    data: dict = {
        "query": query[:SPARQL_QUERY_MAX_CHARS] if isinstance(query, str) else "",
        "plain_editor": bool(st.session_state.get(SPARQL_PLAIN_KEY)),
    }
    for name in SPARQL_LIMIT_KEYS:
        value = st.session_state.get(f"_sparql_cfg_{name}")
        if isinstance(value, int) and not isinstance(value, bool):
            data[name] = value
    return json.dumps(data, sort_keys=True)


def sparql_state_changed() -> None:
    """Note that the query or the editor choice is now the user's own.

    Two jobs, both of them the dirty flag's: it is what lets the state be saved
    at all (an untouched page must never write over what is stored), and it is
    what stops a late restore from replacing what the user is typing right now.
    """
    st.session_state["_sparql_state_dirty"] = True


def restore_sparql_state() -> None:
    """Restore the saved query and editor choice once per session (issue #388).

    Mirrors :func:`restore_language_packs`, retry included: on the cloud the
    localStorage value only arrives on a later rerun, so this is not finished
    until a real value is read. It has to run before the toggle and the editor
    are drawn, because it seeds the keys they start from.
    """
    if st.session_state.get("_sparql_state_restored"):
        return
    if st.session_state.get("_sparql_state_dirty"):
        st.session_state["_sparql_state_restored"] = True
        return
    if local_store.local_persist_enabled():
        _apply_sparql_state(local_store.load_config().get(SPARQL_STATE_KEY))
        st.session_state["_sparql_state_restored"] = True
        return
    ls = _get_local_storage()
    if ls is None:
        st.session_state["_sparql_state_restored"] = True
        return
    saved = ls.getItem(SPARQL_STATE_KEY)
    if isinstance(saved, dict):
        saved = saved.get(SPARQL_STATE_KEY) or next(
            (v for v in saved.values() if isinstance(v, str)), None
        )
    if isinstance(saved, str) and saved.strip():
        try:
            _apply_sparql_state(json.loads(saved))
        except (ValueError, TypeError):
            pass
        st.session_state["_sparql_state_restored"] = True


def persist_sparql_state() -> None:
    """Save the query and the editor choice after a change. No-op otherwise.

    The browser write is re-offered until a pass survives, for the reason
    :func:`_persist_viz_settings` spells out: it is a component render, and a
    pass that ends in ``st.rerun()`` is discarded along with everything it drew.
    The component is keyed by the payload's hash, so the re-offers are one
    component writing one value rather than a queue of writes.
    """
    if not st.session_state.get("_sparql_state_dirty"):
        return
    payload = _sparql_state_payload()
    if local_store.local_persist_enabled():
        if payload == st.session_state.get("_sparql_state_saved_json"):
            return
        try:
            cfg = local_store.load_config()
            cfg[SPARQL_STATE_KEY] = json.loads(payload)
            local_store.save_config(cfg)
        except OSError as e:
            log_error(e, context="SPARQL editor state save")
            return
        st.session_state["_sparql_state_saved_json"] = payload
        return
    ls = _get_local_storage()
    if ls is None:
        return
    h = _content_hash(payload)
    ls.setItem(SPARQL_STATE_KEY, payload, key=f"orionbelt_sparql_state_set_{h[:12]}")


def render_language_pack_sidebar() -> None:
    """The app-wide language-pack picker (issue #252).

    One control in the sidebar rather than one beside each Language field: the
    fields sit on three pages and in the graph panel, and a per-field switch
    would have to be set four times over to mean one thing. The Language Packs
    tab's picker is this same choice seen from there (issue #293).
    """
    restore_language_packs()
    names = language_pack_names()
    seed_language_pack_picker(LANG_PACK_SIDEBAR_KEY)
    st.sidebar.selectbox(
        "Language pack",
        names,
        key=LANG_PACK_SIDEBAR_KEY,
        on_change=_language_pack_picked,
        args=(LANG_PACK_SIDEBAR_KEY,),
        help="Which codes the Language fields offer. Build your own under "
        "Annotations → Language Packs, which switches packs too.",
    )
    persist_language_packs()


def _clearing_key(base: str) -> str:
    """A widget key that changes once :func:`_clear_input` is called on it.

    Popping a widget's key from ``session_state`` does not reset the widget:
    Streamlit restores the value from its own widget store when a widget with
    the same key is created again. Changing the key makes a different widget,
    which starts empty. Used so an add row does not keep the text just added
    and invite adding it twice.
    """
    return f"{base}_{st.session_state.get(f'{base}__gen', 0)}"


def _clear_input(base: str) -> None:
    """Retire the current widget behind ``base`` so the next one starts empty."""
    generation = st.session_state.get(f"{base}__gen", 0)
    st.session_state.pop(f"{base}_{generation}", None)
    st.session_state[f"{base}__gen"] = generation + 1


def render_scheme_metadata_editor(ont, scheme, sk):
    """Rows of Dublin Core metadata on a ConceptScheme, with add and delete.

    Outside the scheme form, for the same reason the concept label editor is:
    a button inside a form cannot act until the form is submitted.

    The fields are not all strings, so the add row changes shape with the one
    picked: a language for the language-tagged ones, none for a date or an IRI.
    Offering a language box beside a licence URL would invite tagging it.
    """
    rows = [
        (field, item)
        for field in ont.SCHEME_METADATA
        for item in scheme["metadata"][field]
    ]
    for i, (field, item) in enumerate(rows):
        col_field, col_lang, col_value, col_del = st.columns([2, 1, 5, 0.7])
        with col_field:
            st.write(f"`{field}`")
        with col_lang:
            st.write(item["lang"] or "—")
        with col_value:
            st.write(f"<{item['value']}>" if item["is_iri"] else item["value"])
        with col_del:
            if st.button("🗑️", key=f"del_meta_{sk}_{i}", help=f"Delete this {field}"):
                ont.remove_scheme_metadata(
                    scheme["uri"], field, item["value"], item["lang"]
                )
                save_checkpoint(f"Delete scheme {field}")
                st.rerun()
    if not rows:
        st.caption("No metadata yet.")

    col_field, col_lang, col_value, col_add = st.columns([2, 1, 5, 0.7])
    with col_field:
        new_field = st.selectbox(
            "Field",
            list(ont.SCHEME_METADATA),
            key=f"add_meta_field_{sk}",
            label_visibility="collapsed",
        )
    entry = ont.SCHEME_METADATA[new_field]
    with col_lang:
        if entry["kind"] == "text":
            new_lang = language_selectbox(
                "Language",
                key=f"add_meta_lang_{sk}",
                label_visibility="collapsed",
            )
        else:
            new_lang = None
            st.write("—")
    placeholder = {
        "date": "2026, 2026-08 or 2026-08-20",
        "iri": "https://creativecommons.org/licenses/by/4.0/",
        "agent": "A name, or an IRI identifying one",
    }.get(entry["kind"], f"New {new_field}…")
    with col_value:
        new_value = st.text_input(
            "Value",
            key=_clearing_key(f"add_meta_value_{sk}"),
            placeholder=placeholder,
            label_visibility="collapsed",
        )
    with col_add:
        if st.button("➕", key=f"add_meta_btn_{sk}", help=f"Set this {new_field}"):
            try:
                ont.set_scheme_metadata(
                    scheme["uri"], new_field, new_value, new_lang or None
                )
            except ValueError as exc:
                show_message(str(exc), "error")
            else:
                save_checkpoint(f"Set scheme {new_field}")
                _clear_input(f"add_meta_value_{sk}")
                st.rerun()


def render_skos_literal_editor(ont, concept, ck):
    """One table of a concept's labels and notes, with add and delete.

    Labels and notes are separate halves of the engine API but the same thing
    to edit: a kind, a language and some text. Rendering them as one table with
    one add row rather than two stacked sections halves the height of the
    editor, which is what makes the panel usable without scrolling.

    This renders *outside* the concept form on purpose. A form submits as a
    unit, so per-row add and delete buttons inside one cannot take effect until
    the whole form is saved, which reads as a dead button. It also renders for
    the single open concept only, per the active-entity state model, so the
    cost does not scale with the size of the vocabulary.
    """
    kinds = [*ont.SKOS_LABEL_KINDS, *ont.SKOS_NOTE_KINDS]

    def _api(kind):
        """(add, remove) for a kind, whichever half of the API owns it."""
        if kind in ont.SKOS_LABEL_KINDS:
            return ont.set_concept_label, ont.remove_concept_label
        return ont.set_concept_note, ont.remove_concept_note

    rows = [
        (kind, item)
        for kind in kinds
        for item in (
            concept["labels"] if kind in ont.SKOS_LABEL_KINDS else concept["notes"]
        )[kind]
    ]
    for i, (kind, item) in enumerate(rows):
        col_kind, col_lang, col_text, col_del = st.columns([2, 1, 5, 0.7])
        with col_kind:
            st.write(f"`{kind}`")
        with col_lang:
            st.write(item["lang"] or "—")
        with col_text:
            st.write(item["value"])
        with col_del:
            if st.button("🗑️", key=f"del_lit_{ck}_{i}", help=f"Delete this {kind}"):
                _api(kind)[1](concept["uri"], kind, item["value"], item["lang"])
                save_checkpoint(f"Delete {kind}")
                st.rerun()
    if not rows and not any(
        concept["xl_labels"][kind] for kind in ont.SKOS_XL_LABEL_KINDS
    ):
        st.caption("No labels or notes yet.")

    # SKOS-XL labels are shown but not editable: this app writes plain SKOS, and
    # a delete button next to one would silently do nothing. Rendering them at
    # all is what keeps an imported AGROVOC or EuroVoc from looking unlabelled.
    xl_rows = [
        (kind, item)
        for kind in ont.SKOS_XL_LABEL_KINDS
        for item in concept["xl_labels"][kind]
    ]
    if xl_rows:
        for kind, item in xl_rows:
            col_kind, col_lang, col_text, _ = st.columns([2, 1, 5, 0.7])
            with col_kind:
                st.write(f"`skosxl:{kind}`")
            with col_lang:
                st.write(item["lang"] or "—")
            with col_text:
                st.write(item["value"])
        st.caption(
            "SKOS-XL labels are read-only here. To edit one, add a plain SKOS "
            "label of the same kind below."
        )

    col_kind, col_lang, col_text, col_add = st.columns([2, 1, 5, 0.7])
    with col_kind:
        new_kind = st.selectbox(
            "Kind", list(kinds), key=f"add_lit_kind_{ck}", label_visibility="collapsed"
        )
    with col_lang:
        # Collapsed like the other two: a visible label here pushes the picker
        # onto its own line and the add row stops reading as a row.
        new_lang = language_selectbox(
            "Language",
            key=f"add_lit_lang_{ck}",
            label_visibility="collapsed",
        )
    with col_text:
        new_text = st.text_input(
            "Text",
            key=_clearing_key(f"add_lit_text_{ck}"),
            placeholder="New label or note…",
            label_visibility="collapsed",
        )
    with col_add:
        if st.button("➕", key=f"add_lit_btn_{ck}", help="Add this label or note"):
            try:
                _api(new_kind)[0](concept["uri"], new_kind, new_text, new_lang or None)
            except ValueError as exc:
                show_message(str(exc), "error")
            else:
                save_checkpoint(f"Add {new_kind}")
                # Clear the text but keep the kind and the language: adding
                # several values in one language is the common case, and a
                # value left in the box invites adding it twice.
                _clear_input(f"add_lit_text_{ck}")
                st.rerun()


def language_selectbox(label, key, value="", help=None, label_visibility="visible"):
    """A searchable code picker for a Language field, returning the bare tag.

    Options come from the active pack and read ``eng · English``, so a code can
    be found by either half. Typing is still accepted, so a tag no pack lists
    (``pt-BR``, ``x-inhouse``) can be entered as before — the picker adds codes,
    it does not fence them off. A value already on the annotation is offered
    even when the active pack has no entry for it, so switching packs cannot
    silently rewrite the tag of an annotation you open to edit.
    """
    options = [
        languages.format_option(e["code"], e["label"]) for e in language_pack_entries()
    ]
    current = (value or "").strip()
    display = None
    if current:
        display = next(
            (o for o in options if languages.code_from_option(o) == current), None
        )
        if display is None:
            display = current
            options = [display, *options]
    choice = clearable_selectbox(
        label,
        options,
        key=key,
        current_display=display,
        accept_new_options=True,
        format_func=_pad_option,
        label_visibility=label_visibility,
        help=help
        or (
            "Optional. Pick a code from the active language pack, or type any "
            "BCP 47 tag (`de`, `grc`, `pt-BR`) to use it as it stands."
        ),
    )
    return languages.code_from_option(choice)


def language_tag_error(tag: str) -> str | None:
    """The message for a language tag the graph would reject, or ``None``.

    Empty is not an error: the tag is optional everywhere it is asked for. A
    tag rdflib refuses raises out of the write, which without this surfaces as
    a page-level crash rather than as something to fix in the field.
    """
    tag = (tag or "").strip()
    return languages.invalid_tag_reason(tag) if tag else None


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
    # Notes about entities the seeds were meant to follow; with no seeds left
    # there is nothing to re-point (see viz_note_rename).
    st.session_state.pop("_viz_pending_renames", None)


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


def viz_auto_show_new_toggled():
    """Persist "Auto-show new", and on switching it on let in what is queued.

    The filter may already be holding entities back behind "Show new (N)" when
    the setting is turned on. Leaving them there would break the half of the
    promise the user can see: those are precisely the ones it says should have
    come in. The reconcile cannot do it — by now they are in ``known``, so it no
    longer reads them as new — so they are folded into the selection here, the
    same merge the button does.

    Order is not preserved and does not need to be: the next render's
    :func:`reconcile_filter_selection` returns the selection in entity-list
    order, and the queued list prunes itself the moment its entries are shown.
    """
    viz_sync("_viz_cfg_auto_show_new", "viz_auto_show_new")
    if not st.session_state.get("_viz_cfg_auto_show_new"):
        return
    for kind in _FILTER_KINDS:
        key = kind["key"]
        pending = st.session_state.get(f"_viz_new_hidden_{key}") or []
        if not pending:
            continue
        selected = st.session_state.get(f"_viz_cfg_selected_{key}_uris") or []
        seen = set(selected)
        st.session_state[f"_viz_cfg_selected_{key}_uris"] = [
            *selected,
            *(uri for uri in pending if uri not in seen),
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


def focus_seeds_after_request(seeds, label, replace=False, focus_on=False):
    """What a modifier-click on a graph node leaves the focus as.

    ``focus_on`` is whether focus mode is on *now*; returns ``(seeds, focus_on)``
    — the new seed list and whether it should be on after the click.

    Ctrl/Cmd-click adds the node to whatever is focused already (issue #56),
    which is what building a neighbourhood up out of several nodes needs.
    Alt-click focuses on that node alone (issue #276): wanting one node at a
    time is the common case, and it otherwise means emptying the picker by hand
    between hops.

    Clicking a node that is *already* focused used to do nothing at all, which
    left no way back out of focus mode except reaching for the checkbox. Each
    modifier now undoes its own action instead (issue #328), but only while the
    mode is on: the seeds outlive it on purpose (see the Alt-click note below),
    so a seed sitting in the list is not the same thing as a node the user can
    see focused. With the mode off there is nothing on screen to undo, and a
    modifier-click is what it always was, an instruction to start focusing.
    Inferring the mode from the seed list instead made Alt-clicking the node you
    had just left refuse to focus it again, and Ctrl-clicking it drop it from a
    focus that was not running (Codex review of PR #334).

    While the mode is on:

    - Ctrl/Cmd-click adds, so on a node that is already a seed it removes it.
      Taking the last one out leaves nothing to focus on, so the mode goes off
      with it.
    - Alt-click sets the focus to exactly one node, so on a node that is
      *already* the only seed it turns the mode off. The seeds are kept, so
      switching focus back on returns you to where you were (issue #235). On one
      of several seeds it still means "now just this one", which is a narrowing
      the user can still want.

    Every behaviour that changes here was a no-op before, so nothing that did
    something does something else now.

    The mode has to go off in the same breath as the seeds empty, never on a
    later render: focus mode with no seeds backfills an arbitrary first node
    (see render_visualization), so passing through that state would jump the
    graph to a class the user never picked.
    """
    seeds = list(seeds or [])
    if not focus_on:
        # Nothing running to undo: start the focus. The seeds kept from last
        # time come back around it, the same restore ticking the checkbox does.
        if replace:
            return [label], True
        if label not in seeds:
            seeds.append(label)
        return seeds, True
    if replace:
        if seeds == [label]:
            return seeds, False
        return [label], True
    if label in seeds:
        seeds.remove(label)
        return seeds, bool(seeds)
    seeds.append(label)
    return seeds, True


def viz_apply_focus_click(label, replace=False):
    """Apply a modifier-click on ``label`` to the focus state in session.

    Returns the ``(seeds, focus_on)`` it wrote. Split out from the page so the
    state it touches can be tested: the click arrives through the graph
    component, which does not render under AppTest, so nothing else can reach
    this path.

    Mode and seeds are written together, never across renders: focus mode with
    no seeds backfills an arbitrary first label, so a pass through that state
    would jump the graph to a class nobody picked (issue #328).
    """
    seeds = list(st.session_state.get("_viz_cfg_focus_seeds") or [])
    mode_before = bool(st.session_state.get("_viz_cfg_focus_mode"))
    seeds, focus_on = focus_seeds_after_request(
        seeds, label, replace=replace, focus_on=mode_before
    )
    st.session_state["_viz_cfg_focus_mode"] = focus_on
    viz_set_focus_seeds(seeds)
    if focus_on != mode_before:
        # focus_mode is a persisted display setting (#142) and the save is gated
        # on the dirty flag the widget callbacks set. Switching the mode from the
        # canvas has to lift the same gate, or what is saved goes stale against
        # what is on screen (Codex review of PR #334).
        st.session_state["_viz_settings_dirty"] = True
    return seeds, focus_on


def viz_focus_toggle():
    """Persist the focus toggle, seeding the focus nodes on first use.

    Turning focus on derives seeds from the class selection only when there are
    none to restore (see focus_seeds_from_selection). Deriving them on *every*
    switch-on threw away whatever you had picked the moment you toggled the mode
    off and on again, so narrowing "Focus node(s)" to the one class you wanted
    never survived (issue #235). The derived seeding is a starting point for the
    first use, not something reapplied over a choice you have already made.

    That also decouples the two controls: after you have expressed a preference,
    the focus seeds are their own list rather than a function of Node options.
    An empty selection still falls back to the first node, downstream.
    """
    if _viz_widget_missing("viz_focus_mode"):
        return
    on = st.session_state["viz_focus_mode"]
    st.session_state["_viz_cfg_focus_mode"] = on
    st.session_state["_viz_settings_dirty"] = True
    if on and not st.session_state.get("_viz_cfg_focus_seeds"):
        # Forgotten wholesale rather than trimmed: these labels are derived
        # from the class selection, not picked by the user as seeds, so an id on
        # file against one describes whatever was loaded before rather than the
        # entity now carrying that name. Trimming would keep such an entry,
        # since the label *is* a seed again, and the next prune would drop the
        # seed as a swapped label (the Codex review of PR #336).
        st.session_state.pop("_viz_cfg_focus_seed_ids_by_label", None)
        viz_set_focus_seeds(
            focus_seeds_from_selection(
                st.session_state.get("_viz_cfg_selected_classes") or [],
                st.session_state.get("_viz_cfg_class_count") or 0,
            )
        )


def viz_set_focus_seeds(seeds) -> None:
    """Store the focus seeds, keeping the label -> id map to just those.

    That map is what :func:`prune_reused_focus_seeds` compares against to tell a
    label that has come to name a *different* entity from one that still names
    the same (issue #180). An entry left behind for a label that is no longer a
    seed outlives the entity it described: clear the focus, import an ontology
    that also has a ``Bicycle``, pick it again, and the stale id says it is a
    different Bicycle, so it is pruned and the focus ends before it starts (the
    Codex review of PR #336).

    Trimming rather than clearing outright, so the labels that *are* still seeds
    keep the identity they were last seen under. A seed with no entry is one the
    user has just picked, which the prune keeps.
    """
    seeds = list(seeds or [])
    st.session_state["_viz_cfg_focus_seeds"] = seeds
    ids = st.session_state.get("_viz_cfg_focus_seed_ids_by_label")
    if ids:
        kept = set(seeds)
        st.session_state["_viz_cfg_focus_seed_ids_by_label"] = {
            label: node_id for label, node_id in ids.items() if label in kept
        }


def viz_focus_on_path(labels) -> None:
    """Focus the graph on exactly the entities a shortest path runs through.

    The path search runs over the whole ontology while the canvas assembles at
    most :data:`GRAPH_MAX_NODES` of it, so a path can name entities the current
    view has no node for — and the highlight then has nothing to paint. Making
    the path the focus is the way back: focus mode assembles past the render cap
    and prunes to its seeds, so the whole path is drawn whatever the graph
    happened to be showing.

    Mode and seeds are written together for the reason
    :func:`viz_apply_focus_click` writes them together: focus mode with no seeds
    backfills an arbitrary node, and a pass through that state would jump the
    graph somewhere nobody asked for.
    """
    labels = [str(label) for label in labels or []]
    if not labels:
        return
    if not st.session_state.get("_viz_cfg_focus_mode"):
        st.session_state["_viz_cfg_focus_mode"] = True
        # focus_mode is a persisted display setting (#142), saved only when the
        # dirty flag is lifted — the same gate the canvas click has to lift.
        st.session_state["_viz_settings_dirty"] = True
    viz_set_focus_seeds(labels)


def viz_leave_empty_focus() -> None:
    """Switch focus mode off because there is nothing left to focus on.

    The one landing every route out of a focus shares: the last Ctrl/Cmd-click
    on the canvas (issue #328), clearing the picker, and a focus whose seeds
    have all gone — an entity deleted, or its whole type switched off.

    It replaces standing in an arbitrary first entity, which is what made the
    picker impossible to clear and moved a focus onto a stranger behind the
    user's back (issue #335). Nothing here picks *for* the user; it just stops
    pretending a focus is running.

    Also lifts the persisted-settings gate, since ``focus_mode`` is a saved
    display setting and the save is gated on that flag (#142, and the Codex
    review of PR #334).
    """
    if not st.session_state.get("_viz_cfg_focus_mode"):
        return
    st.session_state["_viz_cfg_focus_mode"] = False
    # The config key only: the next render copies it into the checkbox's widget
    # key, and writing that here raises once the checkbox has been instantiated
    # — which it has, by the time the panel below it finds the focus empty.
    st.session_state["_viz_settings_dirty"] = True


def viz_focus_seeds_changed():
    """Persist the focus seeds, and leave focus mode when the last one goes.

    Focus mode is "show me this node's neighbourhood", so it has nothing to mean
    with nothing picked. Emptying the picker was undone on the spot by the
    backfill downstream, which put the first class back in and made the list
    impossible to clear at all (issue #335). Clearing it now leaves the mode
    instead, which is where the last Ctrl/Cmd-click on the canvas already lands
    (issue #328), so both ways out of a focus agree.

    Leaving the mode rather than allowing an empty focus is also what keeps the
    node cap honest: focus mode is allowed to assemble more nodes than can be
    drawn only because the prune cuts it back to the seeds' neighbourhood
    afterwards, and with no seeds nothing prunes (see :func:`graph_node_cap`).
    An empty focus would have handed the browser the whole ontology, which is
    the opposite of what clearing the box looks like it should do.

    Switching the mode back on re-derives the seeds from the class selection
    (see :func:`viz_focus_toggle`), which is the "start over" the request was
    after.
    """
    if _viz_widget_missing("viz_focus_seeds"):
        return
    viz_set_focus_seeds(st.session_state["viz_focus_seeds"])
    if not st.session_state["_viz_cfg_focus_seeds"]:
        viz_leave_empty_focus()


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


_VIZ_NODE_ID_PREFIX = {"class": "", "individual": "ind_", "property": "dprop_"}


def viz_node_id(kind: str, ref: str) -> str:
    """The graph node id an entity of ``kind`` gets, as the builder assigns it.

    ``ref`` is the entity's URI, except for SKOS concepts, whose nodes are keyed
    by name. The focus-target map and the rename notes below both go through
    here because they have to agree on the id: a rename that computed it any
    other way would re-point nothing.
    """
    if kind == "concept":
        return f"skos_{ref}"
    return f"{_VIZ_NODE_ID_PREFIX[kind]}{_uid(ref)}"


#: The colour a highlighted path is ringed in. Deliberately outside the palette
#: the graph already gives relation types — green for subclass, blue for
#: properties, orange for individuals, teal for SKOS, red for disjoint — so the
#: ring reads as "on the path" rather than as one more kind of link (issue #176).
PATH_HIGHLIGHT_COLOR = "#FFEB3B"
#: How wide the ring around everything on the path is drawn — a border on its
#: nodes, and a casing under its links, which the viewer draws because
#: vis-network has no edge equivalent of a border. One width for both, so the
#: two read as the same marking. What is ringed is otherwise left exactly as it
#: was drawn, fill and line alike: that is what says which kind of entity or
#: link it is, and it is what the graph is scanned by (issue #357).
PATH_HIGHLIGHT_BORDER = 3


def path_entity_kinds(
    show_classes: bool, show_individuals: bool, show_skos: bool
) -> tuple[str, ...]:
    """Which entities a path may run through, from the display toggles.

    Only the raw-triple walk needs telling (see ``build_path_graph``); the other
    link kinds each join a fixed pair of types and gate themselves.
    """
    kinds = []
    if show_classes:
        kinds.append("class")
    if show_individuals:
        kinds.append("individual")
    if show_skos:
        kinds.append("concept")
    return tuple(kinds)


def path_edge_kinds(
    show_classes: bool,
    show_obj_props: bool,
    show_individuals: bool,
    show_ind_edges: bool,
    show_skos: bool,
    show_triples: bool = False,
) -> tuple[str, ...]:
    """Which link kinds a path may be walked over, from the display toggles.

    The path search runs over the whole ontology while the canvas draws a subset
    of it, so the one thing that must not drift is *which kinds of link count*:
    a path found over a relation the canvas isn't drawing could not be
    highlighted, and would read as the highlight being broken. Each condition
    here mirrors the guard the graph builder puts on the edges it adds.
    """
    kinds = []
    if show_classes:
        kinds += ["subclass", "class_relations"]
        if show_obj_props:
            kinds += ["object_properties", "restrictions"]
        if show_individuals:
            kinds.append("individual_types")
    if show_individuals and show_ind_edges:
        kinds.append("individual_relations")
    if show_skos:
        kinds.append("skos")
    if show_triples:
        kinds.append("triples")
    return tuple(kinds)


def path_nodes(hops: list, source) -> list:
    """The entities a path runs through, in order, as ``(kind, ref)`` pairs.

    Takes ``source`` as well as the hops because a path from an entity to itself
    has no hops at all and is still one node long.
    """
    return [source, *[hop["target"] for hop in hops]]


def path_highlight(hops: list, source) -> tuple[list[str], set[frozenset]]:
    """What to repaint for a path: its node ids, and its links as endpoint pairs.

    Pairs are unordered, and matched against drawn edges by endpoint alone. Two
    entities linked several ways over therefore light up on all of those links
    rather than on the one the search happened to walk — which is the honest
    picture: the path goes between them, and saying which line it took would
    claim more than the search decided.
    """
    ids = [viz_node_id(kind, ref) for kind, ref in path_nodes(hops, source)]
    pairs = {frozenset(pair) for pair in pairwise(ids)}
    return ids, pairs


def path_chain_text(hops: list, source, labels: dict) -> str:
    """The path written out as one line, naming each link and its direction.

    ``labels`` maps a ``(kind, ref)`` node to the name the pickers show it under;
    anything missing falls back to its own reference, which is what an entity
    whose type has since been switched off would have.
    """

    def name(node) -> str:
        return labels.get(node, node[1])

    if not hops:
        return name(source)
    text = name(hops[0]["source"])
    for hop in hops:
        arrow = f" —{hop['relation']}→ " if hop["forward"] else f" ←{hop['relation']}— "
        text += arrow + name(hop["target"])
    return text


def viz_note_rename(kind: str, old_ref: str, new_ref: str) -> None:
    """Record a rename so the focus seeds can follow the entity (issue #275).

    Seeds are held as the labels the multiselect shows, and a rename mints a new
    URI: on the next render the old label names nothing, so the seed was pruned
    and focus mode fell back to an arbitrary first node. Renaming the very class
    you were focused on therefore dropped it out of the graph.

    Nothing in the rebuilt state ties the two names together — the label changed
    and ``_uid`` hashes the URI, so the node id changed with it — which is why
    the rename itself has to leave the note. It is consumed by the next
    Visualization render (see :func:`follow_focus_seed_renames`).
    """
    if old_ref == new_ref:
        return
    renames = st.session_state.setdefault("_viz_pending_renames", {})
    renames[viz_node_id(kind, old_ref)] = viz_node_id(kind, new_ref)


def _renamed_node_id(node_id, renames):
    """Where ``node_id`` ended up after the recorded renames, following a chain
    of them (the seeds are only re-pointed on a Visualization render, so an
    entity can be renamed more than once in between). Guarded against a cycle,
    which a rename back to an earlier name produces."""
    seen = set()
    while node_id in renames and node_id not in seen:
        seen.add(node_id)
        node_id = renames[node_id]
    return node_id


def viz_rename_map(renames):
    """The recorded renames flattened to one ``old id -> where it is now`` map.

    The notes are left one rename at a time (see :func:`viz_note_rename`), so an
    entity renamed twice before the next Visualization render is recorded as a
    chain (A->B, B->C). The graph component needs a single hop per id to carry a
    cached node position across a rename (issue #329), so the chain is walked
    here. A rename back to an earlier name leaves the id where it started and is
    dropped, since there is nothing to carry.
    """
    if not renames:
        return {}
    moved = {}
    for old in renames:
        final = _renamed_node_id(old, renames)
        if final != old:
            moved[old] = final
    return moved


def follow_renamed_node_ids(node_ids, renames):
    """Where ``node_ids`` ended up after the recorded renames (issue #275).

    The seeds saved against a linked file are node ids rather than labels
    (#164), and one saved before a rename made this session resolves to nothing
    when it is read back. Same notes and same chain-following as
    :func:`follow_focus_seed_renames`, one level down: that works in the labels
    the seeds are shown under, this in the ids they are stored as.
    """
    if not renames:
        return list(node_ids or [])
    return [_renamed_node_id(i, renames) for i in node_ids or []]


def follow_focus_seed_renames(seeds, seen_ids_by_label, focus_targets, renames):
    """Re-point focus seeds at entities that were renamed (issue #275).

    Returns ``(seeds, seen_ids_by_label)`` with every seed whose entity now
    answers to a new label swapped for that label, and its recorded id brought
    up to date so the reuse prune that follows still recognises it.

    A seed is only moved when the renamed entity is actually in ``focus_targets``
    — if its type has been toggled off it is not focusable, and leaving the seed
    alone lets the existing prune drop it as it always did.
    """
    if not seeds or not renames or not seen_ids_by_label:
        return list(seeds or []), dict(seen_ids_by_label or {})
    label_by_id = {node_id: label for label, node_id in focus_targets.items()}
    out_seeds: list = []
    out_ids = dict(seen_ids_by_label)
    for s in seeds:
        old_id = seen_ids_by_label.get(s)
        new_id = _renamed_node_id(old_id, renames) if old_id else None
        label = label_by_id.get(new_id) if new_id and new_id != old_id else None
        if label is None:
            if s not in out_seeds:
                out_seeds.append(s)
            continue
        out_ids.pop(s, None)
        out_ids[label] = new_id
        if label not in out_seeds:
            out_seeds.append(label)
    return out_seeds, out_ids


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
        # What the previous file's filter was holding back (issue #194). It
        # names that file's entities, and the next render unions it back into
        # the offer: a new file reusing one of those URIs and restoring it as
        # hidden would be offered as "just created", and taking the offer would
        # edit the filter the new file had asked for.
        st.session_state.pop(f"_viz_new_hidden_{kind['key']}", None)
    # Likewise the toast still queued for entities of the file we are leaving.
    st.session_state.pop("_viz_new_hidden_announce", None)
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
    # Initialised on the way in rather than assumed. This is called from
    # `except` blocks, so raising here — which reading a missing key does —
    # replaces the error being reported with a page crash, and the report is
    # lost either way.
    if "error_log" not in st.session_state:
        st.session_state["error_log"] = []
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


#: Icons for the toast form of a flash message, by message type.
_FLASH_TOAST_ICON = {"success": "✅", "warning": "⚠️", "error": "🚫", "info": "ℹ️"}


def set_flash_message(message: str, type: str = "info", toast: bool = False):
    """Set a flash message to be displayed after rerun.

    ``toast`` floats the message over the page instead of drawing it as a banner.
    The banner goes above the whole page body, so a confirmation for an edit made
    further down — the details panel, a row editor — pushes everything the user
    is looking at out from under the cursor (issue #330). Use it for the short
    confirmations that say only that the edit landed; anything worth reading
    twice, such as a bulk-add summary or an error, stays a banner (issue #114).
    """
    st.session_state.flash_message = {
        "message": message,
        "type": type,
        "toast": toast,
    }


def display_flash_message():
    """Display and clear any pending flash message."""
    if st.session_state.get("flash_message"):
        msg = st.session_state.flash_message
        if msg.get("toast"):
            st.toast(msg["message"], icon=_FLASH_TOAST_ICON.get(msg["type"]))
        else:
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


LABEL_NAME_SEPARATOR = " · "


def picker_option_caption(option: str, name: str, text: str) -> str:
    """What a graph picker shows for one of its options.

    The canvas draws a node under its rdfs:label (a concept's prefLabel), so
    that is what someone reads off the graph and then goes looking for in Find,
    in the focus seeds, or in the path finder — where the options were the local
    name alone. In an ontology whose names are identifiers (``0-I`` labelled
    "zero current") the two share nothing, and the entity could not be found by
    the only name the user had seen.

    The label is shown, never stored: ``option`` stays the identifier the rest of
    the page is built on — focus seeds are persisted as it, the paste box
    round-trips it, and rename notes re-point it (issues #142, #179, #275).
    Only what is drawn in the dropdown changes, which is also what Streamlit
    matches typed text against, so the label is searchable too.
    """
    if text and text != name:
        return f"{option}{LABEL_NAME_SEPARATOR}{text}"
    return option


def format_label_name(name: str, label: str) -> str:
    """Format display string as 'name · Label' if label exists and differs from name."""
    if label and label != name:
        return f"{name}{LABEL_NAME_SEPARATOR}{label}"
    return name


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


_NAV_KIND_BY_TYPE = {
    "Class": "class",
    "Object Property": "objprop",
    "Data Property": "dataprop",
    "Individual": "ind",
    "SKOS Concept": "skos",
}
_PAGE_BY_TYPE = {
    "Class": "Classes",
    "Object Property": "Properties",
    "Data Property": "Properties",
    "Individual": "Individuals",
    "SKOS Concept": "SKOS Vocabulary",
    "Class Relation": "Relations",
    "Restriction": "Restrictions",
}
_PRECISE_NAV_TYPES = {"Class", "Class Relation", "Restriction"}
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


_ANN_ID_PARTS = 5


def _uri_local_name(uri: str) -> str:
    """The local part of a URI, for naming the resource something hangs off."""
    if not uri:
        return ""
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or uri


def annotation_ename(subject_uri: str, ann: dict) -> str:
    """Name the annotation a graph node stands for (issue #223).

    An annotation has no URI of its own — it *is* a triple — so like the
    relations and restrictions drawn as edges it is identified by its parts:
    subject, predicate, value, and the language or datatype that tells two
    otherwise identical literals apart. That is exactly the key
    ``delete_annotation`` matches on, so a node resolves back to the one triple
    it was drawn from.

    Derived from content rather than counted, so the id survives a rebuild. The
    nodes used to be numbered in iteration order, which meant a node id changed
    whenever anything before it did, and a click could not be resolved at all.
    """
    return _edge_id(
        subject_uri,
        ann.get("predicate_uri") or ann["predicate"],
        ann["value"],
        ann.get("language") or "",
        # The full datatype URI, not the local name: two datatypes in different
        # namespaces share a local name, and a non-XSD one does not resolve back
        # from it. "uri" marks a resource-valued annotation, which is a different
        # triple from a literal that happens to spell the same IRI.
        "uri" if ann.get("is_uri") else (ann.get("datatype_uri") or ""),
    )


def annotation_matches_ename(subject_uri: str, ann: dict, parts: tuple) -> bool:
    """Whether ``ann`` on ``subject_uri`` is the annotation ``parts`` names."""
    return annotation_ename(subject_uri, ann) == _edge_id(*parts)


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


def _rename_or_move(ont, kind, rename_fn, old_uri, old_local, new_name, new_namespace):
    """Resolve the target URI from the (possibly changed) local name and
    namespace and rename via ``rename_fn`` if it differs from ``old_uri``.

    A namespace change is just a rename to a full URI in the new namespace, so
    ``rename_fn`` re-points every reference and no links are lost. Returns
    ``(ok, current_ref)``: ``ok`` is False only when ``rename_fn`` refuses
    because the target URI already exists. ``new_namespace`` is ``None`` (base),
    a namespace URI, or the ``_KEEP_NAMESPACE`` sentinel to keep the current
    namespace. ``kind`` is what the entity is to the graph ("class",
    "individual", "property"), so the move can be noted for the focus seeds.
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
        viz_note_rename(kind, old_uri, target_uri)
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
        "class",
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


def restriction_takes_on_class(restriction_type: str) -> bool:
    """Does this restriction type carry an ``owl:onClass``?

    The qualified cardinalities do: OWL 2 requires one to name the class being
    counted, and a qualified cardinality written without it is an axiom no
    reasoner accepts.

    Matched case-insensitively on purpose. The exact-cardinality type is spelled
    ``qualifiedCardinality`` with a lower-case q, so a ``"Qualified" in ...``
    test matched its min and max siblings but silently missed it: that type
    never got an onClass selector and wrote a bare ``owl:qualifiedCardinality``.
    """
    return "qualified" in restriction_type.lower()


def restriction_value_is_class(restriction_type: str) -> bool:
    """Is this restriction's *value* another class, rather than a literal,
    an individual or a number?"""
    return restriction_type in ("someValuesFrom", "allValuesFrom")


def restriction_references_class(restriction_type: str) -> bool:
    """Does this restriction point at a second class at all? (issue #221)

    These are the types worth building by clicking two nodes on the graph. The
    rest (hasValue, the plain cardinalities) say something about one class on
    its own, so the graph has no second end to offer and they stay on the
    Restrictions page.
    """
    return restriction_value_is_class(restriction_type) or restriction_takes_on_class(
        restriction_type
    )


def _apply_annotation_edit(
    ont, subject_uri, ann, new_pred, new_value, new_lang, new_subject_uri=None
):
    """Rewrite one annotation. Returns True when the graph changed (issue #223).

    An annotation is a triple, and the engine has no update for one, so an edit
    is a delete followed by an add. That order can fail halfway: ``add`` rejects
    an unusable predicate (an unbound prefix above all), and by then the original
    is already gone. So a failed add puts the original back before reporting,
    rather than leaving the user with neither.

    The datatype rides along unchanged. Without it the re-add would store a
    plain string and quietly drop a ``^^xsd:date`` that the user never touched.
    """
    # The full datatype URI, never the display local name: a non-XSD local name
    # does not resolve back, so deleting by it matches nothing and re-adding
    # mints a relative ``^^<Thing>`` beside the untouched original.
    datatype = ann.get("datatype_uri") or ann.get("datatype")
    is_uri = bool(ann.get("is_uri"))
    old_pred = ann.get("predicate_uri") or ann["predicate"]
    # Moving an annotation to another resource is the same delete-then-add, just
    # landing somewhere else, so it rides the same guards and rollback (#251).
    target_uri = new_subject_uri or subject_uri
    if (
        new_pred == old_pred
        and new_value == ann["value"]
        and (new_lang or None) == (ann.get("language") or None)
        and target_uri == subject_uri
    ):
        return False

    ont.delete_annotation(
        subject_uri,
        old_pred,
        ann["value"],
        lang=ann.get("language"),
        datatype=datatype,
        value_is_uri=is_uri,
    )
    try:
        ont.add_annotation(
            target_uri,
            new_pred,
            new_value,
            lang=None if is_uri else (new_lang or None),
            datatype=None if (is_uri or new_lang) else datatype,
            value_is_uri=is_uri,
        )
    except Exception as e:  # noqa: BLE001 - a rejected predicate must not eat the annotation
        ont.add_annotation(
            subject_uri,
            old_pred,
            ann["value"],
            lang=ann.get("language"),
            datatype=datatype,
            value_is_uri=is_uri,
        )
        show_message(f"Annotation unchanged: {e!s}", "error")
        return False
    return True


def _apply_restriction_add(ont, target_uri, prop_uri, rtype, value, on_class=None):
    """Write one restriction. Returns True on success.

    Shared by the Restrictions page and the Visualization panel (issue #221).
    The engine rejects a bad cardinality or an empty value by raising, and that
    has to reach the user as a message rather than a traceback.
    """
    try:
        ont.add_restriction(target_uri, prop_uri, rtype, value, on_class=on_class)
    except Exception as e:  # noqa: BLE001 - a rejected axiom must show as a message
        show_message(f"Error adding restriction: {e!s}", "error")
        return False
    save_checkpoint("Add restriction")
    show_message("Restriction added!", "success")
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
        parent_display = clearable_selectbox(
            "Parent Class",
            parent_options,
            key=f"add_cls_parent_{form_key}",
            current_display=parent_options[parent_index],
            help="Select a parent class for hierarchy",
            format_func=_pad_option,
        )
        ns_options, ns_lookup = build_namespace_options(ont)
        ns_display = clearable_selectbox(
            "Namespace",
            ns_options,
            key=f"add_cls_ns_{form_key}",
            current_display=ns_options[0] if ns_options else None,
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
            elif taken := ont.name_conflict_reason(name, "class", ns_val):
                show_message(taken, "error")
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
            viz_note_rename("property", prop["uri"], current_ref)
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
            viz_note_rename("individual", ind["uri"], current_ref)
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


def annotation_subject_options(classes, object_props, data_props, individuals):
    """Everything an annotation can hang off, as ``(options, display -> URI)``.

    Built per kind and tagged with it, so a class and an individual sharing a
    name stay apart, and keyed by URI throughout: local names collide across
    namespaces, and moving an annotation onto the wrong same-named resource
    would be silent (issue #251).
    """
    options: list[str] = []
    lookup: dict[str, str] = {}
    for kind, items in (
        ("Class", classes),
        ("Object Property", object_props),
        ("Data Property", data_props),
        ("Individual", individuals),
    ):
        kind_options, kind_lookup = build_uri_options(items)
        for display in kind_options:
            tagged = f"{display} [{kind}]"
            options.append(tagged)
            lookup[tagged] = kind_lookup[display]
    options.sort(key=str.lower)
    return options, lookup


def _render_panel_annotation_editor(
    ont, ename, classes, object_props, data_props, individuals
):
    """Edit the annotation behind a graph node, in the Details panel (#223).

    The node names the whole triple, which is looked up in the live ontology for
    the same reason the relation and restriction editors do it: a selection can
    outlive what it points at, and an annotation that has changed is a different
    annotation, so this has to say so rather than rewrite whatever is at hand.
    """
    parts = _edge_id_parts(ename, _ANN_ID_PARTS)
    ann = None
    subject_uri = ""
    if parts:
        subject_uri = parts[0]
        try:
            ann = next(
                (
                    a
                    for a in ont.get_annotations(subject_uri)
                    if annotation_matches_ename(subject_uri, a, parts)
                ),
                None,
            )
        except Exception:  # noqa: BLE001 - a subject that has gone reads as "gone"
            ann = None
    if ann is None:
        st.caption(
            "This annotation was edited or removed. Click a node to pick one up."
        )
        return

    render_annotation_form(
        ont,
        subject_uri,
        ann,
        _uid(ename),
        classes,
        object_props,
        data_props,
        individuals,
    )


def render_annotation_form(
    ont,
    subject_uri,
    ann,
    form_key,
    classes,
    object_props,
    data_props,
    individuals,
    on_close=None,
):
    """Render the edit form for one annotation (issue #257).

    Shared by the Annotations page rows and the Visualization details panel, so
    both rewrite the triple through the same guards and rollback. ``form_key``
    makes the widget keys unique — the page passes the row's position, the panel
    the selected node's id. ``on_close`` is what dismissing the editor means; the
    panel has no such thing (it follows the graph selection), so it passes None
    and gets no Cancel button.
    """
    subject_options, subject_lookup = annotation_subject_options(
        classes, object_props, data_props, individuals
    )
    # An annotation can sit on something the picker does not list — the ontology
    # itself, a SKOS concept — and an unlisted subject would otherwise select the
    # first entry, so saving an untouched annotation would quietly move it. Offer
    # the current subject as its own option instead, the way the relation editor
    # offers an external URI (issue #251).
    if subject_uri not in set(subject_lookup.values()):
        _own = f"{_uri_local_name(subject_uri)} [current]"
        subject_options = [_own, *subject_options]
        subject_lookup[_own] = subject_uri
    with st.form(f"edit_ann_{form_key}"):
        # Which resource it hangs off is editable, so an annotation can be moved
        # the way a relation or restriction can be re-pointed from here (#251).
        new_subject = required_selectbox(
            "On",
            subject_options,
            key=f"ann_on_{form_key}",
            current_display=subject_options[
                _uri_option_index(subject_options, subject_lookup, subject_uri)
            ],
            format_func=_pad_option,
            help="Move the annotation by choosing a different resource.",
        )
        new_pred = st.text_input(
            "Predicate",
            value=ann.get("predicate_uri") or ann["predicate"],
            help="A full URI, a prefixed name (dcterms:created), or a common "
            "name like label.",
        )
        new_value = st.text_input(
            "Value" if not ann.get("is_uri") else "Value (IRI)", value=ann["value"]
        )
        new_lang = ""
        if ann.get("is_uri"):
            # A resource-valued annotation has no language or datatype to carry;
            # it stays a resource through the rewrite.
            st.caption("Points at a resource, not a literal.")
        else:
            new_lang = language_selectbox(
                "Language",
                key=f"ann_lang_{form_key}",
                value=ann.get("language") or "",
            )
        if ann.get("datatype") and not ann.get("is_uri"):
            # Not editable here, but say it is there: it is carried through the
            # rewrite untouched, and a silent one would look like data loss.
            st.caption(f"Datatype: {ann['datatype']} (kept)")
        cancelled = False
        if on_close is None:
            save_col, del_col = st.columns(2)
        else:
            save_col, del_col, cancel_col = st.columns(3)
        with save_col:
            saved = st.form_submit_button("Save", use_container_width=True)
        with del_col:
            deleted = st.form_submit_button("Delete", use_container_width=True)
        if on_close is not None:
            with cancel_col:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        on_close()
        st.rerun()
    if deleted:
        ont.delete_annotation(
            subject_uri,
            ann.get("predicate_uri") or ann["predicate"],
            ann["value"],
            lang=ann.get("language"),
            # Same two reasons as the rewrite: the display local name does not
            # resolve back, and a literal match never finds a resource, so
            # either would report a delete that removed nothing.
            datatype=ann.get("datatype_uri") or ann.get("datatype"),
            value_is_uri=bool(ann.get("is_uri")),
        )
        save_checkpoint("Delete annotation")
        if on_close is not None:
            on_close()
        set_flash_message("Annotation deleted!", "success", toast=True)
        st.rerun()
    if saved:
        if _missing := missing_required(On=new_subject):
            # A cleared subject used to fall back to the one it came from, so
            # the annotation was rewritten onto a resource the user had
            # explicitly cleared.
            show_message(_missing, "error")
        elif not new_value.strip():
            show_message("Annotation value is required!", "error")
        elif lang_error := language_tag_error(new_lang):
            show_message(lang_error, "error")
        elif _apply_annotation_edit(
            ont,
            subject_uri,
            ann,
            new_pred,
            new_value,
            new_lang,
            new_subject_uri=subject_lookup.get(new_subject),
        ):
            save_checkpoint("Update annotation")
            if on_close is not None:
                on_close()
            set_flash_message("Annotation updated!", "success", toast=True)
            st.rerun()


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
    _panel_delete_edge(
        ont,
        "relation",
        f"viz_crel_{_uid(ename)}",
        # By URI: a local name resolves into the base namespace, so a relation
        # between imported classes would not be found and nothing would go.
        lambda: ont.remove_class_relation(
            rel.get("subject_uri") or rel["subject"],
            rel["relation"],
            rel.get("object_uri") or rel["object"],
        ),
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
    _panel_delete_edge(
        ont,
        "restriction",
        f"viz_rest_{_uid(ename)}",
        # By URI and by value, like the Restrictions page: a local name resolves
        # into the base namespace, and a sibling on the same property and type
        # would be deleted instead of this one (issue #152).
        lambda: ont.delete_restriction(
            src_uri,
            rest.get("property_uri") or rest["property"],
            rest["type"],
            value=rest.get("value_uri") or rest.get("value"),
            on_class=rest.get("on_class_uri") or rest.get("on_class"),
        ),
    )


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


def panel_heading_html(shown: str, full: str) -> str:
    """The details panel's heading: a node's label, linking to its whole value.

    A node draws a label cut to fit on it, and the heading is that label. As
    plain text Streamlit linkifies a URL in it, so a cut URL became a link to
    the cut URL and clicking it opened the wrong page (issue #313) — and a value
    that merely *starts* with a URL has the same problem with no whole URL to
    link to.

    So the heading is written as one HTML block, which markdown copies through
    raw: nothing in it is linkified, and the only link is the one built here,
    around the text the node drew and pointing at the value in full. Inline HTML
    would not do — markdown still parses the text between inline tags, and the
    linkifier put its own <a> inside ours.
    """
    text = html.escape(shown or full)
    is_url = full.startswith(("http://", "https://")) and not any(
        c.isspace() for c in full
    )
    if not is_url:
        return f"<p><strong>{text}</strong></p>"
    href = html.escape(full, quote=True)
    return f'<p><strong><a href="{href}" target="_blank">{text}</a></strong></p>'


def panel_subject_uri(ntype, ename, classes, object_props, data_props, individuals):
    """The URI of the selected node, when it is something to hang more off.

    Resolved from the same pools the entity editor uses. The edge-borne kinds
    (relations, restrictions) and the annotation nodes themselves have no URI of
    their own, so nothing is offered for them (issue #221).
    """
    pool = {
        "Class": classes,
        "Object Property": object_props,
        "Data Property": data_props,
        "Individual": individuals,
    }.get(ntype)
    if not pool or not ename:
        return None
    return next((e["uri"] for e in pool if _uid(e["uri"]) == ename), None)


def _render_panel_add_individual_form(ont, classes, ntype, ename):
    """Add an individual of the selected class, from the graph (issue #221).

    The class is the point of adding from here: an individual is always an
    instance *of* something, and the graph already says which.
    """
    cls_uri = _panel_add_parent(classes, ntype, ename)
    cls = next((c for c in classes if c["uri"] == cls_uri), None)
    if cls is None:
        _panel_close_add()
        st.rerun()

    st.markdown(f"**New {cls['name']}**")
    with st.form("panel_add_ind_form"):
        name = st.text_input("Individual Name *")
        label = st.text_input("Label")
        comment = st.text_area("Comment")
        ns_options, ns_lookup = build_namespace_options(ont)
        ns_display = clearable_selectbox(
            "Namespace",
            ns_options,
            key="panel_add_ind_ns",
            current_display=ns_options[0] if ns_options else None,
            help="Namespace the individual is created in (default is the base URI)",
        )
        add_col, cancel_col = st.columns(2)
        with add_col:
            submitted = st.form_submit_button(
                "Add individual", use_container_width=True
            )
        with cancel_col:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        _panel_close_add()
        st.rerun()
    if submitted:
        ns_val = ns_lookup.get(ns_display)
        if not name:
            show_message("Individual name is required!", "error")
        elif reason := ont.invalid_name_reason(name):
            show_message(reason, "error")
        elif taken := ont.name_conflict_reason(name, "individual", ns_val):
            show_message(taken, "error")
        else:
            # By URI, not by name: the class may live in another namespace, and
            # its local name alone would resolve into this ontology's own.
            ont.add_individual(
                name, cls["uri"], label=label, comment=comment, namespace=ns_val
            )
            save_checkpoint("Add individual")
            show_message(f"Individual '{name}' added!", "success")
            _panel_close_add()
            st.rerun()


def _render_panel_add_annotation_form(ont, subject_uri, subject_label):
    """Annotate the selected entity, from the graph (issue #221).

    The subject is whatever is selected, which is the whole saving: on the
    Annotations page you pick it out of a list of every resource in the
    ontology. Predicate options are shared with that page, so a type invented
    here is offered there and the other way round.
    """
    if not subject_uri:
        _panel_close_add()
        st.rerun()

    st.markdown(f"**Annotate {subject_label}**")
    options, lookup = annotation_predicate_options(ont)
    with st.form("panel_add_ann_form"):
        predicate_display = required_selectbox(
            "Annotation Type",
            options,
            key="panel_ann_predicate",
            current_display=options[0] if options else None,
            accept_new_options=True,
            help=(
                "Pick a type, or type your own to create it: a name like "
                "`wikidataId`, a bound prefix like `wdt:P31`, or a full URI."
            ),
        )
        value = st.text_area("Value *", key="panel_ann_value")
        lang = language_selectbox("Language", key="panel_ann_lang")
        add_col, cancel_col = st.columns(2)
        with add_col:
            submitted = st.form_submit_button(
                "Add annotation", use_container_width=True
            )
        with cancel_col:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        _panel_close_add()
        st.rerun()
    if submitted:
        if _missing := missing_required(**{"Annotation Type": predicate_display}):
            show_message(_missing, "error")
            return
        if not value.strip():
            show_message("Annotation value is required!", "error")
            return
        if lang_error := language_tag_error(lang):
            show_message(lang_error, "error")
            return
        predicate = lookup.get(predicate_display, predicate_display)
        try:
            ont.add_annotation(subject_uri, predicate, value, lang=lang or None)
        except Exception as e:  # noqa: BLE001 - a rejected predicate is a message
            show_message(str(e), "error")
            return
        save_checkpoint("Add annotation")
        show_message("Annotation added!", "success")
        _panel_close_add()
        st.rerun()


def _render_panel_add_buttons(classes, ntype, ename, subject_uri):
    """What you can create from what is selected, two to a row (issue #221).

    The set depends on the selection, so it is collected and then laid out
    rather than written as a fixed column of buttons: five stacked full-width
    ones push the entity editor off a narrow panel, and most are irrelevant to
    any given node anyway.

    Everything here follows the graph rather than asking again for what the
    graph already says: the class you selected becomes the parent, the subject,
    the type, or the annotated resource.
    """
    parent_uri = _panel_add_parent(classes, ntype, ename)
    parent_name = next((c["name"] for c in classes if c["uri"] == parent_uri), None)
    actions = [
        (
            "Add subclass" if parent_uri else "Add class",
            "class",
            f"Add a class under '{parent_name}'."
            if parent_uri
            else "Add a class. Select a class first to make it the parent.",
        )
    ]
    if parent_uri:
        actions += [
            ("Add relation", "crel", "Then click the class this one points at."),
            ("Add restriction", "rest", "Then click the class it restricts to."),
            ("Add individual", "ind", f"Add an instance of '{parent_name}'."),
        ]
    if subject_uri:
        actions.append(("Add annotation", "ann", "Annotate the selected entity."))

    for row_start in range(0, len(actions), 2):
        row = actions[row_start : row_start + 2]
        columns = st.columns(2)
        for column, (label, kind, help_text) in zip(columns, row, strict=False):
            with column:
                if st.button(
                    label,
                    key=f"panel_add_open_{kind}",
                    use_container_width=True,
                    help=help_text,
                ):
                    st.session_state["_viz_add_kind"] = kind
                    if kind in ("crel", "rest"):
                        st.session_state["_viz_crel_subject"] = ename
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
        subj_disp = required_selectbox(
            "Subject",
            options,
            key=f"panel_rel_subj_{_uid(ename or '')}",
            current_display=display_by_uri[subject["uri"]],
            format_func=_pad_option,
        )
        rel_type = st.selectbox("Relation Type", options=list(ont.CLASS_RELATIONS))
        obj_disp = required_selectbox(
            "Object",
            options,
            key=f"panel_rel_obj_{_uid(ename or '')}",
            current_display=display_by_uri[obj["uri"]],
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
    if submitted and (_missing := missing_required(Subject=subj_disp, Object=obj_disp)):
        show_message(_missing, "error")
    elif submitted and _apply_class_relation_add(
        ont,
        lookup.get(subj_disp),
        rel_type,
        lookup.get(obj_disp),
        subj_disp,
        obj_disp,
    ):
        _panel_close_add()
        st.rerun()


def _render_panel_add_restriction_form(ont, classes, object_props, ntype, ename):
    """Add a restriction by clicking the two classes it relates (issue #221).

    Same arm-then-pick as the relation form: the selected class is the one the
    restriction is applied to, and the next class you click is the one it points
    at. Only the types that *have* a second class are offered here — the two
    value restrictions and the three qualified cardinalities. hasValue and the
    plain cardinalities say something about one class on its own, so the graph
    has no second end to offer and they stay on the Restrictions page.

    ``object_props`` only, deliberately. Everything this flow can produce fills a
    class slot: the value of someValuesFrom/allValuesFrom, or the owl:onClass of
    a qualified cardinality. On a data property those slots take a data range
    instead, so offering one here would write ``owl:someValuesFrom :SomeClass``
    against an ``owl:DatatypeProperty`` — an axiom no reasoner accepts. Data
    properties stay on the Restrictions page until this flow can offer a
    datatype for them.
    """
    by_id = {_uid(c["uri"]): c for c in classes}
    subject = by_id.get(st.session_state.get("_viz_crel_subject"))
    if subject is None:
        _panel_close_add()
        st.rerun()
    if not object_props:
        st.markdown("**New restriction**")
        st.info(
            "Add an object property first. Restrictions built here point at a "
            "class, which a data property cannot do."
        )
        if st.button("Cancel", key="panel_add_rest_nocancel", use_container_width=True):
            _panel_close_add()
            st.rerun()
        return

    obj_id = st.session_state.get("_viz_crel_object")
    if not obj_id:
        st.markdown(f"**Restriction on {subject['name']}**")
        st.info("Now click the class it restricts to.")
        action, picked = resolve_picked_object(
            st.session_state["_viz_crel_subject"], ntype, ename
        )
        if action == "pick":
            st.session_state["_viz_crel_object"] = picked
            st.rerun()
        if action == "cancel":
            _panel_close_add()
            st.rerun()
        if st.button("Cancel", key="panel_add_rest_cancel", use_container_width=True):
            _panel_close_add()
            st.rerun()
        return

    other = by_id.get(obj_id)
    if other is None:
        st.session_state.pop("_viz_crel_object", None)
        st.rerun()

    st.markdown("**New restriction**")
    cls_options, cls_lookup = build_class_options(classes)
    prop_options, prop_lookup = build_uri_options(object_props)
    display_by_uri = {u: d for d, u in cls_lookup.items()}
    types = [t for t in ont.RESTRICTION_TYPES if restriction_references_class(t)]
    # Outside the form on purpose: a form batches until submit and does not rerun
    # when a widget inside it changes, so the fields that depend on the type
    # (which slot the picked class fills, and whether a count is needed) would
    # still be showing the previous type's shape when you pressed Add.
    rtype = st.selectbox("Restriction Type", options=types, key="panel_rest_type")
    qualified = restriction_takes_on_class(rtype)
    with st.form("panel_add_rest_form"):
        target_disp = required_selectbox(
            "Apply to Class",
            cls_options,
            key=f"panel_rest_target_{_uid(ename or '')}",
            current_display=display_by_uri[subject["uri"]],
            format_func=_pad_option,
        )
        prop_disp = required_selectbox(
            "On Property",
            prop_options,
            key=f"panel_rest_prop_{_uid(ename or '')}",
            current_display=prop_options[0] if prop_options else None,
            format_func=_pad_option,
        )
        # The picked class is the value for someValuesFrom / allValuesFrom, and
        # the owl:onClass for the qualified cardinalities. Same click, different
        # slot in the axiom, so the label says which one it is filling.
        klass_disp = required_selectbox(
            "Qualified on Class" if qualified else "Value (Class)",
            cls_options,
            key=f"panel_rest_cls_{_uid(ename or '')}",
            current_display=display_by_uri[other["uri"]],
            format_func=_pad_option,
        )
        cardinality = None
        if qualified:
            cardinality = st.number_input("Cardinality", min_value=0, value=1)
        add_col, cancel_col = st.columns(2)
        with add_col:
            submitted = st.form_submit_button(
                "Add restriction", use_container_width=True
            )
        with cancel_col:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)
    if cancelled:
        _panel_close_add()
        st.rerun()
    if submitted and (
        _missing := missing_required(
            **{
                "Apply to Class": target_disp,
                "On Property": prop_disp,
                ("Qualified on Class" if qualified else "Value (Class)"): klass_disp,
            }
        )
    ):
        show_message(_missing, "error")
    elif submitted:
        picked_uri = cls_lookup.get(klass_disp)
        on_class = picked_uri if restriction_takes_on_class(rtype) else None
        value = cardinality if restriction_takes_on_class(rtype) else picked_uri
        if _apply_restriction_add(
            ont,
            cls_lookup.get(target_disp),
            prop_lookup.get(prop_disp),
            rtype,
            value,
            on_class=on_class,
        ):
            _panel_close_add()
            st.rerun()


def _viz_selection_key(sel):
    """What identifies a selection, whether it is a node or an edge.

    Not the node id alone: the component sends one only for ``selectNode``, so
    every edge selection reports ``None`` there and comparing ids matched them
    all against each other. Type and name are on both.
    """
    if not isinstance(sel, dict):
        return None
    return (sel.get("ntype"), sel.get("ename"), sel.get("nodeId"))


def _viz_live_selection(live, dropped, revision):
    """Reconcile the component's reported selection with a deleted one (#222).

    Returns ``(selection, dropped)``: what the panel should show, and the marker
    to carry into the next run.

    The panel's selection is re-seeded from the component's own value on every
    run, and after a delete the component still reports what it last had, having
    not been told otherwise — so clearing the stored selection alone would last
    exactly one rerun and the panel would reopen on the entity that just went.
    The marker applies only while it matches, and only when there is one:
    comparing against a missing marker is how every edge selection came to be
    read as deleted.

    It is also scoped to the revision it was made at. Undo puts the entity back
    and the component reports the very same payload for it, which is
    indistinguishable from the stale one — so a marker that only cleared on a
    *different* pick left the restored entity unselectable for good. Any
    ontology change moves the revision, which is enough to retire it.
    """
    if not (isinstance(live, dict) and "selected" in live):
        return None, dropped
    if dropped is not None:
        key, at_revision = dropped
        if at_revision != revision:
            dropped = None
        elif _viz_selection_key(live) == key:
            return None, dropped
    return (live if live.get("selected") else None), None


def _panel_drop_selection() -> None:
    """Forget what was selected after deleting what it stood for (issue #222).

    Called after the checkpoint, so the revision recorded is the one the delete
    produced: anything later, undo included, retires the marker.
    """
    st.session_state["_viz_last_selection"] = None
    key = _viz_selection_key(st.session_state.get("graph_viewer"))
    if key is not None:
        st.session_state["_viz_dropped_selection"] = (
            key,
            st.session_state.get("_ont_mutation_count", 0),
        )


@st.dialog("Confirm delete")
def _panel_confirm_dialog(summary, key_suffix, delete) -> None:
    """Ask before deleting, in a modal rather than under the panel.

    The panel is a narrow column beside the graph, and its editor already fills
    it, so a confirmation drawn inline landed below the fold — the impact
    summary and the button to accept it were both off-screen unless you knew to
    scroll. A modal puts the question where it was asked.
    """
    st.warning(summary)
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button(
            "Confirm Delete",
            key=f"yes_{key_suffix}",
            type="primary",
            use_container_width=True,
        ):
            st.session_state[f"confirm_delete_{key_suffix}"] = False
            delete()
            st.rerun()
    with col_no:
        if st.button("Cancel", key=f"no_{key_suffix}", use_container_width=True):
            st.session_state[f"confirm_delete_{key_suffix}"] = False
            st.rerun()


def _panel_delete_entity(ont, kind, entity) -> None:
    """Delete button plus impact confirmation for the selected node (#222).

    The counterpart to adding from the graph (issue #221), and deliberately the
    same two-step the entity pages use: the summary names what else goes with
    it, which matters more here than there — from the graph you are one click
    from an entity you were only looking at.

    Outside the editor's form on purpose: a form batches until submit, so a
    confirmation drawn inside one could not appear until something else was
    submitted.
    """
    suffix = f"viz_{kind}_{_uid(entity['uri'])}"
    st.button(
        "🗑️ Delete",
        key=f"panel_del_{suffix}",
        use_container_width=True,
        help=f"Delete this {kind} from the ontology.",
        on_click=_cb_confirm_delete,
        args=(suffix,),
    )
    if not st.session_state.get(f"confirm_delete_{suffix}"):
        return

    def _delete():
        {
            "class": ont.delete_class,
            "property": ont.delete_property,
            "individual": ont.delete_individual,
        }[kind](entity["uri"])
        save_checkpoint(f"Delete {kind}")
        _panel_drop_selection()
        set_flash_message(f"{entity['name']} deleted!", "success", toast=True)

    _panel_confirm_dialog(
        ont.format_delete_impact(ont.get_delete_impact(entity["uri"], kind)),
        suffix,
        _delete,
    )


def _panel_delete_edge(ont, label, key_suffix, delete) -> None:
    """Delete button plus confirmation for an axiom drawn as an edge (#222).

    An axiom has no URI, so ``get_delete_impact`` has nothing to look up and the
    confirmation says what is going instead.

    Whether anything actually went is worth reporting: an edge can outlive the
    axiom behind it, and a delete that removed nothing while saying otherwise is
    the failure the page-level ones were fixed for (issue #152).
    ``delete_restriction`` answers that itself; ``remove_class_relation`` returns
    nothing, so the graph is measured around the call instead of assuming.
    """
    st.button(
        f"🗑️ Delete {label}",
        key=f"panel_del_{key_suffix}",
        use_container_width=True,
        on_click=_cb_confirm_delete,
        args=(key_suffix,),
    )
    if not st.session_state.get(f"confirm_delete_{key_suffix}"):
        return

    def _delete():
        before = len(ont.graph)
        changed = delete()
        if changed is None:
            changed = len(ont.graph) != before
        if changed:
            save_checkpoint(f"Delete {label}")
            _panel_drop_selection()
            set_flash_message(f"{label.capitalize()} deleted!", "success", toast=True)
        else:
            set_flash_message(f"This {label} is no longer in the ontology.", "error")

    _panel_confirm_dialog(
        f"Delete this {label}? The entities at either end are kept.",
        key_suffix,
        _delete,
    )


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
    if ntype == "Annotation":
        # Like the two above, an annotation has no URI of its own: it resolves
        # from the identity its node carries, not from an entity pool (#223).
        _render_panel_annotation_editor(
            ont, ename, classes, object_props, data_props, individuals
        )
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
            parent = clearable_selectbox(
                "Parent",
                ["None"] + others,
                key=f"panel_edit_cls_parent_{_uid(entity['uri'])}",
                current_display=cur if cur in others else "None",
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
            dom = clearable_selectbox(
                "Domain",
                cls_opts,
                key=f"panel_edit_prop_dom_{_uid(entity['uri'])}",
                current_display=cur_dom if cur_dom in cls_opts else None,
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
                rng = clearable_selectbox(
                    "Range",
                    cls_opts,
                    key=f"panel_edit_prop_rng_{_uid(entity['uri'])}",
                    current_display=cur_rng if cur_rng in cls_opts else None,
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
                rng = required_selectbox(
                    "Range (datatype)",
                    dts,
                    key=f"panel_edit_prop_dtrng_{_uid(entity['uri'])}",
                    current_display=default_rng,
                )
                new_range = rng if rng != default_rng else None
            new_domain = (cls_lookup.get(dom) or "") if dom != cur_dom else None
            if st.form_submit_button("Save", use_container_width=True):
                # A data property's range has no "no datatype" state to fall
                # back on: cleared, it would read as "leave as-is" and the save
                # would quietly do nothing to it.
                if ntype == "Data Property" and (
                    _missing := missing_required(**{"Range (datatype)": rng})
                ):
                    # No rerun: show_message draws inline, so rerunning here
                    # would wipe the error before it was ever seen.
                    show_message(_missing, "error")
                else:
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
            add_cls = clearable_selectbox(
                "Add to class",
                ["None"] + avail,
                key=f"panel_edit_ind_add_{_uid(entity['uri'])}",
                current_display="None",
            )
            rem_cls = clearable_selectbox(
                "Remove from class",
                ["None"] + cur_classes,
                key=f"panel_edit_ind_rem_{_uid(entity['uri'])}",
                current_display="None",
            )
            if st.form_submit_button("Save", use_container_width=True):
                if _apply_individual_edit(
                    ont, entity, name, label, comment, add_cls, rem_cls
                ):
                    save_checkpoint("Update individual")
                    show_message("Individual updated!", "success")
                st.rerun()

    _delete_kind = {
        "Class": "class",
        "Object Property": "property",
        "Data Property": "property",
        "Individual": "individual",
    }.get(ntype)
    if _delete_kind:
        _panel_delete_entity(ont, _delete_kind, entity)

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


LIST_PAGE_SIZE = 50
GRAPH_MAX_NODES = 500
#: The label on the graph's node panel. Named once because it is spoken about
#: elsewhere: the cap and focus notices tell the user to open it by name, and a
#: rename that missed them left the guidance pointing at a panel that no longer
#: existed under that name (review of PR #307).
VIZ_NODE_PANEL = "Node options"

FOCUS_BUILD_MAX_NODES = 5000


def prioritise_pinned(items, node_id_of, pinned):
    """Build the entities in ``pinned`` first, so the cap cannot drop them.

    Each loop stops at a fixed node budget, in list order, so an entity far
    enough down was never drawn. The pickers list every entity regardless of
    what was drawn, so an entity picked from one of them could be missing from
    the graph that is supposed to answer for it.

    Two things are pinned. The entity picked in **Find** (issue #234): picking
    one the cap had cut left the viewer nothing to centre on, it dropped the
    camera pin, and dropping the pin re-enabled the post-layout auto-fit — so
    the graph visibly reframed while the entity the user asked for was missing.
    And every entity on a **highlighted path** (issue #378): a path whose middle
    is not drawn is ringed in disconnected pieces, which reads as a broken
    highlight rather than as a view that does not hold all of it.

    Ordering alone is enough for classes, which are built first and so still fit
    inside the budget. It is not enough for the kinds after them: by the time
    those loops run the budget is spent, so each also lets a pinned entity past
    its own cap check. That costs at most one node over the cap per pinned
    entity — one for Find, at most the length of the path for a path — which is
    immaterial to the browser the cap protects. A graph silently missing what
    you asked for is not.

    ``pinned`` may be a single id or any collection of them; ``None`` and empty
    both mean "nothing pinned", and the items are returned untouched.
    """
    if not pinned:
        return items
    if isinstance(pinned, str):
        pinned = {pinned}
    else:
        pinned = set(pinned)
    first, rest = [], []
    for item in items:
        (first if node_id_of(item) in pinned else rest).append(item)
    if not first:
        return items
    return [*first, *rest]


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


def clearable_selectbox(label, options, key, current_display=None, **kwargs):
    """A dropdown carrying the clear cross, returning None once cleared.

    Streamlit only draws that cross when a selectbox may hold nothing, which
    means ``index=None`` and therefore no preselection — so the current value is
    seeded into the widget's own state instead. That is done once per value
    rather than once per render: re-seeding every run would undo a clear the
    moment it happened, and seeding only on first sight would show a stale value
    when the row underneath changes.

    Use this where empty is a legitimate answer: a picker that chooses what to
    show, or a field whose absence simply means "not set".
    """
    seeded_for = f"{key}__seeded_for"
    # ``key not in session_state`` is the second half of the condition, not a
    # redundancy: Streamlit drops the state of a widget that wasn't rendered on
    # a run, so leaving the page and coming back loses the value — while the
    # marker below, not being a widget key, survives and would suppress the
    # re-seed. The field then came back empty instead of showing what it holds.
    if (
        key not in st.session_state
        or st.session_state.get(seeded_for) != current_display
    ):
        st.session_state[seeded_for] = current_display
        st.session_state[key] = current_display if current_display in options else None
    return st.selectbox(label, options, index=None, key=key, **kwargs)


def required_selectbox(label, options, key, current_display=None, **kwargs):
    """A clearable dropdown for a field that still must be filled.

    Identical to :func:`clearable_selectbox` on screen; the difference is the
    obligation it puts on the caller, which has to check the result with
    :func:`missing_required` and refuse the write. Clearing a required dropdown
    used to fall back to whatever was selected before, so the write landed on a
    resource the user had explicitly cleared, with nothing said either way. A
    test pins the two together so a new form cannot offer one without the other.
    """
    return clearable_selectbox(label, options, key, current_display, **kwargs)


def missing_required(**fields) -> str | None:
    """The message for the first required field left empty, or None.

    Named so the error says which field, since a form can have several and
    "something is required" sends the user hunting.
    """
    for name, value in fields.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"{name} is required."
    return None


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

    # The value is a class, a cardinality or a literal depending on the type, so
    # the type picker sits *outside* the form below: a form batches until submit
    # and does not rerun when a widget inside it changes, so the value field
    # could not follow the type and had to stay free text for every type
    # (issue #250). Outside, changing the type reruns and the right widget
    # appears. It is pre-filled as a full URI in the two cases where a bare local
    # name would not round-trip (review P2):
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

    new_type = st.selectbox(
        "Restriction Type",
        types,
        index=types.index(rest["type"]) if rest["type"] in types else 0,
        key=f"er_type_{form_key}",
    )
    # Carry the row's own value into the class picker only when it already names
    # a class. A hasValue value is an individual or a literal, and offering it
    # here let a switch to someValuesFrom write owl:someValuesFrom :alice, naming
    # an individual where a class belongs (#250 review).
    value_options, value_lookup = _slot_options(
        classes,
        rest.get("value_uri") if restriction_value_is_class(rest["type"]) else None,
    )

    with st.form(f"edit_rest_form_{form_key}"):
        new_class = required_selectbox(
            "Applies to Class",
            cls_options,
            key=f"er_cls_{form_key}",
            current_display=cls_options[
                _uri_option_index(cls_options, cls_lookup, applied_uris[0])
            ],
            format_func=_pad_option,
        )
        new_property = required_selectbox(
            "Property",
            prop_options,
            key=f"er_prop_{form_key}",
            current_display=prop_options[
                _uri_option_index(
                    prop_options,
                    prop_lookup,
                    rest.get("property_uri") or rest["property"],
                )
            ],
            format_func=_pad_option,
        )
        if restriction_value_is_class(new_type):
            # someValuesFrom / allValuesFrom point at a class, so offer the
            # classes rather than asking for the name to be typed (issue #250).
            # A value the list does not hold — an imported class, an external
            # URI — is offered as itself, so an unchanged row round-trips.
            _picked_value = required_selectbox(
                "Value (Class)",
                value_options,
                key=f"er_valcls_{form_key}",
                current_display=value_options[
                    _uri_option_index(
                        value_options, value_lookup, rest.get("value_uri")
                    )
                ],
                format_func=_pad_option,
            )
            new_value = value_lookup.get(_picked_value) if _picked_value else None
        else:
            # Cardinalities and hasValue keep the free-text field: a number and a
            # literal are what they are, and the engine already reports a bad
            # one. Only the class-valued types gained a picker (issue #250).
            new_value = st.text_input(
                "Value",
                value=value_default,
                key=f"er_val_{form_key}",
                help="A number for a cardinality, or a literal for hasValue. A "
                "full URI is kept as it is.",
            )
        new_on_class = None
        if restriction_takes_on_class(new_type):
            new_on_class = required_selectbox(
                "Qualified on Class",
                on_options,
                key=f"er_onclass_{form_key}",
                current_display=on_options[
                    _uri_option_index(on_options, on_lookup, rest["on_class_uri"])
                    if rest.get("on_class_uri")
                    else 0
                ]
                if on_options
                else None,
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
        if saved and (
            _missing := missing_required(
                **{
                    "Applies to Class": new_class,
                    "Property": new_property,
                    # The value is a class only for the types that take one; the
                    # others are free text and the engine already reports empty.
                    **(
                        {"Value (Class)": new_value}
                        if restriction_value_is_class(new_type)
                        else {}
                    ),
                    # A qualified cardinality without its onClass is an axiom
                    # no reasoner accepts, so it cannot be left empty either.
                    **(
                        {"Qualified on Class": new_on_class}
                        if restriction_takes_on_class(new_type)
                        else {}
                    ),
                }
            )
        ):
            # A cleared dropdown used to fall back to the value it started with,
            # so the axiom was rewritten against a class or property the user had
            # explicitly cleared, and nothing was said either way.
            show_message(_missing, "error")
        elif saved:
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
                set_flash_message("Restriction updated!", "success", toast=True)
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
        target_disp = required_selectbox(
            "Apply to Class",
            cls_opts,
            key="add_rest_target",
            current_display=cls_opts[0] if cls_opts else None,
            format_func=_pad_option,
        )
        property_disp = required_selectbox(
            "On Property",
            prop_opts,
            key="add_rest_property",
            current_display=prop_opts[0] if prop_opts else None,
            format_func=_pad_option,
        )

        # Straight from the engine, so a type can never be offered here
        # that it doesn't understand, or omitted when it gains one.
        restriction_type = st.selectbox(
            "Restriction Type", options=list(ont.RESTRICTION_TYPES)
        )

        st.write("**Restriction Value:**")
        value = None
        value_disp = None
        value_label = None
        if restriction_type in ["someValuesFrom", "allValuesFrom"]:
            value_label = "Value (Class)"
            value_disp = required_selectbox(
                "Value (Class)",
                cls_opts,
                key="rest_class_value",
                current_display=cls_opts[0] if cls_opts else None,
                format_func=_pad_option,
            )
            value = cls_lookup.get(value_disp)
        elif restriction_type == "hasValue":
            ind_opts, ind_lookup = build_uri_options(ont.get_individuals())
            value_type = st.radio("Value Type", ["Literal", "Individual"])
            if value_type == "Literal":
                value = st.text_input("Literal Value")
            elif ind_opts:
                value_label = "Individual"
                value_disp = required_selectbox(
                    "Individual",
                    ind_opts,
                    key="rest_individual_value",
                    current_display=ind_opts[0],
                    format_func=_pad_option,
                )
                value = ind_lookup.get(value_disp)
            else:
                # Offering a "No individuals" placeholder let that string
                # be stored as the value.
                st.info("No individuals yet — create one, or use a literal.")
        else:
            value = st.number_input("Cardinality", min_value=0, value=1)

        on_class = None
        on_class_disp = None
        if restriction_takes_on_class(restriction_type):
            on_class_disp = required_selectbox(
                "Qualified on Class",
                cls_opts,
                key="qualified_class",
                current_display=cls_opts[0] if cls_opts else None,
                format_func=_pad_option,
            )
            on_class = cls_lookup.get(on_class_disp)

        submitted = st.form_submit_button("Add Restriction")
        if submitted and (
            _missing := missing_required(
                **{
                    "Apply to Class": target_disp,
                    "On Property": property_disp,
                    **({value_label: value_disp} if value_label else {}),
                    **(
                        {"Qualified on Class": on_class_disp}
                        if restriction_takes_on_class(restriction_type)
                        else {}
                    ),
                }
            )
        ):
            show_message(_missing, "error")
        elif submitted and _apply_restriction_add(
            ont,
            cls_lookup[target_disp],
            prop_lookup[property_disp],
            restriction_type,
            value,
            on_class=on_class,
        ):
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
        new_subject = required_selectbox(
            "Subject",
            row_options,
            key=f"es_{form_key}",
            current_display=row_options[subj_default],
            format_func=_pad_option,
        )
        new_type = st.selectbox(
            "Relation",
            types,
            index=types.index(rel["relation"]) if rel["relation"] in types else 0,
            key=f"et_{form_key}",
        )
        new_object = required_selectbox(
            "Object",
            row_options,
            key=f"eo_{form_key}",
            current_display=row_options[obj_default],
            format_func=_pad_option,
        )
        # The add forms can point an object at an entity in an ontology that
        # was never imported; without this the editor could keep such a
        # target but never set one.
        # ``.get``, not ``[]``: a cleared object has no URI to default to, and
        # the field is still offered because typing an external URI is how the
        # object is set when no local entity holds it.
        ext_obj_uri, ext_err = _external_uri_target(
            ont,
            row_lookup.get(new_object),
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
        # Checked against the resolved target rather than the dropdown: an
        # external URI legitimately replaces the pick, so an object typed there
        # is an object, and only having neither is an error.
        if saved and (
            _missing := missing_required(Subject=new_subject, Object=ext_obj_uri)
        ):
            # A cleared endpoint used to fall back to the one the row started
            # with, rewriting the triple against an entity the user had
            # explicitly cleared.
            show_message(_missing, "error")
            return
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
                set_flash_message("Relation updated!", "success", toast=True)
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


def annotation_predicate_options(ont):
    """The annotation types to offer, and what each display maps to.

    The ones already used in the ontology first, so a vocabulary in play
    stays in play, then the standard ones. Shared by the Annotations page and
    the Visualization panel so both offer the same list (issue #221).
    """
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
        display = f"{p['prefix']}:{p['local_name']}" if p["prefix"] else p["local_name"]
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
    predicate_options.sort(key=lambda x: x.lower())
    return predicate_options, predicate_lookup


def annotation_resource_options(resources) -> tuple:
    """``(options, lookup)`` for the pickers that choose what to annotate.

    Two resources can share a local name across namespaces (issue #119), and
    both annotation pickers identified the chosen one by its display string —
    positionally in the Add form, by first match in the View list. Either way
    the namesake was unreachable: choosing it annotated the first one instead,
    which is the same class of bug as writing by local name, one step earlier.

    Options carry the namespace tag the rest of the app already uses for this
    (``Organization (foaf)``) and the resource kind, and the lookup returns the
    resource itself, so nothing has to be matched back by string.
    """
    collisions = _build_name_collision_set(resources)
    options: list[str] = []
    lookup: dict[str, dict] = {}
    for r in resources:
        display = format_label_name(_disambiguated_name(r, collisions), r.get("label"))
        option = f"{display} [{r['type']}]"
        if option in lookup:
            # Nothing else tells them apart (the same name, kind and namespace
            # under two URIs, or an entry listed twice): name the URI rather
            # than let one option stand for both resources.
            option = f"{option} <{r.get('uri') or r['name']}>"
        options.append(option)
        lookup[option] = r
    return options, lookup


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
        predicate_options, predicate_lookup = annotation_predicate_options(ont)

        # Clear the value of the annotation just saved, on the run after it was
        # added: a widget's state can't be changed once it has been
        # instantiated, so the add flags it here instead. The type, the
        # resource and the language are left alone, so the same type can be
        # applied to one resource after another without re-picking it, and a
        # run of labels in one language is entered without re-picking that.
        if st.session_state.pop("_ann_clear_value", False):
            st.session_state["ann_value"] = ""

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
            # Display, kind, and a namespace tag where two share a local name.
            resource_options, resource_lookup = annotation_resource_options(
                all_resources
            )
            selected = required_selectbox(
                "Select Resource",
                resource_options,
                key="ann_resource",
                current_display=resource_options[0] if resource_options else None,
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
            predicate_display = required_selectbox(
                "Annotation Type",
                predicate_options,
                key="ann_predicate",
                current_display=predicate_options[0] if predicate_options else None,
                accept_new_options=True,
                help=(
                    "Pick a type, or type your own to create it: a name like "
                    "`wikidataId`, a bound prefix like `wdt:P31`, or a full "
                    "URI. A new name of your own is declared as an "
                    "annotation property in the ontology."
                ),
                format_func=_pad_option,
            )

            value = st.text_area("Value", key="ann_value")

            language = language_selectbox("Language Tag (optional)", key="ann_lang")

            submitted = st.form_submit_button("Add Annotation")
            if submitted:
                predicate_uri, predicate_reason = resolve_annotation_predicate_choice(
                    ont, predicate_display, predicate_lookup
                )
                if _missing := missing_required(
                    **{
                        "Select Resource": selected,
                        "Annotation Type": predicate_display,
                    }
                ):
                    # Clearing the resource used to leave the previous pick in
                    # place, so the annotation was written to a resource the
                    # user had cleared, with nothing said either way.
                    show_message(_missing, "error")
                elif not value:
                    show_message("Value is required!", "error")
                elif predicate_reason:
                    show_message(predicate_reason, "error")
                elif lang_error := language_tag_error(language):
                    show_message(lang_error, "error")
                else:
                    # The option the picker holds, not its position: two
                    # resources of the same local name used to produce the same
                    # option, and the second one resolved to the first.
                    picked = resource_lookup[selected]
                    # By URI, not by local name: a local name resolves into this
                    # ontology's own namespace, so annotating an imported class
                    # wrote to a namesake nothing declares. It looked right —
                    # the page read the annotations back the same way — but the
                    # editor and the row delete aimed at the real URI and
                    # quietly did nothing (the same reason every other form here
                    # picks by URI).
                    resource_ref = picked.get("uri") or picked["name"]
                    ont.add_annotation(
                        resource_ref,
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


#: How many lines the text hierarchy will print before it stops.
#:
#: A backstop, not the fix: the expansion below is linear in subClassOf edges,
#: so this is only reached by an ontology genuinely that large. 20,000 lines is
#: about a megabyte of text, which ``st.code`` still shows without complaint.
CLASS_TREE_MAX_LINES = 20_000


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

    A subClassOf graph is a DAG, not a tree, and printing it as one means a
    class with two parents is reached by two paths — so expanding it under each
    of them costs a second copy of everything below it. That compounds: a chain
    of diamonds doubles per level, and 33 classes rendered 131,071 lines. One
    real ontology produced 1.1 GB of text and took the browser down with it
    (issue #371). So a class is expanded once. It is still listed under every
    parent, because being a subclass of both is the fact the tree is drawing —
    only the repeat of its subtree is withheld, and marked where anything was
    actually withheld. That makes the output linear in subClassOf edges.
    """
    by_name = {}
    for c in classes:
        by_name.setdefault(c["name"], c)  # first wins, matching old lookup

    lines = []
    emitted = set()  # classes shown as a real node (not just a cycle back-edge)
    truncated = False

    def walk(start):
        nonlocal truncated
        # Explicit stack of (name, level, ancestors-on-this-branch).
        stack = [(start, 0, frozenset())]
        while stack:
            if len(lines) >= CLASS_TREE_MAX_LINES:
                # Checked here rather than at the end: the point is not to build
                # the text and then trim it, but never to build it.
                truncated = True
                return
            cls_name, level, path = stack.pop()
            cls = by_name.get(cls_name)
            if not cls:
                continue
            prefix = "  " * level + ("└── " if level > 0 else "")
            label = f" ({cls['label']})" if cls["label"] else ""
            if cls_name in path:
                lines.append(f"{prefix}{cls['name']}{label}  (cycle)")
                continue
            if cls_name in emitted:
                # Already expanded under another parent. Listed again, because
                # it really is a subclass of this one too; the note is only
                # added where there was a subtree to withhold.
                note = "  (shown above)" if cls["children"] else ""
                lines.append(f"{prefix}{cls['name']}{label}{note}")
                continue
            lines.append(f"{prefix}{cls['name']}{label}")
            emitted.add(cls_name)
            child_path = path | {cls_name}
            # Push in reverse so children pop in their listed order.
            for child in reversed(cls["children"]):
                stack.append((child, level + 1, child_path))

    for c in classes:
        if truncated:
            break
        if not c["parents"]:
            walk(c["name"])
    # Cover components that no root reaches (disconnected trees, all-cyclic
    # ontologies, multiple detached cycles).
    for c in classes:
        if truncated:
            break
        if c["name"] not in emitted:
            walk(c["name"])

    if truncated:
        # Said in the text itself: this is what the reader is looking at, and a
        # tree that simply stopped would read as a tree that ends there.
        left = len(by_name) - len(emitted)
        lines.append("")
        lines.append(
            f"… stopped at {CLASS_TREE_MAX_LINES:,} lines. "
            f"{left:,} of {len(by_name):,} classes are not shown. "
            f"The Interactive Graph draws a subset of an ontology this size, "
            f"and the Classes page lists all of it."
        )

    return "\n".join(lines)


#: ``node_kind`` is what the entity is to the graph, which is not always the
#: filter's own key: it is how the rename notes are keyed (see
#: :func:`viz_node_id`), and following them is what keeps a renamed entity in a
#: narrowed selection.
_FILTER_KINDS = (
    {
        "key": "class",
        "node_kind": "class",
        "toggle": "show_classes",
        "label": "Classes",
        "singular": "Class",
        "noun": "class",
        "plural": "classes",
    },
    {
        "key": "ind",
        "node_kind": "individual",
        "toggle": "show_individuals",
        "label": "Individuals",
        "singular": "Individual",
        "noun": "individual",
        "plural": "individuals",
    },
)


def viz_hidden_caption(
    focus_mode, focus_seeds, focus_depth, focus_hidden, hidden_by_filter
) -> str:
    """One line saying what is not on screen, or "" when everything is.

    A focus or a narrowed node filter is invisible on the canvas: a class you
    just added simply isn't drawn, and nothing says why. That reads as the graph
    losing the entity rather than as the view you set.

    Seeds are listed by name up to five, then counted, so a focus on half the
    ontology stays one short line.
    """
    parts = []
    if focus_mode and focus_seeds:
        shown = [s.split(": ", 1)[-1] for s in focus_seeds[:5]]
        names = ", ".join(shown)
        if len(focus_seeds) > 5:
            names += f", … (+{len(focus_seeds) - 5})"
        hops = "hop" if focus_depth == 1 else "hops"
        parts.append(f"Focused on {names} · {focus_depth} {hops}")
    if focus_hidden:
        parts.append(f"{focus_hidden} hidden by focus")
    if hidden_by_filter:
        parts.append(f"{hidden_by_filter} hidden by the node filter")
    return " · ".join(parts)


def viz_hidden_note_style(note: str) -> str:
    """A ``<style>`` block that writes ``note`` onto the Node options label.

    The note cannot simply be appended to the expander's label text: Streamlit's
    expander resets its open/closed state to the ``expanded`` argument whenever
    its label changes, and this note changes on every filter edit — so the panel
    snapped shut after each class you added (issue #267). Carrying the note as
    generated content keeps the label string constant: only this stylesheet
    changes, and the expander never notices.

    Everything but the text lives in the app's static CSS; this sets one custom
    property, and ``""`` for no note renders nothing.
    """
    return (
        "<style>.st-key-viz_filter_nodes "
        f"{{ --viz-hidden-note: {css_string(note)}; }}</style>"
    )


def css_string(text: str) -> str:
    """Quote ``text`` as a CSS string literal, safe inside a ``<style>`` block.

    Entity names reach this (the note lists the focus seeds), so quotes and
    backslashes are escaped as CSS demands, and ``<`` — the one character that
    could end the style element early — as a six-digit hex escape, which needs
    no trailing separator.
    """
    out = []
    for ch in text:
        if ch in '\\"':
            out.append("\\" + ch)
        elif ch == "<" or ord(ch) < 0x20:
            out.append(f"\\{ord(ch):06x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def follow_filter_renames(all_uris, selected, known, renames, node_kind):
    """Re-point a filter's selection at entities that were renamed (issue #275).

    A rename mints a new URI, so to a URI-keyed filter the entity you renamed
    reads as deleted and a stranger reads as created. That was harmless while
    every new entity was shown by default, but a narrowed filter now keeps new
    entities out (issue #194) — so renaming the very class you had narrowed to
    would have dropped it out of the view, and announced it as something you
    had just created.

    Returns ``(selected, known)`` with the renamed URIs swapped in, so the
    reconcile that follows sees one entity carrying on under a new name rather
    than a delete plus a create. Both halves move together: leaving ``known``
    behind would make the new URI look new all over again.

    Renames are recorded as graph node ids (see :func:`viz_note_rename`), which
    is why the current URIs are mapped through :func:`viz_node_id` to be found.
    A rename whose entity is no longer here re-points to nothing and keeps the
    URI it had, which the reconcile then drops as the deletion it is.
    """
    if not renames or (selected is None and known is None):
        return selected, known
    uri_by_id = {viz_node_id(node_kind, uri): uri for uri in all_uris}

    def moved(uri):
        node_id = _renamed_node_id(viz_node_id(node_kind, uri), renames)
        return uri_by_id.get(node_id, uri)

    return (
        None if selected is None else [moved(uri) for uri in selected],
        None if known is None else {moved(uri) for uri in known},
    )


def reconcile_filter_selection(
    all_uris, selected, known, replaced=False, auto_show_new=False
):
    """Reconcile one Visualization filter's selection with the ontology.

    Diffs the current URIs against those seen on the previous render (``known``)
    rather than resetting on every edit, so adding an entity or a restriction no
    longer wipes a narrowed filter (issue #180):

    - entities deleted since last render drop out of the selection;
    - entities created since last render are added *only while the filter is
      showing everything*, which is where "new content is shown by default"
      belongs (issue #194) — unless ``auto_show_new`` says otherwise, in which
      case they are added to a narrowed filter too (issue #326);
    - the rest of the selection is left as-is, so a deliberately emptied filter
      stays empty (nothing is "new" when the user clears it), which
      ``auto_show_new`` does not override.

    Auto-adding into a narrowed filter used to be unconditional. It is right for
    the default view and wrong for a curated one: a filter narrowed to a handful
    of key classes is a view the user built, and a class created afterwards
    should not push itself into it (issue #194). No extra state is needed to
    tell the two apart — ``known`` is the previous render's full entity set, so
    ``set(selected) == known`` already means "was showing everything". The
    caller pairs this with :func:`newly_hidden_uris` so a creation that lands
    outside the filter is announced rather than silently dropped.

    Which of the two a user wants turns out to depend on the ontology, not on
    taste: curating a handful of key classes out of five hundred, a new class
    forcing its way in is noise; building a small one class by class, being
    told each time that what you just made is not on the canvas is friction.
    ``auto_show_new`` is that choice, off by default so the shipped behaviour
    is unchanged (issue #326).

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
    # Coerced, not assumed: the session always stores a set here, but this pair
    # is the obvious thing to persist next, and JSON has no sets — a list would
    # otherwise reach the difference below and raise.
    known = None if known is None else set(known)
    if replaced or selected is None or known is None:
        selected_set = all_set
    elif known and not (all_set & known):
        # Not one entity in common: a replacement the counters did not flag
        # (they are a heuristic). Diffing alone used to recover this, because
        # every entity read as new and so got added; with auto-add restricted to
        # the unnarrowed case, a narrowed filter would survive into an unrelated
        # ontology and open it with an empty graph.
        selected_set = all_set
    elif set(selected) == known:
        # Was showing everything, so it keeps showing everything.
        selected_set = all_set
    else:
        selected_set = set(selected) & all_set
        if auto_show_new and selected:
            # Everything the previous render had never seen is new, and the
            # setting says new content joins the view rather than queueing up
            # behind "Show new" (issue #326).
            #
            # Not into a filter the user cleared, though. Empty is a view too,
            # and the one auto-add could never be undone from: every entity
            # created afterwards would walk straight back into it, so there
            # would be no way to keep an empty canvas while building. Clearing
            # it stays the deliberate act the rule above describes, and what is
            # created lands behind "Show new" the way it does with the setting
            # off.
            selected_set |= all_set - known
    ordered = [u for u in all_uris if u in selected_set]
    return ordered, all_set


def newly_hidden_uris(all_uris, selected, known):
    """Entities created since the last render that the filter is keeping hidden.

    ``selected`` is what :func:`reconcile_filter_selection` just returned and
    ``known`` the set it was given, i.e. the *previous* render's entity set.
    Returns the URIs in ``all_uris`` order, so the caller can say which entity
    was created but is not on the canvas (issue #194) — without it, a user who
    narrowed the filter earlier and forgot creates a class, sees nothing appear,
    and lands back on the confusion that opened issue #190.

    Empty on the first render and on a replacement, where everything is selected
    and so nothing is hidden.
    """
    if selected is None or known is None:
        return []
    fresh = set(all_uris) - set(known) - set(selected)
    return [uri for uri in all_uris if uri in fresh]


def viz_new_hidden_message(names, noun, plural) -> str:
    """The toast for entities that were created outside the node filter.

    Names the entity so the message is about the thing the user just made, and
    names the filter so the fix is obvious. A batch (an import into a narrowed
    view, several classes in one edit) switches to a count past three rather
    than growing a toast into a list.
    """
    if not names:
        return ""
    if len(names) == 1:
        what = f"{names[0]} created"
    elif len(names) <= 3:
        what = f"{', '.join(names)} created"
    else:
        what = f"{len(names)} {plural} created"
    return f"{what}, hidden by your {noun} filter"


_CLASS_TOKEN_SEPARATORS = re.compile(r"[\s,;]+")
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
    name (``fn:zero``), the disambiguated display form (``zero (fn)``), anything
    in the entry's optional ``aliases``, or a full URI, optionally wrapped in
    ``<>`` or quotes. Matching is exact first, then case-insensitive. A plain
    local name shared by several namespaces selects all of them — the prefixed
    form picks just one.

    Returns ``(keys, unmatched)``: the matched entries' ``uri`` values in
    entry-list order without repeats, and the tokens nothing matched, in input
    order. That field is the entry's identity rather than its label, because a
    label moves under the entity (issue #179); for the node filters it is the
    URI, and for the focus box the picker's label (see
    :func:`build_focus_seed_entries`).
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
        # Further spellings that are not the entry's identity. The focus box
        # needs them: two of its entries can be one IRI (a punned resource that
        # is both a class and a concept), so they are told apart by label and
        # the IRI is an alias both answer to.
        for alias in entry.get("aliases") or ():
            _register(alias, uri)

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


def build_focus_seed_entries(targets):
    """Describe focus-mode seeds for the paste / copy box (issue #283).

    ``targets`` is what the focus picker was built from, in its order: dicts
    carrying the ``kind`` word its label shows ("Class", "Individual", "Data
    Property", "Concept"), the ``name`` in the already-disambiguated form the
    picker lists, the ``label`` the multiselect holds it under, and the ``uri``
    where the entity has one (a SKOS concept's node is keyed by name instead).

    Returns ``(entries, tokens_by_label)``: entries in the shape
    :func:`parse_filter_text` reads, whose identity is the picker's label — so
    parsing answers in labels directly — and what to write each label down as.

    The label, not the URI, because one IRI can be two focus targets: OWL puns,
    and an imported vocabulary that types a resource both ``owl:Class`` and
    ``skos:Concept`` lists it under Classes and under Concepts. Keyed by URI
    the two collapsed into one, so ``Class:Person Concept:Person`` restored a
    single seed. The URI rides along as an alias instead, which is right on its
    own terms: it names both, so pasting it focuses on both.

    A seed is written as its plain name, and as ``Kind:Name`` when the name
    belongs to more than one kind — a class and an individual can share one, and
    the picker's labels are how the app tells them apart. The kind loses its
    space there (``DataProperty:``) because a token cannot carry one, and so
    does a name the picker has had to tag for its namespace (``zero(fn)``).
    That tag is the only namespace handling needed: the names arrive already
    disambiguated, since that is what the picker lists.
    """
    # A name the picker has had to tag carries a space ("zero (fn)"), and a
    # token cannot: closed up it survives the split, and the parser closes the
    # pasted text up the same way, so both forms are read.
    names = {t["label"]: _CLASS_DISPLAY_GAP.sub("(", t["name"]) for t in targets}
    kinds_by_name: dict[str, set] = {}
    for t in targets:
        kinds_by_name.setdefault(names[t["label"]], set()).add(t["kind"])
    entries = []
    tokens_by_label = {}
    for t in targets:
        name = names[t["label"]]
        entry = {
            "name": name,
            "uri": t["label"],
            "ambiguous": len(kinds_by_name.get(name, ())) > 1,
            "prefix": t["kind"].replace(" ", ""),
            "display": t["label"],
            "aliases": [t["uri"]] if t.get("uri") else [],
        }
        entries.append(entry)
        tokens_by_label[t["label"]] = filter_entry_token(entry)
    return entries, tokens_by_label


def _fmt_unknown(tokens, limit=20):
    """Render unmatched paste tokens for a warning, capped so a wholly wrong
    paste doesn't fill the panel."""
    shown = ", ".join(tokens[:limit])
    return f"{shown} (+{len(tokens) - limit} more)" if len(tokens) > limit else shown


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

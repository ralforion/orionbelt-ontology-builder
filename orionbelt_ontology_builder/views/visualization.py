"""The visualization page."""

import html
import json
import logging

import streamlit as st

from ..ui import (
    _FILTER_KINDS,
    _PAGE_BY_TYPE,
    _PRECISE_NAV_TYPES,
    GRAPH_MAX_NODES,
    PKG_DIR,
    VIZ_NODE_PANEL,
    _build_name_collision_set,
    _disambiguated_name,
    _edge_id,
    _edge_id_parts,
    _fmt_unknown,
    _nav_open_entity,
    _panel_add_kind,
    _Path,
    _persist_viz_file_state,
    _persist_viz_settings,
    _render_panel_add_annotation_form,
    _render_panel_add_buttons,
    _render_panel_add_class_form,
    _render_panel_add_individual_form,
    _render_panel_add_relation_form,
    _render_panel_add_restriction_form,
    _render_panel_entity_editor,
    _restore_viz_file_state,
    _restore_viz_settings,
    _str_list,
    _uid,
    _viz_live_selection,
    annotation_ename,
    build_class_hierarchy_text,
    build_class_options,
    build_filter_entries,
    build_focus_seed_entries,
    filter_entry_token,
    focus_seeds_from_selection,
    follow_filter_renames,
    follow_focus_seed_renames,
    follow_renamed_node_ids,
    graph_node_cap,
    local_store,
    newly_hidden_uris,
    panel_heading_html,
    panel_subject_uri,
    parse_filter_text,
    prioritise_find_target,
    prune_reused_focus_seeds,
    reconcile_filter_selection,
    seed_filter_from_saved,
    viz_apply_focus_click,
    viz_auto_show_new_toggled,
    viz_filter_changed,
    viz_find_changed,
    viz_focus_seeds_changed,
    viz_focus_toggle,
    viz_hidden_caption,
    viz_hidden_note_style,
    viz_leave_empty_focus,
    viz_mark_ontology_seen,
    viz_new_hidden_message,
    viz_node_id,
    viz_ontology_was_replaced,
    viz_rename_map,
    viz_set_focus_seeds,
    viz_sync,
)

logger = logging.getLogger(__name__)

# The row that holds the canvas and both of its overlays, keyed off the graph
# component itself — nothing else on the page carries that key.
_GRAPH_ROW = '[data-testid="stHorizontalBlock"]:has(.st-key-graph_viewer)'

# The canvas keeps its own download and fullscreen buttons in its top-right
# corner (see the graph viewer's #download-btn / #fullscreen-btn: 8px down,
# 32px tall). The overlays claim that same corner, and being outside the iframe
# they win every hit test, so they start below the toolbar instead of on top of
# it. test_viz_overlays.py keeps this in step with the buttons' own CSS.
_TOOLBAR_CLEARANCE = "2.75rem"


#: The clipboard icon the canvas uses, so both copies read as the same action.
COPY_ICON_PATH = (
    "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 "
    "2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"
)


def status_bar_copy_html(text: str) -> str:
    """The copy button that sits at the end of the status bar (issue #312).

    It takes the whole line the bar reports — the ellipsis is exactly what makes
    that worth having — where the canvas button takes only what the selection is
    called. Two buttons, two answers, both a single click.

    It is a little iframe of its own because Streamlit strips ``onclick`` from
    the HTML it renders: the clipboard is reachable only from real script, and
    the alternative was a button that could merely open something to copy out
    of. The async clipboard is used where there is one, and the old
    selection-based copy where there is not (the desktop webview).
    """
    # The text lands inside a <script>, where "</script>" in a value would end
    # the block early and spill the rest into the page as markup.
    payload = json.dumps(text).replace("</", "<\\/")
    return f"""<style>
    html, body {{ margin: 0; padding: 0; background: transparent; }}
    #copy {{
        width: 100%; height: 36px; border: none; background: transparent;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; opacity: 0.75; padding: 0;
    }}
    #copy:hover {{ opacity: 1; }}
    #copy svg {{ width: 16px; height: 16px; fill: #fff; }}
    </style>
    <button id="copy" title="Copy this line">
        <svg viewBox="0 0 24 24"><path d="{COPY_ICON_PATH}"/></svg>
    </button>
    <script>
    var TEXT = {payload};
    var COPY = '<path d="{COPY_ICON_PATH}"/>';
    var DONE = '<path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>';
    var btn = document.getElementById('copy');
    function flash(ok) {{
        btn.querySelector('svg').innerHTML = ok ? DONE : COPY;
        btn.title = ok ? 'Copied' : 'Could not copy — select the text instead';
        setTimeout(function () {{
            btn.querySelector('svg').innerHTML = COPY;
            btn.title = 'Copy this line';
        }}, 1400);
    }}
    function legacy() {{
        try {{
            var ta = document.createElement('textarea');
            ta.value = TEXT;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            var ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return ok;
        }} catch (e) {{ return false; }}
    }}
    btn.addEventListener('click', function () {{
        try {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(TEXT).then(
                    function () {{ flash(true); }},
                    function () {{ flash(legacy()); }}
                );
                return;
            }}
        }} catch (e) {{ /* no async clipboard here */ }}
        flash(legacy());
    }});
    </script>"""


def graph_overlay_css(dark: bool) -> str:
    """CSS that floats the graph page's panels over the canvas.

    The details panel used to take a quarter of the row's width, the reopen
    toggle a sliver of it, and the Node options picker pushed the graph down
    far enough to squeeze it to its floor. All three now sit on top of the
    canvas, so the graph keeps its size whatever is open.

    Solid cards, not translucent ones: chips and labels read over a busy graph
    are unreadable. Colours follow the graph's own two themes.
    """
    bg = "#262730" if dark else "#ffffff"
    edge = "rgba(250,250,250,0.2)" if dark else "rgba(49,51,63,0.15)"
    shadow = "0 8px 28px rgba(0,0,0,0.55)" if dark else "0 8px 28px rgba(0,0,0,0.16)"
    return f"""<style>
    {_GRAPH_ROW} {{
        position: relative;
        /* No column gap above the canvas. Every other row on this page is a
           control that reads as its own line; the canvas is the page, and the
           strip of empty graph above its legend already reads as a margin. */
        margin-top: -12px;
    }}
    /* The canvas takes the whole row, panel open or not. */
    {_GRAPH_ROW} > [data-testid="stColumn"]:has(.st-key-graph_viewer) {{
        flex: 1 1 100% !important;
        width: 100% !important;
    }}
    /* The details panel, as a card over the right of the canvas. Both edges are
       pinned so `max-height` has a length to resolve against, and a long editor
       scrolls inside the card instead of running past the graph. */
    {_GRAPH_ROW} > [data-testid="stColumn"]:has(.st-key-viz_hide_panel) {{
        position: absolute; top: {_TOOLBAR_CLEARANCE}; bottom: 0; right: 0;
        z-index: 20;
        width: 21rem; max-width: 45%;
        /* The cap has to pay for the offset too: the card starts a toolbar's
           height down, so a full-height one would hang that far past the
           canvas and over the status bar. Border-box so its padding is inside
           the cap rather than added to it. */
        box-sizing: border-box;
        height: fit-content;
        max-height: calc(100% - {_TOOLBAR_CLEARANCE});
        overflow-y: auto;
        padding: 0.6rem 0.9rem 0.9rem;
        background: {bg};
        border: 1px solid {edge};
        border-radius: 10px;
        box-shadow: {shadow};
    }}
    /* A dropdown inside a card opens into the card's own scrollport, and with
       no room left below the input BaseWeb flips the list upwards — over the
       input being typed into and the controls above it (issue #315). The list
       is portaled out of the card anyway, so while one is open the card stops
       scrolling and the list hangs past its edge instead. */
    {_GRAPH_ROW} > [data-testid="stColumn"]:has(.st-key-viz_hide_panel):has(
        [aria-expanded="true"]
    ),
    .st-key-viz_filter_nodes details[open]
        > [data-testid="stExpanderDetails"]:has([aria-expanded="true"]) {{
        overflow: visible;
    }}
    /* Panel closed: the reopen toggle alone, in the same corner. */
    {_GRAPH_ROW} > [data-testid="stColumn"]:has(.st-key-viz_show_panel) {{
        position: absolute; top: {_TOOLBAR_CLEARANCE}; right: 0; z-index: 20;
        width: auto;
    }}
    /* Node options drops over the canvas rather than shoving it down. The card
       hangs off the bottom edge of its own summary, so the picker still reads
       as part of the control it opened from. Above the details panel: it is
       the thing the click just opened. */
    .st-key-viz_filter_nodes {{ position: relative; z-index: 25; }}
    /* Streamlit animates an expander open by running a height animation on the
       <details> from JavaScript. It measures the body, which is out of the flow
       here, so the graph slid down by the height of a card that was never in
       the flow and snapped back when the animation ended. An !important
       declaration outranks a script animation, and with the body absolute the
       natural height is the summary — which is what it should have been all
       along. */
    .st-key-viz_filter_nodes details {{ height: auto !important; }}
    .st-key-viz_filter_nodes details[open] > [data-testid="stExpanderDetails"] {{
        position: absolute; top: 100%; left: 0; right: 0;
        max-height: 60vh; overflow-y: auto;
        padding: 0.25rem 1rem 1rem;
        background: {bg};
        border: 1px solid {edge};
        border-top: none;
        border-radius: 0 0 10px 10px;
        box-shadow: {shadow};
    }}
    </style>"""


def _add_annotation_nodes(net, ont, subject_uri, subject_node_id, room):
    """Hang ``subject_uri``'s annotations off its node, at most ``room`` of them.

    Returns ``(added, left_out)`` — how many nodes were drawn, and how many were
    left for want of room, so the caller can say so.

    Shared by the plain build and the pass focus mode runs after its prune
    (issue #272), so an annotation node looks the same however it got there.
    ``label`` and ``comment`` are skipped: they are already in the node's
    tooltip. Annotations are read by URI, not local name — two classes sharing a
    name would otherwise each show the other's.
    """
    added = 0
    left_out = 0
    for ann in ont.get_annotations(subject_uri):
        if ann["predicate"] in ("label", "comment"):
            continue
        if added >= room:
            left_out += 1
            continue
        ann_ename = annotation_ename(subject_uri, ann)
        ann_id = f"ann_{_uid(ann_ename)}"
        pred_display = ann.get("predicate_prefixed", ann["predicate"])
        value_display = (
            ann["value"][:30] + "..." if len(ann["value"]) > 30 else ann["value"]
        )
        # Count what was actually drawn: an id already in the graph is dropped by
        # the builder, and charging the budget for it would leave room unused.
        before = len(net.nodes)
        net.add_node(
            ann_id,
            label=value_display,
            title=f"{pred_display}: {ann['value']}",
            color={"background": "#795548", "border": "#5D4037"},
            shape="box",
            size=8,
            font={"size": 10, "color": "#f0f0f0"},
            ntype="Annotation",
            ename=ann_ename,
            # The drawn label is cut to fit the node; the details panel wants the
            # whole value. A cut URL there rendered as a link to the cut URL,
            # which opens the wrong page (issue #313).
            flabel=ann["value"],
        )
        net.add_edge(
            subject_node_id,
            ann_id,
            title=f"Annotation: {pred_display}",
            color="#A1887F",
            arrows="to",
            dashes=True,
        )
        added += len(net.nodes) - before
    return added, left_out


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
            # Off keeps the shipped behaviour: a narrowed filter is a view the
            # user built, and a class created afterwards waits behind "Show
            # new" rather than pushing into it (issues #194, #326).
            "auto_show_new": False,
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
        auto_show_new = _cfg["_viz_cfg_auto_show_new"]

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
        # Peeked, not popped: the focus-seed block below owns these notes and
        # clears them once both readers have had them. On a replacement they
        # name entities of the ontology that has just been swapped out, so they
        # are ignored here for the same reason they are there.
        _filter_renames = (
            None if replaced else st.session_state.get("_viz_pending_renames")
        )
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
            # A rename mints a new URI, which a URI-keyed filter reads as a
            # delete plus a create. Follow it first, so a narrowed filter keeps
            # the entity you just renamed instead of dropping it and announcing
            # it as new (issue #275, and the review of #194).
            _prev_sel, _prev_known = follow_filter_renames(
                _all_uris,
                _prev_sel,
                _prev_known,
                _filter_renames,
                _kind["node_kind"],
            )
            _sel_uris, _known_uris = reconcile_filter_selection(
                _all_uris,
                _prev_sel,
                _prev_known,
                replaced=replaced,
                auto_show_new=auto_show_new,
            )
            st.session_state[f"_viz_cfg_selected_{_key}_uris"] = _sel_uris
            st.session_state[f"_viz_cfg_known_{_key}_uris"] = _known_uris
            _display_by_uri = {e["uri"]: e["display"] for e in _entries}
            # An entity created while this filter is narrowed no longer forces
            # itself into the view (issue #194), so the creation would otherwise
            # be invisible: nothing appears on the canvas and nothing says why.
            # Announce it, and remember it so the panel can offer a one-click
            # way in. The remembered list is pruned rather than cleared on a
            # timer — an entry drops out the moment the entity is deleted or
            # shown — so the button always offers exactly what is still missing.
            _fresh_hidden = newly_hidden_uris(_all_uris, _sel_uris, _prev_known)
            _pending_key = f"_viz_new_hidden_{_key}"
            _pending_set = set(st.session_state.get(_pending_key) or []) | set(
                _fresh_hidden
            )
            _sel_set = set(_sel_uris)
            st.session_state[_pending_key] = [
                uri for uri in _all_uris if uri in _pending_set and uri not in _sel_set
            ]
            if _fresh_hidden:
                # Queued, not raised here: the hidden-note recompute further
                # down reruns the page whenever the hidden count changes —
                # which is exactly this render — and a toast raised before a
                # rerun is discarded with the rest of that pass's output.
                st.session_state["_viz_new_hidden_announce"] = [
                    *(st.session_state.get("_viz_new_hidden_announce") or []),
                    viz_new_hidden_message(
                        [_display_by_uri[u] for u in _fresh_hidden],
                        _kind["noun"],
                        _kind["plural"],
                    ),
                ]
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
        # The same targets in list form, carrying what the paste / copy box
        # needs to write one down and read it back (issue #283).
        focus_records: list[dict] = []

        def _focus_target(kind_word, name, node_kind, ref, uri=None):
            """Register one focusable entity under the label the picker shows."""
            label = f"{kind_word}: {name}"
            focus_targets[label] = viz_node_id(node_kind, ref)
            focus_records.append(
                {"kind": kind_word, "name": name, "uri": uri, "label": label}
            )

        if show_classes:
            for e in class_entries:
                _focus_target("Class", e["display"], "class", e["uri"], e["uri"])
        if show_individuals:
            for e in ind_entries:
                _focus_target(
                    "Individual", e["display"], "individual", e["uri"], e["uri"]
                )
        if show_data_props:
            for prop in data_props:
                _focus_target(
                    "Data Property", prop["name"], "property", prop["uri"], prop["uri"]
                )
        if show_skos and _has_skos:
            for concept in ont.get_concepts():
                # A concept's node is keyed by name, not by URI (see
                # viz_node_id), but the URI is still what a paste may carry.
                _focus_target(
                    "Concept",
                    concept["name"],
                    "concept",
                    concept["name"],
                    concept.get("uri"),
                )

        # A seed whose entity was renamed is held under a label that no longer
        # exists; re-point it at the new one first, or the prune below reads the
        # rename as "the class is gone" and focus mode falls back to an
        # arbitrary node (issue #275). Both seed sources are re-pointed from this
        # one pop: the labels already in session here, and the ids restored from
        # the linked file further down.
        _renames = st.session_state.pop("_viz_pending_renames", None)
        if replaced:
            # The notes name entities of the ontology that has just been swapped
            # out. Following them into the new one would re-point a seed at
            # whatever happens to hold that URI now, which is the very thing the
            # reuse prune below exists to stop (issue #180).
            _renames = None
        # The graph component carries a renamed node's cached position over to
        # the id it now has, so the render it lands on stays where it was
        # instead of re-framing the whole graph (issue #329). Flattened here
        # because the component applies one hop per id.
        _viz_renames = viz_rename_map(_renames)
        if _renames and "_viz_cfg_focus_seeds" in st.session_state:
            (
                st.session_state["_viz_cfg_focus_seeds"],
                st.session_state["_viz_cfg_focus_seed_ids_by_label"],
            ) = follow_focus_seed_renames(
                st.session_state["_viz_cfg_focus_seeds"],
                st.session_state.get("_viz_cfg_focus_seed_ids_by_label"),
                focus_targets,
                _renames,
            )

        # Seeds whose label now names a *different* entity than it did last
        # render belong to an ontology that has since been swapped out, so drop
        # them before anything reads or persists them.
        if "_viz_cfg_focus_seeds" in st.session_state:
            # Through the setter, so an id recorded for a label the prune has
            # just dropped goes with it. This runs whether or not focus mode is
            # on, and it is the path that empties the seeds while the mode is
            # off — where nothing else trims the map (Codex review of PR #336).
            viz_set_focus_seeds(
                prune_reused_focus_seeds(
                    st.session_state["_viz_cfg_focus_seeds"],
                    st.session_state.get("_viz_cfg_focus_seed_ids_by_label"),
                    focus_targets,
                )
            )

        # Seeds saved for this linked file are stored as node ids (#164); turn
        # them back into the labels the multiselect works in. An id whose entity
        # is gone — or whose type is toggled off, and so isn't in focus_targets —
        # simply drops out, the same pruning the focus block does below.
        _pending_seed_ids = st.session_state.pop("_viz_pending_focus_seed_ids", None)
        if _pending_seed_ids and "_viz_cfg_focus_seeds" not in st.session_state:
            # An id saved before a rename made earlier this session resolves to
            # nothing, and there are no labels in session yet for the block above
            # to have followed — this is the first look at the file's seeds.
            _pending_seed_ids = follow_renamed_node_ids(_pending_seed_ids, _renames)
            _label_by_id = {node_id: label for label, node_id in focus_targets.items()}
            _restored_seeds = [
                _label_by_id[i] for i in _pending_seed_ids if i in _label_by_id
            ]
            if _restored_seeds:
                viz_set_focus_seeds(_restored_seeds)

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
        # Find, the mode switch, then the panel the mode chooses the contents
        # of. Focus is not a node filter: turning it on *replaces* the filter
        # controls with its own (see the branch below), so the switch belongs
        # outside the panel it swaps, next to Find — the two are a pair, one
        # picking an entity and the other narrowing to it. It used to sit inside
        # that panel, one click deep, while ten display toggles that matter far
        # less sat in the open (issue #305).
        # The mode column is sized to the checkbox, not to an even third: the
        # spare width goes to the panel, whose collapsed label carries the note
        # about what the view is holding back.
        _find_col, _mode_col, _filter_col = st.columns([1, 0.5, 2.5])
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
                                viz_set_focus_seeds(_seeds + [_find_choice])
                                _reveal_rerun = True
                        if _reveal_rerun:
                            st.rerun()
        # What the view is holding back, on the expander's own label: it costs
        # no vertical space there, and it sits on the control that causes it.
        # Written by the run that built the graph (below), because the numbers
        # come from the focus controls inside this very expander and from the
        # prune, neither of which has happened yet. The CSS hides it while the
        # expander is open — the controls then say it in full.
        #
        # It reaches the label as generated content, not as part of the label
        # string: Streamlit's expander snaps back to `expanded` whenever its
        # label changes, so a note that moves with the filter closed the panel
        # under the user on every edit (issue #267).
        with _mode_col:
            focus_mode = st.checkbox(
                "Focus on one node",
                key="viz_focus_mode",
                on_change=viz_focus_toggle,
                help=(
                    "Show only a chosen node plus everything linked to it within "
                    "N hops, across all node types — handy for large ontologies "
                    "where showing everything at once is overwhelming. "
                    "Annotations come along with whatever is shown; the "
                    "Annotations checkbox above still turns them off. "
                    "The panel beside this switches to the focus controls."
                ),
            )

        _hidden_note = st.session_state.get("_viz_hidden_note") or ""
        with (
            _filter_col.container(key="viz_filter_nodes"),
            st.expander(VIZ_NODE_PANEL, expanded=False),
        ):
            st.html(viz_hidden_note_style(_hidden_note))
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
                # Written before the branch below reruns. Labels that have just
                # resolved to nothing must not survive as "the seeds to restore":
                # they are still truthy, so switching focus back on would skip
                # re-deriving from the class selection, find them invalid again,
                # and turn straight off — a focus that can never be switched on
                # again (the Codex review of PR #336).
                viz_set_focus_seeds(saved_seeds)
                if not saved_seeds:
                    # Nothing left to focus on. This used to stand in an
                    # arbitrary first entity, which is how the picker became
                    # impossible to clear and how a focus whose entity type was
                    # switched off silently moved to a stranger (issue #335).
                    # Leave the mode instead, the one landing every route out of
                    # a focus now shares (issue #328). Reruns so the panel can
                    # swap back to the node filter; it converges because the
                    # mode is off on the next pass, so this branch is not taken.
                    viz_leave_empty_focus()
                    # Queued, not raised here: this pass reruns, and a toast
                    # drawn before a rerun goes with the rest of its output.
                    st.session_state["_viz_focus_left_note"] = True
                    st.rerun()
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
                        on_change=viz_focus_seeds_changed,
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
                # Picking seeds out of a long list is slow and a focus worth
                # setting is worth keeping, so focus mode takes a pasted list
                # too and prints the current one back in the same syntax — the
                # node filter's story (issue #179), asked for here by #283. It
                # sits where that box does, so the button does not move when the
                # panel switches between the two modes.
                # Parsing answers in the picker's own labels: those are the
                # entries' identity, since one IRI can be two focus targets.
                _focus_entries, _focus_tokens = build_focus_seed_entries(focus_records)
                with st.columns([1, 1])[1].popover(
                    "Paste / copy", use_container_width=True
                ):
                    _fpaste_text = st.text_area(
                        "Paste a list of focus nodes",
                        key="viz_focus_paste",
                        height=80,
                        placeholder="Person Organization Dog",
                        help="Separate names with spaces, commas or line breaks. "
                        "Applying replaces the focus. A name shared by several "
                        "kinds focuses on all of them — write 'Class:Person' "
                        "(or paste the full URI) to pick just one.",
                    )
                    if st.button(
                        "Apply pasted list",
                        key="viz_focus_apply_paste",
                        help="Focus on exactly the pasted entities.",
                    ):
                        _fpasted, _funknown = parse_filter_text(
                            _fpaste_text, _focus_entries
                        )
                        # Recorded, not warned from here, for the reason the
                        # node filter's box records it: applying reruns the
                        # page and takes anything drawn on that pass with it.
                        st.session_state["_viz_focus_paste_unknown"] = _funknown
                        if _fpasted:
                            viz_set_focus_seeds(_fpasted)
                            st.rerun()
                        elif not _funknown:
                            st.info("Paste one or more entity names first.")
                    _funknown_last = st.session_state.get("_viz_focus_paste_unknown")
                    if _funknown_last:
                        st.warning(
                            "Ignored, not focusable (the entity types above "
                            f"decide what is): {_fmt_unknown(_funknown_last)}"
                        )
                    if focus_seeds:
                        st.caption("Current focus — copy to restore it later:")
                        st.code(
                            " ".join(
                                _focus_tokens[s]
                                for s in focus_seeds
                                if s in _focus_tokens
                            ),
                            language=None,
                            wrap_lines=True,
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
                    # Entities created since the filter was narrowed, which the
                    # view is therefore holding back (issue #194). The button
                    # only exists while there are some, so the usual two-button
                    # row is unchanged for everyone else.
                    _new_hidden = st.session_state.get(f"_viz_new_hidden_{_key}") or []
                    if _new_hidden:
                        _bcol1, _bcol_new, _bcol2 = st.columns([1, 1, 1])
                    else:
                        _bcol1, _bcol2 = st.columns([1, 1])
                        _bcol_new = None
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
                    if _bcol_new is not None:
                        with _bcol_new:
                            # Adds them to the selection rather than replacing
                            # it: the point is to keep the curated view and let
                            # the new entity join it.
                            if st.button(
                                f"Show new ({len(_new_hidden)})",
                                key=f"viz_show_new_{_key}",
                                use_container_width=True,
                                help=f"Add the {_plural} created since you "
                                "narrowed this filter to the selection.",
                            ):
                                _keep = set(_picked_uris) | set(_new_hidden)
                                st.session_state[f"_viz_cfg_selected_{_key}_uris"] = [
                                    u for u in active["uris"] if u in _keep
                                ]
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
                            # Recorded rather than warned from here. Applying a
                            # selection changes the hidden note, which reruns
                            # the page, and anything drawn on the pass that
                            # reruns is discarded with it — so a partly matching
                            # paste applied silently and never said what it had
                            # dropped. Recorded, it is there on the pass the
                            # user sees, and stands until the next Apply
                            # replaces it. Per kind, so the individuals box does
                            # not inherit what the classes box ignored.
                            st.session_state[f"_viz_paste_unknown_{_key}"] = _unknown
                            if _pasted:
                                st.session_state[f"_viz_cfg_selected_{_key}_uris"] = (
                                    _pasted
                                )
                                st.rerun()
                            elif not _unknown:
                                st.info(f"Paste one or more {_noun} names first.")
                        _unknown_last = st.session_state.get(
                            f"_viz_paste_unknown_{_key}"
                        )
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
                    # Which behaviour a narrowed filter should have is a
                    # property of the ontology you are working on, so it is a
                    # setting rather than a fixed rule (issue #326). It sits
                    # here, under the "Show new" button it replaces, because
                    # this is where the behaviour is visible; it governs every
                    # filterable kind, not just the segment on screen, so the
                    # label names none of them.
                    st.checkbox(
                        "Auto-show new",
                        key="viz_auto_show_new",
                        on_change=viz_auto_show_new_toggled,
                        help="Let entities created from now on join a narrowed "
                        "filter by themselves, instead of being held back and "
                        "offered as 'Show new'. Turning it on also lets in "
                        "whatever is queued there now. Applies to every "
                        "filterable kind.",
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
        # cannot resolve until some unrelated change happened to evict it. 20:
        # focus mode stopped charging an annotation a hop (issue #272), so a
        # cached focus payload is one built under the old pruning.
        _graph_ver = 20
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
            # Node id -> the resource it stands for, for everything annotations
            # can hang off. Focus mode adds them after its prune, so it needs a
            # way back from a node it kept to the resource to read (issue #272).
            annotatable: dict = {}

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
                    annotatable[cls_node_id] = cls["uri"]
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
                    annotatable[ind_node_id] = ind["uri"]
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

            # Add annotations for classes and individuals.
            #
            # Not under a focus: that build is allowed past the render cap
            # because the prune brings it back down, so an annotation added here
            # could be spent on an entity the focus then throws away — and the
            # ones belonging to the entities it keeps would never be reached at
            # all (issue #272 review). The focus pass below adds them once it
            # knows what survived.
            if show_annotations and not focus_pruning and node_count < max_nodes:
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
                            added, _left = _add_annotation_nodes(
                                net,
                                ont,
                                cls["uri"],
                                _uid(cls["uri"]),
                                max_nodes - node_count,
                            )
                            node_count += added
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
                            added, _left = _add_annotation_nodes(
                                net,
                                ont,
                                ind["uri"],
                                ind_node_id,
                                max_nodes - node_count,
                            )
                            node_count += added
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
                    # ``get_concepts()`` returns ``prefLabel`` and ``schemes``.
                    # This read ``pref_label`` and ``scheme``, which it has never
                    # returned, so every SKOS node fell back to its local name
                    # and the tooltip never showed a label or a scheme.
                    label = concept.get("prefLabel") or concept["name"]
                    title = f"SKOS Concept: {concept['name']}"
                    if concept.get("prefLabel"):
                        title += f"\nprefLabel: {concept['prefLabel']}"
                    if concept.get("definition"):
                        title += f"\nDefinition: {concept['definition'][:100]}"
                    if concept.get("schemes"):
                        title += f"\nScheme: {', '.join(concept['schemes'])}"
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
                                flabel=o_str,
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
                    f"{VIZ_NODE_PANEL}, or focus on one node, to see the rest."
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

                    # Now that the hops are counted, hang the annotations off
                    # what survived (issue #272). An annotation node belongs to
                    # the one entity it annotates and leads nowhere else, so it
                    # is no part of the neighbourhood walk — it used to cost a
                    # hop, which drew the seed's neighbours stripped of their
                    # annotations. Built here rather than with the rest of the
                    # graph so the ones that end up drawn are the ones the focus
                    # kept, whatever the assembly ran out of before it
                    # (issue #272 review). Counted after focus_hidden, which is
                    # about the entities the focus hid.
                    if show_annotations:
                        room = GRAPH_MAX_NODES - len(net.nodes)
                        ann_left_out = 0
                        # Sorted, so which annotations a tight budget reaches is
                        # the same on every render of the same graph.
                        for node_id in sorted(keep & set(annotatable)):
                            try:
                                added, left_out = _add_annotation_nodes(
                                    net,
                                    ont,
                                    annotatable[node_id],
                                    node_id,
                                    max(room, 0),
                                )
                            except Exception:
                                logger.debug(
                                    "Skipping a focused annotation node",
                                    exc_info=True,
                                )
                                continue
                            room -= added
                            ann_left_out += left_out
                        if ann_left_out and not graph_notice:
                            graph_notice = (
                                f"This focus and its annotations cover more than "
                                f"the {GRAPH_MAX_NODES} nodes the graph can draw, "
                                f"so {ann_left_out} annotation(s) are not shown. "
                                f"Pick fewer focus nodes, a lower depth, or turn "
                                f"Annotations off."
                            )
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
                        f"or individuals in {VIZ_NODE_PANEL} to bring it into "
                        f"range."
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
        # Recompute the note for the Node options label now that the focus
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
        # Past that rerun, so it survives to reach the user: what the filter
        # kept out of the view when it was created (issue #194).
        for _announcement in (
            st.session_state.pop("_viz_new_hidden_announce", None) or []
        ):
            st.toast(_announcement, icon="🙈")
        # Focus mode ended itself because nothing was left to focus on — the
        # entity went, its type was switched off, or there was nothing to derive
        # a first seed from. Silently un-ticking the box is the confusing half of
        # not standing an arbitrary entity in (issue #335), so say so, and say
        # what starts a focus instead.
        if st.session_state.pop("_viz_focus_left_note", False):
            st.toast(
                "Focus off: nothing left to focus on. Ctrl/Cmd-click a node to "
                "start a new one.",
                icon="🎯",
            )
        # Say what is being held back, small, right above the canvas: a focus or
        # a narrowed filter is otherwise invisible, and an entity that isn't
        # drawn looks lost rather than filtered (issue #222 follow-up).
        if gdata:
            import os as _os

            _component_path = str(PKG_DIR / "lib" / "graph_viewer")
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

            # Everything that opens on this page used to be paid for out of
            # the canvas: the details panel took a quarter of the width, the
            # reopen toggle took a sliver of it, and the Node options picker
            # pushed the graph down far enough to squeeze it to its floor.
            st.markdown(graph_overlay_css(_gv_dark), unsafe_allow_html=True)

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
                    # What the canvas copy button offers after a rebuild. The
                    # component restores a selected *node* by id and can read
                    # the rest off it, but an edge selection has no id to
                    # restore — without this the button vanished on the next
                    # rerun while the edge was still selected (issue #312).
                    copy_text=(
                        (_prev_sel.get("flabel") or _prev_sel.get("label") or "")
                        if _prev_has_sel
                        else ""
                    ),
                    # Find & centre target + a change-seq, so the component
                    # re-centres only on a fresh pick (issue #144).
                    focus_node=_find_id,
                    focus_seq=st.session_state.get("_viz_find_seq", 0),
                    # On desktop the webview can't download; the component sends
                    # the PNG back for us to save instead (#86).
                    web_download=not local_store.local_persist_enabled(),
                    # Where entities renamed since the last render went, so the
                    # cached layout follows them and a rename doesn't zoom the
                    # graph out (issue #329).
                    renames=json.dumps(_viz_renames),
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

            # A modifier-click in the graph requests focusing on a node: add it
            # to the "Focus on one node" seeds and enable focus mode (issue #56),
            # or replace them with it when the click was an Alt-click (#276). The
            # reqId guard ensures each click is applied once (the component value
            # persists across reruns).
            if isinstance(selection, dict) and selection.get("focusRequest"):
                _req_id = selection.get("reqId")
                if _req_id and _req_id != st.session_state.get("_viz_last_focus_req"):
                    st.session_state["_viz_last_focus_req"] = _req_id
                    _id_to_label = {v: k for k, v in focus_targets.items()}
                    _focus_label = _id_to_label.get(selection.get("nodeId"))
                    if _focus_label:
                        _replace = bool(selection.get("replace"))
                        _seeds, _focus_on = viz_apply_focus_click(
                            _focus_label, replace=_replace
                        )
                        if not _focus_on:
                            _note = "Focus off"
                        elif _focus_label not in _seeds:
                            # Ctrl/Cmd-click took it out and left others behind.
                            _note = f"Dropped {_focus_label} from the focus"
                        else:
                            _note = f"Focusing on {_focus_label}" + (
                                " only" if _replace else ""
                            )
                        st.toast(_note, icon="🎯")
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
                            ont, classes, _sel_ntype, _sel_ename
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
                            "Click a node to see details. Ctrl/Cmd-click adds it to "
                            "the focus, Alt-click focuses on it alone."
                        )
                        _render_panel_add_buttons(classes, None, None, None)
                    else:
                        # The node's own label reads best here, but it is cut
                        # to fit the node — so the link under it is the value in
                        # full, not the cut text (issue #313).
                        _shown = _sel.get("label", "")
                        st.markdown(
                            panel_heading_html(_shown, _sel.get("flabel") or _shown),
                            unsafe_allow_html=True,
                        )
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
                # The line is one row and ellipsises what does not fit, so the
                # whole of it goes in the tooltip — otherwise the tail of an
                # annotation's value can be neither read nor selected (#312).
                _bar_title = ""
                if has_selection:
                    _full_label = _sel.get("flabel") or _sel.get("label", "")
                    title_text = (_sel.get("title") or "").replace("\n", " | ")
                    prefix = "Edge: " if _sel.get("isEdge") else ""
                    _bar_title = f"{prefix}{_full_label}"
                    sel_html = f"<b>{html.escape(_bar_title)}</b>"
                    if title_text:
                        _bar_title += f" — {title_text}"
                        sel_html += f" — {html.escape(title_text)}"
                else:
                    sel_html = (
                        "Click a node or edge to see details · "
                        "Ctrl/Cmd-click a node to add it to the focus · "
                        "Alt-click to focus on it alone"
                    )

                # Inject CSS to remove gap between status bar columns, and pin
                # the bar to the bottom of the scroll port. The bar reports the
                # node you just clicked, so it has to stay in view while you
                # work the graph; with the display options open it otherwise
                # sits below the fold. A sticky element can only travel inside
                # its own parent, so every wrapper Streamlit puts between the
                # bar and the page column gets the rule — the one with room to
                # move is the one that ends up sticking, and which that is
                # differs between the two layouts below (the button row is
                # wrapped, the lone markdown block is not). Streamlit also
                # collapses that block to a text line's height, which would
                # leave the 36px bar hanging past the sticky edge, so pin it.
                st.markdown(
                    """<style>
            div[data-testid="stLayoutWrapper"]:has(#graph-status-bar),
            div[data-testid="stHorizontalBlock"]:has(#graph-status-bar),
            div[data-testid="stVerticalBlockBorderWrapper"]:has(#graph-status-bar),
            div[data-testid="stElementContainer"]:has(#graph-status-bar) {
                position: sticky !important; bottom: 0.75rem; z-index: 20;
            }
            div[data-testid="stElementContainer"]:has(#graph-status-bar) {
                height: 36px !important;
            }
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
            /* The copy button's iframe, laid over the end of the black strip
               it belongs to. Both live in the same container, which is the one
               thing it can be positioned against in either layout — beside the
               View button in a column, or alone in the page block. Out of the
               flow, so the row stays one bar tall and the bar does not move
               when a selection gives it a button. */
            .st-key-graph_status_cell { position: relative; }
            .st-key-graph_status_cell [data-testid="stElementContainer"]:has([data-testid="stIFrame"]) {
                position: absolute !important; top: 0; right: 4px;
                width: 36px !important; height: 36px !important;
                min-height: 0 !important; z-index: 21;
            }
            .st-key-graph_status_cell [data-testid="stIFrame"] {
                width: 36px !important; height: 36px !important;
                display: block; border: none;
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

                def _draw_status_bar(alone):
                    """The bar and the copy button that sits on it.

                    Rounded on both ends when it is the whole row, square on the
                    right when a button abuts it. The two go in a container of
                    their own so the button has one thing to be positioned
                    against, whichever layout this is — a column beside the View
                    button, or the page block with the row to itself.
                    """
                    radius = "4px" if alone else "4px 0 0 4px"
                    # The copy button is laid over the right end of the strip,
                    # so the line stops short of it rather than running under.
                    pad = "6px 44px 6px 12px" if _bar_title else "6px 12px"
                    tip = f' title="{html.escape(_bar_title, quote=True)}"'
                    cell = st.container(key="graph_status_cell")
                    cell.markdown(
                        f'<div id="graph-status-bar" style="background:#1e1e1e;color:#fff;padding:{pad};'
                        f"border-radius:{radius};font-size:14px;display:flex;align-items:center;gap:8px;"
                        f'height:36px;">'
                        f'<span{tip if _bar_title else ""} style="flex:1;overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap;">{sel_html}</span>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    # Inside the black strip, at its end. Its own iframe, laid
                    # over the bar by the CSS above — the bar itself is markdown
                    # and Streamlit strips the script a copy button needs.
                    if _bar_title:
                        with cell:
                            st.components.v1.html(
                                status_bar_copy_html(_bar_title), height=36
                            )

                if show_view:
                    col_info, col_btn = st.columns([7, 2])
                    with col_info:
                        _draw_status_bar(alone=False)
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
                    _draw_status_bar(alone=True)

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

"""The findings table both the Quality and the SHACL sections show.

One filterable table instead of an expander per rule: it sorts and filters,
and it is one widget however many findings there are, where a button per
finding was hundreds of widgets and the kind of render the desktop webview
falls over on. Selecting a row shows the finding in full, with the evidence
behind it and buttons to open the resources it is about.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Any

import streamlit as st

from ..quality import QualityFinding
from ..ui import _PAGE_BY_TYPE, _nav_open_entity, _uid

SEVERITY_ICONS = {"error": "🔴", "warning": "🟡", "info": "🔵"}
_SEVERITY_ORDER = ("error", "warning", "info")


def open_resource(uri: str, kind: str) -> None:
    """Callback: open a resource on its own page."""
    st.session_state.search_navigate_to = _PAGE_BY_TYPE[kind]
    _nav_open_entity(kind, _uid(uri), uri)


def _short_name(uri: str) -> str:
    for sep in ("#", "/", ":"):
        if sep in uri.rstrip(sep):
            return uri.rstrip(sep).rsplit(sep, 1)[-1]
    return uri


def table_key(key: str, shown: Sequence[QualityFinding]) -> str:
    """The table's widget key, which changes when the rows shown do.

    The selection is a row position. Kept across a change of rows, it would
    point at whatever finding moved into that position, and the details and
    Open button would quietly switch to it (Codex review of PR #507). A new
    key per set of rows starts that set unselected; the same rows keep it.
    """
    digest = hashlib.sha256(
        "\n".join(repr(f.key) for f in shown).encode("utf-8")
    ).hexdigest()[:12]
    return f"{key}_table_{digest}"


def render_findings_table(
    findings: Sequence[QualityFinding],
    *,
    key: str,
    group_of: Callable[[QualityFinding], str],
    group_label: str,
    name_of: Callable[[str], str] | None = None,
    kind_of: Callable[[str], str | None] | None = None,
) -> None:
    """Filters, the table, and the selected finding's details.

    ``group_of`` names the column findings are grouped by (the rule on the
    Quality section, the source shape on the SHACL one). ``name_of`` and
    ``kind_of`` resolve resources for display and for the Open buttons of
    related resources; without them URIs are shortened and only the
    finding's own resource can be opened.
    """
    name_of = name_of or _short_name
    if not findings:
        return

    severities = [s for s in _SEVERITY_ORDER if any(f.severity == s for f in findings)]
    groups = sorted({group_of(f) for f in findings})
    kinds = sorted({f.resource_kind or "Other" for f in findings})

    sev_col, group_col, kind_col, text_col = st.columns([2, 3, 2, 3])
    # Empty means all, as for the other filters: a default of "the severities
    # there are now" would stay put while a rerun brings a new one, and hide
    # it (Codex review of PR #507).
    chosen_sev = sev_col.multiselect(
        "Severity",
        severities,
        placeholder="All",
        format_func=lambda s: f"{SEVERITY_ICONS[s]} {s}",
        key=f"{key}_f_sev",
    )
    chosen_groups = group_col.multiselect(
        group_label, groups, placeholder="All", key=f"{key}_f_group"
    )
    chosen_kinds = kind_col.multiselect(
        "Kind", kinds, placeholder="All", key=f"{key}_f_kind"
    )
    query = (
        text_col.text_input(
            "Search", key=f"{key}_f_text", placeholder="Resource or message"
        )
        .strip()
        .lower()
    )

    shown = [
        f
        for f in findings
        if (not chosen_sev or f.severity in chosen_sev)
        and (not chosen_groups or group_of(f) in chosen_groups)
        and (not chosen_kinds or (f.resource_kind or "Other") in chosen_kinds)
        and (
            not query
            or query in f.message.lower()
            or query in f.resource.lower()
            or query in name_of(f.resource).lower()
        )
    ]
    st.caption(
        f"{len(shown)} of {len(findings)} finding{'s' if len(findings) != 1 else ''}"
        " · select a row for details"
    )
    rows: list[dict[str, Any]] = [
        {
            "Severity": f"{SEVERITY_ICONS[f.severity]} {f.severity}",
            group_label: group_of(f),
            "Resource": name_of(f.resource),
            "Kind": f.resource_kind or "",
            "Message": f.message,
        }
        for f in shown
    ]
    event = st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=table_key(key, shown),
        column_config={"Message": st.column_config.TextColumn(width="large")},
    )
    selected = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    if selected and selected[0] < len(shown):
        _render_details(shown[selected[0]], key=key, name_of=name_of, kind_of=kind_of)


def _render_details(
    finding: QualityFinding,
    *,
    key: str,
    name_of: Callable[[str], str],
    kind_of: Callable[[str], str | None] | None,
) -> None:
    with st.container(border=True):
        text_col, open_col = st.columns([6, 1])
        text_col.markdown(f"{SEVERITY_ICONS[finding.severity]} **{finding.message}**")
        if finding.resource_kind in _PAGE_BY_TYPE:
            open_col.button(
                "Open",
                key=f"{key}_open_{_uid(finding.resource)}",
                on_click=open_resource,
                args=(finding.resource, finding.resource_kind),
                help=f"Open on the {_PAGE_BY_TYPE[finding.resource_kind]} page",
            )
        if finding.suggestion:
            st.caption(finding.suggestion)
        st.code(finding.resource, language=None)
        if finding.source_shape:
            st.markdown(f"**Source shape:** {finding.source_shape}")
        if finding.related_resources:
            st.markdown("**Related**")
            for i, uri in enumerate(finding.related_resources):
                rel_kind = kind_of(uri) if kind_of else None
                name_col, rel_open = st.columns([6, 1])
                name_col.markdown(f"- {name_of(uri)}")
                if rel_kind in _PAGE_BY_TYPE:
                    rel_open.button(
                        "Open",
                        key=f"{key}_rel_{i}_{_uid(uri)}",
                        on_click=open_resource,
                        args=(uri, rel_kind),
                    )
        evidence = {
            k: v for k, v in finding.evidence.items() if v not in (None, "", [])
        }
        if evidence:
            with st.expander("Evidence", expanded=False):
                st.json(evidence)

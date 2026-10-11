"""The validation page."""

import uuid

import streamlit as st

from ..ontology_manager import rdf_format_for_path
from ..quality import (
    CATEGORIES,
    RULES,
    QualityConfig,
    QualityFinding,
    RuleSettings,
    analyze,
)
from ..quality.context import QualityContext
from ..shacl import (
    ShapesError,
    add_shapes,
    list_shapes,
    parse_shapes,
    remove_shape,
    run_shacl,
    shape_turtle,
    split_shapes,
)
from ..ui import (
    _PAGE_BY_TYPE,
    _download_or_save,
    _nav_open_entity,
    _uid,
    request_autosave_flush,
    save_checkpoint,
    set_flash_message,
    show_message,
)

_SEVERITY_ICONS = {"error": "🔴", "warning": "🟡", "info": "🔵"}

#: Findings listed per check before "and N more": one button per finding, and
#: a few hundred of them is the kind of render the desktop webview falls over on.
_FINDINGS_SHOWN = 50


def render_validation():
    """Render the validation and reasoning page."""
    st.header("Validation & Reasoning")

    ont = st.session_state.ontology

    _val_tab = st.segmented_control(
        "Section",
        ["Validation", "Quality", "SHACL", "Reasoning"],
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

    if _val_tab == "Quality":
        _render_quality(ont)

    if _val_tab == "SHACL":
        _render_shacl(ont)

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


def _open_finding(finding: QualityFinding) -> None:
    """Callback: open the resource a finding is about on its own page."""
    kind = finding.resource_kind
    if kind not in _PAGE_BY_TYPE:
        return
    st.session_state.search_navigate_to = _PAGE_BY_TYPE[kind]
    _nav_open_entity(kind, _uid(finding.resource), finding.resource)


def _quality_config(scope: str) -> QualityConfig:
    """The configuration the "Rules" expander describes, for this ontology.

    Kept under a key of its own, not only in the widgets: Streamlit drops a
    widget's state once the widget stops rendering, so leaving the Quality
    section used to reset every choice (Codex review of PR #504). The widgets
    start from the stored configuration and write back to it.
    """
    store_key = f"_quality_config_{scope}"
    stored: QualityConfig = st.session_state.get(store_key) or QualityConfig()
    with st.expander("Rules", expanded=False):
        include_imports = st.checkbox(
            "Include imported vocabularies",
            value=stored.include_imports,
            key=f"quality_imports_{scope}",
            help="By default only the ontology's own classes and properties are "
            "checked: those in its base namespace or rdfs:isDefinedBy it. Turn "
            "this on to check merged-in vocabularies too.",
        )
        overrides: dict[str, RuleSettings] = {}
        for category, title in CATEGORIES.items():
            st.markdown(f"**{title}**")
            for rule in RULES.values():
                if rule.category != category:
                    continue
                # Titles only: the stable ID is for config files and exports,
                # and a list showing Q001, Q006, Q019 reads as if rules were
                # missing. The tooltip still names it.
                enabled = st.checkbox(
                    rule.title,
                    value=stored.enabled(rule.id),
                    key=f"quality_rule_{scope}_{rule.id}",
                    help=f"{rule.description} (Rule ID {rule.id})",
                )
                if enabled != rule.default_enabled:
                    overrides[rule.id] = RuleSettings(enabled=enabled)
    config = QualityConfig(
        profile=stored.profile, include_imports=include_imports, rules=overrides
    )
    st.session_state[store_key] = config
    return config


def _render_quality(ont) -> None:
    """The quality rules: configure them, run them, read the findings."""
    st.subheader("Model Quality")
    st.caption(
        "Modelling advice, not errors: each finding is worth a look, and some "
        "will be deliberate. Formal problems are under Validation."
    )

    # Keyed by ontology, so switching ontologies keeps each one's choices.
    scope = _uid(str(ont.ontology_uri))
    config = _quality_config(scope)

    run_key = f"_quality_run_{scope}"
    if st.button("Run Quality Checks"):
        st.session_state[run_key] = analyze(ont, config)

    run = st.session_state.get(run_key)
    if run is None:
        return

    # Runs are explicit: an edit or a changed rule leaves the last results up,
    # marked, rather than re-running on every rerender.
    if run.graph_fingerprint != ont.revision_token():
        st.warning("The ontology changed since this run. Run the checks again.")
    elif run.config_fingerprint != config.fingerprint:
        st.warning("The rule selection changed since this run. Run the checks again.")

    counts = run.counts()
    ran = sum(status.state == "ran" for status in run.rules)
    skipped = [status for status in run.rules if status.state == "skipped"]
    failed = [status for status in run.rules if status.state == "failed"]
    st.write(
        " · ".join(
            [
                *(
                    f"{_SEVERITY_ICONS[sev]} {counts[sev]} {sev}"
                    f"{'s' if counts[sev] != 1 else ''}"
                    for sev in counts
                    if counts[sev]
                ),
                f"{ran} rule{'s' if ran != 1 else ''} ran",
            ]
        )
    )
    st.caption(f"Run {run.started_at} · graph {run.graph_fingerprint}")
    for status in failed:
        st.error(f"{RULES[status.rule_id].title} failed: {status.reason}")
    if skipped:
        st.caption(
            "Skipped: "
            + "; ".join(f"{RULES[s.rule_id].title} ({s.reason})" for s in skipped)
        )
    if not run.findings and not failed:
        st.success("No findings from the enabled rules.")

    for rule_id, rule in RULES.items():
        findings = run.by_rule(rule_id)
        if not findings:
            continue
        # A constant label: one that changed with the count would close the
        # expander whenever a fix made the count move.
        with st.expander(
            f"{_SEVERITY_ICONS[findings[0].severity]} {rule.title}",
            expanded=False,
        ):
            st.caption(f"{len(findings)} finding(s). {rule.description}")
            for i, finding in enumerate(findings[:_FINDINGS_SHOWN]):
                text_col, open_col = st.columns([6, 1])
                text_col.markdown(f"- {finding.message}")
                if finding.suggestion:
                    text_col.caption(finding.suggestion)
                if finding.resource_kind in _PAGE_BY_TYPE:
                    open_col.button(
                        "Open",
                        key=f"quality_open_{rule_id}_{i}_{_uid(finding.resource)}",
                        on_click=_open_finding,
                        args=(finding,),
                        help=finding.resource,
                    )
            if len(findings) > _FINDINGS_SHOWN:
                st.caption(f"…and {len(findings) - _FINDINGS_SHOWN} more.")

    with st.expander("Rule coverage", expanded=False):
        st.dataframe(
            [
                {
                    "Rule": RULES[status.rule_id].title,
                    "Status": status.state,
                    "Checked": status.checked,
                    "Affected": status.affected,
                    "ms": round(status.duration_ms, 1),
                    "Note": status.reason or "",
                    "ID": status.rule_id,
                }
                for status in run.rules
            ],
            hide_index=True,
            width="stretch",
        )


# -- SHACL ---------------------------------------------------------------------

#: The two places shapes come from, in the order they are checked and shown.
_SHAPE_SOURCES = {
    "shacl:ontology": "Shapes in this ontology",
    "shacl:user": "One-off shapes (not saved)",
}


def _remove_shape_cb(node, name: str) -> None:
    """Callback: remove one shape from the ontology, as one undo step."""
    ont = st.session_state.ontology
    try:
        removed = remove_shape(ont.graph, node)
    except ShapesError as exc:
        set_flash_message(f"Cannot remove {name}: {exc}", "error")
        return
    if removed:
        save_checkpoint(f"Remove SHACL shape {name}")
        request_autosave_flush()
        set_flash_message(f"Removed SHACL shape {name}.", "success")
    else:
        set_flash_message(f"Nothing to remove for {name}.", "info")


def _render_finding(finding: QualityFinding, key: str) -> None:
    """One finding: message, suggestion, and Open where a page can show it."""
    text_col, open_col = st.columns([6, 1])
    text_col.markdown(f"- {finding.message}")
    if finding.suggestion:
        text_col.caption(finding.suggestion)
    if finding.resource_kind in _PAGE_BY_TYPE:
        open_col.button(
            "Open",
            key=key,
            on_click=_open_finding,
            args=(finding,),
            help=finding.resource,
        )


def _render_shacl(ont) -> None:
    """Shapes in the ontology, shapes to add, and closed-world checks."""
    st.subheader("SHACL")
    st.caption(
        "Closed-world checks of the data against shapes: here a missing value "
        "is a violation, not just unknown. Shapes you add are stored in the "
        "ontology file. The shapes themselves are never checked as data."
    )
    scope = _uid(str(ont.ontology_uri))
    pending_key = f"_shacl_pending_{scope}"
    once_key = f"_shacl_once_{scope}"
    run_key = f"_shacl_run_{scope}"

    shapes = list_shapes(ont.graph)
    st.write(f"{len(shapes)} shape{'s' if len(shapes) != 1 else ''} in this ontology.")
    # Constant labels: a count in the label would close the expander whenever
    # adding or removing a shape changed it.
    with st.expander("Shapes in this ontology", expanded=False):
        if not shapes:
            st.caption(
                "None yet. Add shapes below, or import an ontology that carries them."
            )
        for info in shapes:
            name_col, show_col, remove_col = st.columns([5, 1, 1])
            targets = ", ".join(info.targets) or "no target"
            name_col.markdown(
                f"**{info.name}** · {info.kind} · {targets} · "
                f"{info.constraints} constraint{'s' if info.constraints != 1 else ''}"
            )
            with show_col.popover("Show"):
                st.code(shape_turtle(ont.graph, info.node), language="turtle")
            remove_col.button(
                "Remove",
                key=f"shacl_remove_{_uid(str(info.node))}",
                on_click=_remove_shape_cb,
                args=(info.node, info.name),
            )

    with st.expander("Add shapes", expanded=False):
        method = st.radio(
            "Source",
            ["Paste Turtle", "Upload file"],
            horizontal=True,
            key=f"shacl_add_method_{scope}",
        )
        text, fmt = None, "turtle"
        if method == "Paste Turtle":
            text = st.text_area(
                "Shapes (Turtle)",
                height=200,
                key=f"shacl_add_text_{scope}",
                placeholder="@prefix sh: <http://www.w3.org/ns/shacl#> .\n...",
            )
        else:
            upload = st.file_uploader(
                "Shapes file",
                type=["ttl", "rdf", "owl", "xml", "jsonld", "json", "nt", "n3"],
                key=f"shacl_add_file_{scope}",
            )
            if upload is not None:
                text = upload.getvalue().decode("utf-8", errors="replace")
                fmt = rdf_format_for_path(upload.name)
        # Not disabled while empty: a pasted value only reaches the script when
        # the text area loses focus, so a disabled button would stay grey under
        # freshly pasted shapes until the reader clicked somewhere else first.
        if st.button("Check shapes"):
            st.session_state.pop(pending_key, None)
            if not (text or "").strip():
                st.warning("Paste or upload shapes first.")
            else:
                try:
                    st.session_state[pending_key] = parse_shapes(text or "", format=fmt)
                except ShapesError as exc:
                    message, _, detail = str(exc).partition("\n")
                    st.error(message)
                    if detail.strip():
                        st.code(detail.strip(), language=None)
        pending = st.session_state.get(pending_key)
        if pending is not None:
            found = list_shapes(pending)
            st.success(
                f"Valid SHACL: {len(found)} shape{'s' if len(found) != 1 else ''}, "
                f"{len(pending)} triples."
            )
            for info in found:
                st.markdown(
                    f"- **{info.name}** · {', '.join(info.targets) or 'no target'}"
                )
            add_col, once_col, drop_col = st.columns(3)
            if add_col.button("Add to ontology", type="primary"):
                added = add_shapes(ont.graph, pending)
                save_checkpoint("Add SHACL shapes")
                request_autosave_flush()
                st.session_state.pop(pending_key, None)
                set_flash_message(f"Added {added} triples of SHACL shapes.", "success")
                st.rerun()
            if once_col.button("Use for one check"):
                # With an identity of its own, so a check run against earlier
                # one-off shapes shows as stale once these replace them.
                st.session_state[once_key] = (uuid.uuid4().hex, pending)
                st.session_state.pop(pending_key, None)
                st.rerun()
            if drop_col.button("Discard"):
                st.session_state.pop(pending_key, None)
                st.rerun()

    once_id, once = st.session_state.get(once_key) or (None, None)
    sources = []
    if shapes:
        sources.append("shacl:ontology")
    if once is not None:
        sources.append("shacl:user")
        note_col, drop_col = st.columns([5, 1])
        note_col.caption(
            f"One-off shapes ready: {len(list_shapes(once))} shape(s), not saved "
            "in the ontology."
        )
        if drop_col.button("Forget"):
            st.session_state.pop(once_key, None)
            st.rerun()

    if st.button("Run SHACL check", disabled=not sources):
        data, embedded = split_shapes(ont.graph)
        ctx = QualityContext(ont, include_imports=True)
        shape_graphs = {"shacl:ontology": embedded}
        if once is not None:
            shape_graphs["shacl:user"] = once
        runs = {
            origin: run_shacl(
                data,
                shape_graphs[origin],
                origin=origin,
                kind=ctx.kind,
                name=ctx.name,
            )
            for origin in sources
        }
        st.session_state[run_key] = (ont.revision_token(), once_id, runs)
    if not sources:
        st.caption("Add shapes to check the data against.")

    stored = st.session_state.get(run_key)
    if stored is None:
        return
    token, ran_once_id, runs = stored
    if token != ont.revision_token():
        st.warning("The ontology changed since this check. Run it again.")
    elif ran_once_id != once_id:
        st.warning("The one-off shapes changed since this check. Run it again.")
    for origin, run in runs.items():
        st.markdown(f"**{_SHAPE_SOURCES[origin]}**")
        if run.error:
            st.error(run.error)
            continue
        # A run can conform and still carry warnings and info results: only
        # violations decide conformance, so those are listed either way.
        if run.conforms and not run.findings:
            st.success(
                f"Conforms: the data meets all {run.shapes_checked} shape(s) "
                f"({run.duration_ms:.0f} ms)."
            )
        elif run.conforms:
            st.success("Conforms: no violations, but see the notes below.")
        counts: dict[str, int] = {}
        for finding in run.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        if counts:
            st.write(
                " · ".join(
                    f"{_SEVERITY_ICONS[sev]} {counts[sev]} "
                    f"{sev}{'s' if counts[sev] != 1 else ''}"
                    for sev in ("error", "warning", "info")
                    if counts.get(sev)
                )
                + f" · {run.duration_ms:.0f} ms"
            )
        by_shape: dict[str, list[QualityFinding]] = {}
        for finding in run.findings:
            by_shape.setdefault(finding.source_shape or "(unnamed shape)", []).append(
                finding
            )
        for shape, findings in by_shape.items():
            with st.expander(
                f"{_SEVERITY_ICONS[findings[0].severity]} {shape}", expanded=False
            ):
                st.caption(f"{len(findings)} finding(s).")
                for i, finding in enumerate(findings[:_FINDINGS_SHOWN]):
                    _render_finding(
                        finding,
                        f"shacl_open_{origin}_{_uid(shape)}_{i}_{_uid(finding.resource)}",
                    )
                if len(findings) > _FINDINGS_SHOWN:
                    st.caption(f"…and {len(findings) - _FINDINGS_SHOWN} more.")
        if run.report_ttl is not None:
            _download_or_save(
                "Download validation report (.ttl)",
                run.report_ttl,
                "shacl-report.ttl",
                key=f"shacl_report_{origin}",
            )

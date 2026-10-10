"""The validation page."""

import streamlit as st

from ..quality import (
    CATEGORIES,
    RULES,
    QualityConfig,
    QualityFinding,
    RuleSettings,
    analyze,
)
from ..ui import (
    _PAGE_BY_TYPE,
    _nav_open_entity,
    _uid,
    request_autosave_flush,
    save_checkpoint,
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
        ["Validation", "Quality", "Reasoning"],
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

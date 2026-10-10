"""The validation page."""

import streamlit as st

from ..quality import QUALITY_CHECKS
from ..ui import (
    _PAGE_BY_TYPE,
    _nav_open_entity,
    _uid,
    request_autosave_flush,
    save_checkpoint,
    show_message,
)

_SEVERITY_ICONS = {"error": "🔴", "warning": "🟡", "info": "🔵"}
_CATEGORY_TITLES = {"structure": "Structure", "naming": "Naming"}

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


def _open_finding(issue: dict[str, str]) -> None:
    """Callback: open the entity a finding is about on its own page."""
    kind = issue["subject_kind"]
    st.session_state.search_navigate_to = _PAGE_BY_TYPE[kind]
    _nav_open_entity(kind, _uid(issue["subject_uri"]), issue["subject_uri"])


def _render_quality(ont) -> None:
    """The model quality checks: pick checks, run them, read the score."""
    st.subheader("Model Quality")
    st.caption(
        "Modelling heuristics, not errors: each finding is worth a look, and "
        "some will be deliberate. The score is the share of classes and "
        "properties each check found nothing wrong with, weighted by severity."
    )

    # Keyed by ontology, so switching ontologies keeps each one's choices.
    scope = _uid(str(ont.ontology_uri))
    with st.expander("Checks", expanded=False):
        include_external = st.checkbox(
            "Include entities from other namespaces",
            value=False,
            key=f"quality_external_{scope}",
            help="By default only the ontology's own classes and properties are "
            "checked: those in its base namespace or rdfs:isDefinedBy it. Turn "
            "this on to check merged-in vocabularies too.",
        )
        enabled = []
        for category, title in _CATEGORY_TITLES.items():
            st.markdown(f"**{title}**")
            for check in QUALITY_CHECKS:
                if check.category != category:
                    continue
                if st.checkbox(
                    check.title,
                    value=check.default_on,
                    key=f"quality_check_{scope}_{check.key}",
                    help=check.description,
                ):
                    enabled.append(check.key)

    if st.button("Run Quality Checks"):
        st.session_state["_quality_ran"] = True

    if not st.session_state.get("_quality_ran"):
        return

    # Recomputed per graph revision (OntologyManager memoizes it), so an entity
    # fixed through one of the links below drops off the list on return.
    report = ont.assess_quality(enabled=enabled, include_external=include_external)

    if report.score is None:
        st.metric("Quality score", "Score not available")
        st.caption("No enabled check had any classes or properties to look at.")
        return
    band = (
        "Good" if report.score >= 90 else "Fair" if report.score >= 70 else "Needs work"
    )
    st.metric("Quality score", f"{report.score} / 100")
    st.caption(band)

    counts: dict[str, int] = {}
    for issue in report.issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    if not counts:
        st.success("No findings from the enabled checks.")
    else:
        st.write(
            " · ".join(
                f"{_SEVERITY_ICONS[sev]} {counts[sev]} "
                f"{sev}{'s' if counts[sev] != 1 else ''}"
                for sev in ("warning", "info")
                if counts.get(sev)
            )
        )

    for check in QUALITY_CHECKS:
        findings = report.findings.get(check.key)
        if not findings:
            continue
        # A constant label: one that changed with the count would close the
        # expander whenever a fix made the count move.
        with st.expander(
            f"{_SEVERITY_ICONS[check.severity]} {check.title}", expanded=False
        ):
            st.caption(f"{len(findings)} finding(s). {check.description}")
            for i, issue in enumerate(findings[:_FINDINGS_SHOWN]):
                text_col, open_col = st.columns([6, 1])
                text_col.markdown(f"- {issue['message']}")
                open_col.button(
                    "Open",
                    key=f"quality_open_{check.key}_{i}_{_uid(issue['subject_uri'])}",
                    on_click=_open_finding,
                    args=(issue,),
                    help=f"Open '{issue['subject']}'",
                )
            if len(findings) > _FINDINGS_SHOWN:
                st.caption(f"…and {len(findings) - _FINDINGS_SHOWN} more.")

    with st.expander("Score breakdown", expanded=False):
        st.dataframe(
            [
                {
                    "Check": check.title,
                    "Affected": result.affected,
                    "Out of": result.population,
                    "Score": None
                    if result.score is None
                    else round(100 * result.score),
                }
                for check in QUALITY_CHECKS
                if (result := report.per_check.get(check.key))
            ],
            hide_index=True,
            width="stretch",
        )

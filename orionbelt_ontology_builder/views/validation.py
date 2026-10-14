"""The validation page."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import streamlit as st

from ..ontology_manager import rdf_format_for_path
from ..quality import (
    CATEGORIES,
    PROFILES,
    RULES,
    SEVERITIES,
    QualityConfig,
    QualityConfigError,
    RuleSettings,
    Suppression,
    analyze,
    partition,
)
from ..quality.context import QualityContext
from ..quality.exports import findings_csv, findings_json
from ..shacl import (
    BUNDLED_SHAPES,
    ShapesError,
    add_shapes,
    bundled_in,
    list_shapes,
    load_bundled,
    parse_shapes,
    remove_shape,
    run_shacl,
    shape_turtle,
    split_shapes,
)
from ..shacl_generate import generate_shapes
from ..ui import (
    QUALITY_CONFIGS_GENERATION,
    QUALITY_CONFIGS_STATE,
    _download_or_save,
    _uid,
    persist_quality_configs,
    request_autosave_flush,
    restore_quality_configs,
    save_checkpoint,
    set_flash_message,
    show_message,
)
from .findings import SEVERITY_ICONS as _SEVERITY_ICONS
from .findings import render_findings_table


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
            # A pass over a large ontology takes seconds, and the closure
            # repeats until nothing new appears: say which pass is running.
            limit = ont.REASONING_MAX_PASSES
            bar = st.progress(0.0, text="Applying reasoning…")

            def report(pass_number: int, added: int) -> None:
                bar.progress(
                    (pass_number - 1) / limit,
                    text=f"Pass {pass_number}: {added} triples inferred so far…",
                )

            try:
                new_triples = ont.apply_reasoning(profile=profile[1], progress=report)
                save_checkpoint("Apply reasoning")
                request_autosave_flush()
                show_message(
                    f"Reasoning complete! {new_triples} new triples inferred.",
                    "success",
                )
                st.write(f"New triple count: {len(ont.graph)}")
            except Exception as e:  # noqa: BLE001 - reasoner failure must show as a message, not a traceback
                show_message(f"Error during reasoning: {e!s}", "error")
            finally:
                bar.empty()


_PROFILE_LABELS = {
    "general_ontology": "General ontology",
    "skos_vocabulary": "SKOS vocabulary",
    "strict_documentation": "Strict documentation",
}


def _stored_config(iri: str) -> QualityConfig:
    raw = (st.session_state.get(QUALITY_CONFIGS_STATE) or {}).get(iri)
    if not raw:
        return QualityConfig()
    try:
        return QualityConfig.from_dict(raw)
    except QualityConfigError:
        return QualityConfig()


def _store_config(iri: str, config: QualityConfig) -> None:
    """Keep ``config`` for this ontology, and mark it for saving if it changed."""
    configs = dict(st.session_state.get(QUALITY_CONFIGS_STATE) or {})
    if configs.get(iri) != config.to_dict():
        configs[iri] = config.to_dict()
        st.session_state[QUALITY_CONFIGS_STATE] = configs
        st.session_state["_quality_configs_dirty"] = True


def _redraw_rule_widgets() -> None:
    """Have the rule widgets drawn afresh from the stored settings."""
    st.session_state[QUALITY_CONFIGS_GENERATION] = (
        st.session_state.get(QUALITY_CONFIGS_GENERATION, 0) + 1
    )


def _profile_changed_cb(iri: str, key: str) -> None:
    """Callback: a new profile starts from its own defaults. Suppressions
    stay: they are about findings, not about which rules run."""
    _store_config(
        iri,
        QualityConfig(
            profile=st.session_state[key],
            suppressions=_stored_config(iri).suppressions,
        ),
    )
    _redraw_rule_widgets()


def _reset_cb(iri: str, profile: str) -> None:
    """Callback: drop every per-rule change, keep the profile (and the
    suppressions)."""
    _store_config(
        iri,
        QualityConfig(profile=profile, suppressions=_stored_config(iri).suppressions),
    )
    _redraw_rule_widgets()


def _suppress_cb(
    iri: str, rule_id: str, resource: str, why_key: str, by_key: str
) -> None:
    """Callback: mark a finding as fine, with the reason given."""
    suppression = Suppression(
        rule_id,
        resource,
        st.session_state.get(why_key, "").strip(),
        st.session_state.get(by_key, "").strip(),
        datetime.now(UTC).date().isoformat(),
    )
    _store_config(iri, _stored_config(iri).with_suppression(suppression))


def _lift_cb(iri: str, rule_id: str, resource: str) -> None:
    """Callback: show a suppressed finding again."""
    _store_config(iri, _stored_config(iri).without_suppression(rule_id, resource))


def _quality_config(ont) -> QualityConfig:
    """The settings the "Rules" expander shows, for this ontology.

    Kept per ontology IRI under a key of its own (saved to the browser, or to
    the config file on desktop), not in the widgets: Streamlit drops a
    widget's state once it stops rendering (Codex review of PR #504). The
    widgets start from the stored settings and write back to them; their keys
    carry a generation, bumped when stored settings replace what they show.
    """
    iri = str(ont.ontology_uri)
    stored = _stored_config(iri)
    scope = f"{_uid(iri)}_{st.session_state.get(QUALITY_CONFIGS_GENERATION, 0)}"
    with st.expander("Rules", expanded=False):
        profile_key = f"quality_profile_{scope}"
        profile = st.selectbox(
            "Profile",
            list(PROFILES),
            index=list(PROFILES).index(stored.profile),
            format_func=lambda p: _PROFILE_LABELS.get(p, p),
            key=profile_key,
            on_change=_profile_changed_cb,
            args=(iri, profile_key),
            help="A starting set of rules and severities. Changing it resets the "
            "rules below to that profile's defaults.",
        )
        include_imports = st.checkbox(
            "Include imported vocabularies",
            value=stored.include_imports,
            key=f"quality_imports_{scope}",
            help="By default only the ontology's own classes and properties are "
            "checked: those in its base namespace or rdfs:isDefinedBy it. Turn "
            "this on to check merged-in vocabularies too.",
        )
        baseline = QualityConfig(profile=profile)
        overrides: dict[str, RuleSettings] = {}
        for category, title in CATEGORIES.items():
            st.markdown(f"**{title}**")
            for rule in RULES.values():
                if rule.category != category:
                    continue
                on_col, sev_col = st.columns([4, 1])
                # Titles only: the stable ID is for config files and exports,
                # and a list showing Q001, Q006, Q019 reads as if rules were
                # missing. The tooltip still names it.
                enabled = on_col.checkbox(
                    rule.title,
                    value=stored.enabled(rule.id),
                    key=f"quality_rule_{scope}_{rule.id}",
                    help=f"{rule.description} (Rule ID {rule.id})",
                )
                severity = sev_col.selectbox(
                    f"Severity of {rule.title}",
                    list(SEVERITIES),
                    index=SEVERITIES.index(stored.severity(rule.id)),
                    format_func=lambda s: f"{_SEVERITY_ICONS[s]} {s}",
                    key=f"quality_sev_{scope}_{rule.id}",
                    label_visibility="collapsed",
                    disabled=not enabled,
                )
                setting = RuleSettings(
                    enabled=enabled if enabled != baseline.enabled(rule.id) else None,
                    severity=severity
                    if severity != baseline.severity(rule.id)
                    else None,
                )
                if setting != RuleSettings():
                    overrides[rule.id] = setting
        config = QualityConfig(
            profile=profile,
            include_imports=include_imports,
            rules=overrides,
            suppressions=stored.suppressions,
        )
        st.button(
            "Reset to profile defaults",
            key=f"quality_reset_{scope}",
            on_click=_reset_cb,
            args=(iri, profile),
            disabled=not overrides and not include_imports,
        )
        st.markdown("**Settings file**")
        _download_or_save(
            "Download settings (.json)",
            config.to_json(),
            "quality-settings.json",
            mime="application/json",
            key=f"quality_cfg_{scope}",
        )
        upload = st.file_uploader(
            "Apply a settings file",
            type=["json"],
            key=f"quality_cfg_upload_{scope}",
        )
        if upload is not None and st.button(
            "Apply settings", key=f"quality_cfg_apply_{scope}"
        ):
            try:
                imported = QualityConfig.from_json(
                    upload.getvalue().decode("utf-8", errors="replace")
                )
            except QualityConfigError as exc:
                st.error(f"Not applied: {exc}")
            else:
                _store_config(iri, imported)
                _redraw_rule_widgets()
                set_flash_message("Quality settings applied.", "success")
                st.rerun()
    # Only a real change is stored and marked for saving. Drawing the
    # defaults is not one: on the web the saved settings can arrive a few
    # reruns later, and writing the defaults first would overwrite them and
    # end the restore (Codex review of PR #507).
    if config.to_dict() != stored.to_dict():
        _store_config(iri, config)
    return config


def _render_quality(ont) -> None:
    """The quality rules: configure them, run them, read the findings."""
    st.subheader("Model Quality")
    st.caption(
        "Modelling advice, not errors: each finding is worth a look, and some "
        "will be deliberate. Formal problems are under Validation."
    )
    restore_quality_configs()
    config = _quality_config(ont)
    persist_quality_configs()

    # Keyed by ontology, so switching ontologies keeps each one's results.
    scope = _uid(str(ont.ontology_uri))
    run_key = f"_quality_run_{scope}"
    if st.button("Run Quality Checks"):
        # A large ontology takes seconds; without this the button looked like
        # it did nothing.
        bar = st.progress(0.0, text="Running the quality checks…")

        def report(done: int, total: int, rule_id: str) -> None:
            bar.progress(
                done / total,
                text=f"Rule {done + 1} of {total}: {RULES[rule_id].title}…",
            )

        st.session_state[run_key] = analyze(ont, config, progress=report)
        bar.empty()

    run = st.session_state.get(run_key)
    if run is None:
        return
    # Suppressions apply to the stored run as they are now, so marking a
    # finding as fine (or taking that back) shows without a new run.
    shown, suppressed = partition(run.all_findings(), config)
    run = replace(run, findings=shown, suppressed=suppressed)
    iri = str(ont.ontology_uri)

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
                *([f"{len(suppressed)} suppressed"] if suppressed else []),
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

    def suppress_controls(finding) -> None:
        if finding.rule_id not in RULES:
            return
        tag = f"quality_{scope}_{finding.rule_id}_{_uid(finding.resource)}"
        why_col, by_col, button_col = st.columns([5, 2, 1.4])
        why = why_col.text_input(
            "Why is this fine?",
            key=f"{tag}_why",
            placeholder="A deliberate modelling choice, because …",
        )
        by_col.text_input("By (optional)", key=f"{tag}_by")
        button_col.button(
            "Suppress",
            key=f"{tag}_suppress",
            disabled=not why.strip(),
            on_click=_suppress_cb,
            args=(iri, finding.rule_id, finding.resource, f"{tag}_why", f"{tag}_by"),
            help="Hide this finding from now on, for this rule and resource. "
            "Kept with the quality settings, and listed in exports.",
        )

    ctx = QualityContext(ont, include_imports=True)
    render_findings_table(
        run.findings,
        key=f"quality_{scope}",
        group_of=lambda f: RULES[f.rule_id].title if f.rule_id in RULES else f.rule_id,
        group_label="Rule",
        name_of=ctx.name,
        kind_of=ctx.kind,
        actions=suppress_controls,
    )
    if suppressed:
        _render_suppressed(suppressed, iri=iri, scope=scope, name_of=ctx.name)

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
    if run.findings or suppressed:
        with st.expander("Export findings", expanded=False):
            _download_or_save(
                "Download findings (.json)",
                findings_json(run.findings, run=run, suppressed=suppressed),
                "quality-findings.json",
                mime="application/json",
                key=f"quality_export_json_{scope}",
            )
            _download_or_save(
                "Download findings (.csv)",
                findings_csv(run.findings, suppressed),
                "quality-findings.csv",
                mime="text/csv",
                key=f"quality_export_csv_{scope}",
            )


def _render_suppressed(suppressed, *, iri: str, scope: str, name_of) -> None:
    """The findings marked as fine, why, and a way to show one again."""
    with st.expander(f"Suppressed findings ({len(suppressed)})", expanded=False):
        st.dataframe(
            [
                {
                    "Rule": RULES[f.rule_id].title,
                    "Resource": name_of(f.resource),
                    "Why": s.justification,
                    "By": s.author,
                    "Date": s.date,
                }
                for f, s in suppressed
            ],
            hide_index=True,
            width="stretch",
        )
        pick_col, lift_col = st.columns([5, 1])
        index = pick_col.selectbox(
            "Show again",
            list(range(len(suppressed))),
            format_func=lambda i: (
                f"{RULES[suppressed[i][0].rule_id].title}: "
                f"{name_of(suppressed[i][0].resource)}"
            ),
            key=f"quality_{scope}_lift_pick",
        )
        if index is not None and index < len(suppressed):
            finding = suppressed[index][0]
            lift_col.button(
                "Show again",
                key=f"quality_{scope}_lift",
                on_click=_lift_cb,
                args=(iri, finding.rule_id, finding.resource),
            )


# -- SHACL ---------------------------------------------------------------------


#: The two places shapes come from, in the order they are checked and shown.
def _checking_against(source: str) -> str:
    """A shapes source as the progress text names it."""
    if source == "ontology":
        return "the shapes in this ontology"
    if source == "once":
        return "the one-off shapes"
    if source == "generated":
        return "the shapes generated from the model"
    return f"{BUNDLED_SHAPES[source.removeprefix('bundled:')].title} (built-in)"


def _source_title(source: str) -> str:
    """How a shapes source is named above its results."""
    if source == "ontology":
        return "Shapes in this ontology"
    if source == "once":
        return "One-off shapes (not saved)"
    if source == "generated":
        return "Generated from the model"
    return f"{BUNDLED_SHAPES[source.removeprefix('bundled:')].title} (built-in)"


def _adopt_bundled_cb(key: str) -> None:
    """Callback: copy a built-in shapes set into the ontology, one undo step."""
    ont = st.session_state.ontology
    added = (
        0 if bundled_in(ont.graph, key) else add_shapes(ont.graph, load_bundled(key))
    )
    if added:
        save_checkpoint(f"Add {BUNDLED_SHAPES[key].title} shapes")
        request_autosave_flush()
    title = BUNDLED_SHAPES[key].title
    set_flash_message(
        f"Copied {title} into the ontology ({added} triples)."
        if added
        else f"{title} is already in the ontology.",
        "success" if added else "info",
    )


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

    with st.expander("Built-in shapes", expanded=False):
        st.caption(
            "Shapes that ship with the app. Tick one below to check against it, "
            "or copy it into the ontology to edit it or export it with the file."
        )
        for bundled in BUNDLED_SHAPES.values():
            text_col, show_col, copy_col = st.columns([5, 1, 1])
            text_col.markdown(
                f"**{bundled.title}** · {bundled.description}  \n"
                f"<span style='opacity:.6'>Source: {bundled.source}</span>",
                unsafe_allow_html=True,
            )
            with show_col.popover("Show"):
                st.code(
                    load_bundled(bundled.key).serialize(format="turtle"),
                    language="turtle",
                )
            copy_col.button(
                "Copy in",
                key=f"shacl_adopt_{bundled.key}",
                on_click=_adopt_bundled_cb,
                args=(bundled.key,),
                help="Add these shapes to the ontology (one undo step).",
            )

    with st.expander("Shapes generated from the model", expanded=False):
        st.markdown(
            "Checks individuals against what the model already says, read "
            "closed-world: cardinality restrictions become minimum and maximum "
            "counts, `someValuesFrom` a required value of that class, "
            "`allValuesFrom` the class every value must have, `hasValue` a "
            "required value, a functional property at most one value, and a "
            "property range the class or datatype of its values. Derived afresh "
            "on every check, so there is nothing to keep in sync, and never "
            "stored. Each finding names the axiom it comes from."
        )
        if st.toggle("Show the generated shapes", key=f"shacl_show_generated_{scope}"):
            generated_ttl = generate_shapes(split_shapes(ont.graph)[0]).serialize(
                format="turtle"
            )
            st.code(generated_ttl, language="turtle")
            _download_or_save(
                "Download generated shapes (.ttl)",
                generated_ttl,
                "generated-shapes.ttl",
                key=f"shacl_generated_dl_{scope}",
            )

    once_id, once = st.session_state.get(once_key) or (None, None)
    sources = []
    if shapes:
        sources.append("ontology")
    if once is not None:
        sources.append("once")
        note_col, drop_col = st.columns([5, 1])
        note_col.caption(
            f"One-off shapes ready: {len(list_shapes(once))} shape(s), not saved "
            "in the ontology."
        )
        if drop_col.button("Forget"):
            st.session_state.pop(once_key, None)
            st.rerun()

    # A checkbox per built-in set rather than one multiselect of every
    # source: a multiselect's default would not follow one-off shapes that
    # appear later. The ontology's own and one-off shapes are always checked.
    st.markdown("**Also check against**")
    infer = True
    if st.checkbox(
        "Generated from the model",
        value=False,
        key=f"shacl_use_generated_{scope}",
        help="Check individuals against the ontology's own restrictions, "
        "functional properties and ranges, read closed-world (issue #498).",
    ):
        sources.append("generated")
        # For the generated check only: those shapes are the model's axioms
        # read closed-world, and inference is what makes them mean what the
        # model does. Shapes written to be checked as stated (the ontology's
        # own, uploaded, built-in) stay so; inference adds triples a closed
        # shape or a labelling policy would object to (Codex review of #509).
        _, indent = st.columns([1, 24])
        infer = indent.checkbox(
            "Apply OWL RL inference first",
            value=True,
            key=f"shacl_infer_{scope}",
            help="Check what the ontology implies, not only what it states: a "
            "value a hasValue restriction entails, or a type a subclass axiom "
            "entails, no longer reads as missing. Reasoning runs on a copy for "
            "the check only; the ontology is not changed (Reasoning's Apply "
            "Reasoning is what writes inferences in). Range checks say nothing "
            "while this is on, since inference types every value as its "
            "range's class.",
        )
    for bundled in BUNDLED_SHAPES.values():
        if st.checkbox(
            bundled.title,
            value=False,
            key=f"shacl_use_{bundled.key}_{scope}",
            help=bundled.description,
        ):
            sources.append(f"bundled:{bundled.key}")

    if st.button("Run SHACL check", disabled=not sources):
        # Each source is a check of its own, and with inference one can take
        # seconds: say which one is running rather than leave the page still.
        bar = st.progress(0.0, text="Preparing the SHACL check…")
        data, embedded = split_shapes(ont.graph)
        ctx = QualityContext(ont, include_imports=True)

        def shapes_for(source: str):
            if source == "ontology":
                return embedded, "shacl:ontology"
            if source == "once":
                return once, "shacl:user"
            if source == "generated":
                return generate_shapes(data), "shacl:generated"
            return load_bundled(source.removeprefix("bundled:")), "shacl:bundled"

        runs = {}
        for done, source in enumerate(sources):
            step = f" ({done + 1} of {len(sources)})" if len(sources) > 1 else ""
            if source == "generated":
                bar.progress(
                    done / len(sources),
                    text=f"Generating shapes from the model{step}…",
                )
            graph, origin = shapes_for(source)
            doing = f"Checking against {_checking_against(source)}"
            if source == "generated" and infer:
                doing += ", with OWL RL inference first"
            bar.progress(done / len(sources), text=f"{doing}{step}…")
            runs[source] = run_shacl(
                data,
                graph,
                origin=origin,
                kind=ctx.kind,
                name=ctx.name,
                infer=infer and source == "generated",
            )
        st.session_state[run_key] = (
            ont.revision_token(),
            once_id,
            tuple(sources),
            infer and "generated" in sources,
            runs,
        )
        bar.empty()
    if not sources:
        st.caption("Add shapes, or tick a built-in set, to check the data against.")

    stored = st.session_state.get(run_key)
    if stored is None:
        return
    token, ran_once_id, ran_sources, ran_infer, runs = stored
    if token != ont.revision_token():
        st.warning("The ontology changed since this check. Run it again.")
    elif ran_once_id != once_id:
        st.warning("The one-off shapes changed since this check. Run it again.")
    elif ran_sources != tuple(sources):
        st.warning("The shapes selection changed since this check. Run it again.")
    elif ran_infer != (infer and "generated" in sources):
        st.warning("The inference setting changed since this check. Run it again.")
    ctx = QualityContext(ont, include_imports=True)
    for origin, run in runs.items():
        st.markdown(f"**{_source_title(origin)}**")
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
        render_findings_table(
            run.findings,
            key=f"shacl_{origin}_{scope}",
            group_of=lambda f: f.source_shape or "(unnamed shape)",
            group_label="Shape",
            name_of=ctx.name,
            kind_of=ctx.kind,
        )
        if run.report_ttl is not None:
            with st.expander("Export results", expanded=False):
                _download_or_save(
                    "Download validation report (.ttl)",
                    run.report_ttl,
                    "shacl-report.ttl",
                    key=f"shacl_report_{origin}",
                )
                if run.findings:
                    _download_or_save(
                        "Download findings (.json)",
                        findings_json(run.findings, source="shacl"),
                        "shacl-findings.json",
                        mime="application/json",
                        key=f"shacl_export_json_{origin}",
                    )
                    _download_or_save(
                        "Download findings (.csv)",
                        findings_csv(run.findings),
                        "shacl-findings.csv",
                        mime="text/csv",
                        key=f"shacl_export_csv_{origin}",
                    )

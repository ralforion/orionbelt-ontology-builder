"""The dashboard page: an overview of the ontology, and its settings."""

from __future__ import annotations

import textwrap
from collections import Counter
from collections.abc import Callable, Iterable
from typing import NamedTuple

import streamlit as st
from rdflib.namespace import RDFS

from ..overview import NO_LANGUAGE, Overview, ontology_overview
from ..quality import RULES, QualityFinding, analyze, partition
from ..ui import (
    _uid,
    chart_accent,
    chart_ink,
    save_checkpoint,
    set_flash_message,
    show_message,
    sized_table,
)
from .charts import column_bars, describe, meter_list, percent, ranked_bars
from .findings import SEVERITY_ICONS
from .validation import quality_run_key, stored_quality_config

#: Up to this many triples the Overview runs validation and the quality rules
#: by itself, once per edit: together about 0.3 s at 10k triples on a laptop,
#: where 21k took 0.9 s and 43k 2.1 s. Above it they wait for a click.
CHECKS_AUTORUN_MAX_TRIPLES = 10_000

#: How many rules the findings chart names before folding the rest.
_TOP_RULES = 6

#: The quality rule that reports a validation issue of this type as well, on
#: the same class. Cycles are matched by their members instead.
_QUALITY_RULE_FOR = {"missing_label": "Q001", "orphan_class": "Q007"}

_SUBCLASS_OF = str(RDFS.subClassOf)

_OVERVIEW_STATE = "_dashboard_overview"
_VALIDATION_STATE = "_dashboard_validation"


class _Validation(NamedTuple):
    token: str
    issues: list[dict[str, str]]
    #: ``validate()``'s class cycles, one per ``class_cycle`` issue, in order.
    cycles: list[list[str]]


def render_dashboard():
    """Render the dashboard: an overview of the ontology, or its settings."""
    st.header("Dashboard")
    ont = st.session_state.ontology
    # Seeded rather than given as ``default=``, so another page can pre-set it.
    if "dash_active_tab" not in st.session_state:
        st.session_state["dash_active_tab"] = "Overview"
    section = st.segmented_control(
        "Section",
        ["Overview", "Settings"],
        key="dash_active_tab",
        label_visibility="collapsed",
    )
    if section == "Settings":
        _render_settings(ont)
    else:
        _render_overview(ont)


def _open_page(page: str, tab_key: str | None = None, tab: str | None = None) -> None:
    """Callback: open ``page``, on ``tab`` when given."""
    st.session_state.search_navigate_to = page
    if tab_key:
        st.session_state[tab_key] = tab


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _cached_overview(ont) -> Overview:
    """The overview of ``ont``, worked out once per revision of the graph."""
    token = ont.revision_token()
    cached = st.session_state.get(_OVERVIEW_STATE)
    if cached is None or cached[0] != token:
        cached = (token, ontology_overview(ont))
        st.session_state[_OVERVIEW_STATE] = cached
    return cached[1]


def _render_overview(ont) -> None:
    overview = _cached_overview(ont)
    _render_header(overview)
    # An empty ontology gets no tiles: a row of zeros says what the note says.
    if overview.is_empty:
        st.info(
            "Nothing to measure yet. Add classes, properties or concepts on "
            "their pages, or import or create an ontology."
        )
        st.button(
            "Open Import / Export",
            on_click=_open_page,
            args=("Import / Export",),
            key="dash_open_import",
        )
        return

    cols = st.columns(len(overview.counts))
    for col, (label, value) in zip(cols, overview.counts.items(), strict=True):
        col.metric(label, f"{value:,}", border=True)

    accent = chart_accent()
    coverage_col, hierarchy_col = st.columns(2, gap="large")
    with coverage_col:
        _render_coverage(overview, accent)
    with hierarchy_col:
        _render_hierarchy(overview, accent)
    _render_checks(ont, overview.triples, accent)
    _render_distributions(overview, accent)


def _render_header(overview: Overview) -> None:
    with st.container(border=True):
        st.subheader(overview.title, anchor=False)
        facts = [f"`{overview.ontology_iri}`"]
        if overview.version:
            facts.append(f"version `{overview.version}`")
        facts.append(_plural(overview.triples, "triple"))
        facts.append(
            _plural(overview.imports, "import") if overview.imports else "no imports"
        )
        st.caption(" · ".join(facts))
        if overview.comment:
            st.write(textwrap.shorten(overview.comment, 280, placeholder=" …"))


def _render_coverage(overview: Overview, accent: str) -> None:
    st.subheader("Coverage", anchor=False)
    rows = [(c.label, c.have, c.total) for c in overview.coverage]
    if not rows:
        st.caption("No classes, properties or concepts of its own.")
        return
    st.vega_lite_chart(
        spec=meter_list(rows, accent, ink=chart_ink()),
        width="stretch",
        alt="Coverage: "
        + describe([(n, f"{h:,} of {t:,}", f"{percent(h, t)}%") for n, h, t in rows]),
    )
    note = (
        "Labels are rdfs:label or skos:prefLabel; definitions are rdfs:comment, "
        "skos:definition or a Dublin Core description, as the quality rules "
        "read them."
    )
    if overview.own_scope_only:
        note += (
            " Only the ontology's own entities count: those in its namespace or "
            "rdfs:isDefinedBy it."
        )
    st.caption(note)


def _render_hierarchy(overview: Overview, accent: str) -> None:
    st.subheader("Class hierarchy", anchor=False)
    shape = overview.hierarchy
    if not shape.classes:
        st.caption("No classes of its own.")
        return
    depth_col, roots_col, leaves_col, multi_col = st.columns(4)
    depth_col.metric(
        "Depth",
        f"{shape.max_depth:,}",
        help="The longest rdfs:subClassOf path from a root class",
    )
    roots_col.metric("Roots", f"{shape.roots:,}", help="Classes without a superclass")
    leaves_col.metric("Leaves", f"{shape.leaves:,}", help="Classes without a subclass")
    multi_col.metric(
        "Multi-parent",
        f"{shape.multi_parent:,}",
        help="Classes with more than one superclass",
    )
    rows = [(str(depth), count) for depth, count in enumerate(shape.per_depth)]
    if rows:
        st.vega_lite_chart(
            spec=column_bars(
                rows,
                accent,
                x_title="Classes per depth (0 = root)",
                what="Classes",
                ink=chart_ink(),
            ),
            width="stretch",
            alt="Classes per depth: " + describe([(f"depth {d}:", n) for d, n in rows]),
        )
    if shape.in_cycles:
        st.caption(
            f"{_plural(shape.in_cycles, 'class')} sit on or below a subClassOf "
            "cycle and have no depth; Quality names the cycle."
        )


def _render_checks(ont, triples: int, accent: str) -> None:
    """Validation and the quality rules, run here while the ontology is small."""
    st.subheader("Checks", anchor=False)
    config = stored_quality_config(ont)
    run_key = quality_run_key(ont)
    # Per ontology, as the quality run is: another ontology's issues must
    # never show as this one's.
    validation_key = f"{_VALIDATION_STATE}_{_uid(str(ont.ontology_uri))}"
    token = ont.revision_token()
    run = st.session_state.get(run_key)
    validation = st.session_state.get(validation_key)
    # One kept by an older version of this page has no cycles: run again.
    if not isinstance(validation, _Validation):
        validation = None
    stale = not (
        run is not None
        and run.graph_fingerprint == token
        and run.config_fingerprint == config.fingerprint
        and validation is not None
        and validation.token == token
    )
    small = triples <= CHECKS_AUTORUN_MAX_TRIPLES
    if stale and (
        small or st.button("Run checks", key="dash_run_checks", type="primary")
    ):
        with st.spinner("Running validation and the quality checks…"):
            validation = _Validation(
                token,
                ont.validate(check_missing_domain_range=False),
                ont.class_cycles(),
            )
            run = analyze(ont, config)
        st.session_state[validation_key] = validation
        st.session_state[run_key] = run
        stale = False

    if run is None or validation is None:
        st.caption(
            f"The checks run by themselves up to "
            f"{CHECKS_AUTORUN_MAX_TRIPLES:,} triples; this ontology has "
            f"{triples:,}."
        )
        return
    if stale:
        st.warning("The ontology changed since these checks ran. Run them again.")

    validation_col, quality_col = st.columns([2, 3], gap="large")
    findings = run.all_findings()
    with validation_col:
        _render_validation(_not_counted_by_quality(validation, findings))
    with quality_col:
        # Suppressions apply as they are now, as on the Quality section.
        shown, suppressed = partition(findings, config)
        _render_quality(shown, len(suppressed), accent)


def _not_counted_by_quality(
    validation: _Validation, findings: Iterable[QualityFinding]
) -> list[dict[str, str]]:
    """The validation issues no quality finding reports as well.

    Missing labels (Q001), unconnected classes (Q007) and subClassOf cycles
    (Q006, or Q009 for a class that is its own subclass) are in both, so an
    issue is left out where its rule reported the same class or the same
    cycle, suppressed findings included. One the rules do not reach stays:
    a class outside the ontology's own scope or not declared an owl:Class,
    or a rule switched off, so a problem never drops out of both panels
    (Codex review of PR #564).
    """
    reported: set[tuple[str, object]] = set()
    for finding in findings:
        if finding.rule_id not in ("Q006", "Q009"):
            reported.add((finding.rule_id, finding.resource))
        # Both cover SKOS hierarchies too, and a resource that is a class and
        # a concept can be on a cycle in each: only a subClassOf one is a
        # class_cycle's (Codex review of PR #564).
        elif finding.evidence.get("predicate") == _SUBCLASS_OF:
            cycle = finding.evidence.get("cycle")
            reported.add(
                ("Q006", tuple(cycle)) if cycle else ("Q009", finding.resource)
            )
    cycles = iter(validation.cycles)
    kept = []
    for issue in validation.issues:
        key: tuple[str, object]
        if issue["type"] == "class_cycle":
            cycle = next(cycles)
            key = ("Q009", cycle[0]) if len(cycle) == 1 else ("Q006", tuple(cycle))
        else:
            key = (_QUALITY_RULE_FOR.get(issue["type"], ""), issue.get("subject_uri"))
        if key not in reported:
            kept.append(issue)
    return kept


def _render_validation(issues: list[dict[str, str]]) -> None:
    st.markdown("**Validation**")
    st.caption(
        "Missing labels, unconnected classes and hierarchy cycles that Model "
        "quality reports are counted there."
    )
    if not issues:
        st.success("No structural problems found.")
        return
    counts = Counter(issue["severity"] for issue in issues)
    st.write(
        " · ".join(
            f"{SEVERITY_ICONS[severity]} {_plural(counts[severity], severity)}"
            for severity in SEVERITY_ICONS
            if counts[severity]
        )
    )
    with st.expander("Validation details"), sized_table():
        st.dataframe(
            [
                {
                    "Severity": f"{SEVERITY_ICONS.get(i['severity'], '')} "
                    f"{i['severity']}",
                    "Subject": i["subject"],
                    "Message": i["message"],
                }
                for i in issues
            ],
            hide_index=True,
            width="stretch",
        )


def _render_quality(findings, suppressed: int, accent: str) -> None:
    st.markdown("**Model quality**")
    counts = Counter(f.severity for f in findings)
    for col, (severity, label) in zip(
        st.columns(3),
        (("error", "Errors"), ("warning", "Warnings"), ("info", "Info")),
        strict=True,
    ):
        col.metric(
            f"{SEVERITY_ICONS[severity]} {label}", f"{counts[severity]:,}", border=True
        )
    per_rule = Counter(f.rule_id for f in findings)
    if per_rule:
        ranked = per_rule.most_common()
        rows = [
            (RULES[rule_id].title if rule_id in RULES else rule_id, n)
            for rule_id, n in ranked[:_TOP_RULES]
        ]
        rest = ranked[_TOP_RULES:]
        if rest:
            rows.append((f"Other rules ({len(rest)})", sum(n for _, n in rest)))
        _render_ranked(
            rows,
            accent,
            what="Findings",
            alone=lambda rule, n: f"{_plural(n, 'finding')}, all from {rule}.",
        )
    else:
        st.caption("No findings from the enabled rules.")
    if suppressed:
        st.caption(f"{_plural(suppressed, 'finding')} marked as fine, not counted.")
    st.button(
        "Open Quality",
        on_click=_open_page,
        args=("Validation & Reasoning", "val_active_tab", "Quality"),
        key="dash_open_quality",
        help="Every finding, with filters, details and rule settings",
    )


def _render_ranked(
    rows: list[tuple[str, int]],
    accent: str,
    *,
    what: str,
    alone: Callable[[str, int], str],
) -> None:
    """Ranked bars, or for a single row the sentence ``alone`` makes of it:
    one bar only restates its number."""
    if len(rows) == 1:
        st.write(alone(*rows[0]))
        return
    st.vega_lite_chart(
        spec=ranked_bars(rows, accent, what=what, ink=chart_ink()),
        width="stretch",
        alt=f"{what}: " + describe(rows),
    )


def _all_individuals(class_name: str, count: int) -> str:
    return f"{_plural(count, 'individual')}, all of class {class_name}."


def _all_labels(language: str, count: int) -> str:
    if language == NO_LANGUAGE:
        return f"{_plural(count, 'label')}, none with a language tag."
    return f"{_plural(count, 'label')}, all tagged {language}."


def _render_distributions(overview: Overview, accent: str) -> None:
    panels = []
    if overview.uses_owl:
        panels.append("individuals")
    panels.append("languages")
    for col, panel in zip(st.columns(2, gap="large"), panels, strict=False):
        alone: Callable[[str, int], str]
        with col:
            if panel == "individuals":
                st.subheader("Individuals per class", anchor=False)
                rows = list(overview.instances_per_class)
                empty = "No individuals."
                what = "Individuals"
                alone = _all_individuals
            else:
                st.subheader("Label languages", anchor=False)
                rows = list(overview.label_languages)
                empty = "No labels."
                what = "Labels"
                alone = _all_labels
            if not rows:
                st.caption(empty)
                continue
            _render_ranked(rows, accent, what=what, alone=alone)
            if panel == "languages":
                st.caption(
                    "Preferred labels of its own classes, properties and "
                    "concepts, by language tag."
                )


def _render_settings(ont) -> None:
    """Ontology metadata, imports and namespace prefixes."""
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
        prefix_data: dict[str, list[str]] = {
            "Prefix": [],
            "Namespace": [],
            "Source": [],
        }
        for p in all_prefixes:
            prefix_data["Prefix"].append(p["prefix"])
            prefix_data["Namespace"].append(p["namespace"])
            prefix_data["Source"].append(p["source"])
        with sized_table():
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

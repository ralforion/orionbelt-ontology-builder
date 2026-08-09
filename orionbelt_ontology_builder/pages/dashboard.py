"""The dashboard page."""

import streamlit as st

from ..ui import (
    save_checkpoint,
    set_flash_message,
    show_message,
)


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

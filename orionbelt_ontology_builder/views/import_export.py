"""The import export page."""

import streamlit as st

from ..ui import (
    _download_or_save,
    clearable_selectbox,
    get_ontology_manager_class,
    request_autosave_flush,
    save_checkpoint,
    set_flash_message,
    show_message,
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
                from ..ontology_manager import UndoManager

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
                # The same count the sidebar shows, which is what the user
                # checks it against. len(graph) includes the ontology header,
                # so an import of a file carrying one announced more triples
                # than Quick Stats then displayed, and the difference read as
                # data lost on the way in (issue #263). The template and
                # upper/reference loaders below already report it this way.
                set_flash_message(
                    "Ontology imported successfully! "
                    f"({ont.get_statistics()['content_triples']} triples)",
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
            from ..ontology_manager import (
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
                        triples = ont.get_statistics()["content_triples"]
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
                    from ..ontology_manager import UndoManager

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
        from ..templates import get_template, get_template_names, render_template

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
        selected_template = clearable_selectbox(
            "Select Template",
            template_names,
            key="template_select",
            current_display=template_names[0] if template_names else None,
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
        from ..templates import (
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
        selected_upper = clearable_selectbox(
            "Select Upper Ontology",
            upper_names,
            key="upper_ontology_select",
            current_display=upper_names[0] if upper_names else None,
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
        from ..templates import (
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
        selected_ref = clearable_selectbox(
            "Select Reference Ontology",
            ref_names,
            key="reference_ontology_select",
            current_display=ref_names[0] if ref_names else None,
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

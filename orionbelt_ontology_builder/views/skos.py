"""The skos vocabulary page."""

import streamlit as st

from ..ui import (
    _cb_confirm_delete,
    _cb_toggle_edit,
    _cb_toggle_view,
    _cb_view_to_edit,
    _custom_uri_field,
    _is_open,
    _open_entity,
    _pad_option,
    _renamed_ref,
    _resolve_list_view,
    build_uri_options,
    clearable_selectbox,
    confirm_delete,
    format_label_name,
    language_selectbox,
    language_tag_error,
    missing_required,
    render_skos_literal_editor,
    required_selectbox,
    save_checkpoint,
    set_flash_message,
    show_message,
    viz_note_rename,
)


def _fmt_tagged(items):
    """Render ``[{"value","lang"}]`` as ``value (lang), value (lang)``."""
    return ", ".join(
        f"{item['value']} ({item['lang']})" if item["lang"] else item["value"]
        for item in items
    )


def render_skos_vocabulary():
    """Render the SKOS Vocabulary management page."""
    st.header("SKOS Vocabulary")

    ont = st.session_state.ontology
    schemes = ont.get_concept_schemes()
    concepts = ont.get_concepts()
    # URI-keyed dropdown options for scheme/concept selectors (issue #87 part B):
    # a scheme or concept moved to a custom URI can share a local name with
    # another, so pass the picked URI to the engine instead of a bare local name
    # that would resolve through the base namespace. ``.get(sentinel)`` returns
    # None for the "All"/"None" entries, which is what the engine expects.
    scheme_opts, scheme_lookup = build_uri_options(schemes)

    # Clean up unused navigation flag
    st.session_state.pop("_skos_navigate_to_concept", None)

    _skos_tab = st.segmented_control(
        "Section",
        ["Concepts", "Concept Schemes", "Concept Hierarchy", "SKOS Validation"],
        default="Concepts",
        key="skos_active_tab",
        label_visibility="collapsed",
    )
    if not _skos_tab:
        _skos_tab = "Concepts"

    if _skos_tab == "Concept Schemes":
        st.subheader("Concept Schemes")
        if not schemes:
            st.info("No concept schemes defined yet.")
        else:
            for scheme in schemes:
                display_name = format_label_name(scheme["name"], scheme.get("label"))
                # Key and address schemes by a URI-derived id, not the local name:
                # a scheme moved to a custom URI can share a local name with
                # another, which would collide Streamlit widget keys and make
                # local-name-based actions ambiguous (issue #87 part B).
                _sk = str(abs(hash(scheme["uri"])))[:8]
                _scheme_expanded = _is_open("scheme", _sk)
                with st.expander(
                    f"📚 **{display_name}** ({scheme['concept_count']} concepts)",
                    expanded=_scheme_expanded,
                ):
                    st.write(
                        f"**URI:** `{scheme['uri']}`"
                        if scheme["uri"].startswith("http://example.org/")
                        else f"**URI:** {scheme['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("scheme", _sk),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("scheme", _sk),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_scheme_{_sk}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"scheme_{_sk}",),
                        )

                    if _is_open("scheme", _sk, "view"):
                        st.divider()
                        st.write(f"**Name:** {scheme['name']}")
                        st.write(f"**Label:** {scheme['label'] or '—'}")
                        st.write(f"**Comment:** {scheme['comment'] or '—'}")
                        st.write(f"**Concepts:** {scheme['concept_count']}")

                    if confirm_delete(scheme["uri"], "scheme", f"scheme_{_sk}"):
                        ont.delete_concept_scheme(scheme["uri"])
                        save_checkpoint("Delete concept scheme")
                        set_flash_message(
                            f"Scheme '{scheme['name']}' deleted!", "success"
                        )
                        st.rerun()

                    if _is_open("scheme", _sk, "edit"):
                        st.divider()
                        with st.form(f"edit_scheme_form_{_sk}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=scheme["name"],
                                key=f"scheme_name_{_sk}",
                                help="Renaming updates every reference, including "
                                "the inScheme links from its concepts — no "
                                "membership is lost.",
                            )
                            new_label = st.text_input(
                                "Label",
                                value=scheme["label"] or "",
                                key=f"scheme_lbl_{_sk}",
                            )
                            new_comment = st.text_area(
                                "Comment",
                                value=scheme["comment"] or "",
                                key=f"scheme_cmt_{_sk}",
                            )
                            new_name = _custom_uri_field(
                                scheme["uri"],
                                new_name,
                                key=f"custom_uri_scheme_{_sk}",
                            )
                            if st.form_submit_button("Save Changes"):
                                if (
                                    new_name
                                    and new_name != scheme["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                renamed = bool(new_name and new_name != scheme["name"])
                                # Address the scheme by its actual URI so a scheme
                                # in a non-base namespace resolves; target is the
                                # URI it now lives at (issue #87 part B).
                                if renamed and not ont.rename_concept_scheme(
                                    scheme["uri"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = (
                                        _renamed_ref(ont, scheme["uri"], new_name)
                                        if renamed
                                        else scheme["uri"]
                                    )
                                    ont.update_concept_scheme(
                                        target,
                                        new_label=new_label,
                                        new_comment=new_comment,
                                    )
                                    save_checkpoint("Update concept scheme")
                                    _new_sk = str(abs(hash(target)))[:8]
                                    _open_entity("scheme", _new_sk)
                                    show_message(
                                        f"Scheme '{scheme['name']}' updated!", "success"
                                    )
                                    st.rerun()

        st.divider()
        st.subheader("Add Concept Scheme")
        with st.form("add_scheme_form"):
            s_name = st.text_input("Scheme Name *")
            s_label = st.text_input("Label")
            s_comment = st.text_area("Comment")
            if st.form_submit_button("Add Scheme"):
                if not s_name:
                    show_message("Scheme name is required!", "error")
                elif reason := ont.invalid_name_reason(s_name):
                    show_message(reason, "error")
                # Rejected by target URI, not local name, so a base scheme can
                # be recreated after an existing one is moved to a custom URI
                # (issue #87 part B), and across every entity kind, since one
                # URI cannot be two things (issue #279). Mirrors the
                # class/property/individual add flows.
                elif taken := ont.name_conflict_reason(s_name, "scheme"):
                    show_message(taken, "error")
                else:
                    ont.add_concept_scheme(
                        s_name, label=s_label or None, comment=s_comment or None
                    )
                    save_checkpoint("Add concept scheme")
                    show_message(f"Scheme '{s_name}' added!", "success")
                    st.rerun()

    if _skos_tab == "Concepts":
        st.subheader("Concepts")
        # Above the list, not below it: adding a concept meant scrolling
        # past every concept already there. Collapsed by default, and the
        # label never changes — a changed expander label force-closes it.
        with (
            st.expander("➕ Add Concept", expanded=False),
            st.form("add_concept_form"),
        ):
            c_name = st.text_input("Concept Name *")
            c_pref = st.text_input("Preferred Label")
            c_def = st.text_area("Definition")
            c_scheme = clearable_selectbox(
                "Scheme",
                ["None"] + scheme_opts,
                key="concept_scheme_select",
                current_display="None",
                format_func=_pad_option,
            )
            _add_broader_opts, _add_broader_lookup = build_uri_options(concepts)
            c_broader = clearable_selectbox(
                "Broader Concept",
                ["None"] + _add_broader_opts,
                key="concept_broader_select",
                current_display="None",
                format_func=_pad_option,
            )
            c_lang = language_selectbox("Language Tag", key="concept_lang")
            if st.form_submit_button("Add Concept"):
                if not c_name:
                    show_message("Concept name is required!", "error")
                elif reason := ont.invalid_name_reason(c_name):
                    show_message(reason, "error")
                # Rejected by target URI, not local name (issue #87 part B), and
                # across every entity kind (issue #279), as for schemes above.
                elif taken := ont.name_conflict_reason(c_name, "concept"):
                    show_message(taken, "error")
                elif lang_error := language_tag_error(c_lang):
                    show_message(lang_error, "error")
                else:
                    ont.add_concept(
                        c_name,
                        scheme=scheme_lookup.get(c_scheme),
                        pref_label=c_pref or None,
                        definition=c_def or None,
                        broader=_add_broader_lookup.get(c_broader),
                        lang=c_lang or None,
                    )
                    save_checkpoint("Add concept")
                    show_message(f"Concept '{c_name}' added!", "success")
                    st.rerun()

        if not concepts:
            st.info("No concepts defined yet.")
        else:
            # Filter by scheme
            filter_scheme = st.selectbox(
                "Filter by Scheme",
                ["All"] + scheme_opts,
                key="concept_filter_scheme",
                format_func=_pad_option,
            )
            filtered = (
                concepts
                if filter_scheme == "All"
                else ont.get_concepts(scheme=scheme_lookup.get(filter_scheme))
            )

            def _concept_key(c):
                return str(abs(hash(c["uri"])))[:8]

            # Single-active selection + pagination, keyed by the concept's URI
            # hash (local names may collide across schemes).
            filtered, _ = _resolve_list_view(
                filtered, "skos", _concept_key, "skos_view_page", "concepts"
            )

            for concept in filtered:
                pref = concept["prefLabel"] or concept["name"]
                display_name = format_label_name(
                    concept["name"], pref if pref != concept["name"] else ""
                )
                badges = []
                if concept["broader"]:
                    badges.append(f"broader: {', '.join(concept['broader'])}")
                if concept["schemes"]:
                    badges.append(f"scheme: {', '.join(concept['schemes'])}")
                badge_str = f" — {'; '.join(badges)}" if badges else ""

                # Use URI hash for unique widget keys (local name may not be unique)
                _ck = str(abs(hash(concept["uri"])))[:8]

                _skos_expanded = _is_open("skos", _ck)
                with st.expander(
                    f"🏷️ **{display_name}**{badge_str}", expanded=_skos_expanded
                ):
                    st.write(
                        f"**URI:** `{concept['uri']}`"
                        if concept["uri"].startswith("http://example.org/")
                        else f"**URI:** {concept['uri']}"
                    )

                    btn_view, btn_edit, btn_del, _ = st.columns([1, 1, 1, 4])
                    with btn_view:
                        st.button(
                            "👁️ View",
                            key=f"btn_view_{_ck}",
                            use_container_width=True,
                            on_click=_cb_toggle_view,
                            args=("skos", _ck),
                        )
                    with btn_edit:
                        st.button(
                            "✏️ Edit",
                            key=f"btn_edit_{_ck}",
                            use_container_width=True,
                            on_click=_cb_toggle_edit,
                            args=("skos", _ck),
                        )
                    with btn_del:
                        st.button(
                            "🗑️ Delete",
                            key=f"btn_del_{_ck}",
                            use_container_width=True,
                            on_click=_cb_confirm_delete,
                            args=(f"c_{_ck}",),
                        )

                    # View details
                    if _is_open("skos", _ck, "view"):
                        st.divider()
                        st.write(f"**Name:** {concept['name']}")
                        for _kind in ont.SKOS_LABEL_KINDS:
                            if concept["labels"][_kind]:
                                st.write(
                                    f"**{_kind}:** "
                                    f"{_fmt_tagged(concept['labels'][_kind])}"
                                )
                        if concept["notation"]:
                            st.write(f"**notation:** {concept['notation']}")
                        for _kind in ont.SKOS_NOTE_KINDS:
                            if concept["notes"][_kind]:
                                st.write(
                                    f"**{_kind}:** "
                                    f"{_fmt_tagged(concept['notes'][_kind])}"
                                )
                        if concept["top_of"]:
                            st.write(
                                f"**topConceptOf:** {', '.join(concept['top_of'])}"
                            )
                        for _rel in ont.SKOS_MAPPING_RELATIONS:
                            for _i, _target in enumerate(concept["mappings"][_rel]):
                                _mc1, _mc2 = st.columns([8, 0.7])
                                with _mc1:
                                    st.write(f"**{_rel}:** {_target}")
                                with _mc2:
                                    if st.button(
                                        "🗑️",
                                        key=f"del_map_{_ck}_{_rel}_{_i}",
                                        help="Remove this mapping",
                                    ):
                                        ont.remove_concept_relation(
                                            concept["uri"], _rel, _target
                                        )
                                        save_checkpoint("Remove concept mapping")
                                        st.rerun()
                        if concept["broader"]:
                            st.write(f"**broader:** {', '.join(concept['broader'])}")
                        if concept["narrower"]:
                            st.write(f"**narrower:** {', '.join(concept['narrower'])}")
                        if concept["related"]:
                            st.write(f"**related:** {', '.join(concept['related'])}")
                        if concept["schemes"]:
                            st.write(f"**schemes:** {', '.join(concept['schemes'])}")

                        # Add relation inline
                        with st.popover("Add Relation"):
                            # A mapping property is the one kind of SKOS link
                            # meant to leave the vocabulary, so an external
                            # target offers only those. Before this, the engine
                            # accepted an exactMatch to Wikidata but the UI had
                            # no way to express one.
                            _target_mode = st.radio(
                                "Target",
                                ["Concept in this vocabulary", "External URI"],
                                key=f"rel_mode_{_ck}",
                                horizontal=True,
                            )
                            _external = _target_mode == "External URI"
                            rel_type = st.selectbox(
                                "Relation",
                                list(ont.SKOS_MAPPING_RELATIONS)
                                if _external
                                else list(ont.SKOS_RELATIONS.keys()),
                                key=f"rel_type_{_ck}_{'ext' if _external else 'int'}",
                            )
                            if _external:
                                rel_target = st.text_input(
                                    "Target URI",
                                    key=f"rel_uri_{_ck}",
                                    placeholder=("http://www.wikidata.org/entity/Q144"),
                                    help="An absolute IRI in another "
                                    "vocabulary — Wikidata, EuroVoc, AGROVOC, "
                                    "anything addressable.",
                                )
                                _resolved = rel_target
                                _required_label = "Target URI"
                            else:
                                _rel_opts, _rel_lookup = build_uri_options(
                                    [c for c in concepts if c["uri"] != concept["uri"]]
                                )
                                rel_target = required_selectbox(
                                    "Target Concept",
                                    _rel_opts,
                                    key=f"rel_target_{_ck}",
                                    current_display=_rel_opts[0] if _rel_opts else None,
                                    format_func=_pad_option,
                                )
                                _resolved = _rel_lookup.get(rel_target)
                                _required_label = "Target Concept"
                            _add_rel = st.button("Add", key=f"add_rel_{_ck}")
                            if _add_rel and (
                                _missing := missing_required(
                                    **{_required_label: rel_target}
                                )
                            ):
                                show_message(_missing, "error")
                            elif _add_rel and rel_target:
                                # Address both concepts by their actual URIs: a
                                # concept moved to a non-base namespace (e.g. via a
                                # custom URI) would not resolve through the base
                                # namespace, and two concepts can share a local
                                # name across namespaces (issue #87 part B).
                                try:
                                    if _external:
                                        ont.add_concept_mapping(
                                            concept["uri"], rel_type, _resolved
                                        )
                                    else:
                                        ont.add_concept_relation(
                                            concept["uri"], rel_type, _resolved
                                        )
                                except ValueError as exc:
                                    show_message(str(exc), "error")
                                else:
                                    save_checkpoint("Add concept relation")
                                    show_message(
                                        f"Added {rel_type} relation!", "success"
                                    )
                                    st.rerun()

                        st.button(
                            "✏️ Edit",
                            key=f"btn_v2e_{_ck}",
                            on_click=_cb_view_to_edit,
                            args=("skos", _ck),
                        )

                    if confirm_delete(concept["uri"], "concept", f"c_{_ck}"):
                        ont.delete_concept(concept["uri"])
                        save_checkpoint("Delete concept")
                        set_flash_message(
                            f"Concept '{concept['name']}' deleted!", "success"
                        )
                        st.rerun()

                    # Inline edit form
                    if _is_open("skos", _ck, "edit"):
                        st.divider()
                        # Labels and notes are repeatable and language-tagged,
                        # so they are edited as rows with their own add/delete
                        # rather than as fields in the form below: a button
                        # inside a form cannot act until the form is submitted.
                        st.markdown("**Labels and notes**")
                        render_skos_literal_editor(ont, concept, _ck)

                        st.divider()
                        with st.form(f"edit_concept_form_{_ck}"):
                            new_name = st.text_input(
                                "Name (URI local part)",
                                value=concept["name"],
                                key=f"cname_{_ck}",
                                help="Renaming updates every reference to this "
                                "concept (broader/narrower, inScheme, etc.) — "
                                "nothing is lost, unlike delete-and-recreate.",
                            )
                            new_notation = st.text_input(
                                "Notation",
                                value=concept["notation"],
                                key=f"notation_{_ck}",
                                help="A code in a classification scheme "
                                "(e.g. `636.7`). Carries a datatype, never a "
                                "language tag.",
                            )

                            # Broader concepts — multi-valued: SKOS allows a
                            # concept more than one parent (poly-hierarchy), and
                            # URI-keyed so a parent in a non-base namespace
                            # resolves unambiguously (#87).
                            _broader_opts, _broader_lookup = build_uri_options(
                                [c for c in concepts if c["uri"] != concept["uri"]]
                            )
                            _cur_broader_disp = [
                                d
                                for d, u in _broader_lookup.items()
                                if u in set(concept["broader_uris"])
                            ]
                            new_broader = st.multiselect(
                                "Broader Concepts",
                                _broader_opts,
                                default=_cur_broader_disp,
                                key=f"broader_{_ck}",
                                format_func=_pad_option,
                                help="A concept may have several parents. An "
                                "edge that would make this concept its own "
                                "ancestor is refused.",
                            )

                            # Scheme — URI-keyed for the same reason.
                            _cur_scheme_uri = (
                                concept["scheme_uris"][0]
                                if concept.get("scheme_uris")
                                else None
                            )
                            _cur_scheme_disp = next(
                                (
                                    d
                                    for d, u in scheme_lookup.items()
                                    if u == _cur_scheme_uri
                                ),
                                "None",
                            )
                            scheme_options = ["None"] + scheme_opts
                            new_scheme = clearable_selectbox(
                                "Scheme",
                                scheme_options,
                                key=f"scheme_{_ck}",
                                current_display=_cur_scheme_disp
                                if _cur_scheme_disp in scheme_options
                                else "None",
                                format_func=_pad_option,
                            )

                            # Top concepts: checked writes skos:topConceptOf and
                            # the scheme's skos:hasTopConcept together, and puts
                            # the concept in that scheme if it was not already.
                            _top_now = set(concept["top_of_uris"])
                            _top_choices = {}
                            for _scheme in schemes:
                                _su = _scheme["uri"]
                                _top_choices[_su] = st.checkbox(
                                    f"Top concept of {_scheme['name']}",
                                    value=_su in _top_now,
                                    key=f"top_{_ck}_{str(abs(hash(_su)))[:8]}",
                                )

                            new_name = _custom_uri_field(
                                concept["uri"],
                                new_name,
                                key=f"custom_uri_concept_{_ck}",
                            )

                            if st.form_submit_button("Save Changes"):
                                # Rename first (updates all references) so the
                                # rest of the update targets the new name.
                                if (
                                    new_name
                                    and new_name != concept["name"]
                                    and (reason := ont.invalid_name_reason(new_name))
                                ):
                                    show_message(reason, "error")
                                    st.rerun()
                                renamed = bool(new_name and new_name != concept["name"])
                                # Address the concept by its actual URI so a
                                # concept in a non-base namespace (e.g. moved via
                                # a custom URI) resolves; ``target`` is the full
                                # URI it now lives at, which later updates use
                                # instead of a base-namespace local name (#87).
                                if renamed and not ont.rename_concept(
                                    concept["uri"], new_name
                                ):
                                    show_message(
                                        f"Cannot rename: '{new_name}' already exists!",
                                        "error",
                                    )
                                else:
                                    target = (
                                        _renamed_ref(ont, concept["uri"], new_name)
                                        if renamed
                                        else concept["uri"]
                                    )
                                    if renamed:
                                        # Concept nodes are keyed by local name,
                                        # which is what a custom-URI rename
                                        # leaves behind too.
                                        viz_note_rename(
                                            "concept",
                                            concept["name"],
                                            ont._local_name(target),
                                        )

                                    # Handle scheme change (resolve by URI)
                                    old_scheme = _cur_scheme_uri or ""
                                    new_scheme_val = scheme_lookup.get(new_scheme) or ""
                                    add_s = (
                                        new_scheme_val
                                        if new_scheme_val
                                        and new_scheme_val != old_scheme
                                        else None
                                    )
                                    remove_s = (
                                        old_scheme
                                        if old_scheme and old_scheme != new_scheme_val
                                        else None
                                    )
                                    ont.update_concept(
                                        target,
                                        add_scheme=add_s,
                                        remove_scheme=remove_s,
                                    )

                                    # One atomic call, not a remove-then-add
                                    # loop here: the engine restores the prior
                                    # parents if any new edge is refused, so a
                                    # rejected re-parent cannot also cost the
                                    # user the hierarchy they already had.
                                    _refused = []
                                    try:
                                        ont.set_concept_broader(
                                            target,
                                            [
                                                _broader_lookup[d]
                                                for d in new_broader
                                                if d in _broader_lookup
                                            ],
                                        )
                                    except ValueError as exc:
                                        _refused.append(str(exc))

                                    ont.set_concept_notation(target, new_notation)

                                    for _su, _checked in _top_choices.items():
                                        if _checked != (_su in _top_now):
                                            ont.set_top_concept(target, _su, _checked)

                                    save_checkpoint("Update concept")
                                    _new_ck = (
                                        str(abs(hash(target)))[:8] if renamed else _ck
                                    )
                                    _open_entity("skos", _new_ck)
                                    # A flash, not show_message: the rerun below
                                    # throws away anything rendered in this run,
                                    # so a refusal reported that way is silent.
                                    if _refused:
                                        set_flash_message(" ".join(_refused), "error")
                                    else:
                                        set_flash_message(
                                            f"Concept '{target}' updated!", "success"
                                        )
                                    st.rerun()

    if _skos_tab == "Concept Hierarchy":
        st.subheader("Concept Hierarchy")
        if not concepts:
            st.info("No concepts to display.")
        else:
            h_scheme = st.selectbox(
                "Scheme",
                ["All"] + scheme_opts,
                key="hierarchy_scheme_select",
                format_func=_pad_option,
            )
            hierarchy = ont.get_concept_hierarchy(
                scheme=scheme_lookup.get(h_scheme) if h_scheme != "All" else None
            )

            # Find root concepts (those that are not narrower of any other)
            all_children = set()
            for children in hierarchy.values():
                all_children.update(children)
            roots = [name for name in hierarchy if name not in all_children]

            def render_tree(name, indent=0, trail=()):
                pad = "&nbsp;&nbsp;&nbsp;&nbsp;" * indent
                arm = "└─ " if indent > 0 else ""
                # The trail is the current path, not a global visited set: under
                # poly-hierarchy a concept legitimately appears beneath several
                # parents, and de-duplicating that would hide real structure.
                # Only a repeat *on the same path* is a cycle, and without this
                # guard an imported cyclic vocabulary recurses until the app
                # dies, before the warning below ever renders.
                if name in trail:
                    st.markdown(f"{pad}{arm}↻ **{name}** — cycle, not expanded")
                    return
                concept_data = next((c for c in concepts if c["name"] == name), None)
                pref = (
                    concept_data["prefLabel"]
                    if concept_data and concept_data["prefLabel"]
                    else name
                )
                st.markdown(f"{pad}{arm}**{pref}** ({name})")
                for child in sorted(hierarchy.get(name, [])):
                    render_tree(child, indent + 1, (*trail, name))

            for root in sorted(roots):
                render_tree(root)

            if not roots and hierarchy:
                st.warning("All concepts have broader concepts — possible cycle.")

    if _skos_tab == "SKOS Validation":
        st.subheader("SKOS Validation")
        st.caption(
            "Errors are conditions the SKOS Reference states outright. "
            "Conventions are thesaurus practice; editorial checks are about "
            "completeness. Both advisory tiers can be switched off, which is "
            "what makes this usable on a large imported vocabulary."
        )
        _c1, _c2 = st.columns(2)
        with _c1:
            _conventions = st.checkbox(
                "Conventions (warnings)", value=True, key="skos_check_conventions"
            )
        with _c2:
            _editorial = st.checkbox(
                "Editorial (info)", value=True, key="skos_check_editorial"
            )

        # Rendered from the engine's catalogue, not retyped here: a check code
        # like `hierarchy_redundancy` means nothing on its own, and a reference
        # maintained separately from the checks drifts from them.
        with st.expander("What is checked", expanded=False):
            for _sev, _title in (
                ("error", "Errors — always checked"),
                ("warning", "Conventions — the warnings checkbox"),
                ("info", "Editorial — the info checkbox"),
            ):
                st.markdown(f"**{_title}**")
                for _kind, _entry in ont.SKOS_CHECKS.items():
                    if _entry["severity"] == _sev:
                        st.markdown(
                            f"- `{_kind}` — {_entry['summary']} "
                            f"<span style='opacity:.6'>({_entry['source']})</span>",
                            unsafe_allow_html=True,
                        )

        if st.button("Run SKOS Validation", key="run_skos_validation"):
            st.session_state["_skos_issues"] = ont.validate_skos(
                check_conventions=_conventions, check_editorial=_editorial
            )

        if (_issues := st.session_state.get("_skos_issues")) is not None:
            if not _issues:
                st.success("No SKOS issues found!")
            else:
                _icons = {"error": "🔴", "warning": "🟡", "info": "🔵"}
                _counts: dict[str, int] = {}
                for _issue in _issues:
                    _counts[_issue["severity"]] = _counts.get(_issue["severity"], 0) + 1
                st.write(
                    " · ".join(
                        f"{_icons[_sev]} {_counts[_sev]} "
                        f"{_sev}{'s' if _counts[_sev] != 1 else ''}"
                        for _sev in ("error", "warning", "info")
                        if _counts.get(_sev)
                    )
                )

                # Grouped by check, not a flat list: a real vocabulary produces
                # hundreds of issues and "37 concepts have no definition" is one
                # decision, while thirty-seven lines of it is a wall.
                _by_type: dict[str, list[dict[str, str]]] = {}
                for _issue in _issues:
                    _by_type.setdefault(_issue["type"], []).append(_issue)
                for _kind, _group in _by_type.items():
                    _sev = _group[0]["severity"]
                    with st.expander(
                        f"{_icons[_sev]} {_kind} — {len(_group)}", expanded=False
                    ):
                        for _issue in _group:
                            st.markdown(f"- {_issue['message']}")

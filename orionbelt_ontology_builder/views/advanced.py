"""The advanced page."""

import streamlit as st

from ..ui import (
    missing_required,
    required_selectbox,
    save_checkpoint,
    show_message,
)


def render_advanced():
    """Render the advanced OWL features page."""
    st.header("Advanced OWL Features")

    ont = st.session_state.ontology
    classes = ont.get_classes()
    class_names = [c["name"] for c in classes]
    object_props = ont.get_object_properties()
    data_props = ont.get_data_properties()
    all_prop_names = [p["name"] for p in object_props] + [p["name"] for p in data_props]
    individuals = ont.get_individuals()
    ind_names = [i["name"] for i in individuals]

    _adv_tab = st.segmented_control(
        "Section",
        [
            "Class Expressions",
            "Property Chains",
            "Disjoint Union",
            "All Different",
            "Has Key",
        ],
        default="Class Expressions",
        key="adv_active_tab",
        label_visibility="collapsed",
    )
    if not _adv_tab:
        _adv_tab = "Class Expressions"

    if _adv_tab == "Class Expressions":
        st.subheader("Class Expressions")
        st.caption("Define complex class expressions using set operations")

        # View existing expressions
        expressions = ont.get_class_expressions()
        if expressions:
            st.write("**Existing Expressions:**")
            for expr in expressions:
                st.write(
                    f"- **{expr['class']}** {expr['type']}: {', '.join(expr['members'])}"
                )
        else:
            st.info("No class expressions defined yet.")

        st.divider()

        if len(class_names) < 2:
            st.warning("Need at least 2 classes to create expressions.")
        else:
            with st.form("add_class_expression_form"):
                target_class = required_selectbox(
                    "Target Class",
                    class_names,
                    key="adv_expr_target",
                    current_display=class_names[0] if class_names else None,
                    help="The class to define with this expression",
                )

                expr_type = st.selectbox(
                    "Expression Type",
                    options=["unionOf", "intersectionOf", "complementOf", "oneOf"],
                )

                st.write("**Select members:**")
                if expr_type == "complementOf":
                    complement_class = required_selectbox(
                        "Complement of Class",
                        class_names,
                        key="adv_expr_complement",
                        current_display=class_names[0] if class_names else None,
                    )
                    selected_classes = [complement_class] if complement_class else []
                    selected_individuals = []
                elif expr_type == "oneOf":
                    selected_individuals = st.multiselect(
                        "Individuals (enumeration)", options=ind_names
                    )
                    selected_classes = []
                else:
                    selected_classes = st.multiselect("Classes", options=class_names)
                    selected_individuals = []

                submitted = st.form_submit_button("Add Expression")
                if submitted:
                    if _missing := missing_required(**{"Target Class": target_class}):
                        show_message(_missing, "error")
                    elif expr_type == "oneOf" and selected_individuals:
                        ont.add_class_expression(
                            target_class, expr_type, individuals=selected_individuals
                        )
                        save_checkpoint("Add class expression")
                        show_message(f"Expression added to {target_class}", "success")
                        st.rerun()
                    elif selected_classes:
                        ont.add_class_expression(
                            target_class, expr_type, classes=selected_classes
                        )
                        save_checkpoint("Add class expression")
                        show_message(f"Expression added to {target_class}", "success")
                        st.rerun()
                    else:
                        show_message("Please select at least one member!", "error")

    if _adv_tab == "Property Chains":
        st.subheader("Property Chains")
        st.caption(
            "Define property chain axioms (e.g., hasParent o hasBrother = hasUncle)"
        )

        # View existing chains
        chains = ont.get_property_chains()
        if chains:
            st.write("**Existing Property Chains:**")
            for chain in chains:
                st.write(f"- **{chain['property']}** = {' o '.join(chain['chain'])}")
        else:
            st.info("No property chains defined yet.")

        st.divider()

        obj_prop_names = [p["name"] for p in object_props]
        if len(obj_prop_names) < 2:
            st.warning("Need at least 2 object properties to create chains.")
        else:
            with st.form("add_property_chain_form"):
                result_prop = required_selectbox(
                    "Result Property",
                    obj_prop_names,
                    key="adv_chain_result",
                    current_display=obj_prop_names[0] if obj_prop_names else None,
                    help="The property that results from following the chain",
                )

                chain_props = st.multiselect(
                    "Chain Properties (in order)",
                    options=obj_prop_names,
                    help="Select properties in the order they should be followed",
                )

                submitted = st.form_submit_button("Add Property Chain")
                if submitted:
                    if _missing := missing_required(**{"Result Property": result_prop}):
                        show_message(_missing, "error")
                    elif len(chain_props) < 2:
                        show_message("Chain must have at least 2 properties!", "error")
                    else:
                        ont.add_property_chain(result_prop, chain_props)
                        save_checkpoint("Add property chain")
                        show_message(
                            f"Property chain added for {result_prop}", "success"
                        )
                        st.rerun()

    if _adv_tab == "Disjoint Union":
        st.subheader("Disjoint Union")
        st.caption("Define a class as the disjoint union of other classes")

        # View existing disjoint unions
        unions = ont.get_disjoint_unions()
        if unions:
            st.write("**Existing Disjoint Unions:**")
            for union in unions:
                st.write(
                    f"- **{union['class']}** = disjointUnionOf({', '.join(union['members'])})"
                )
        else:
            st.info("No disjoint unions defined yet.")

        st.divider()

        if len(class_names) < 3:
            st.warning(
                "Need at least 3 classes (1 parent + 2 children) for disjoint union."
            )
        else:
            with st.form("add_disjoint_union_form"):
                parent_class = required_selectbox(
                    "Parent Class",
                    class_names,
                    key="adv_union_parent",
                    current_display=class_names[0] if class_names else None,
                    help="The class that is the disjoint union",
                )

                member_classes = st.multiselect(
                    "Member Classes",
                    options=class_names,
                    help="Classes that make up the disjoint union",
                )

                submitted = st.form_submit_button("Add Disjoint Union")
                if submitted:
                    if _missing := missing_required(**{"Parent Class": parent_class}):
                        show_message(_missing, "error")
                    elif len(member_classes) < 2:
                        show_message("Need at least 2 member classes!", "error")
                    elif parent_class in member_classes:
                        show_message("Parent class cannot be a member!", "error")
                    else:
                        ont.add_disjoint_union(parent_class, member_classes)
                        save_checkpoint("Add disjoint union")
                        show_message(
                            f"Disjoint union added for {parent_class}", "success"
                        )
                        st.rerun()

    if _adv_tab == "All Different":
        st.subheader("All Different")
        st.caption("Declare that a set of individuals are all mutually different")

        # View existing AllDifferent declarations
        all_diffs = ont.get_all_different()
        if all_diffs:
            st.write("**Existing AllDifferent Declarations:**")
            for i, diff in enumerate(all_diffs):
                st.write(f"- AllDifferent: {', '.join(diff)}")
        else:
            st.info("No AllDifferent declarations yet.")

        st.divider()

        if len(ind_names) < 2:
            st.warning("Need at least 2 individuals for AllDifferent.")
        else:
            with st.form("add_all_different_form"):
                selected_inds = st.multiselect(
                    "Select Individuals",
                    options=ind_names,
                    help="All selected individuals will be declared mutually different",
                )

                submitted = st.form_submit_button("Add AllDifferent")
                if submitted:
                    if len(selected_inds) < 2:
                        show_message("Select at least 2 individuals!", "error")
                    else:
                        ont.add_all_different(selected_inds)
                        save_checkpoint("Add all different")
                        show_message("AllDifferent declaration added!", "success")
                        st.rerun()

    if _adv_tab == "Has Key":
        st.subheader("Has Key")
        st.caption("Define key properties that uniquely identify instances of a class")

        # View existing hasKey declarations
        keys = ont.get_has_keys()
        if keys:
            st.write("**Existing hasKey Declarations:**")
            for key in keys:
                st.write(f"- **{key['class']}** hasKey: {', '.join(key['properties'])}")
        else:
            st.info("No hasKey declarations yet.")

        st.divider()

        if not class_names:
            st.warning("Need at least 1 class.")
        elif not all_prop_names:
            st.warning("Need at least 1 property.")
        else:
            with st.form("add_has_key_form"):
                target_class = required_selectbox(
                    "Class",
                    class_names,
                    key="adv_haskey_class",
                    current_display=class_names[0] if class_names else None,
                )

                key_props = st.multiselect(
                    "Key Properties",
                    options=all_prop_names,
                    help="Properties that together uniquely identify instances",
                )

                submitted = st.form_submit_button("Add hasKey")
                if submitted:
                    if _missing := missing_required(Class=target_class):
                        show_message(_missing, "error")
                    elif not key_props:
                        show_message("Select at least 1 property!", "error")
                    else:
                        ont.add_has_key(target_class, key_props)
                        save_checkpoint("Add has key")
                        show_message(f"hasKey added for {target_class}", "success")
                        st.rerun()

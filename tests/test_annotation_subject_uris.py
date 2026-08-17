"""An annotation belongs to the resource's own URI, not to its local name.

The Annotations page addressed the resource it was annotating by local name,
and a local name resolves into *this* ontology's namespace — so annotating an
imported class (``gist:Account``) wrote to ``:Account``, a subject nothing
declares. It looked right, because the page read the annotations back the same
way, but the row editor's Save and Delete aimed at the real URI and quietly did
nothing.

The Add form is driven directly rather than through the page, for the reason the
other annotation UI tests give: the page's tab picker is a ``segmented_control``,
which AppTest mis-serializes.
"""

import pandas as pd
import pytest
from rdflib import OWL, RDF, BNode, Graph, Literal, URIRef
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import app
from orionbelt_ontology_builder.ontology_manager import OntologyManager

GIST = "https://w3id.org/semanticarts/ns/ontology/gist/"
ACCOUNT = GIST + "Account"
BASE = "http://test.org/ont#"
COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"


def _om():
    """An ontology with one class of its own and one from another namespace.

    The prefix is bound as an import would bind it, so a namesake reads
    ``Account (gist)`` rather than falling back to the whole namespace.
    """
    m = OntologyManager(base_uri=BASE)
    m.add_class("Invoice")
    m.graph.bind("gist", GIST)
    m.graph.add((URIRef(ACCOUNT), RDF.type, OWL.Class))
    return m


def _resources(om):
    """``all_resources`` as the page builds it, which carries each URI."""
    return [
        {
            "name": c["name"],
            "uri": c["uri"],
            "label": c.get("label"),
            "type": "Class",
            "display": c["name"],
        }
        for c in om.get_classes()
    ]


# --- the write path ---------------------------------------------------------


def _add_script():
    # AppTest runs this function's own source as the script, so it takes the
    # ontology from session state rather than from anything at module level
    # here, which is not in scope inside it.
    import streamlit as st

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_add_annotation(
        ont,
        [
            {
                "name": c["name"],
                "uri": c["uri"],
                "label": c.get("label"),
                "type": "Class",
                "display": c["name"],
            }
            for c in ont.get_classes()
        ],
    )


def _run(script, om):
    at = AppTest.from_function(script)
    at.session_state["ontology"] = om
    at.session_state["_autosave_restored"] = True
    at.run(timeout=120)
    assert not at.exception, at.exception
    return at


def _add(at, resource, value):
    at.selectbox(key="ann_resource").set_value(resource)
    at.selectbox(key="ann_predicate").set_value("rdfs:comment")
    at.text_area(key="ann_value").set_value(value)
    at.button[0].click().run(timeout=120)
    assert not at.exception, at.exception


def test_the_add_form_annotates_the_resource_it_was_shown():
    at = _run(_add_script, _om())
    _add(at, "Account [Class]", "an account")

    ont = at.session_state["ontology"]
    assert (URIRef(ACCOUNT), URIRef(COMMENT), Literal("an account")) in ont.graph
    # And nothing on the namesake in this ontology's own namespace.
    assert ont.get_annotations(BASE + "Account") == []


def test_what_the_add_form_writes_can_be_deleted_again():
    """The round trip the bug broke: the editor and the row delete address the
    resource by URI, so they must find what the form wrote."""
    at = _run(_add_script, _om())
    _add(at, "Account [Class]", "an account")

    ont = at.session_state["ontology"]
    # Listed under the resource itself, so what the editor reads is what the
    # form wrote — the delete below would otherwise pass by removing nothing.
    assert [a["value"] for a in ont.get_annotations(ACCOUNT)] == ["an account"]
    ont.delete_annotation(ACCOUNT, COMMENT, "an account")
    assert ont.get_annotations(ACCOUNT) == []


def test_a_resource_of_this_ontologys_own_is_unaffected():
    at = _run(_add_script, _om())
    _add(at, "Invoice [Class]", "a bill")

    ont = at.session_state["ontology"]
    assert [a["value"] for a in ont.get_annotations(BASE + "Invoice")] == ["a bill"]


# --- what the old behaviour left behind -------------------------------------


def _om_with_stray():
    """What an older version produced: the annotation on the local-name URI."""
    m = _om()
    m.graph.add((URIRef(BASE + "Account"), URIRef(COMMENT), Literal("an account")))
    return m


def test_a_stray_annotation_is_found_under_the_resource_it_was_meant_for():
    m = _om_with_stray()
    assert m.stray_annotation_subject(ACCOUNT) == BASE + "Account"
    # Nothing to adopt for a resource that has no misplaced namesake.
    assert m.stray_annotation_subject(BASE + "Invoice") is None


def test_a_resource_of_this_ontologys_own_never_looks_stray():
    m = _om_with_stray()
    m.add_annotation(BASE + "Invoice", "comment", "a bill")
    assert m.stray_annotation_subject(BASE + "Invoice") is None


def test_a_declared_namesake_is_left_alone():
    """A base-namespace class of the same name is a resource in its own right,
    and its annotations are its own."""
    m = _om_with_stray()
    m.add_class("Account")
    assert m.stray_annotation_subject(ACCOUNT) is None
    assert m.adopt_stray_annotations(ACCOUNT) == 0
    assert [a["value"] for a in m.get_annotations(BASE + "Account")] == ["an account"]


def test_adopting_moves_the_annotations_and_leaves_nothing_behind():
    m = _om_with_stray()
    assert m.adopt_stray_annotations(ACCOUNT) == 1
    assert [a["value"] for a in m.get_annotations(ACCOUNT)] == ["an account"]
    assert m.get_annotations(BASE + "Account") == []
    # Moved, not copied, so a second run finds nothing to do.
    assert m.adopt_stray_annotations(ACCOUNT) == 0


def test_adopting_carries_the_language_tag_and_the_datatype():
    m = _om()
    m.add_annotation(BASE + "Account", "label", "Konto", lang="deu")
    m.add_annotation(BASE + "Account", "date", "2026-01-01", datatype="date")
    assert m.adopt_stray_annotations(ACCOUNT) == 2

    moved = {a["value"]: a for a in m.get_annotations(ACCOUNT)}
    assert moved["Konto"]["language"] == "deu"
    assert moved["2026-01-01"]["datatype"] == "date"


def test_adopting_leaves_structure_and_blank_nodes_where_they_are():
    m = _om_with_stray()
    stray = URIRef(BASE + "Account")
    m.graph.add((stray, RDF.type, OWL.Class))  # now declared: not stray at all
    assert m.adopt_stray_annotations(ACCOUNT) == 0

    m.graph.remove((stray, RDF.type, OWL.Class))
    node = BNode()
    m.graph.add((stray, URIRef(BASE + "sub"), node))
    assert m.adopt_stray_annotations(ACCOUNT) == 1
    assert (stray, URIRef(BASE + "sub"), node) in m.graph


def _view_script():
    # Self-contained, for the reason given on _add_script.
    import streamlit as st

    from orionbelt_ontology_builder import app

    ont = st.session_state.ontology
    app.render_view_annotations(
        ont,
        [
            {
                "name": c["name"],
                "uri": c["uri"],
                "label": c.get("label"),
                "type": "Class",
                "display": c["name"],
            }
            for c in ont.get_classes()
        ],
        ont.get_classes(),
        ont.get_object_properties(),
        ont.get_data_properties(),
        ont.get_individuals(),
    )


def test_the_view_tab_offers_to_move_a_stray_onto_the_resource():
    """Reading by URI means those annotations are no longer listed, so the tab
    has to say where they went or they are invisible as well as unreachable."""
    at = _run(_view_script, _om_with_stray())
    assert at.selectbox(key="view_annotations_select").value == "Account [Class]"
    assert BASE + "Account" in at.warning[0].value

    at.button(key=f"adopt_ann_{app._uid(ACCOUNT)}").click().run(timeout=120)
    assert not at.exception, at.exception

    ont = at.session_state["ontology"]
    assert [a["value"] for a in ont.get_annotations(ACCOUNT)] == ["an account"]
    assert not at.warning


def test_the_row_delete_reaches_an_annotation_on_an_imported_resource():
    """The other half of the bug: the row deleted by local name, so a listed
    annotation on an imported resource could not be removed from here."""
    om = _om()
    om.add_annotation(ACCOUNT, "comment", "an account")
    at = _run(_view_script, om)
    assert not at.warning  # nothing misplaced to report

    at.button(key=f"del_ann_{app._uid(ACCOUNT)}_0").click().run(timeout=120)
    assert not at.exception, at.exception
    assert at.session_state["ontology"].get_annotations(ACCOUNT) == []


# --- the bulk editor --------------------------------------------------------


def _frame(rows):
    return pd.DataFrame(rows, columns=["Resource", "Predicate", "Value", "Action"])


def test_a_bulk_row_is_applied_to_the_uri_it_was_listed_from():
    updates, ambiguous = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": "Account",
                    "Predicate": "comment",
                    "Value": "v",
                    "Action": "add",
                }
            ]
        ),
        {"Account": {ACCOUNT}},
    )
    assert ambiguous == []
    assert updates[0]["resource"] == ACCOUNT


def test_a_bulk_row_for_a_name_two_resources_answer_to_is_refused():
    updates, ambiguous = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": "Account",
                    "Predicate": "comment",
                    "Value": "v",
                    "Action": "add",
                }
            ]
        ),
        {"Account": {ACCOUNT, BASE + "Account"}},
    )
    assert updates == []
    assert ambiguous == ["Account"]


def test_a_hand_written_bulk_row_is_passed_through_as_typed():
    updates, _ = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": "Newcomer",
                    "Predicate": "comment",
                    "Value": "v",
                    "Action": "add",
                }
            ]
        ),
        {"Account": {ACCOUNT}},
    )
    assert updates[0]["resource"] == "Newcomer"


def test_rows_left_on_keep_are_not_applied():
    updates, ambiguous = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": "Account",
                    "Predicate": "comment",
                    "Value": "v",
                    "Action": "keep",
                }
            ]
        ),
        {"Account": {ACCOUNT}},
    )
    assert (updates, ambiguous) == ([], [])


def test_a_cell_the_user_never_touched_does_not_abort_the_batch():
    """The engine strips the language tag before its per-row guard, so a NaN
    from an untouched cell used to take the whole batch down with it."""
    frame = pd.DataFrame(
        [
            {
                "Resource": "Account",
                "Predicate": "comment",
                "Value": "v",
                "Language": None,
                "Action": "add",
            }
        ]
    )
    updates, _ = app.bulk_annotation_updates(frame, {"Account": {ACCOUNT}})
    assert updates[0]["lang"] == ""

    result = _om().bulk_update_annotations(updates)
    assert result["applied"] == 1


@pytest.mark.parametrize(
    ("action", "value", "expected"),
    [
        ("delete", "an account", []),
        ("add", "and another", ["an account", "and another"]),
    ],
)
def test_a_bulk_round_trip_reaches_an_imported_resource(action, value, expected):
    m = _om()
    m.add_annotation(ACCOUNT, "comment", "an account")
    updates, _ = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": "Account",
                    "Predicate": "rdfs:comment",
                    "Value": value,
                    "Action": action,
                }
            ]
        ),
        {"Account": {ACCOUNT}},
    )
    result = m.bulk_update_annotations(updates)
    assert result["applied"] == 1
    assert not result["errors"]
    assert sorted(a["value"] for a in m.get_annotations(ACCOUNT)) == expected


# --- picking between two resources of the same local name -------------------


def _om_with_namesakes():
    """Two classes called Account: one imported, one this ontology's own."""
    m = _om()
    m.add_class("Account")
    return m


def test_two_resources_of_one_local_name_get_an_option_each():
    """They rendered identically, so the second could not be picked at all: the
    Add form resolved by position and the View list by first match, and both
    landed on the first of the two."""
    options, lookup = app.annotation_resource_options(_resources(_om_with_namesakes()))
    assert len(set(options)) == len(options)

    picked = {lookup[o]["uri"] for o in options if o.startswith("Account")}
    assert picked == {ACCOUNT, BASE + "Account"}
    # Tagged with what tells them apart, as the sidebar search already does.
    # The bound prefix ("Account (gist)") needs the session's ontology to
    # resolve it, so outside an app run this is the namespace it falls back to.
    assert any(GIST in o for o in options)


def test_a_local_name_only_one_resource_answers_to_is_left_plain():
    options, _ = app.annotation_resource_options(_resources(_om()))
    assert "Invoice [Class]" in options


def test_the_add_form_annotates_the_namesake_that_was_chosen():
    at = _run(_add_script, _om_with_namesakes())
    option = next(
        o
        for o in at.selectbox(key="ann_resource").options
        if o.strip().startswith("Account (gist)")
    )
    _add(at, option.strip(), "the imported one")

    ont = at.session_state["ontology"]
    assert [a["value"] for a in ont.get_annotations(ACCOUNT)] == ["the imported one"]
    assert ont.get_annotations(BASE + "Account") == []


def test_the_view_tab_lists_the_namesake_that_was_chosen():
    om = _om_with_namesakes()
    om.add_annotation(ACCOUNT, "comment", "the imported one")
    om.add_annotation(BASE + "Account", "comment", "the local one")
    at = _run(_view_script, om)

    picker = at.selectbox(key="view_annotations_select")
    option = next(
        o for o in picker.options if o.strip().startswith("Account (gist)")
    ).strip()
    picker.set_value(option).run(timeout=120)
    assert not at.exception, at.exception

    shown = " ".join(m.value for m in at.markdown)
    assert "the imported one" in shown
    assert "the local one" not in shown


# --- resources whose URI is not http ----------------------------------------

URN_ACCOUNT = "urn:example:Account"


def test_a_uri_of_any_scheme_is_left_as_it_is():
    """``_uri`` only passed ``http(s)`` through, so every other scheme was read
    as a local name and placed in the base namespace."""
    m = _om()
    assert str(m._uri(URN_ACCOUNT)) == URN_ACCOUNT
    assert str(m._uri("did:example:123")) == "did:example:123"
    assert str(m._uri("file:///tmp/o.ttl")) == "file:///tmp/o.ttl"
    # A name is still a name: no colon can appear in one, so the two never meet.
    assert str(m._uri("Account")) == BASE + "Account"
    assert str(m._uri("Account", namespace=GIST)) == ACCOUNT


def _om_with_urn_class():
    m = _om()
    m.graph.add((URIRef(URN_ACCOUNT), RDF.type, OWL.Class))
    return m


def test_a_urn_resource_is_annotated_read_and_deleted_as_itself():
    m = _om_with_urn_class()
    m.add_annotation(URN_ACCOUNT, "comment", "an account")

    assert [str(s) for s, _p, o in m.graph if str(o) == "an account"] == [URN_ACCOUNT]
    assert [a["value"] for a in m.get_annotations(URN_ACCOUNT)] == ["an account"]
    m.delete_annotation(URN_ACCOUNT, "comment", "an account")
    assert m.get_annotations(URN_ACCOUNT) == []


def test_a_urn_resources_annotation_survives_a_round_trip_through_turtle():
    """Read back through a plain graph, not through the manager: asking the
    manager was what hid this, since reading minted the same wrong subject as
    writing. Only the exported triples say where the annotation really went."""
    m = _om_with_urn_class()
    m.add_annotation(URN_ACCOUNT, "comment", "an account")

    exported = Graph().parse(data=m.graph.serialize(format="turtle"), format="turtle")
    assert (URIRef(URN_ACCOUNT), URIRef(COMMENT), Literal("an account")) in exported


def test_the_add_form_annotates_a_urn_resource_as_itself():
    at = _run(_add_script, _om_with_urn_class())
    option = next(
        o for o in at.selectbox(key="ann_resource").options if URN_ACCOUNT in o
    ).strip()
    _add(at, option, "an account")

    # Against the graph, for the reason the turtle test gives.
    ont = at.session_state["ontology"]
    assert (URIRef(URN_ACCOUNT), URIRef(COMMENT), Literal("an account")) in ont.graph


def test_a_bulk_row_reaches_a_urn_resource():
    m = _om_with_urn_class()
    updates, ambiguous = app.bulk_annotation_updates(
        _frame(
            [
                {
                    "Resource": URN_ACCOUNT,
                    "Predicate": "rdfs:comment",
                    "Value": "an account",
                    "Action": "add",
                }
            ]
        ),
        {URN_ACCOUNT: {URN_ACCOUNT}},
    )
    assert ambiguous == []
    assert m.bulk_update_annotations(updates)["applied"] == 1
    assert (URIRef(URN_ACCOUNT), URIRef(COMMENT), Literal("an account")) in m.graph


def test_what_the_old_behaviour_wrote_for_a_urn_resource_can_be_adopted():
    """The wrong subject was the base namespace plus the whole URN, which is
    exactly where the repair looks."""
    m = _om_with_urn_class()
    m.graph.add(
        (URIRef(BASE + URN_ACCOUNT), URIRef(COMMENT), Literal("an account")),
    )
    assert m.stray_annotation_subject(URN_ACCOUNT) == BASE + URN_ACCOUNT
    assert m.adopt_stray_annotations(URN_ACCOUNT) == 1
    assert [a["value"] for a in m.get_annotations(URN_ACCOUNT)] == ["an account"]

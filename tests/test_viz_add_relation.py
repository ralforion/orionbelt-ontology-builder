"""Adding a class relation by clicking its two ends on the graph (issue #221).

Pressing "Add relation" fixes the selected class as the subject and waits for the
next class click to be the object. Everything hinges on what an armed click
means, which is the one piece that is not Streamlit wiring: read it wrongly and
the app either asserts a triple nobody meant or throws away a half-built one.
"""

from orionbelt_ontology_builder.app import resolve_picked_object

SUBJECT = "aaaaaaaaaaaa"
OTHER = "bbbbbbbbbbbb"


def test_clicking_another_class_is_the_object():
    assert resolve_picked_object(SUBJECT, "Class", OTHER) == ("pick", OTHER)


def test_the_subject_stays_selected_and_does_not_pair_with_itself():
    """The subject is still selected the moment the pick is armed.

    Reading that as the object would assert a relation from a class to itself
    before the user has clicked anything at all.
    """
    assert resolve_picked_object(SUBJECT, "Class", SUBJECT) == ("wait", None)


def test_losing_the_selection_cancels():
    """Clicking empty canvas clears the selection, and so does clicking the
    subject again, which is the gesture people reach for to undo a click."""
    assert resolve_picked_object(SUBJECT, None, None) == ("cancel", None)
    assert resolve_picked_object(SUBJECT, "Class", "") == ("cancel", None)


def test_clicking_a_non_class_keeps_waiting():
    """A misclick on a property must not throw the pairing away.

    Only a class can be the object of a class relation, so these are ignored
    rather than treated as either a pick or a cancel.
    """
    for ntype in ("Data Property", "Individual", "SKOS Concept", "Object Property"):
        assert resolve_picked_object(SUBJECT, ntype, OTHER) == ("wait", None), ntype


def test_clicking_an_edge_keeps_waiting():
    """Relations and restrictions are edges; neither can be an endpoint."""
    assert resolve_picked_object(SUBJECT, "Class Relation", "x|y|z") == ("wait", None)
    assert resolve_picked_object(SUBJECT, "Restriction", "w|x|y|z") == ("wait", None)

"""Required dropdowns can be cleared, and say so when they are.

Clearing one was already possible by selecting its text and deleting it, but
there was no cross to do it with and clearing achieved nothing useful: the value
fell back to whatever had been selected before, so the write landed on an entity
the user had explicitly cleared, with neither an error nor a confirmation.

The two halves have to stay together. A dropdown that can be cleared but is not
checked writes the wrong thing; one that is checked but cannot be cleared just
never fires. The last test here fails if they come apart.
"""

import ast
import pathlib

import pytest

from orionbelt_ontology_builder.app import missing_required

APP = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder/app.py"


# --- the message ------------------------------------------------------------


def test_nothing_missing_reads_as_none():
    assert missing_required(Subject="a", Object="b") is None


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_empty_field_is_named(empty):
    """Named, because a form has several and "something is required" sends the
    user hunting for which."""
    assert missing_required(Subject="a", Object=empty) == "Object is required."


def test_the_first_empty_field_is_the_one_reported():
    assert missing_required(Subject=None, Object=None) == "Subject is required."


def test_a_label_with_spaces_survives():
    assert (
        missing_required(**{"Applies to Class": None})
        == "Applies to Class is required."
    )


# --- the two halves stay together -------------------------------------------


def _functions_calling(name):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                return node.name
        return "<module>"

    return {
        enclosing(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    }


def test_every_form_with_a_clearable_dropdown_checks_it():
    """A cleared field must be reported, not written past.

    Both are function-scoped, so a form that grows a clearable dropdown without
    a check — or loses its check — shows up here rather than in someone's
    ontology.
    """
    clearable = _functions_calling("required_selectbox")
    checked = _functions_calling("missing_required")
    assert clearable, "no form uses required_selectbox"
    unchecked = clearable - checked
    assert not unchecked, (
        f"these forms offer a clearable dropdown but never check it: {sorted(unchecked)}"
    )


def test_no_form_checks_without_offering_one():
    """The mirror: a check with nothing clearable can never fire, which reads
    as protection that is not there."""
    clearable = _functions_calling("required_selectbox")
    checked = _functions_calling("missing_required")
    assert not (checked - clearable), sorted(checked - clearable)


# --- nothing new slips back to a plain dropdown -----------------------------

# The dropdowns the rule below cannot read off the call itself, because their
# options were built a line earlier and passed by name: three fixed sets from
# the engine (the restriction types, the relation types) and one "All" filter.
ALLOWED_BY_NAME = {
    ("render_restriction_form", "Restriction Type"),
    ("_render_panel_add_restriction_form", "Restriction Type"),
    ("render_relation_form", "Relation"),
    ("render_annotations", "Filter by Type"),
}


def _plain_selectboxes():
    """Every ``st.selectbox`` left in the app, as (function, label, node)."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef):
                return node.name
        return "<module>"

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "selectbox" or not node.args:
            continue
        label = node.args[0]
        label = label.value if isinstance(label, ast.Constant) else None
        yield enclosing(node), label, node


def _options_of(node):
    if len(node.args) > 1:
        return node.args[1]
    return next((k.value for k in node.keywords if k.arg == "options"), None)


def _is_exempt(func, label, node):
    """A plain dropdown is fine when clearing it would mean nothing.

    Three shapes qualify: it already passes ``index=None`` (so it draws the
    cross itself), its options carry an explicit "All" (empty already has a
    name), or its options are a fixed enum — a list literal, or one built
    straight from an engine constant.
    """
    if func == "clearable_selectbox":
        return True
    if any(k.arg == "index" and _is_none(k.value) for k in node.keywords):
        return True
    options = _options_of(node)
    if options is None:
        return True
    if any(isinstance(c, ast.Constant) and c.value == "All" for c in ast.walk(options)):
        return True
    if isinstance(options, (ast.List, ast.Tuple)):
        return True
    if isinstance(options, ast.Call) and isinstance(options.func, ast.Name):
        return options.func.id in ("list", "sorted")
    return (func, label) in ALLOWED_BY_NAME


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None


def test_no_dropdown_worth_clearing_is_left_plain():
    """Every picker of an entity, a namespace or a datatype offers the cross.

    Written as a rule rather than a list of labels so a new form is covered the
    day it is added: only a fixed enum, an "All"-style filter or a dropdown that
    is already clearable may stay a plain ``st.selectbox``.
    """
    offenders = [
        f"app.py:{node.lineno} {func}() {label!r}"
        for func, label, node in _plain_selectboxes()
        if not _is_exempt(func, label, node)
    ]
    assert not offenders, (
        "these dropdowns hold a value worth clearing but offer no way to:\n  "
        + "\n  ".join(sorted(offenders))
    )


# --- seeding ----------------------------------------------------------------


def _seed(monkeypatch, key, options, current_display):
    """Run the helper's seeding with a stubbed selectbox, returning what it
    would have rendered with."""
    import streamlit as st

    from orionbelt_ontology_builder import app

    seen = {}

    def fake_selectbox(label, opts, index=None, key=None, **kwargs):
        seen["value"] = st.session_state.get(key)
        return seen["value"]

    monkeypatch.setattr(app.st, "selectbox", fake_selectbox)
    app.clearable_selectbox("L", options, key=key, current_display=current_display)
    return seen["value"]


def test_a_clear_survives_the_next_render(monkeypatch):
    """Re-seeding on every run would undo the clear the moment it happened."""
    import streamlit as st

    st.session_state.clear()
    assert _seed(monkeypatch, "k", ["a", "b"], "a") == "a"
    st.session_state["k"] = None  # the user clears it
    assert _seed(monkeypatch, "k", ["a", "b"], "a") is None


def test_the_value_comes_back_after_the_widget_is_dropped(monkeypatch):
    """Streamlit discards the state of a widget that wasn't rendered on a run,
    so leaving the page and returning must re-seed rather than show empty."""
    import streamlit as st

    st.session_state.clear()
    assert _seed(monkeypatch, "k", ["a", "b"], "a") == "a"
    del st.session_state["k"]  # what Streamlit does while the page is away
    assert _seed(monkeypatch, "k", ["a", "b"], "a") == "a"


def test_a_changed_row_underneath_reseeds(monkeypatch):
    """Seeding only on first sight would leave the previous row's value on
    screen when the editor is reopened for another row."""
    import streamlit as st

    st.session_state.clear()
    assert _seed(monkeypatch, "k", ["a", "b"], "a") == "a"
    assert _seed(monkeypatch, "k", ["a", "b"], "b") == "b"

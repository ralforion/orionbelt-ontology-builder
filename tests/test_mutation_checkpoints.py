"""Every graph mutation must checkpoint (issue #190 investigation).

``save_checkpoint()`` is the only place ``_ont_mutation_count`` is bumped, and
three things hang off that revision:

* the undo history,
* the Visualization's cache key, so the canvas redraws,
* both autosave backends, which skip the write when the revision hasn't moved.

So a mutation that forgets it is not merely un-undoable: it leaves the graph on
screen stale and is never written to disk or localStorage, surviving only in
memory until some later checkpointed action sweeps it up. Six call sites did
exactly that (imports, property chains, disjoint unions, AllDifferent, hasKey).

The check is scope-aware rather than a line window: it asks whether the handler
that performed the mutation goes on to move the revision, searching the
statements after the call in its own block and then widening to each enclosing
block up to the function. A line window was tried first and was wrong in both
directions — it missed a checkpoint 42 lines below a rename, and exempting such
false positives by method name blanket-exempted every other call site of that
same method (review P3).
"""

import ast
import inspect
import pathlib

from orionbelt_ontology_builder.ontology_manager import OntologyManager

PKG = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder"
# The UI modules, found by the import rather than named: app.py was split, and a
# check that reads one file would quietly stop covering whatever moved out of it
# while still passing. The engine is excluded because checkpointing is the UI's
# job — OntologyManager's own methods call each other freely.
SOURCES = sorted(
    p for p in PKG.rglob("*.py") if "import streamlit" in p.read_text(encoding="utf-8")
)

# The only calls exempt from carrying their own bump, keyed by the function they
# sit in: these helpers apply an edit on behalf of a page that checkpoints around
# the call. Scoped to the enclosing function, so another call site of the same
# engine method is still checked.
CHECKPOINTED_BY_CALLER = {
    "_apply_class_edit",
    "_apply_property_edit",
    "_apply_individual_edit",
    # Rewrites an annotation as a delete plus an add, and puts the original back
    # when the add is rejected. The panel checkpoints on the True return; the
    # rollback path returns False having restored the graph, so there is nothing
    # to checkpoint there either (issue #223).
    "_apply_annotation_edit",
    # Hands its write to render_add_class_form as the ``after_add`` callback,
    # which that function calls immediately before its own save_checkpoint — on
    # purpose, so creating a superclass and hanging the selected class under it
    # is one entry in the undo history rather than two (issue #327).
    "_render_panel_add_superclass_form",
    # Both hand their delete to _panel_delete_edge as a callback, and that is
    # where the checkpoint sits — the axiom has no URI, so the panel resolves it
    # and the shared helper confirms, deletes and checkpoints (issue #222).
    "_render_panel_relation_editor",
    "_render_panel_restriction_editor",
}

# Either of these moves the revision: the checkpoint helper, or a direct bump
# where the whole graph is replaced and there is no prior state to snapshot.
BUMP_MARKERS = ("save_checkpoint", "_ont_mutation_count")


def _mutating_methods() -> set:
    prefixes = (
        "add_",
        "remove_",
        "delete_",
        "update_",
        "set_",
        "rename_",
        "link_",
        "bulk_",
        "merge",
        "load_",
        "clear",
        "import_",
        "apply_",
        "create_",
    )
    names = {
        name
        for name, fn in inspect.getmembers(OntologyManager, inspect.isfunction)
        if not name.startswith("_") and name.startswith(prefixes)
    }
    return {n for n in names if not n.startswith(("get_", "export_"))}


def _bumps_revision(node: ast.AST) -> bool:
    """Whether this statement contains a checkpoint or a direct revision bump."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if isinstance(func, ast.Name) and func.id in BUMP_MARKERS:
                return True
            if isinstance(func, ast.Attribute) and func.attr in BUMP_MARKERS:
                return True
        if (
            isinstance(inner, ast.Subscript)
            and isinstance(inner.slice, ast.Constant)
            and inner.slice.value == "_ont_mutation_count"
        ):
            return True
    return False


def _parents(tree: ast.AST) -> dict:
    return {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }


def _handler_bumps(call: ast.Call, parents: dict) -> bool:
    """True when the mutation's own handler goes on to move the revision.

    Walks out from the call: in each enclosing block the statements that follow
    the one holding the call are searched, then the search widens to the block
    around it, stopping at the function containing it all.
    """
    node: ast.AST = call
    while node in parents:
        parent = parents[node]
        # At the function's own body the search goes shallow: a page function
        # holds many independent handlers, so only a bump written directly in
        # the flow counts. A checkpoint nested inside a *different* handler's
        # branch must not vouch for this mutation.
        shallow = isinstance(parent, ast.FunctionDef)
        for field in ("body", "orelse", "finalbody"):
            block = getattr(parent, field, None)
            if not isinstance(block, list) or node not in block:
                continue
            for statement in block[block.index(node) :]:
                if shallow and not isinstance(statement, (ast.Expr, ast.Assign)):
                    continue
                if _bumps_revision(statement):
                    return True
        if shallow:
            return False
        node = parent
    return False


def _enclosing_function(node: ast.AST, parents: dict) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.FunctionDef):
            return node.name
    return "<module>"


def test_every_mutation_site_moves_the_revision():
    """Fails with the file and line of any mutation whose handler doesn't."""
    mutators = _mutating_methods()

    offenders = []
    for source in SOURCES:
        tree = ast.parse(source.read_text())
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr not in mutators:
                continue
            if _enclosing_function(node, parents) in CHECKPOINTED_BY_CALLER:
                continue
            if not _handler_bumps(node, parents):
                offenders.append(f"{source.name}:{node.lineno} {node.func.attr}()")

    assert not offenders, (
        "these mutations never move _ont_mutation_count, so they cannot be "
        "undone, leave the Visualization stale and are never autosaved:\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_save_checkpoint_moves_the_revision():
    """Why the invariant above matters: the revision is the single signal the
    undo history, the graph cache and both autosave backends key off."""
    import streamlit as st

    from orionbelt_ontology_builder import app

    st.session_state.clear()
    st.session_state["_ont_mutation_count"] = 7
    app.save_checkpoint("Add has key")
    assert st.session_state["_ont_mutation_count"] == 8

"""Every graph mutation must checkpoint (issue #190 investigation).

``save_checkpoint()`` is the only place ``_ont_mutation_count`` is bumped, and
three things hang off that counter:

* the undo history,
* the Visualization's cache key, so the canvas redraws,
* both autosave backends, which skip the write when the revision hasn't moved.

So a mutation that forgets it is not merely un-undoable: it leaves the graph on
screen stale and is never written to disk or localStorage, surviving only in
memory until some later checkpointed action sweeps it up. Six call sites did
exactly that (imports, property chains, disjoint unions, AllDifferent, hasKey).
"""

import ast
import inspect
import pathlib

from orionbelt_ontology_builder.ontology_manager import OntologyManager

APP = pathlib.Path(__file__).resolve().parents[1] / "orionbelt_ontology_builder/app.py"

# Mutating calls whose bump happens elsewhere, with the reason it is correct:
ALLOWED_WITHOUT_CHECKPOINT = {
    # Replacing the whole graph bumps _ont_mutation_count directly, because
    # there is no prior state worth a checkpoint (restore, import, New).
    "load_from_file",
    "load_from_string",
    "set_ontology_metadata",
    # Applied inside helpers that the page checkpoints around.
    "update_class",
    "update_property",
    "update_individual",
    "rename_property",
    "rename_individual",
    "rename_concept",
}


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


def test_every_mutation_site_checkpoints():
    """Fails with the file and line of any new mutation that skips the bump."""
    source = APP.read_text()
    lines = source.split("\n")
    mutators = _mutating_methods()

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name not in mutators or name in ALLOWED_WITHOUT_CHECKPOINT:
            continue
        # The checkpoint follows the call in the same handler; a generous window
        # keeps this from tripping on formatting.
        window = "\n".join(lines[max(0, node.lineno - 6) : node.lineno + 25])
        if "save_checkpoint(" not in window:
            offenders.append(f"app.py:{node.lineno} {name}()")

    assert not offenders, (
        "these mutations never bump _ont_mutation_count, so they cannot be "
        "undone, leave the Visualization stale and are never autosaved:\n  "
        + "\n  ".join(offenders)
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

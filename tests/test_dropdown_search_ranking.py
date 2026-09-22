"""Dropdown search ranks the entity you typed first.

The entity pickers are ``case_picker`` components, whose search runs in the
browser (``lib/case_picker/case_picker.js``); these are the scenarios that went
wrong over the years in Streamlit's own dropdowns, run against that search:
a longer fuzzy match or a camelCase compound ranked above the exact name
(issue #210), a longer label cost an option its place (#214, #461), a query in
another case found nothing useful (#244), and ``fn`` / ``FN`` could not be told
apart at all (#466, #468). ``test_case_picker.py`` covers the search itself.

What the app still decides is the order it supplies, which settles every tie
the search leaves: ``option_sort_key``, guarded below.
"""

import ast

import sources
from case_pickers import rank_in_component

from orionbelt_ontology_builder import app


def _options(*items: tuple[str, str]) -> list[str]:
    """Dropdown options for (name, label) pairs, ordered as the app orders them."""
    return sorted(
        (app.format_label_name(name, label) for name, label in items),
        key=app.option_sort_key,
    )


def test_exact_name_outranks_longer_fuzzy_match():
    """The scenario from issue #210."""
    exact = app.format_label_name("trans-fn", "transcendental function")
    options = _options(
        ("trans-fn", "transcendental function"),
        ("transfer-fn", "transfer function"),
    )
    assert rank_in_component(options, "trans-fn")[0] == exact


def test_exact_name_outranks_camelcase_compound():
    """The pizza.owl case, where 'HamTopping' ranked 'ParmaHamTopping' first."""
    exact = app.format_label_name("HamTopping", "CoberturaDePresunto")
    options = _options(
        ("HamTopping", "CoberturaDePresunto"),
        ("ParmaHamTopping", "CoberturaDePrezuntoParma"),
    )
    assert rank_in_component(options, "HamTopping")[0] == exact


def test_exact_name_outranks_longer_name_sharing_a_prefix():
    exact = app.format_label_name("OnionTopping", "CoberturaDeCebola")
    options = _options(
        ("OnionTopping", "CoberturaDeCebola"),
        ("RedOnionTopping", "CoberturaDeCebolaVermelha"),
        ("SlicedOnionTopping", "CoberturaDeCebolaFatiada"),
    )
    assert rank_in_component(options, "OnionTopping")[0] == exact


def test_label_search_ranks_its_own_entity_first():
    wanted = app.format_label_name("PriceSpecification", "Price specification")
    options = _options(
        ("PriceSpecification", "Price specification"),
        ("UnitPriceSpecification", "Unit price specification"),
    )
    assert rank_in_component(options, "Price specification")[0] == wanted


def test_unlabelled_name_outranks_names_containing_it():
    options = _options(("Person", ""), ("PersonAddress", ""), ("LegalPerson", ""))
    assert rank_in_component(options, "Person") == [
        "Person",
        "PersonAddress",
        "LegalPerson",
    ]


def test_a_query_in_another_case_still_finds_its_entity():
    """The scenario from issue #244: ``py-trip`` ranked ``Py-trig-id`` first."""
    wanted = app.format_label_name("Py-trip", "Pythagorean triple")
    options = _options(
        ("Py-trig-id", "Pythagorean trigonometric identity"),
        ("Py-trip", "Pythagorean triple"),
    )
    assert options[0] != wanted  # the supplied order alone gets it wrong
    for query in ("py-trip", "Py-trip", "PY-TRIP", "pytrip"):
        assert rank_in_component(options, query)[0] == wanted, query


def test_names_differing_only_in_case_rank_by_the_case_typed():
    """Issues #466 and #468: the order is fixed whichever order the graph
    listed them in, and the case typed decides which comes first."""
    for supplied in (["FN", "fn"], ["fn", "FN"]):
        items = [{"name": n, "uri": f"http://ex.org/{n}"} for n in supplied]
        options, _lookup = app.build_uri_options(items)
        assert options == ["fn", "FN"]
        assert rank_in_component(options, "fn") == ["fn", "FN"]
        assert rank_in_component(options, "FN") == ["FN", "fn"]
        assert rank_in_component(options, "Fn") == ["fn", "FN"]


def test_option_sort_key_orders_case_variants_lowercase_first():
    names = ["FN", "Fn", "fn", "fN", "Apple", "apple", "b"]
    assert sorted(names, key=app.option_sort_key) == [
        "apple",
        "Apple",
        "b",
        "fn",
        "fN",
        "Fn",
        "FN",
    ]


def test_short_labelled_name_outranks_longer_bare_name():
    """The scenario from issue #214: ``node`` ranked above ``n · number``."""
    short = app.format_label_name("n", "number")
    options = _options(("n", "number"), ("node", "node"))
    assert rank_in_component(options, "n")[0] == short


def test_graph_picker_caption_ranks_the_typed_name_first():
    """The scenario from issue #461: ``vl · value`` above ``va · variable``."""
    wanted = app.picker_option_caption("Class: va", "va", "variable")
    shorter = app.picker_option_caption("Class: vl", "vl", "value")
    options = sorted([wanted, shorter], key=app.option_sort_key)
    assert rank_in_component(options, "va")[0] == wanted


def test_short_name_outranks_longer_one_sharing_its_prefix():
    """The wine.owl case #210 had to leave mis-ranked."""
    options = _options(("Wine", ""), ("Winery", "Wine estate"))
    assert rank_in_component(options, "Wine")[0] == "Wine"


def _sorts_by_option_key(node: ast.expr) -> bool:
    """Whether ``node`` is ``sorted(...)`` keyed through ``option_sort_key``.

    The key may be the function itself or a lambda that calls it on a field.
    """
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sorted"
    ):
        return False
    key = next((k.value for k in node.keywords if k.arg == "key"), None)
    return key is not None and any(
        isinstance(n, ast.Name) and n.id == "option_sort_key" for n in ast.walk(key)
    )


def test_graph_pickers_order_case_variants_lowercase_first():
    """Every Visualization picker lists its options through option_sort_key.

    Issue #469: #467 sorted the Find and path pickers but not Node options,
    whose entities kept the engine's codepoint order (``FN`` before ``fn``).
    Options are sorted inline, held in a local that was, or (the node filter)
    drawn from filter entries that are sorted where they are built, which is
    also the order the filter's selected chips are rebuilt in.
    """
    tree = ast.parse((sources.PKG / "views" / "visualization.py").read_text("utf-8"))
    sorted_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _sorts_by_option_key(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    entry_builds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_filter_entries"
    ]
    assert entry_builds, "the node filter no longer builds its entries here"
    wrapped = {
        id(arg)
        for node in ast.walk(tree)
        if _sorts_by_option_key(node)
        for arg in node.args
    }
    for build in entry_builds:
        assert id(build) in wrapped, f"line {build.lineno}: filter entries unsorted"

    pickers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        if node.func.attr in ("selectbox", "multiselect")
    ]
    # The case-aware pickers (issue #468) keep the supplied order among equal
    # matches, so they need the same sort; their options are the second
    # argument.
    case_pickers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        if node.func.id in ("case_selectbox", "case_multiselect")
    ]
    assert pickers or case_pickers, "the page draws no picker at all"
    for picker in pickers + case_pickers:
        options = (
            picker.args[1]
            if picker in case_pickers
            else next(k.value for k in picker.keywords if k.arg == "options")
        )
        from_entries = (
            isinstance(options, ast.Subscript)
            and isinstance(options.slice, ast.Constant)
            and options.slice.value == "displays"
        )
        assert (
            _sorts_by_option_key(options)
            or from_entries
            or (isinstance(options, ast.Name) and options.id in sorted_names)
        ), f"picker on line {picker.lineno} skips option_sort_key"


def _entity_dropdowns_left_to_streamlit() -> list[tuple[int, str]]:
    """Streamlit selectboxes and multiselects fed by the option builders.

    Streamlit ranks a search without regard to the case typed, so an entity
    listed through one of them keeps issue #468 however its options are
    ordered; entity pickers go through ``case_picker``.
    """
    builders = {"build_uri_options", "build_class_options", "_slot_options"}
    missing = []

    def option_targets(node: ast.Assign) -> set[str]:
        """Names bound to the options half of an ``(options, lookup)`` pair."""
        names = set()
        for target in node.targets:
            elements = target.elts if isinstance(target, ast.Tuple) else [target]
            # The builders return (options, lookup); only the first carries what
            # the dropdown renders.
            if elements and isinstance(elements[0], ast.Name):
                names.add(elements[0].id)
        return names

    # Scope-by-scope: the same local name means different things in different
    # functions (``prop_options`` is builder output in one and a list of bare
    # names in another), so a module-wide name set would flag the wrong calls.
    # Every UI module, not app.py alone: the dropdowns this guards live in
    # ui.py and the page modules since the split, and a scan of one file would
    # pass while the rest went unchecked (PR #262 review).
    scopes = [
        (source.name, scope)
        for source in sources.ui_sources()
        for scope in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(scope, ast.FunctionDef)
    ]
    for _module, scope in scopes:
        body = [n for stmt in scope.body for n in ast.walk(stmt)]

        option_vars: set[str] = set()
        for node in body:
            if not isinstance(node, ast.Assign):
                continue
            calls = [n for n in ast.walk(node.value) if isinstance(n, ast.Call)]
            called = {c.func.id for c in calls if isinstance(c.func, ast.Name)}
            if called & builders:
                option_vars |= option_targets(node)
        # One more hop for plain copies (``row_options = list(options)``). Calls
        # on an object are excluded, so a widget's *return* value never counts.
        for node in body:
            if not isinstance(node, ast.Assign):
                continue
            calls = [n for n in ast.walk(node.value) if isinstance(n, ast.Call)]
            if any(isinstance(c.func, ast.Attribute) for c in calls):
                continue
            names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            if names & option_vars:
                option_vars |= option_targets(node)

        for node in body:
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in ("selectbox", "multiselect"):
                continue
            referenced = {
                n.id
                for arg in [*node.args, *(k.value for k in node.keywords)]
                for n in ast.walk(arg)
                if isinstance(n, ast.Name)
            }
            if not referenced & option_vars:
                continue
            first = node.args[0] if node.args else None
            label = first.value if isinstance(first, ast.Constant) else "?"
            missing.append((node.lineno, str(label)))
    return sorted(missing)


def test_no_entity_dropdown_is_left_to_streamlit():
    assert _entity_dropdowns_left_to_streamlit() == []

"""Dropdown search ranks the entity you typed first (issues #210, #214, #461).

Streamlit filters a selectbox client-side: it keeps every option whose label
contains the typed text as a *subsequence*, then sorts by an fzy score. That
scorer is not configurable from Python (it is bundled JS), so the only levers
the app has are the option string it emits and the label ``format_func`` renders.

Two properties of the scorer drive the format:

* It scores a match partly by the character *preceding* it: 0.9 after ``/``, 0.8
  after a space / ``-`` / ``_``, 0.7 for a camelCase hump, and 0.0 after ``(``.
  The old ``'Label (name)'`` format gave the local name no boundary bonus at all,
  and an unrelated camelCase compound could outscore an exact match: searching
  ``HamTopping`` in pizza.owl ranked ``ParmaHamTopping`` first (issue #210). The
  name now leads, behind a separator that ends in a space.
* It subtracts 0.005 for every character *after* the last match, so a longer
  option scores lower purely for being longer. Searching ``n`` ranked ``node``
  above ``n · number`` (issue #214). :func:`app._pad_option` pads every option to
  one width through ``format_func``, which makes that penalty identical for all
  of them; equal scores then keep the order the app supplied.

``_score`` / ``_has_match`` below are a direct port of the scorer bundled with
the pinned Streamlit (1.63), so these tests fail if either lever stops ranking
the typed entity first. Both filtering and scoring ignore case; only the bonuses
read the label's own capitalisation. Streamlit before 1.51 scored with
``caseSensitive=true``, so a lowercase query for a capitalised name got no
ranking at all and fell back to alphabetical order (issue #244, fixed upstream
in streamlit/streamlit#12849).
"""

import ast

import sources

from orionbelt_ontology_builder import app

# fzy constants, as bundled by Streamlit.
_SCORE_MIN = float("-inf")
_SCORE_MAX = float("inf")
_GAP_LEADING = -0.005
_GAP_TRAILING = -0.005
_GAP_INNER = -0.01
_MATCH_CONSECUTIVE = 1.0
_MATCH_SLASH = 0.9
_MATCH_WORD = 0.8
_MATCH_CAPITAL = 0.7
_MATCH_DOT = 0.6


def _precompute_bonus(haystack: str) -> list[float]:
    """Per-character bonus, derived from the preceding character."""
    bonuses = []
    prev = "/"
    for ch in haystack:
        if prev == "/":
            bonuses.append(_MATCH_SLASH)
        elif prev in "-_ ":
            bonuses.append(_MATCH_WORD)
        elif prev == ".":
            bonuses.append(_MATCH_DOT)
        elif prev.islower() and ch.isupper():
            bonuses.append(_MATCH_CAPITAL)
        else:
            bonuses.append(0.0)
        prev = ch
    return bonuses


def _has_match(needle: str, haystack: str) -> bool:
    """Whether ``needle`` appears in ``haystack`` as a subsequence.

    Case-insensitive, like :func:`_score`.
    """
    needle, haystack = needle.lower(), haystack.lower()
    at = 0
    for ch in needle:
        at = haystack.find(ch, at) + 1
        if at == 0:
            return False
    return True


def _score(needle: str, haystack: str) -> float:
    n, m = len(needle), len(haystack)
    if not n or not m:
        return _SCORE_MIN
    # Only filtered options are scored, so one as long as the query is the
    # query up to case, and fzy scores it as a certainty.
    if n == m:
        return _SCORE_MAX
    if m > 1024:
        return _SCORE_MIN

    # Bonuses read the original case (camelCase humps); matching ignores it.
    bonus = _precompute_bonus(haystack)
    needle, haystack = needle.lower(), haystack.lower()
    # best[i][j]: score of a match ending exactly at j; running[i][j]: best so far.
    best = [[_SCORE_MIN] * m for _ in range(n)]
    running = [[_SCORE_MIN] * m for _ in range(n)]

    for i in range(n):
        prev_running = _SCORE_MIN
        gap = _GAP_TRAILING if i == n - 1 else _GAP_INNER
        for j in range(m):
            if needle[i] == haystack[j]:
                if i == 0:
                    score = j * _GAP_LEADING + bonus[j]
                elif j:
                    score = max(
                        running[i - 1][j - 1] + bonus[j],
                        best[i - 1][j - 1] + _MATCH_CONSECUTIVE,
                    )
                else:
                    score = _SCORE_MIN
                best[i][j] = score
                prev_running = max(score, prev_running + gap)
            else:
                best[i][j] = _SCORE_MIN
                prev_running = prev_running + gap
            running[i][j] = prev_running

    return running[n - 1][m - 1]


def _rank(query: str, options: list[str]) -> list[str]:
    """The order Streamlit's selectbox shows for ``query``.

    Scores the rendered label, which is what the widget filters on, so the
    ``format_func`` every entity dropdown passes is part of what is measured.
    ``sorted`` is stable, like the lodash ``sortBy`` Streamlit ranks with, so
    equal scores keep the order the app supplied.
    """
    matches = [o for o in options if _has_match(query, o)]
    return sorted(matches, key=lambda o: -_score(query, app._pad_option(o)))


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
    assert _rank("trans-fn", options)[0] == exact


def test_exact_name_outranks_camelcase_compound():
    """A camelCase hump earns 0.7; the exact match must still win.

    Regression for the pizza.owl case, where 'HamTopping' used to rank
    'ParmaHamTopping' first.
    """
    exact = app.format_label_name("HamTopping", "CoberturaDePresunto")
    options = _options(
        ("HamTopping", "CoberturaDePresunto"),
        ("ParmaHamTopping", "CoberturaDePrezuntoParma"),
    )
    assert _rank("HamTopping", options)[0] == exact


def test_exact_name_outranks_longer_name_sharing_a_prefix():
    exact = app.format_label_name("OnionTopping", "CoberturaDeCebola")
    options = _options(
        ("OnionTopping", "CoberturaDeCebola"),
        ("RedOnionTopping", "CoberturaDeCebolaVermelha"),
        ("SlicedOnionTopping", "CoberturaDeCebolaFatiada"),
    )
    assert _rank("OnionTopping", options)[0] == exact


def test_label_search_still_ranks_its_own_entity_first():
    """Moving the name out of parentheses must not cost label searches."""
    wanted = app.format_label_name("PriceSpecification", "Price specification")
    options = _options(
        ("PriceSpecification", "Price specification"),
        ("UnitPriceSpecification", "Unit price specification"),
    )
    assert _rank("Price specification", options)[0] == wanted


def test_unlabelled_name_is_an_exact_option_match():
    """Without a label the option *is* the name, which fzy scores as a certainty."""
    options = _options(("Person", ""), ("PersonAddress", ""), ("LegalPerson", ""))
    assert _rank("Person", options)[0] == "Person"
    assert _score("Person", "Person") == _SCORE_MAX


def test_query_case_does_not_change_the_ranking():
    """The scenario from issue #244.

    ``py-trip`` ranked ``Py-trig-id`` first: the scorer was case-sensitive, so
    both options scored negative infinity and alphabetical order decided.
    """
    wanted = app.format_label_name("Py-trip", "Pythagorean triple")
    options = _options(
        ("Py-trig-id", "Pythagorean trigonometric identity"),
        ("Py-trip", "Pythagorean triple"),
    )
    assert options[0] != wanted  # alphabetical order alone gets it wrong
    for query in ("py-trip", "Py-trip", "PY-TRIP", "pytrip"):
        assert _rank(query, options)[0] == wanted, query


def test_names_differing_only_in_case_list_lowercase_first():
    """The scenario from issue #466.

    Case-insensitive scoring gives ``fn`` and ``FN`` the same score for any
    query, so the order the app supplies decides. It must be the same every
    time, whichever order the graph listed them in.
    """
    for supplied in (["FN", "fn"], ["fn", "FN"]):
        items = [{"name": n, "uri": f"http://ex.org/{n}"} for n in supplied]
        options, _lookup = app.build_uri_options(items)
        assert options == ["fn", "FN"]
        for query in ("fn", "FN", "Fn"):
            assert _score(query, app._pad_option("fn")) == _score(
                query, app._pad_option("FN")
            )
            assert _rank(query, options) == ["fn", "FN"]


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


def test_separator_gives_the_local_name_a_word_boundary_bonus():
    """Guards the reason for the separator, not just its appearance.

    A separator ending in '(' (the old format) would silently reintroduce
    issue #210, so assert the bonus fzy actually awards.
    """
    display = app.format_label_name("HamTopping", "CoberturaDePresunto")
    name_starts_at = display.index("HamTopping")
    assert _precompute_bonus(display)[name_starts_at] >= _MATCH_WORD


def test_short_labelled_name_outranks_longer_bare_name():
    """The scenario from issue #214.

    Both match at position 0 and earn the same 0.9 bonus; unpadded, 'node' won
    only because 'n · number' is six characters longer.
    """
    short = app.format_label_name("n", "number")
    options = _options(("n", "number"), ("node", "node"))
    assert _rank("n", options)[0] == short
    assert _score("n", "node") > _score("n", short)  # what padding cancels out


def test_graph_picker_caption_ranks_the_typed_name_first():
    """The scenario from issue #461.

    The Visualization pickers render ``Class: <name> · <label>``, so a
    label match and a name match earn the same bonuses and only length
    separated them: ``vl · value`` came out above ``va · variable``
    for the query that names the second one.
    """
    wanted = app.picker_option_caption("Class: va", "va", "variable")
    shorter = app.picker_option_caption("Class: vl", "vl", "value")
    assert _rank("va", sorted([wanted, shorter], key=str.lower))[0] == wanted
    assert _score("va", shorter) > _score("va", wanted)  # what padding cancels out


def test_graph_pickers_pad_their_captions():
    """Every Visualization picker renders through a caption that pads.

    The page builds its own ``format_func`` rather than passing ``_pad_option``
    straight in, so the guard below (which follows the option builders) cannot
    see these call sites: follow the format_func instead.
    """
    tree = ast.parse((sources.PKG / "views" / "visualization.py").read_text("utf-8"))
    locals_by_name = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    captions = {
        keyword.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        if node.func.id in ("case_selectbox", "case_multiselect")
        for keyword in node.keywords
        if keyword.arg == "format_func" and isinstance(keyword.value, ast.Name)
    }
    assert captions, "the page draws no picker at all"
    for name in sorted(captions & set(locals_by_name)):
        called = {
            call.func.id
            for call in ast.walk(locals_by_name[name])
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        assert "_pad_option" in called, f"{name} renders unpadded labels"


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


def test_short_name_outranks_longer_one_sharing_its_prefix():
    """The wine.owl case #210 had to leave mis-ranked, now that length is neutral."""
    options = _options(("Wine", ""), ("Winery", "Wine estate"))
    assert _rank("Wine", options)[0] == "Wine"


def test_padding_is_invisible_and_leaves_the_option_value_alone():
    """The value the widget returns is the key every lookup is built from."""
    display = app.format_label_name("Person", "A person")
    padded = app._pad_option(display)
    assert padded.strip() == display
    assert padded != display  # it really did pad
    assert len(padded) == app.SEARCH_PAD_WIDTH


def test_option_longer_than_the_pad_width_still_ranks_below_an_exact_match():
    """Padding is a no-op past SEARCH_PAD_WIDTH; that must not invert a match."""
    long_label = "x" * app.SEARCH_PAD_WIDTH
    options = _options(("Order", ""), ("OrderLine", long_label))
    assert len(app._pad_option(options[1])) > app.SEARCH_PAD_WIDTH
    assert _rank("Order", options)[0] == "Order"


def _entity_dropdowns_missing_format_func() -> list[tuple[int, str]]:
    """Selectboxes fed by the option builders that do not pad their labels.

    Every one of them filters on the rendered label, so a missed call site keeps
    the issue #214 ranking with nothing to show for it.
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
            if not any(k.arg == "format_func" for k in node.keywords):
                first = node.args[0] if node.args else None
                label = first.value if isinstance(first, ast.Constant) else "?"
                missing.append((node.lineno, str(label)))
    return sorted(missing)


def test_every_entity_dropdown_pads_its_labels():
    assert _entity_dropdowns_missing_format_func() == []

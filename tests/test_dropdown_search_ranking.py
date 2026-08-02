"""Dropdown search ranks the entity you typed first (issues #210 and #214).

Streamlit filters a selectbox client-side: it keeps every option whose label
contains the typed text as a *subsequence*, then sorts by an fzy score. That
scorer is not configurable from Python (it is bundled JS, and it is byte-for-byte
identical in every Streamlit release from 1.49 through 1.60), so the only levers
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

``_score`` / ``_has_match`` below are a direct port of the bundled scorer, so
these tests fail if either lever stops ranking the typed entity first. Note that
Streamlit calls it as ``score(query, label, /*caseSensitive=*/true)``: options
are *filtered* case-insensitively but *scored* case-sensitively, and the port
mirrors that. It also means the ``haystack.length === needle.length`` shortcut to
SCORE_MAX is disabled, so only a byte-identical option scores as a certainty.
"""

import ast
from pathlib import Path

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

    Case-insensitive, unlike :func:`_score` — that asymmetry is Streamlit's.
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
    # An option equal to the query wins outright. Streamlit passes
    # caseSensitive=true, which disables fzy's same-length shortcut.
    if needle == haystack:
        return _SCORE_MAX
    if m > 1024:
        return _SCORE_MIN

    bonus = _precompute_bonus(haystack)
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
        key=str.lower,
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
    tree = ast.parse(Path(app.__file__).read_text(encoding="utf-8"))
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
    for scope in ast.walk(tree):
        if not isinstance(scope, ast.FunctionDef):
            continue
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

"""Dropdown search puts an exact local-name match first (issue #210).

Streamlit filters a selectbox client-side: it keeps every option whose label
contains the typed text as a *subsequence*, then sorts by an fzy score. That
scorer is not configurable from Python (it is bundled JS, and it is byte-for-byte
identical in every Streamlit release from 1.49 through 1.60), so the only lever
the app has is the option string it emits.

fzy scores a match partly by the character *preceding* it: 0.9 after ``/``, 0.8
after a space / ``-`` / ``_``, 0.7 for a camelCase hump, and 0.0 after ``(``.
The old ``'Label (name)'`` format therefore gave the local name no boundary
bonus at all, and an unrelated camelCase compound could outscore an exact match:
searching ``HamTopping`` in pizza.owl ranked ``ParmaHamTopping`` first. The
name now leads, behind a separator that ends in a space, which restores the
bonus.

``_score`` / ``_has_match`` below are a direct port of that bundled scorer, so
these tests fail if the display format stops ranking exact matches first.
"""

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
    """Whether ``needle`` appears in ``haystack`` as a subsequence."""
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
    # An option equal to the query (or merely the same length) wins outright.
    if needle == haystack or m == n:
        return _SCORE_MAX
    if m > 1024:
        return _SCORE_MIN

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
    """The order Streamlit's selectbox shows for ``query``."""
    matches = [o for o in options if _has_match(query, o)]
    return sorted(matches, key=lambda o: -_score(query, o))


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

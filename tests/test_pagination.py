"""Tests for View Classes pagination bounds (issue #140)."""

from orionbelt_ontology_builder.app import _page_bounds
from orionbelt_ontology_builder.ui import filter_list_items


def test_single_page_when_total_fits():
    # Everything on one page; end is the item count, not the page size.
    assert _page_bounds(30, 1, 50) == (1, 1, 0, 30)


def test_empty_still_reports_one_page():
    assert _page_bounds(0, 1, 50) == (1, 1, 0, 0)


def test_multiple_pages_slice_bounds():
    # 120 items, 50 per page -> 3 pages.
    assert _page_bounds(120, 1, 50) == (3, 1, 0, 50)
    assert _page_bounds(120, 2, 50) == (3, 2, 50, 100)
    # Last page is short: only 20 items remain.
    assert _page_bounds(120, 3, 50) == (3, 3, 100, 120)


def test_page_clamped_into_range():
    # A stale/too-high page (e.g. after deletions) clamps to the last page.
    assert _page_bounds(120, 99, 50) == (3, 3, 100, 120)
    # A too-low page clamps to the first.
    assert _page_bounds(120, 0, 50) == (3, 1, 0, 50)
    assert _page_bounds(120, -5, 50) == (3, 1, 0, 50)


def test_exact_multiple_has_no_trailing_page():
    # 100 items at 50 per page is exactly 2 pages, not 3.
    assert _page_bounds(100, 2, 50) == (2, 2, 50, 100)


_ITEMS = [
    {"name": "Address", "label": ""},
    {"name": "AddressUsageType", "label": "Address Usage Type"},
    {"name": "EquipmentType", "label": "Equipment Type"},
    {"name": "Building", "label": "Mailing address"},
    {"name": "a.b", "label": ""},
    {"name": "concept1", "prefLabel": "Street Address"},
]


def _names(pattern):
    return [i["name"] for i in filter_list_items(_ITEMS, pattern)]


def test_plain_text_matches_anywhere_in_name_or_label_ignoring_case():
    assert _names("ADDRESS") == [
        "Address",
        "AddressUsageType",
        "Building",
        "concept1",
    ]


def test_a_star_anchors_the_rest():
    assert _names("address*") == ["Address", "AddressUsageType"]
    assert _names("*type") == ["AddressUsageType", "EquipmentType"]
    assert _names("*usage*") == ["AddressUsageType"]


def test_a_question_mark_is_one_character():
    assert _names("a?b") == ["a.b"]
    assert _names("addres?") == ["Address"]


def test_other_regex_characters_are_literal():
    assert _names("a.b") == ["a.b"]
    assert _names("a.*") == ["a.b"]  # the dot is a dot, not any character
    assert _names("[ab]*") == []


def test_an_empty_filter_keeps_everything():
    assert filter_list_items(_ITEMS, "  ") == _ITEMS


def test_a_run_of_stars_takes_no_time():
    # A regex backtracked exponentially on this one (Codex review of #565).
    items = [{"name": "AddressUsageType" * 4, "label": ""}]
    assert filter_list_items(items, "*" * 40 + "Z") == []
    assert filter_list_items(items, "*" * 40 + "type") == items
    assert filter_list_items(items, "a*d*d*r*e*s*s*u*s*a*g*e*t*y*p*e") == items

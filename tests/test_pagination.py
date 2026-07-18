"""Tests for View Classes pagination bounds (issue #140)."""

from orionbelt_ontology_builder.app import _page_bounds


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

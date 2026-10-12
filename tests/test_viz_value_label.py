"""How annotation and literal values are drawn on graph nodes (issue #511)."""

import pytest

from orionbelt_ontology_builder.views.visualization import (
    VALUE_LABEL_LINES,
    VALUE_LABEL_WIDTH,
    value_label,
)


def test_the_reported_label_wraps_onto_two_lines():
    assert (
        value_label("la catena del valore di Porter")
        == "la catena del valore di\nPorter"
    )


@pytest.mark.parametrize(
    "value",
    [
        "\nla catena del valore di Porter",
        "la catena del valore di Porter\n",
        "la catena  del\tvalore\r\ndi Porter",
    ],
)
def test_stray_whitespace_does_not_add_lines(value):
    """A line break in the value drew an empty line and cut the text short."""
    assert value_label(value) == "la catena del valore di\nPorter"


def test_a_short_value_is_drawn_as_is():
    assert value_label("Q646107") == "Q646107"
    assert value_label("") == ""


def test_a_long_value_is_cut_on_the_last_line_only():
    value = "A definition that runs on well past what two lines of a node can hold"
    drawn = value_label(value)
    lines = drawn.split("\n")
    assert len(lines) == VALUE_LABEL_LINES
    assert all(len(line) <= VALUE_LABEL_WIDTH for line in lines)
    assert drawn.endswith("…")
    assert value.startswith(lines[0])


def test_a_long_url_is_broken_and_cut():
    url = "https://www.wikidata.org/wiki/Special:EntityData/Q646107.json"
    lines = value_label(url).split("\n")
    assert len(lines) == VALUE_LABEL_LINES
    assert all(len(line) <= VALUE_LABEL_WIDTH for line in lines)
    assert url.startswith(lines[0]) and lines[-1].endswith("…")


@pytest.mark.parametrize(
    "value",
    [
        "A" * 5_000_000,  # base64-like, no spaces
        "word " * 1_000_000,
        " " * 5_000_000 + "late text",
    ],
)
def test_a_huge_value_costs_only_what_is_drawn(value):
    """Codex review of #512: wrapping 5 MB to draw two lines took seconds."""
    import time

    began = time.perf_counter()
    drawn = value_label(value)
    assert time.perf_counter() - began < 0.5
    lines = drawn.split("\n")
    assert len(lines) <= VALUE_LABEL_LINES
    assert all(len(line) <= VALUE_LABEL_WIDTH for line in lines)


def test_a_value_just_past_two_lines_is_marked_as_cut():
    value = "abcdefghijklmnopqrstuvwx " * 2 + "y"
    assert value_label(value).endswith("…")

"""Edit confirmations must not shove the page around (issue #330).

A flash message is drawn above the whole page body, so "Relation updated!" for
an edit made further down — in the details panel, or a row editor near the
bottom of a long list — inserted a banner at the top and pushed everything the
user was looking at out from under the cursor. Those confirmations say only that
the edit landed, so they float over the page instead.

Messages worth reading twice stay banners: a bulk-add summary names every row
that failed (issue #114), and an error has to survive longer than a toast.
"""

import pytest

from orionbelt_ontology_builder import ui


class _State(dict):
    """Stand-in for ``st.session_state``, which is read and written both ways."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def flash(monkeypatch):
    """Record what the flash was rendered as, without a Streamlit runtime."""
    state = _State()
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(
        ui.st, "toast", lambda message, icon=None: shown.append(("toast", message))
    )
    for kind in ("success", "warning", "error", "info"):
        monkeypatch.setattr(
            ui.st, kind, lambda message, k=kind: shown.append((k, message))
        )
    return state, shown


def test_a_plain_flash_is_still_a_banner(flash):
    state, shown = flash
    ui.set_flash_message("Created 2 class(es). 1 row failed", "warning")

    ui.display_flash_message()

    assert shown == [("warning", "Created 2 class(es). 1 row failed")]
    assert state["flash_message"] is None


def test_a_toast_flash_floats_over_the_page(flash):
    state, shown = flash
    ui.set_flash_message("Relation updated!", "success", toast=True)

    ui.display_flash_message()

    assert shown == [("toast", "Relation updated!")]
    assert state["flash_message"] is None


def test_nothing_pending_renders_nothing(flash):
    _state, shown = flash
    ui.display_flash_message()
    assert shown == []


def test_the_editor_confirmations_are_the_ones_that_float():
    """The confirmations that follow an in-place edit — the ones the issue is
    about — ask for a toast; everything else keeps its banner."""
    import inspect

    src = inspect.getsource(ui)
    for message in (
        '"Relation updated!", "success"',
        '"Restriction updated!", "success"',
        '"Annotation updated!", "success"',
        '"Annotation deleted!", "success"',
    ):
        assert f"set_flash_message({message}, toast=True)" in src, message
    # An error the user has to act on is not a toast.
    assert (
        'set_flash_message(f"This {label} is no longer in the ontology.", "error")'
        in src
    )

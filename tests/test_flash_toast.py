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
        ui.st,
        "toast",
        lambda message, icon=None, duration=None: shown.append(
            ("toast", message, duration)
        ),
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

    assert shown == [("toast", "Relation updated!", ui._FLASH_TOAST_SECONDS)]
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


def test_a_confirmation_does_not_outstay_the_edit(flash):
    """Two seconds, not Streamlit's four (issue #419).

    The confirmation carries one piece of news, read at a glance. What is left
    of the default is a message about the last edit sitting over the next one.
    """
    _state, shown = flash
    ui.set_flash_message("Relation updated!", "success", toast=True)

    ui.display_flash_message()

    assert shown[0][2] == 2


def test_a_warning_toast_keeps_the_default(flash):
    """Only the confirmations are cut back: a warning is not read that fast."""
    _state, shown = flash
    ui.set_flash_message("Saved, but the label was dropped", "warning", toast=True)

    ui.display_flash_message()

    assert shown[0][2] == "short"


def test_a_clean_bulk_result_is_a_toast_and_errors_a_banner(patch_ui):
    """A banner above the page pushes the bulk grid and its Apply button out
    of view; the failed rows of a result with errors are worth reading."""
    from orionbelt_ontology_builder import ui

    class _St:
        def __init__(self):
            self.session_state = _State()

    class _State(dict):
        def __getattr__(self, name):
            return self[name]

        def __setattr__(self, name, value):
            self[name] = value

    fake = _St()
    patch_ui("st", fake)
    ui.flash_bulk_result("Updated 3 class(es)")
    assert fake.session_state.flash_message["toast"] is True
    ui.flash_bulk_result("2 rows failed", "warning")
    assert fake.session_state.flash_message["toast"] is False


def test_a_success_is_a_toast_unless_the_caller_says_otherwise(patch_ui):
    """Every plain confirmation floats; errors, warnings and notes stay
    banners, to be read (issue #114)."""
    from orionbelt_ontology_builder import ui

    class _State(dict):
        def __getattr__(self, name):
            return self[name]

        def __setattr__(self, name, value):
            self[name] = value

    class _St:
        session_state = _State()

    patch_ui("st", _St())
    flash = _St.session_state
    for kind, toast in (
        ("success", True),
        ("error", False),
        ("warning", False),
        ("info", False),
    ):
        ui.set_flash_message("x", kind)
        assert flash.flash_message["toast"] is toast, kind
    ui.set_flash_message("x", "success", toast=False)
    assert flash.flash_message["toast"] is False

"""A single-choice picker whose search ranks by the case you type (issue #468).

Streamlit's selectbox ranks a search case-insensitively, so options that differ
only in case (``fn`` / ``FN``) always score the same, whatever was typed. This
picker ranks in the browser instead (``lib/case_picker/case_picker.js``): a
match in the exact case comes first, so ``FN`` lists ``FN`` above ``fn`` and
``fn`` lists ``fn`` above ``FN``.

It stands in for ``st.selectbox(..., index=None)``: the chosen option, or
``None``, lives in ``st.session_state[key]``, which is an ordinary session value
rather than widget state. Code can seed or clear it at any time, and it outlives
the picker not being rendered.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache
from typing import Any

import streamlit as st

from .ui import PKG_DIR

_ASSET_DIR = PKG_DIR / "lib" / "case_picker"

_HTML = (
    '<div class="cp-root">'
    '<label><span></span><span class="cp-help" hidden>?</span></label>'
    '<div class="cp-field"><span class="cp-chips"></span>'
    '<input type="text" role="combobox" autocomplete="off" spellcheck="false"'
    ' aria-autocomplete="list" aria-expanded="false">'
    '<button type="button" class="cp-clear" aria-label="Clear" hidden>×</button>'
    '</div><ul role="listbox" hidden></ul></div>'
)


@cache
def _asset(name: str) -> str:
    return (_ASSET_DIR / name).read_text(encoding="utf-8")


def _component() -> Callable[..., Any]:
    # Registered on every call, not cached: the registry belongs to the
    # runtime, and a cached handle outlives it (a fresh AppTest, a restart).
    return st.components.v2.component(
        "orionbelt_case_picker",
        html=_HTML,
        css=_asset("case_picker.css"),
        js=_asset("case_picker.js"),
    )


def _component_key(key: str) -> str:
    return f"{key}_case_picker"


_RUN = "_case_picker_run"
_DRAWN = "_case_picker_drawn"


def new_run() -> None:
    """Count a full run of the app; ``app.main`` calls it first thing."""
    st.session_state[_RUN] = st.session_state.get(_RUN, 0) + 1


def drawn_last_run(key: str) -> bool:
    """Whether the picker keyed ``key`` was drawn on the previous run.

    ``st.session_state[key]`` is kept whatever happens, where Streamlit drops a
    ``st.selectbox``'s state on a run that does not draw it; this is how a
    caller tells the two apart. Counted by :func:`new_run`, so a fragment's
    rerun, which does not go through ``app.main``, leaves it as it was.
    """
    run = st.session_state.get(_RUN, 0)
    return st.session_state.get(_DRAWN, {}).get(key) in (run, run - 1)


def mark_drawn(key: str) -> None:
    """Record that the picker keyed ``key`` is drawn on this run."""
    st.session_state.setdefault(_DRAWN, {})[key] = st.session_state.get(_RUN, 0)


def _picked(key: str, on_change: Callable[..., None] | None, args: tuple = ()) -> None:
    """Copy a pick from the browser into ``st.session_state[key]``.

    Runs as the component's change callback, so before the script, like any
    widget callback; inside a form that is on submit.
    """
    state = st.session_state.get(_component_key(key)) or {}
    reported = state.get("value") or [None]
    st.session_state[key] = reported[0]
    if on_change is not None:
        on_change(*args)


def _mount(
    key: str,
    options: list[str],
    value: Any,
    format_func: Callable[[str], str],
    on_change: Callable[..., None] | None,
    args: tuple,
    **data: Any,
) -> None:
    _component()(
        key=_component_key(key),
        data={
            **data,
            "options": options,
            "captions": [str(format_func(o)).rstrip() for o in options],
            "value": value,
        },
        on_value_change=lambda: _picked(key, on_change, args),
    )


def case_selectbox(
    label: str,
    options: Sequence[str],
    *,
    key: str,
    format_func: Callable[[str], str] = str,
    placeholder: str = "Choose an option",
    label_visibility: str = "visible",
    help: str | None = None,
    on_change: Callable[[], None] | None = None,
    disabled: bool = False,
    accept_new_options: bool = False,
) -> str | None:
    """Render the picker and return the chosen option, or ``None``.

    ``options`` should already be in display order (see ``ui.option_sort_key``):
    the search keeps that order among equally good matches. ``format_func`` is
    what is drawn and searched, as with ``st.selectbox``; trailing padding
    meant for Streamlit's scorer is stripped, since this search has no use for
    it. With ``accept_new_options``, text typed in is a value too, as with
    ``st.selectbox``; it is offered as an option from then on.
    """
    options = list(options)
    mark_drawn(key)
    value = st.session_state.get(key)
    if value not in options:
        if accept_new_options and isinstance(value, str) and value:
            options = [value, *options]
        else:
            value = None
            st.session_state[key] = None
    _mount(
        key,
        options,
        value,
        format_func,
        on_change,
        (),
        label=label,
        labelVisibility=label_visibility,
        help=help,
        placeholder=placeholder,
        disabled=disabled,
        acceptNewOptions=accept_new_options,
    )
    return value


def case_multiselect(
    label: str,
    options: Sequence[str],
    *,
    key: str,
    default: Sequence[str] | None = None,
    format_func: Callable[[str], str] = str,
    placeholder: str = "Choose options",
    label_visibility: str = "visible",
    help: str | None = None,
    on_change: Callable[..., None] | None = None,
    args: tuple = (),
    disabled: bool = False,
    select_all: bool = True,
) -> list[str]:
    """Render the picker for several options and return them in picked order.

    The stand-in for ``st.multiselect``, searched the same way as
    :func:`case_selectbox`, its value a list in ``st.session_state[key]``.
    ``default`` fills it where there is none yet and, as a multiselect's did,
    again after a run that did not draw the picker, so an editor left with
    unsaved picks shows what it holds when it comes back. Without ``default``
    the value is only ever the page's or the user's, which is what lets a page
    restore it from saved settings before drawing it. ``select_all`` offers
    the row that takes every option, or every match (see SELECT_ALL_NOTE in
    ui.py).
    """
    options = list(options)
    if key not in st.session_state or (default is not None and not drawn_last_run(key)):
        st.session_state[key] = list(default or [])
    mark_drawn(key)
    held = st.session_state[key] or []
    value = [o for o in held if o in options]
    if value != held:
        st.session_state[key] = value
    _mount(
        key,
        options,
        value,
        format_func,
        on_change,
        args,
        label=label,
        labelVisibility=label_visibility,
        help=help,
        placeholder=placeholder,
        disabled=disabled,
        multi=True,
        selectAll=select_all,
    )
    return value

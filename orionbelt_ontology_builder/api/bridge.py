"""Tie the running Streamlit session to the API.

Three things, all no-ops unless the API is enabled (:func:`.server.api_enabled`):

* **One lock.** :func:`run_guard` holds a process-wide lock for a whole UI
  run, :func:`_lock_widget_callbacks` holds it for the widget callbacks
  Streamlit runs before that, and every API call takes the same lock, so the
  two never change the graph at once. ``runner.fastReruns`` is already off
  for the same reason (see :data:`~..local_store.STREAMLIT_OPTIONS`).
* **The live ontology.** At the end of every run the session's
  ``OntologyManager`` and ``UndoManager`` are handed to the API, so a load
  or "new ontology" in the UI is what the next API call sees. With several
  browser tabs open, the tab that ran last is the one the API works on.
* **A refresh.** An API edit bumps a counter; the next run turns that into
  the UI's own mutation bump (autosave, caches), and a small fragment polls
  the counter so the open page reruns by itself after an agent's edit.
* **A notice.** That run also shows a toast naming what the agent changed,
  and the sidebar keeps the last few agent changes, so a change made while
  nobody was looking is still visible once the toast has gone.
"""

from __future__ import annotations

import contextlib
import functools
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from ..ontology_manager import OntologyManager, UndoManager
from . import server
from .service import Busy

#: Seconds between the UI's checks for edits made through the API.
REFRESH_SECONDS = 2.0

#: Agent changes the sidebar list keeps.
HISTORY_SIZE = 10
#: Changes named one by one in a toast; beyond that they are counted.
TOAST_NAMED = 3

_SEEN_KEY = "_api_seen_writes"


@dataclass(frozen=True)
class AgentChange:
    """One change made through the API, as the UI tells the user about it."""

    seq: int
    at: float
    label: str
    detail: str = ""

    @property
    def text(self) -> str:
        what = self.label.removeprefix("API: ")
        return f"{what} ({self.detail})" if self.detail else what


class StreamlitWorkspace:
    """The workspace the API serves: whatever the last UI run left in place."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.writes = 0
        self.changes: deque[AgentChange] = deque(maxlen=HISTORY_SIZE)
        self._manager: OntologyManager | None = None
        self._undo: UndoManager | None = None

    def attach(self, manager: OntologyManager, undo: UndoManager | None) -> None:
        self._manager, self._undo = manager, undo

    def manager(self) -> OntologyManager:
        if self._manager is None:
            raise Busy("The app has not finished starting; open it in a browser.")
        return self._manager

    def undo(self) -> UndoManager | None:
        return self._undo

    @contextlib.contextmanager
    def locked(self, timeout: float) -> Iterator[None]:
        if not self.lock.acquire(timeout=timeout):
            raise Busy("The app is busy with a long action; try again shortly.")
        try:
            yield
        finally:
            self.lock.release()

    def note_write(self, label: str, detail: str = "") -> None:
        # Called by the service while it holds the lock, and read by UI runs,
        # which hold it too, so the counter and the log never disagree.
        self.writes += 1
        self.changes.append(AgentChange(self.writes, time.time(), label, detail))

    def changes_since(self, seq: int) -> list[AgentChange]:
        return [c for c in self.changes if c.seq > seq]


WORKSPACE = StreamlitWorkspace()


@contextlib.contextmanager
def run_guard() -> Iterator[None]:
    """Wrap one UI run: hold the lock, then hand the session to the API."""
    if not server.api_enabled():
        yield
        return
    # Started before the first run renders, so its sidebar line shows at
    # once; until a run has attached a session, API calls answer "busy".
    server.ensure_started(WORKSPACE)
    with WORKSPACE.lock:
        _lock_widget_callbacks()
        try:
            yield
        finally:
            ont = st.session_state.get("ontology")
            if ont is not None:
                WORKSPACE.attach(ont, st.session_state.get("undo_manager"))


#: The wrapper :func:`_lock_widget_callbacks` put in place, so it goes in once.
_locked_callbacks: Callable[..., None] | None = None


def _lock_widget_callbacks() -> None:
    """Run widget callbacks under the API's lock too.

    Streamlit runs ``on_click`` and ``on_change`` callbacks before the script
    body, so outside :func:`run_guard`, and most edits in the app are made in
    one (loading an upper ontology is). Unlocked, an API batch could run while
    a callback changes the graph: a dry run's rollback would take back part of
    the user's change, or record a revision that already includes it as the
    same as the one before the dry run, and the apply's revision check would
    then pass over it.

    This wraps the one Streamlit method that dispatches the callbacks, an
    internal one. ``streamlit`` is pinned to an exact version, and a test runs
    a callback and checks that it holds the lock. The lock is taken before
    Streamlit's own session-state lock, in the order a script body takes them.
    """
    global _locked_callbacks
    from streamlit.runtime.state.safe_session_state import SafeSessionState

    original = SafeSessionState.on_script_will_rerun
    if original is _locked_callbacks:
        return

    @functools.wraps(original)
    def locked(self: SafeSessionState, *args: Any, **kwargs: Any) -> None:
        with WORKSPACE.lock:
            original(self, *args, **kwargs)

    _locked_callbacks = locked
    SafeSessionState.on_script_will_rerun = locked  # type: ignore[method-assign]


def absorb_api_writes() -> None:
    """Turn API edits since the last run into the UI's own mutation bump.

    Called near the top of a run, after the session state exists, so the
    autosave and the derived caches see the API's changes as they see an
    edit made in the UI.
    """
    if not server.api_enabled():
        return
    if _SEEN_KEY not in st.session_state:
        # A new session starts from here: changes made before it opened are
        # history (the sidebar list still shows them), not news to toast.
        st.session_state[_SEEN_KEY] = WORKSPACE.writes
        return
    seen = st.session_state[_SEEN_KEY]
    if seen != WORKSPACE.writes:
        from ..ui import note_mutation

        fresh = WORKSPACE.changes_since(seen)
        st.session_state[_SEEN_KEY] = WORKSPACE.writes
        note_mutation()
        if fresh:
            st.toast(toast_text(fresh), icon="🤖")


def toast_text(changes: list[AgentChange]) -> str:
    """One toast for every change since the last run: a few named, the rest counted."""
    if len(changes) == 1:
        return f"Agent changed the ontology: {changes[0].text}. Undo is in the sidebar."
    named = "; ".join(c.text for c in changes[-TOAST_NAMED:])
    rest = len(changes) - TOAST_NAMED
    more = f" and {rest} earlier" if rest > 0 else ""
    return f"Agent made {len(changes)} changes: {named}{more}. Undo is in the sidebar."


@st.fragment(run_every=REFRESH_SECONDS)
def _watch_api_writes() -> None:
    if st.session_state.get(_SEEN_KEY, 0) != WORKSPACE.writes:
        st.rerun(scope="app")


def status_lines(url: str, token_file: Path | None) -> list[dict[str, str]]:
    """The sidebar's lines: a label, the value a copy takes, what is shown.

    Only the API has an address. The MCP server is a process of its own,
    on stdio unless started with ``--http``, and finds the API through the
    token file. With no ``token_file`` (the user set the token, so knows
    it), the API's line is the only one.
    """
    lines = [{"label": "API:", "value": url, "shown": url, "what": "the API address"}]
    if token_file is not None:
        lines.append(
            {
                "label": "Token in:",
                "value": str(token_file),
                "shown": _home_relative(token_file),
                "what": "the token file's path",
            }
        )
    return lines


def _home_relative(path: Path) -> str:
    """``~/...`` for a path under the home directory, to keep the line short."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


#: One line per value, cut short with an ellipsis rather than wrapped, the
#: whole value on hover, and a button that copies it. A component, not a
#: caption, because copying needs the browser's clipboard. The ``--st-*``
#: variables are the theme Streamlit hands its components.
_LINES_HTML = '<div class="ob-lines"></div>'

_LINES_CSS = """
.ob-lines {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-family: var(--st-font, inherit);
  font-size: 0.875rem;
  line-height: 1.5;
  color: color-mix(in srgb, currentColor 60%, transparent);
}
.ob-line {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}
.ob-label {
  flex: none;
  white-space: nowrap;
}
.ob-value {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-family: var(--st-code-font, monospace);
  font-size: 0.8em;
  color: var(--st-code-text-color, inherit);
  background: var(--st-code-background-color, transparent);
}
.ob-copy {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.375rem;
  height: 1.375rem;
  padding: 0;
  border: 0;
  border-radius: 0.25rem;
  background: none;
  color: inherit;
  cursor: pointer;
}
.ob-copy:hover {
  color: var(--st-text-color, currentColor);
  background: color-mix(in srgb, currentColor 10%, transparent);
}
.ob-copy:focus-visible {
  outline: 2px solid var(--st-primary-color, currentColor);
  outline-offset: 1px;
}
.ob-copy svg {
  width: 0.875rem;
  height: 0.875rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}
"""

_LINES_JS = """
const COPY_ICON =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/>' +
  '<path d="M3.5 10.5H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1h6.5a1 1 0 0 1 1 1v.5"/></svg>';
const DONE_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7"/></svg>';

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // No async clipboard outside a secure context, e.g. the app opened by a
    // LAN address over plain http.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function line({ label, value, shown, what }) {
  const row = document.createElement("div");
  row.className = "ob-line";
  const name = document.createElement("span");
  name.className = "ob-label";
  name.textContent = label;
  const text = document.createElement("code");
  text.className = "ob-value";
  text.textContent = shown;
  text.title = value;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ob-copy";
  const show = (icon, hint) => {
    button.innerHTML = icon;
    button.title = hint;
    button.setAttribute("aria-label", hint);
  };
  show(COPY_ICON, `Copy ${what}`);
  let timer;
  button.addEventListener("click", async () => {
    const ok = await copy(value);
    show(ok ? DONE_ICON : COPY_ICON, ok ? "Copied" : "Could not copy");
    clearTimeout(timer);
    timer = setTimeout(() => show(COPY_ICON, `Copy ${what}`), 1500);
  });
  row.append(name, text, button);
  return row;
}

export default function ({ data, parentElement }) {
  parentElement.querySelector(".ob-lines").replaceChildren(...data.lines.map(line));
}
"""


def render_sidebar_status() -> None:
    """The API's address (or why it is not running), and the refresh poller."""
    if not server.api_enabled():
        return
    status = server.status()
    if status is None:
        return
    if status.running:
        with st.sidebar:
            # Registered on every call, as the case picker's is: the registry
            # belongs to the runtime, and a cached handle outlives it.
            st.components.v2.component(
                "orionbelt_api_status", html=_LINES_HTML, css=_LINES_CSS, js=_LINES_JS
            )(
                key="api_status_lines",
                data={
                    "lines": status_lines(
                        status.url,
                        None if status.token_given else server.discovery_file(),
                    )
                },
            )
        _render_agent_changes()
        _watch_api_writes()
    else:
        st.sidebar.caption(f"API not running: {status.error}")


def _render_agent_changes() -> None:
    """The last few agent changes, newest first, under the API line."""
    changes = list(WORKSPACE.changes)
    if not changes:
        return
    with st.sidebar.expander(f"🤖 Agent changes ({len(changes)})", expanded=False):
        for c in reversed(changes):
            st.caption(f"{time.strftime('%H:%M:%S', time.localtime(c.at))} · {c.text}")
        st.caption("Each one is a step in the Undo history.")

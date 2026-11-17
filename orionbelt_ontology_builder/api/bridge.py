"""Tie the running Streamlit session to the API.

Three things, all no-ops unless the API is enabled (:func:`.server.api_enabled`):

* **One lock.** :func:`run_guard` holds a process-wide lock for a whole UI
  run, and every API call takes the same lock, so the two never change the
  graph at once. ``runner.fastReruns`` is already off for the same reason
  (see :data:`~..local_store.STREAMLIT_OPTIONS`).
* **The live ontology.** At the end of every run the session's
  ``OntologyManager`` and ``UndoManager`` are handed to the API, so a load
  or "new ontology" in the UI is what the next API call sees. With several
  browser tabs open, the tab that ran last is the one the API works on.
* **A refresh.** An API edit bumps a counter; the next run turns that into
  the UI's own mutation bump (autosave, caches), and a small fragment polls
  the counter so the open page reruns by itself after an agent's edit.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator

import streamlit as st

from ..ontology_manager import OntologyManager, UndoManager
from . import server
from .service import Busy

#: Seconds between the UI's checks for edits made through the API.
REFRESH_SECONDS = 2.0

_SEEN_KEY = "_api_seen_writes"


class StreamlitWorkspace:
    """The workspace the API serves: whatever the last UI run left in place."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.writes = 0
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

    def note_write(self, label: str) -> None:
        self.writes += 1


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
        try:
            yield
        finally:
            ont = st.session_state.get("ontology")
            if ont is not None:
                WORKSPACE.attach(ont, st.session_state.get("undo_manager"))


def absorb_api_writes() -> None:
    """Turn API edits since the last run into the UI's own mutation bump.

    Called near the top of a run, after the session state exists, so the
    autosave and the derived caches see the API's changes as they see an
    edit made in the UI.
    """
    if not server.api_enabled():
        return
    if st.session_state.get(_SEEN_KEY, 0) != WORKSPACE.writes:
        from ..ui import note_mutation

        st.session_state[_SEEN_KEY] = WORKSPACE.writes
        note_mutation()


@st.fragment(run_every=REFRESH_SECONDS)
def _watch_api_writes() -> None:
    if st.session_state.get(_SEEN_KEY, 0) != WORKSPACE.writes:
        st.rerun(scope="app")


def render_sidebar_status() -> None:
    """The API's address (or why it is not running), and the refresh poller."""
    if not server.api_enabled():
        return
    status = server.status()
    if status is None:
        return
    if status.running:
        st.sidebar.caption(
            f"API & MCP: `{status.url}` · token in `{server.discovery_file()}`"
        )
        _watch_api_writes()
    else:
        st.sidebar.caption(f"API not running: {status.error}")

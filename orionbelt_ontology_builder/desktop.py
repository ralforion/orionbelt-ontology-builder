"""Native desktop launcher for the OrionBelt app.

Exposed as the ``orionbelt-ontology-builder-desktop`` command (see
``[project.scripts]`` in ``pyproject.toml``). It opens the app in a native
window via :mod:`streamlit_desktop_app` (pywebview + a real Streamlit server),
so there is no browser tab to manage and no manual start/stop of the server.

``streamlit-desktop-app`` is an optional dependency; install it with the
``desktop`` extra::

    pip install "orionbelt-ontology-builder[desktop]"
    orionbelt-ontology-builder-desktop

The ``desktop`` extra uses the Qt backend (PySide6). ``qt`` is an explicit alias
for it, and ``gtk`` selects pywebview's GTK backend instead (Linux only). See the
README for the GTK system-package prerequisites.

This reuses the same in-package Streamlit entry script as the console launcher
(:mod:`orionbelt_ontology_builder.cli`).
"""

import importlib.util
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .app import APP_NAME
from .local_store import BRAND_PRIMARY_COLOR, ENV_FLAG, data_dir, resolved_startup_base

logger = logging.getLogger(__name__)


def _preferred_gui() -> str | None:
    """Pick a pywebview GUI backend deterministically from what is installed.

    On Linux pywebview tries GTK before Qt regardless of which is actually
    present, logging a noisy ``ImportError`` traceback when only Qt is installed
    (issue #73). Returning an explicit backend (exported via ``PYWEBVIEW_GUI``)
    makes the choice match the installed extra and silences that traceback.

    Returns ``None`` when the platform or the user should decide: on macOS, where
    Cocoa is the right default, or when ``PYWEBVIEW_GUI`` is already set.
    """
    if sys.platform == "darwin":
        return None
    if os.environ.get("PYWEBVIEW_GUI"):
        return None
    # find_spec only checks importability — it does not import the backend (and
    # so never loads the heavy Qt/GTK shared libraries) as a side effect.
    if importlib.util.find_spec("gi") is not None:
        return "gtk"
    if importlib.util.find_spec("qtpy") is not None:
        return "qt"
    return None


# Injected into the desktop webview: mirror the page's document.title (set by
# st.set_page_config, so it carries the current ontology name) onto the native
# window through the exposed bridge below. pywebview does not propagate
# document.title to the OS window on its own, so the window would otherwise keep
# its static launch title (issue #90).
_TITLE_SYNC_JS = """
(function () {
  if (window.__orionbeltTitleSync) return;
  window.__orionbeltTitleSync = true;
  function push() {
    try {
      var api = window.pywebview && window.pywebview.api;
      if (api && api.orionbelt_set_window_title) {
        api.orionbelt_set_window_title(document.title);
      }
    } catch (e) {}
  }
  var head = document.head || document.documentElement;
  new MutationObserver(push).observe(head, {
    subtree: true, childList: true, characterData: true
  });
  push();
})();
"""


# Injected into the desktop webview: the embedded browser blocks
# JavaScript-initiated clipboard writes, so Streamlit's built-in copy buttons
# (e.g. the IRI in the Visualization details panel) silently do nothing (issue
# #120, the same webview capability gap as the disabled downloads in #86).
# Reroute navigator.clipboard.writeText through the native bridge exposed below;
# the page keeps calling the standard API, so every copy button just works.
_CLIPBOARD_BRIDGE_JS = """
(function () {
  if (window.__orionbeltClipboardBridge) return;
  window.__orionbeltClipboardBridge = true;
  // Hand the text to the native writer and return its Promise<bool>, or null
  // when the bridge is not available. The Python side reports whether the OS
  // clipboard actually accepted the text, so callers must await it.
  function nativeCopy(text) {
    try {
      var api = window.pywebview && window.pywebview.api;
      if (api && api.orionbelt_copy_to_clipboard) {
        return Promise.resolve(
          api.orionbelt_copy_to_clipboard(text == null ? '' : String(text))
        );
      }
    } catch (e) {}
    return null;
  }
  try {
    var clip = navigator.clipboard;
    if (!clip) return;
    var original = typeof clip.writeText === 'function'
      ? clip.writeText.bind(clip)
      : null;
    function fallback(text) {
      return original
        ? original(text)
        : Promise.reject(new Error('clipboard unavailable'));
    }
    clip.writeText = function (text) {
      var pending = nativeCopy(text);
      if (!pending) return fallback(text);
      // Only resolve once the native write succeeds; on failure (e.g. no
      // clipboard tool installed) fall back to the original API.
      return pending.then(function (ok) {
        return ok ? undefined : fallback(text);
      });
    };
  } catch (e) {}
})();
"""


def _clipboard_commands() -> list[list[str]]:
    """Return OS clipboard tools (stdin -> clipboard), tried in order.

    macOS and Windows ship one; Linux depends on the session's clipboard helper
    being installed, so Wayland and X11 tools are attempted in turn.
    """
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform == "win32":
        return [["clip"]]
    return [
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]


def _copy_to_clipboard(text: str) -> bool:
    """Write ``text`` to the OS clipboard from the desktop process (issue #120).

    The embedded webview blocks JavaScript-initiated clipboard writes, so
    Streamlit's built-in copy buttons do nothing there. :data:`_CLIPBOARD_BRIDGE_JS`
    reroutes the page's ``navigator.clipboard.writeText`` to this, and because
    the desktop app's Streamlit server runs on the user's own machine, writing
    from Python lands on their real clipboard.

    Best effort: returns ``True`` once a clipboard tool accepts the text, and
    ``False`` when none is available (e.g. a Linux box without ``xclip`` /
    ``wl-copy``) rather than raising.
    """
    data = text.encode("utf-8")
    for command in _clipboard_commands():
        try:
            subprocess.run(command, input=data, check=True)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _install_window_bridges(app_name: str):
    """Wire the native <-> page bridges each webview window needs.

    Hooks ``webview.create_window`` so every window (a) exposes a title setter
    and a clipboard writer to JS and (b) once loaded, injects the companion
    scripts: :data:`_TITLE_SYNC_JS` (a MutationObserver mirroring
    ``document.title`` onto the window, issue #90) and
    :data:`_CLIPBOARD_BRIDGE_JS` (route the page's clipboard writes through the
    native writer, issue #120). It also mirrors native fullscreen exits back to
    the page so the graph's fullscreen overlay can't outlive them (issue #177
    follow-up). Every step is defensive: any failure leaves the window working
    without that enhancement rather than breaking the desktop launch. Returns the
    original ``create_window`` for restoration, or ``None`` when there is nothing
    to hook (e.g. a stubbed webview in tests).
    """
    import webview

    original_create = getattr(webview, "create_window", None)
    if original_create is None:
        return None

    def _create(*args, **kwargs):
        window = original_create(*args, **kwargs)

        def orionbelt_set_window_title(title):
            # Ignore the Streamlit default / empty title so the window keeps a
            # meaningful name during the brief window before the app connects.
            try:
                window.set_title(title if title and title != "Streamlit" else app_name)
            except Exception:
                logger.debug("Backend rejected set_title()", exc_info=True)
            return True

        def orionbelt_copy_to_clipboard(text):
            # Called from _CLIPBOARD_BRIDGE_JS when the page copies text. The
            # desktop server runs on the user's own machine, so writing here
            # reaches their real clipboard (issue #120).
            try:
                return _copy_to_clipboard("" if text is None else str(text))
            except Exception:  # noqa: BLE001 - clipboard bridge is best-effort across backends
                return False

        try:
            window.expose(
                orionbelt_set_window_title,
                orionbelt_copy_to_clipboard,
            )
        except Exception:
            logger.debug(
                "JS bridge not exposed; backend has no window.expose()", exc_info=True
            )

        def _inject():
            for script in (_TITLE_SYNC_JS, _CLIPBOARD_BRIDGE_JS):
                try:
                    window.evaluate_js(script)
                except Exception:
                    logger.debug("Startup script injection failed", exc_info=True)

        try:
            window.events.loaded += _inject
        except Exception:
            logger.debug(
                "Backend has no 'loaded' event; script injection disabled",
                exc_info=True,
            )
        return window

    webview.create_window = _create
    return original_create


#: How long the server child waits for Streamlit's own SIGTERM handling before
#: it exits outright. A daemon thread, so a normal shutdown never waits on it.
_EXIT_GRACE_SECONDS = 5.0

# The original ``streamlit_desktop_app.core.run_streamlit``, kept while
# :func:`_run_streamlit_watched` stands in for it. Under ``fork`` the child
# inherits this binding; under ``spawn`` (macOS, Windows) the child imports this
# module afresh, finds ``None``, and takes the library's own, unpatched function.
_original_run_streamlit = None


def _exit_with_launcher() -> None:
    """Block until the launcher process is gone, then stop this server.

    Runs on a daemon thread inside the Streamlit server child. The library
    stops the server from a ``finally`` once the window closes, which covers a
    normal close, Sway's ``kill`` binding included. It does not cover the
    launcher dying before it gets there: the compositor going away at logout
    (Qt and GTK exit hard when the Wayland connection breaks), a webview crash
    on a heavy render, or a SIGKILL. The server then lived on with the whole
    app and ontology in memory, one idle process per incident, and survived
    logout because logind does not kill user processes by default (issue #437).

    The parent sentinel is a pipe the launcher holds, so waiting on it works
    under ``fork``, under ``forkserver`` (the Python 3.14 default on Linux,
    where the child's OS parent is the forkserver rather than the launcher),
    and under ``spawn``. The stop is the same SIGTERM the library sends on a
    normal close, so Streamlit shuts down through its own handler; if that has
    not ended the process after a grace period, exit outright.
    """
    parent = multiprocessing.parent_process()
    if parent is None:
        return
    parent.join()
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except OSError:
        logger.debug("SIGTERM to self failed; exiting outright", exc_info=True)
        os._exit(1)
    time.sleep(_EXIT_GRACE_SECONDS)
    os._exit(1)


def _run_streamlit_watched(script_path: str, options: dict) -> None:
    """The server child's target: the library's ``run_streamlit`` plus a watchdog.

    Module level, and looked up by name, so ``multiprocessing`` can pickle it
    for a ``spawn`` start. The thread is a daemon: it never keeps the process
    alive once the server has stopped on its own.
    """
    threading.Thread(
        target=_exit_with_launcher, name="orionbelt-exit-with-launcher", daemon=True
    ).start()
    original = _original_run_streamlit
    if original is None:
        from streamlit_desktop_app import core

        original = core.run_streamlit
    original(script_path, options)


def _install_server_watchdog():
    """Point the library's server target at :func:`_run_streamlit_watched`.

    ``start_desktop_app`` looks the target up on its module at call time, so
    rebinding it there is enough. Returns the original for restoration, or
    ``None`` when there is nothing to hook (an older library, or the stub in
    tests), in which case the launch proceeds without the watchdog.
    """
    global _original_run_streamlit
    try:
        from streamlit_desktop_app import core
    except ImportError:
        logger.debug("streamlit_desktop_app.core not importable; no watchdog")
        return None
    original = getattr(core, "run_streamlit", None)
    if original is None:
        return None
    _original_run_streamlit = original
    core.run_streamlit = _run_streamlit_watched
    return original


def _restore_server_target(original) -> None:
    global _original_run_streamlit
    from streamlit_desktop_app import core

    core.run_streamlit = original
    _original_run_streamlit = None


def run() -> None:
    """Launch the app in a native desktop window.

    Falls back to a helpful message (and a non-zero exit) when the optional
    ``desktop`` extra is not installed.
    """
    try:
        from streamlit_desktop_app import start_desktop_app
    except ImportError:
        print(
            "The native desktop window needs the optional 'desktop' extra.\n"
            'Install it with: pip install "orionbelt-ontology-builder[desktop]"',
            file=sys.stderr,
        )
        sys.exit(1)

    # Running locally with full filesystem access — opt into the disk-backed
    # autosave / linked-file persistence (off by default on the cloud).
    os.environ[ENV_FLAG] = "1"

    # Force pywebview onto the installed backend so it doesn't try (and noisily
    # fail) GTK before Qt on Linux (issue #73).
    gui = _preferred_gui()
    if gui:
        os.environ["PYWEBVIEW_GUI"] = gui

    # streamlit_desktop_app calls ``webview.start()`` with no arguments, so
    # pywebview runs in its default private mode and discards cookies /
    # localStorage when the window closes. Streamlit persists the user's theme
    # choice (and similar UI settings) in localStorage, so without persistent
    # storage it reverts to the bundled brand theme on every launch (issue #70).
    # The library doesn't expose pywebview's storage options, so wrap
    # ``webview.start`` to opt into a persistent per-user storage directory.
    import webview

    storage_path = data_dir() / "webview"
    storage_path.mkdir(parents=True, exist_ok=True)
    original_start = webview.start

    def _start_with_persistent_storage(*args, **kwargs):
        kwargs.setdefault("private_mode", False)
        kwargs.setdefault("storage_path", str(storage_path))
        return original_start(*args, **kwargs)

    # Pass the brand colour as an explicit Streamlit option so it applies
    # regardless of CWD (config.toml is only found from the repo root) and
    # without relying on env inheritance into the Streamlit subprocess.
    # Apply the saved startup theme so the app opens the way it was left
    # (issues #70, #78).
    options = {"theme.primaryColor": BRAND_PRIMARY_COLOR}
    saved_base = resolved_startup_base()
    if saved_base:
        options["theme.base"] = saved_base

    entry = Path(__file__).parent / "streamlit_entry.py"
    webview.start = _start_with_persistent_storage
    # Wire the native bridges: mirror the page title onto the window (issue #90)
    # and route the page's clipboard writes to the OS clipboard (issue #120).
    original_create_window = _install_window_bridges(APP_NAME)
    # Have the server child stop itself when this process dies without reaching
    # the library's own cleanup (issue #437).
    original_run_streamlit = _install_server_watchdog()
    try:
        start_desktop_app(
            script_path=str(entry),
            title=APP_NAME,
            options=options,
            width=1280,
            height=800,
        )
    finally:
        webview.start = original_start
        if original_create_window is not None:
            webview.create_window = original_create_window
        if original_run_streamlit is not None:
            _restore_server_target(original_run_streamlit)


if __name__ == "__main__":
    run()

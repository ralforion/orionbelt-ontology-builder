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
import os
import subprocess
import sys
from pathlib import Path

from .app import APP_NAME
from .local_store import BRAND_PRIMARY_COLOR, ENV_FLAG, data_dir, resolved_startup_base


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
  function nativeCopy(text) {
    try {
      var api = window.pywebview && window.pywebview.api;
      if (api && api.orionbelt_copy_to_clipboard) {
        api.orionbelt_copy_to_clipboard(text == null ? '' : String(text));
        return true;
      }
    } catch (e) {}
    return false;
  }
  try {
    var clip = navigator.clipboard;
    if (!clip) return;
    var original = typeof clip.writeText === 'function'
      ? clip.writeText.bind(clip)
      : null;
    clip.writeText = function (text) {
      if (nativeCopy(text)) return Promise.resolve();
      return original
        ? original(text)
        : Promise.reject(new Error('clipboard unavailable'));
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
    native writer, issue #120). Every step is defensive: any failure leaves the
    window working without that enhancement rather than breaking the desktop
    launch. Returns the original ``create_window`` for restoration, or ``None``
    when there is nothing to hook (e.g. a stubbed webview in tests).
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
                pass
            return True

        def orionbelt_copy_to_clipboard(text):
            # Called from _CLIPBOARD_BRIDGE_JS when the page copies text. The
            # desktop server runs on the user's own machine, so writing here
            # reaches their real clipboard (issue #120).
            try:
                return _copy_to_clipboard("" if text is None else str(text))
            except Exception:
                return False

        try:
            window.expose(orionbelt_set_window_title, orionbelt_copy_to_clipboard)
        except Exception:
            pass

        def _inject():
            for script in (_TITLE_SYNC_JS, _CLIPBOARD_BRIDGE_JS):
                try:
                    window.evaluate_js(script)
                except Exception:
                    pass

        try:
            window.events.loaded += _inject
        except Exception:
            pass
        return window

    webview.create_window = _create
    return original_create


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


if __name__ == "__main__":
    run()

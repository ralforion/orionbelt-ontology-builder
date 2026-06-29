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


if __name__ == "__main__":
    run()

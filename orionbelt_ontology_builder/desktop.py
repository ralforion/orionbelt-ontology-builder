"""Native desktop launcher for the OrionBelt app.

Exposed as the ``orionbelt-ontology-builder-desktop`` command (see
``[project.scripts]`` in ``pyproject.toml``). It opens the app in a native
window via :mod:`streamlit_desktop_app` (pywebview + a real Streamlit server),
so there is no browser tab to manage and no manual start/stop of the server.

``streamlit-desktop-app`` is an optional dependency; install it with the
``desktop`` extra::

    pip install "orionbelt-ontology-builder[desktop]"
    orionbelt-ontology-builder-desktop

This reuses the same in-package Streamlit entry script as the console launcher
(:mod:`orionbelt_ontology_builder.cli`).
"""

import os
import sys
from pathlib import Path

from .app import APP_NAME
from .local_store import BRAND_PRIMARY_COLOR, ENV_FLAG, data_dir


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
    entry = Path(__file__).parent / "streamlit_entry.py"
    webview.start = _start_with_persistent_storage
    try:
        start_desktop_app(
            script_path=str(entry),
            title=APP_NAME,
            options={"theme.primaryColor": BRAND_PRIMARY_COLOR},
            width=1280,
            height=800,
        )
    finally:
        webview.start = original_start


if __name__ == "__main__":
    run()

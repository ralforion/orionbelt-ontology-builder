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

import sys
from pathlib import Path

from .app import APP_NAME


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

    entry = Path(__file__).parent / "streamlit_entry.py"
    start_desktop_app(
        script_path=str(entry),
        title=APP_NAME,
        width=1280,
        height=800,
    )


if __name__ == "__main__":
    run()

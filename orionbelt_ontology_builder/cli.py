"""Console entry point for launching the OrionBelt Streamlit app.

Exposed as the ``orionbelt-ontology-builder`` command (see
``[project.scripts]`` in ``pyproject.toml``) so the app can be installed and
run without ``streamlit run`` — e.g. ``uv tool install`` / ``uvx`` / ``pipx``.
"""

import os
import sys
from pathlib import Path

from .local_store import BRAND_PRIMARY_COLOR, ENV_FLAG


def run() -> None:
    """Launch the app via Streamlit, forwarding any extra CLI args.

    Equivalent to ``streamlit run <package>/streamlit_entry.py [args...]``, so
    users can still pass Streamlit flags, e.g.::

        orionbelt-ontology-builder --server.port 8502
    """
    from streamlit.web import cli as stcli

    # This is a local launch with full filesystem access, so opt into the
    # disk-backed autosave / linked-file persistence (the cloud deployment runs
    # ``streamlit run app.py`` directly and never sets this).
    os.environ[ENV_FLAG] = "1"

    # Pass the brand theme as an explicit Streamlit flag so it applies regardless
    # of CWD (config.toml is only found from the repo root) — otherwise the
    # console/desktop runs fall back to Streamlit's default red. Placed before
    # the user's args so an explicit --theme.primaryColor still wins.
    entry = Path(__file__).parent / "streamlit_entry.py"
    sys.argv = [
        "streamlit",
        "run",
        str(entry),
        f"--theme.primaryColor={BRAND_PRIMARY_COLOR}",
        *sys.argv[1:],
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    run()

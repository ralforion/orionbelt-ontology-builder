"""Console entry point for launching the OrionBelt Streamlit app.

Exposed as the ``orionbelt-ontology-builder`` command (see
``[project.scripts]`` in ``pyproject.toml``) so the app can be installed and
run without ``streamlit run`` — e.g. ``uv tool install`` / ``uvx`` / ``pipx``.
"""

import os
import sys
from pathlib import Path

from .local_store import (
    BRAND_PRIMARY_COLOR,
    ENV_FLAG,
    STREAMLIT_OPTIONS,
    resolved_startup_base,
)


def run() -> None:
    """Launch the app via Streamlit, forwarding any extra CLI args.

    Equivalent to ``streamlit run <package>/streamlit_entry.py [args...]``, so
    users can still pass Streamlit flags, e.g.::

        orionbelt-ontology-builder --server.port 8502

    ``--api`` also starts the local HTTP API (and so lets the MCP server in);
    ``--api-port N`` and ``--api-host H`` set where it listens. These three
    are taken out before the rest goes to Streamlit.
    """
    from streamlit.web import cli as stcli

    # This is a local launch with full filesystem access, so opt into the
    # disk-backed autosave / linked-file persistence (the cloud deployment runs
    # ``streamlit run app.py`` directly and never sets this).
    os.environ[ENV_FLAG] = "1"
    args = _take_api_args(sys.argv[1:])

    # Pass the brand theme as an explicit Streamlit flag so it applies regardless
    # of CWD (config.toml is only found from the repo root) — otherwise the
    # console/desktop runs fall back to Streamlit's default red. Placed before
    # the user's args so an explicit --theme.primaryColor still wins.
    # Apply the user's saved startup theme so the app opens the way they left it
    # (issues #70, #78). Placed before the user's args so an explicit
    # --theme.base still wins.
    entry = Path(__file__).parent / "streamlit_entry.py"
    theme_args = [f"--theme.primaryColor={BRAND_PRIMARY_COLOR}"]
    saved_base = resolved_startup_base()
    if saved_base:
        theme_args.append(f"--theme.base={saved_base}")
    option_args = [
        f"--{name}={str(value).lower()}" for name, value in STREAMLIT_OPTIONS.items()
    ]
    sys.argv = [
        "streamlit",
        "run",
        str(entry),
        *theme_args,
        *option_args,
        *args,
    ]
    sys.exit(stcli.main())


def _take_api_args(args: list[str]) -> list[str]:
    """Apply the API flags to the environment; return the other arguments.

    The variables are the ones :mod:`.api.server` reads, so the API is on
    for this launch only and the hosted app, which never sets them, stays off.
    """
    from .api.server import ENV_ENABLE, ENV_HOST, ENV_PORT

    rest: list[str] = []
    values = {"--api-port": ENV_PORT, "--api-host": ENV_HOST}
    it = iter(args)
    for arg in it:
        name, _, inline = arg.partition("=")
        if arg == "--api":
            os.environ[ENV_ENABLE] = "1"
        elif name in values:
            value = inline or next(it, "")
            if not value:
                raise SystemExit(f"{name} needs a value")
            os.environ[values[name]] = value
            os.environ[ENV_ENABLE] = "1"
        else:
            rest.append(arg)
    return rest


if __name__ == "__main__":
    run()

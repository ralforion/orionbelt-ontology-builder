"""Run the HTTP API in a thread of the Streamlit process, once per process.

Off unless asked for: ``ORIONBELT_API=1`` (the ``--api`` launcher flag sets
it). The hosted Streamlit Cloud app never sets it, so it never opens a port.

Settings, all optional:

* ``ORIONBELT_API_HOST`` — default ``127.0.0.1``. Anything else exposes the
  ontology to the network; the token is then all that guards it.
* ``ORIONBELT_API_PORT`` — default ``8765``.
* ``ORIONBELT_API_TOKEN`` — default a fresh random token each start.

On start the URL and token go into ``~/.orionbelt_ontology_builder/api.json``
(owner-only), which is how the MCP server finds the API without being told.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import local_store

if TYPE_CHECKING:
    from .service import Workspace

logger = logging.getLogger(__name__)

ENV_ENABLE = "ORIONBELT_API"
ENV_HOST = "ORIONBELT_API_HOST"
ENV_PORT = "ORIONBELT_API_PORT"
ENV_TOKEN = "ORIONBELT_API_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DISCOVERY_NAME = "api.json"


def api_enabled() -> bool:
    return os.environ.get(ENV_ENABLE, "").strip().lower() in ("1", "true", "yes", "on")


def discovery_file() -> Path:
    return local_store.data_dir() / DISCOVERY_NAME


@dataclass
class ApiStatus:
    url: str = ""
    error: str = ""

    @property
    def running(self) -> bool:
        return bool(self.url) and not self.error


_lock = threading.Lock()
_status: ApiStatus | None = None


def status() -> ApiStatus | None:
    return _status


def _write_discovery(url: str, token: str) -> None:
    path = discovery_file()
    text = json.dumps({"url": url, "token": token, "pid": os.getpid()}, indent=2)
    local_store.atomic_write(path, text)
    try:
        path.chmod(0o600)
    except OSError:  # Windows, or a filesystem without modes
        logger.debug("Could not restrict %s to its owner", path, exc_info=True)


def ensure_started(workspace: Workspace) -> ApiStatus:
    """Start the API server if it is not running yet; return its status."""
    global _status
    with _lock:
        if _status is not None:
            return _status
        try:
            import uvicorn

            from .rest import create_app
            from .service import OntologyService
        except ImportError as e:
            _status = ApiStatus(
                error=f"API extra not installed ({e.name}); "
                "pip install 'orionbelt-ontology-builder[api]'"
            )
            logger.warning(_status.error)
            return _status

        host = os.environ.get(ENV_HOST, DEFAULT_HOST)
        port = int(os.environ.get(ENV_PORT, DEFAULT_PORT))
        token = os.environ.get(ENV_TOKEN) or secrets.token_urlsafe(32)
        app = create_app(OntologyService(workspace), token)
        server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="warning")
        )
        # A port that is taken must not take the app down with it: the error
        # is shown in the sidebar instead.
        started = threading.Event()
        failure: list[str] = []

        def serve() -> None:
            try:
                server.run()
            except SystemExit:
                failure.append(f"could not bind {host}:{port}")
            except Exception as e:  # noqa: BLE001 - reported, never raised into the UI
                failure.append(str(e))
            finally:
                started.set()

        thread = threading.Thread(target=serve, name="orionbelt-api", daemon=True)
        thread.start()
        for _ in range(100):
            if server.started or started.is_set():
                break
            started.wait(0.05)
        if failure or not server.started:
            _status = ApiStatus(error=failure[0] if failure else "did not start")
            logger.warning("OrionBelt API: %s", _status.error)
            return _status
        url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
        _write_discovery(url, token)
        _status = ApiStatus(url=url)
        logger.info("OrionBelt API listening on %s", url)
        return _status

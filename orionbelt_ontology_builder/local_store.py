"""Local-filesystem persistence for the desktop / locally launched app.

The hosted Streamlit Cloud deployment must never write to the local filesystem,
so every feature here is gated behind :func:`local_persist_enabled`, which only
returns ``True`` when the launcher set the ``ORIONBELT_LOCAL_PERSIST`` env var.
The local launchers (:mod:`orionbelt_ontology_builder.cli` and
:mod:`orionbelt_ontology_builder.desktop`) set it; ``streamlit run app.py`` on
the cloud does not, so the app falls back to its browser-``localStorage``
autosave there.

Two disk-backed mechanisms live on top of these helpers (wired up in
``app.py``):

* a **recovery file** (:func:`recovery_file`) that the app mirrors the working
  ontology into on every change, so an unexpected close (crash, freeze) can be
  recovered from on the next launch; and
* an optional **linked working file** whose path the user chooses
  (:func:`get_linked_path` / :func:`set_linked_path`). Pointing it at a synced
  folder (Nextcloud, Dropbox, ...) gives fully automatic off-machine backups.

No third-party dependencies: only the standard library is used.
"""

import json
import os
import tempfile
from pathlib import Path

#: Env var the local launchers set to opt the filesystem features in.
ENV_FLAG = "ORIONBELT_LOCAL_PERSIST"

#: Brand primary colour, mirroring ``.streamlit/config.toml`` ``[theme]``. The
#: launchers export it as ``STREAMLIT_THEME_PRIMARY_COLOR`` so the brand colour
#: applies even when launched outside the repo (where config.toml isn't found
#: and Streamlit would otherwise fall back to its default red).
BRAND_PRIMARY_COLOR = "#0D2B7A"

#: Per-user application data directory (created on demand).
_DIR_NAME = ".orionbelt_ontology_builder"
#: Crash-recovery snapshot the app mirrors the working ontology into.
_RECOVERY_NAME = "recovery.ttl"
#: Small JSON config persisting cross-session settings (e.g. the linked path).
_CONFIG_NAME = "config.json"


def local_persist_enabled() -> bool:
    """True when the launcher opted this run into filesystem persistence.

    Only the local launchers set :data:`ENV_FLAG`; the cloud deployment runs
    ``streamlit run app.py`` without it, so disk access stays off there.
    """
    return os.environ.get(ENV_FLAG, "").strip() not in ("", "0", "false", "False")


def data_dir() -> Path:
    """Return (creating if needed) the per-user application data directory."""
    d = Path.home() / _DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def recovery_file() -> Path:
    """Path of the crash-recovery snapshot inside :func:`data_dir`."""
    return data_dir() / _RECOVERY_NAME


def config_file() -> Path:
    """Path of the JSON settings file inside :func:`data_dir`."""
    return data_dir() / _CONFIG_NAME


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically.

    Writes to a temp file in the same directory and ``os.replace``s it into
    place, so a crash or a backup tool reading mid-write never sees a partial
    or corrupt file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave the partial temp file behind on failure.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_text(path: Path) -> str | None:
    """Return the text contents of ``path``, or ``None`` if it can't be read."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def load_config() -> dict:
    """Load the settings dict, returning ``{}`` when absent or unreadable."""
    raw = read_text(config_file())
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> None:
    """Persist the settings dict to :func:`config_file`."""
    atomic_write(config_file(), json.dumps(config, indent=2))


def get_linked_path() -> Path | None:
    """Return the user's linked working-file path, or ``None`` if unset."""
    p = load_config().get("linked_path")
    if isinstance(p, str) and p.strip():
        return Path(p).expanduser()
    return None


def set_linked_path(path: str | os.PathLike | None) -> None:
    """Set (or clear, when ``path`` is falsy) the linked working-file path."""
    config = load_config()
    if path:
        config["linked_path"] = str(path)
    else:
        config.pop("linked_path", None)
    save_config(config)

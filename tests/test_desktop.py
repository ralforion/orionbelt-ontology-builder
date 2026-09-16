"""Tests for the native desktop launcher (``orionbelt-ontology-builder-desktop``)."""

import importlib.util
import os
import signal
import sys
import threading
import types
from importlib.metadata import entry_points

import pytest

from orionbelt_ontology_builder import desktop
from orionbelt_ontology_builder.app import APP_NAME
from orionbelt_ontology_builder.local_store import BRAND_PRIMARY_COLOR, ENV_FLAG


def test_entry_point_registered():
    """The console_scripts entry point should map to ``desktop:run``."""
    eps = [
        ep
        for ep in entry_points(group="console_scripts")
        if ep.name == "orionbelt-ontology-builder-desktop"
    ]
    assert eps, "orionbelt-ontology-builder-desktop console script not registered"
    assert eps[0].value == "orionbelt_ontology_builder.desktop:run"


def test_run_invokes_start_desktop_app(monkeypatch, tmp_path):
    """``run()`` should open the in-package entry script in a native window."""
    captured = {}

    def _fake_start_desktop_app(**kwargs):
        captured.update(kwargs)

    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = _fake_start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    # pywebview ships only with the optional desktop extra, so stub it out to
    # keep this test runnable without that extra installed.
    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    # Keep the persistent-storage setup off the real home directory.
    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert captured["script_path"].endswith("streamlit_entry.py")
    assert captured["title"] == APP_NAME
    # A native launch runs locally, so disk-backed persistence is opted in.
    assert os.environ[ENV_FLAG] == "1"
    # Brand colour passed as an explicit Streamlit option (not via env) so it
    # applies in the subprocess regardless of CWD.
    assert captured["options"]["theme.primaryColor"] == BRAND_PRIMARY_COLOR


def test_run_enables_persistent_webview_storage(monkeypatch, tmp_path):
    """The launcher should make pywebview persist localStorage across launches.

    streamlit_desktop_app calls ``webview.start()`` with no arguments, which
    defaults to private mode and wipes the saved Streamlit theme on close
    (issue #70). ``run()`` should inject a persistent ``storage_path`` and
    disable private mode, then restore the original ``webview.start``.
    """
    captured = {}

    fake_webview = types.ModuleType("webview")

    def _record_start(*args, **kwargs):
        captured.update(kwargs)

    fake_webview.start = _record_start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    fake_sda = types.ModuleType("streamlit_desktop_app")

    def _start_desktop_app(**kwargs):
        # The real library starts pywebview with no storage arguments.
        import webview

        webview.start()

    fake_sda.start_desktop_app = _start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_sda)

    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert captured["private_mode"] is False
    assert captured["storage_path"] == str(tmp_path / "webview")
    assert (tmp_path / "webview").is_dir()
    # The wrapper must not leak: the original start is restored afterwards.
    assert fake_webview.start is _record_start


def _fake_find_spec(available):
    """Return a ``find_spec`` stub reporting only ``available`` modules present."""

    def _find_spec(name, *args, **kwargs):
        return object() if name in available else None

    return _find_spec


def test_preferred_gui_prefers_gtk_when_pygobject_present(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec({"gi", "qtpy"}))
    assert desktop._preferred_gui() == "gtk"


def test_preferred_gui_falls_back_to_qt(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec({"qtpy"}))
    assert desktop._preferred_gui() == "qt"


def test_preferred_gui_none_without_any_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec(set()))
    assert desktop._preferred_gui() is None


def test_preferred_gui_respects_user_override(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("PYWEBVIEW_GUI", "gtk")
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec({"qtpy"}))
    assert desktop._preferred_gui() is None


def test_preferred_gui_none_on_macos(monkeypatch):
    """macOS should keep Cocoa as the default rather than forcing Qt/GTK."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec({"qtpy"}))
    assert desktop._preferred_gui() is None


def test_run_exports_selected_gui_backend(monkeypatch, tmp_path):
    """``run()`` should export the chosen backend via PYWEBVIEW_GUI."""
    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop, "_preferred_gui", lambda: "qt")
    monkeypatch.delenv("PYWEBVIEW_GUI", raising=False)

    desktop.run()

    assert os.environ["PYWEBVIEW_GUI"] == "qt"


def test_run_reapplies_saved_theme_base(monkeypatch, tmp_path):
    """A saved light/dark preference is passed to start_desktop_app (issue #70)."""
    captured = {}

    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = lambda **kwargs: captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop, "resolved_startup_base", lambda: "dark")
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert captured["options"]["theme.base"] == "dark"


def test_run_omits_theme_base_when_unset(monkeypatch, tmp_path):
    captured = {}

    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = lambda **kwargs: captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)

    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop, "resolved_startup_base", lambda: None)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert "theme.base" not in captured["options"]


class _Event:
    """Minimal stand-in for a pywebview event that supports ``+= handler``.

    Holds its handlers rather than subclassing list: pywebview's Event isn't a
    list either, and ``+=`` taking a single handler is incompatible with
    ``list.__add__`` taking an iterable.
    """

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __getitem__(self, index):
        return self.handlers[index]

    def __len__(self):
        return len(self.handlers)


class _FakeWindow:
    def __init__(self):
        self.exposed = []
        self.title = None
        self.evaluated = []
        # `restored` is real pywebview's; it is kept here so a bridge that
        # started watching it again would be caught rather than skipped.
        self.events = types.SimpleNamespace(loaded=_Event(), restored=_Event())

    def expose(self, *fns):
        self.exposed.extend(fns)

    def set_title(self, title):
        self.title = title

    def evaluate_js(self, js):
        self.evaluated.append(js)


def test_window_title_sync_wiring(monkeypatch):
    """The bridge hook exposes a title setter and injects the observer, and the
    setter mirrors the page title onto the window (issue #90)."""
    window = _FakeWindow()
    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = lambda *a, **k: window
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    original = desktop._install_window_bridges("AppName")
    assert original is not None  # a real create_window was hooked

    # start_desktop_app would call create_window; simulate that.
    import webview

    returned = webview.create_window("AppName", "http://localhost")
    assert returned is window

    # The setter was exposed to JS, and mirrors a real title through.
    assert window.exposed, "title setter was not exposed"
    setter = window.exposed[0]
    setter("Pizza Ontology · OrionBelt")
    assert window.title == "Pizza Ontology · OrionBelt"
    # The Streamlit default / empty title falls back to the app name.
    setter("Streamlit")
    assert window.title == "AppName"
    setter("")
    assert window.title == "AppName"

    # On load, the MutationObserver script is injected.
    assert window.events.loaded, "no loaded handler registered"
    window.events.loaded[0]()
    assert any("MutationObserver" in js for js in window.evaluated)


def test_window_title_sync_noop_without_create_window(monkeypatch):
    """A stubbed webview lacking create_window must not raise (returns None)."""
    fake_webview = types.ModuleType("webview")  # no create_window attribute
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    assert desktop._install_window_bridges("AppName") is None


def test_window_bridges_wire_clipboard(monkeypatch):
    """The bridge hook exposes a clipboard writer and injects the bridge script,
    and the exposed writer delegates to the OS clipboard helper (issue #120)."""
    window = _FakeWindow()
    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = lambda *a, **k: window
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    desktop._install_window_bridges("AppName")

    import webview

    webview.create_window("AppName", "http://localhost")

    # The clipboard writer is exposed alongside the title setter, and routes
    # text through _copy_to_clipboard.
    copied = {}

    def _fake_copy(text):
        copied["text"] = text
        return True

    monkeypatch.setattr(desktop, "_copy_to_clipboard", _fake_copy)
    writer = next(
        fn for fn in window.exposed if fn.__name__ == "orionbelt_copy_to_clipboard"
    )
    assert writer("http://example.org/ontology#Dog") is True
    assert copied["text"] == "http://example.org/ontology#Dog"
    # None coalesces to an empty string rather than crashing.
    assert writer(None) is True
    assert copied["text"] == ""

    # On load, the clipboard bridge script is injected.
    window.events.loaded[0]()
    assert any("__orionbeltClipboardBridge" in js for js in window.evaluated)


def test_the_window_is_never_put_into_fullscreen(monkeypatch):
    """The graph's Fullscreen button hides the app's chrome and stops there.

    It used to route through a bridge to pywebview's toggle_fullscreen() where
    the webview had no HTML Fullscreen API (issue #177), which took the whole
    desktop window into fullscreen along with the graph. Nothing asks for the
    screen any more (issue #390), so nothing is exposed to ask with.
    """
    window = _FakeWindow()
    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = lambda *a, **k: window
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    desktop._install_window_bridges("AppName")

    import webview

    webview.create_window("AppName", "http://localhost")

    assert [fn.__name__ for fn in window.exposed] == [
        "orionbelt_set_window_title",
        "orionbelt_copy_to_clipboard",
    ]
    # ...and no window event is watched for a fullscreen exit that can't happen.
    assert not window.events.restored, "nothing should watch for a native exit"


def test_copy_to_clipboard_uses_platform_command(monkeypatch):
    """Each platform writes stdin to its native clipboard tool (issue #120)."""
    calls = {}

    def _fake_run(command, input, check):
        calls["command"] = command
        calls["input"] = input
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(desktop.subprocess, "run", _fake_run)

    monkeypatch.setattr(sys, "platform", "darwin")
    assert desktop._copy_to_clipboard("Dog") is True
    assert calls["command"] == ["pbcopy"]
    assert calls["input"] == b"Dog"

    monkeypatch.setattr(sys, "platform", "win32")
    assert desktop._copy_to_clipboard("Dog") is True
    assert calls["command"] == ["clip"]


def test_copy_to_clipboard_falls_back_across_linux_tools(monkeypatch):
    """On Linux, an unavailable tool is skipped for the next candidate."""
    tried = []

    def _fake_run(command, input, check):
        tried.append(command[0])
        if command[0] == "wl-copy":
            raise FileNotFoundError("wl-copy")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.subprocess, "run", _fake_run)

    assert desktop._copy_to_clipboard("Dog") is True
    assert tried == ["wl-copy", "xclip"]


def test_copy_to_clipboard_returns_false_when_unavailable(monkeypatch):
    """With no working clipboard tool, it reports failure instead of raising."""
    monkeypatch.setattr(sys, "platform", "linux")

    def _fake_run(command, input, check):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(desktop.subprocess, "run", _fake_run)
    assert desktop._copy_to_clipboard("Dog") is False


def test_run_without_dependency_exits_cleanly(monkeypatch):
    """Missing the optional ``desktop`` extra should exit non-zero, not crash."""
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", None)

    with pytest.raises(SystemExit) as excinfo:
        desktop.run()

    assert excinfo.value.code == 1


def _stub_desktop_library(monkeypatch, start_desktop_app):
    """Install a fake ``streamlit_desktop_app`` with a ``core.run_streamlit``."""
    fake_core = types.ModuleType("streamlit_desktop_app.core")
    fake_core.run_streamlit = lambda script_path, options: None
    fake_sda = types.ModuleType("streamlit_desktop_app")
    fake_sda.core = fake_core
    fake_sda.start_desktop_app = start_desktop_app
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_sda)
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app.core", fake_core)
    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    return fake_core


def test_run_installs_the_server_watchdog_for_the_launch(monkeypatch, tmp_path):
    """The library's server target is the watched one during the launch only.

    The launcher's ``finally`` stops the server on a normal close, but not when
    the launcher dies first (logout, a webview crash, SIGKILL), which left an
    idle server behind each time (issue #437). ``start_desktop_app`` looks the
    target up on its module at call time, so it is rebound there for the call
    and restored afterwards, even when the launch raises.
    """
    seen = {}

    def _start_desktop_app(**kwargs):
        from streamlit_desktop_app import core

        seen["target"] = core.run_streamlit
        seen["kept"] = desktop._original_run_streamlit
        raise RuntimeError("window backend failed")

    fake_core = _stub_desktop_library(monkeypatch, _start_desktop_app)
    original = fake_core.run_streamlit
    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    with pytest.raises(RuntimeError):
        desktop.run()

    assert seen["target"] is desktop._run_streamlit_watched
    assert seen["kept"] is original
    assert fake_core.run_streamlit is original
    assert desktop._original_run_streamlit is None


def test_run_tolerates_a_library_without_the_server_target(monkeypatch, tmp_path):
    """No ``core.run_streamlit`` (an older library, a stub): launch without it."""
    called = {}
    fake_module = types.ModuleType("streamlit_desktop_app")
    fake_module.start_desktop_app = lambda **kwargs: called.setdefault("ok", True)
    monkeypatch.setitem(sys.modules, "streamlit_desktop_app", fake_module)
    fake_webview = types.ModuleType("webview")
    fake_webview.start = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop, "data_dir", lambda: tmp_path)
    monkeypatch.delenv(ENV_FLAG, raising=False)

    desktop.run()

    assert called["ok"] is True
    assert desktop._original_run_streamlit is None


class _FakeParent:
    """Stands in for ``multiprocessing.parent_process()``: gone once ``ended`` is set."""

    def __init__(self):
        self.ended = threading.Event()

    def join(self, timeout=None):
        self.ended.wait(timeout)


def test_watched_server_runs_the_original_and_stops_when_the_launcher_dies(
    monkeypatch,
):
    """The child runs the library's server, and its watchdog waits on the parent.

    Nothing happens while the launcher lives; once its sentinel closes the
    child sends itself the SIGTERM the library uses on a normal close, so
    Streamlit shuts down through its own handler.
    """
    ran = {}
    stopped = threading.Event()
    sent = {}
    parent = _FakeParent()

    def _run_streamlit(script_path, options):
        ran["args"] = (script_path, options)

    def _kill(pid, sig):
        sent["pid"], sent["sig"] = pid, sig
        stopped.set()

    monkeypatch.setattr(desktop, "_original_run_streamlit", _run_streamlit)
    monkeypatch.setattr(desktop.multiprocessing, "parent_process", lambda: parent)
    monkeypatch.setattr(desktop.os, "kill", _kill)
    monkeypatch.setattr(desktop.os, "_exit", lambda code: None)
    monkeypatch.setattr(desktop, "_EXIT_GRACE_SECONDS", 0)

    desktop._run_streamlit_watched("entry.py", {"server.port": "1"})

    assert ran["args"] == ("entry.py", {"server.port": "1"})
    watchdogs = [
        t for t in threading.enumerate() if t.name == "orionbelt-exit-with-launcher"
    ]
    assert len(watchdogs) == 1 and watchdogs[0].daemon
    assert not stopped.wait(0.2)

    parent.ended.set()

    assert stopped.wait(5)
    assert sent == {"pid": os.getpid(), "sig": signal.SIGTERM}
    watchdogs[0].join(5)


def test_watched_server_takes_the_library_target_in_a_spawned_child(monkeypatch):
    """Under ``spawn`` the child imports this module afresh, with nothing kept.

    It must then fall back to the library's own ``run_streamlit`` rather than
    call itself.
    """
    ran = {}
    fake_core = _stub_desktop_library(monkeypatch, lambda **kwargs: None)
    fake_core.run_streamlit = lambda script_path, options: ran.setdefault(
        "args", (script_path, options)
    )
    monkeypatch.setattr(desktop, "_original_run_streamlit", None)
    monkeypatch.setattr(desktop.multiprocessing, "parent_process", lambda: None)

    desktop._run_streamlit_watched("entry.py", {})

    assert ran["args"] == ("entry.py", {})


def test_watchdog_is_inert_without_a_parent_process(monkeypatch):
    """Run directly (no parent sentinel) the watchdog returns at once."""
    monkeypatch.setattr(desktop.multiprocessing, "parent_process", lambda: None)
    killed = []
    monkeypatch.setattr(desktop.os, "kill", lambda *a: killed.append(a))

    desktop._exit_with_launcher()

    assert killed == []

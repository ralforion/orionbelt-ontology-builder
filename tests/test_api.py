"""The local API (service + REST) and the MCP server that is its client."""

import asyncio
import json
import threading
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from ontology_manager import OntologyManager
from orionbelt_ontology_builder import mcp_server
from orionbelt_ontology_builder.api.rest import create_app
from orionbelt_ontology_builder.api.service import (
    Busy,
    Conflict,
    LocalWorkspace,
    NotFound,
    OntologyService,
    ServiceError,
)

BASE = "http://test.org/ont#"
TOKEN = "secret-token"


@pytest.fixture
def workspace():
    m = OntologyManager(base_uri=BASE)
    m.add_class("Agent", label="Agent")
    m.add_class("Person", parent="Agent", label="Person", comment="A human being")
    m.add_class("Organization", parent="Agent")
    m.add_object_property("worksFor", domain="Person", range_="Organization")
    m.add_individual("alice", "Person", label="Alice")
    m.add_individual("acme", "Organization")
    m.add_individual_property("alice", "worksFor", "acme")
    return LocalWorkspace(m)


@pytest.fixture
def service(workspace):
    return OntologyService(workspace, lock_timeout=0.2)


@pytest.fixture
def client(service):
    return TestClient(
        create_app(service, TOKEN), headers={"Authorization": f"Bearer {TOKEN}"}
    )


# -- service: asking ------------------------------------------------------


def test_overview(service):
    o = service.overview()
    assert o["statistics"]["classes"] == 3
    assert o["top_classes"] == ["Agent"]
    assert o["revision"]


def test_list_and_find(service):
    subs = service.list_entities("class", parent="Agent")
    assert {i["name"] for i in subs["items"]} == {"Person", "Organization"}
    members = service.list_entities("individual", parent="Person")
    assert [i["name"] for i in members["items"]] == ["alice"]
    found = service.find_entities("human")
    assert found["items"][0]["name"] == "Person"
    assert found["items"][0]["kind"] == "class"


def test_describe_by_name_uri_and_prefix(service):
    by_name = service.describe("Person")
    assert by_name["kind"] == "class"
    assert by_name["properties_with_domain"] == ["worksFor"]
    assert by_name["individuals"]["sample"] == ["alice"]
    assert service.describe(BASE + "Person")["uri"] == by_name["uri"]
    with pytest.raises(NotFound):
        service.describe("Nobody")


def test_hierarchy_and_paths(service):
    tree = service.hierarchy("class")
    agent = tree["roots"][0]
    assert agent["name"] == "Agent"
    assert {c["name"] for c in agent["children"]} == {"Organization", "Person"}
    route = service.paths("alice", "acme")
    assert route["connected"]
    assert route["paths"][0][0]["relation"] == "worksFor"


def test_sparql_is_read_only(service):
    res = service.sparql("SELECT ?c WHERE { ?c a owl:Class } ORDER BY ?c")
    assert res["row_count"] == 3
    with pytest.raises(ServiceError):
        service.sparql("INSERT DATA { <urn:a> <urn:b> <urn:c> }")


# -- service: changing ----------------------------------------------------


def test_edit_batch_is_one_undo_step(service, workspace):
    rev = service.overview()["revision"]
    out = service.edit(
        [
            {"op": "add_class", "name": "Employee", "parent": "Person"},
            {
                "op": "add_data_property",
                "name": "salary",
                "domain": "Employee",
                "range": "decimal",
            },
        ],
        expected_revision=rev,
    )
    assert out["applied"] and out["diff"]["added"] > 0
    assert workspace.undo().undo_labels == [out["label"]]
    assert workspace.writes == [out["label"]]
    service.undo()
    with pytest.raises(NotFound):
        service.describe("Employee")


def test_dry_run_keeps_nothing_and_keeps_the_revision(service, workspace):
    rev = service.overview()["revision"]
    out = service.edit(
        [{"op": "add_class", "name": "Robot", "parent": "Agent"}], dry_run=True
    )
    assert not out["applied"]
    assert any("Robot" in t for t in out["diff"]["added_sample"])
    with pytest.raises(NotFound):
        service.describe("Robot")
    assert workspace.writes == []
    # The preview did not "change" the ontology, so the real call still goes,
    # and says it started from the revision it was checked against.
    out = service.edit([{"op": "add_class", "name": "Robot"}], expected_revision=rev)
    assert out["revision_before"] == rev


def test_failed_batch_rolls_everything_back(service):
    with pytest.raises(ServiceError) as err:
        service.edit([{"op": "add_class", "name": "Ghost"}, {"op": "no_such_op"}])
    assert err.value.details["rolled_back"]
    with pytest.raises(NotFound):
        service.describe("Ghost")
    with pytest.raises(ServiceError) as err:
        service.edit([{"op": "add_class", "name": "X", "colour": "red"}])
    assert "name" in err.value.details["parameters"]


def test_stale_revision_is_refused(service):
    rev = service.overview()["revision"]
    service.edit([{"op": "add_class", "name": "A1"}])
    service.edit([{"op": "add_class", "name": "Dry"}], dry_run=True)
    with pytest.raises(Conflict) as err:
        service.edit([{"op": "add_class", "name": "A2"}], expected_revision=rev)
    # The revision to start again from, as a read reports it.
    assert err.value.details["revision"] == service.overview()["revision"]


def test_a_change_between_dry_run_and_apply_is_refused(service, workspace):
    """A user's edit in the app between an agent's preview and its apply."""
    ttl = f"@prefix : <{BASE}> . @prefix owl: <http://www.w3.org/2002/07/owl#> .\n:Team a owl:Class ."
    preview = service.merge_rdf(ttl)
    workspace.manager().add_class("FromTheUser")
    workspace.undo().checkpoint("Add class FromTheUser")
    with pytest.raises(Conflict):
        service.merge_rdf(ttl, dry_run=False, expected_revision=preview["revision"])


def test_merge_turtle(service):
    ttl = f"@prefix : <{BASE}> . @prefix owl: <http://www.w3.org/2002/07/owl#> .\n:Team a owl:Class ."
    preview = service.merge_rdf(ttl)
    assert preview["applied"] is False and preview["diff"]["added"] == 1
    service.merge_rdf(ttl, dry_run=False)
    assert service.describe("Team")["kind"] == "class"
    with pytest.raises(ServiceError):
        service.merge_rdf("not turtle at all {")


def test_busy_lock_answers_busy(service, workspace):
    held = threading.Event()
    release = threading.Event()

    def hold():
        with workspace.locked(1):
            held.set()
            release.wait(2)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(1)
    try:
        with pytest.raises(Busy):
            service.overview()
    finally:
        release.set()
        t.join()


# -- REST -----------------------------------------------------------------


def test_rest_needs_the_token(service):
    anon = TestClient(create_app(service, TOKEN))
    assert anon.get("/v1/health").status_code == 200
    assert anon.get("/v1/overview").status_code == 401
    bad = anon.get("/v1/overview", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_rest_round_trip(client):
    assert client.get("/v1/entities", params={"q": "alice"}).json()["total"] == 1
    # A full URI with '#' survives the path once encoded.
    r = client.get("/v1/entities/" + quote(BASE + "Person", safe=""))
    assert r.status_code == 200 and r.json()["name"] == "Person"
    r = client.post(
        "/v1/edits", json={"operations": [{"op": "delete_class", "name": "Nobody"}]}
    )
    assert r.status_code in (400, 404)
    assert r.json()["rolled_back"]
    assert client.get("/v1/entities/Nobody").status_code == 404


def test_rest_conflict_status(client):
    rev = client.get("/v1/overview").json()["revision"]
    client.post("/v1/edits", json={"operations": [{"op": "add_class", "name": "B1"}]})
    r = client.post(
        "/v1/edits",
        json={
            "operations": [{"op": "add_class", "name": "B2"}],
            "expected_revision": rev,
        },
    )
    assert r.status_code == 409


# -- MCP ------------------------------------------------------------------


@pytest.fixture
def mcp_into_app(service, monkeypatch):
    """Route the MCP server's HTTP calls into the REST app, in process."""
    app = create_app(service, TOKEN)
    monkeypatch.setitem(mcp_server._override, "url", "http://app")
    monkeypatch.setitem(mcp_server._override, "token", TOKEN)
    monkeypatch.setitem(
        mcp_server._client_options, "transport", httpx.ASGITransport(app=app)
    )


def _tool(name, **args):
    result = asyncio.run(mcp_server.mcp.call_tool(name, args))
    assert not getattr(result, "is_error", False), result
    return result.structured_content or json.loads(result.content[0].text)


def test_mcp_tool_surface_is_small():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert len(names) <= 12
    assert {"describe_entity", "sparql_query", "edit_ontology", "merge_turtle"} <= names


def test_mcp_edit_description_lists_every_op():
    from orionbelt_ontology_builder.api.service import EDIT_OPS

    tool = next(
        t for t in asyncio.run(mcp_server.mcp.list_tools()) if t.name == "edit_ontology"
    )
    for op in EDIT_OPS:
        assert f"- {op}(" in tool.description


@pytest.mark.usefixtures("mcp_into_app")
def test_mcp_ask_and_edit_through_the_api(service):
    assert _tool("describe_entity", ref=BASE + "Person")["name"] == "Person"
    rev = _tool("ontology_overview")["revision"]
    out = _tool(
        "edit_ontology",
        operations=[{"op": "add_class", "name": "Contractor", "parent": "Person"}],
        expected_revision=rev,
    )
    assert out["applied"]
    assert service.describe("Contractor")["parents"] == ["Person"]
    assert _tool("undo_redo", action="undo")["label"]


def test_mcp_without_a_running_app_says_how_to_start_it(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mcp_server, "_discovery_path", lambda: tmp_path / "missing.json"
    )
    monkeypatch.delenv(mcp_server.ENV_URL, raising=False)
    monkeypatch.delenv(mcp_server.ENV_TOKEN, raising=False)
    with pytest.raises(ToolError, match="--api"):
        asyncio.run(mcp_server.mcp.call_tool("ontology_overview", {}))


# -- telling the user -----------------------------------------------------


class _RecordingWorkspace(LocalWorkspace):
    def __init__(self, manager):
        super().__init__(manager)
        self.details: list[tuple[str, str]] = []

    def note_write(self, label, detail=""):
        super().note_write(label, detail)
        self.details.append((label, detail))


def test_writes_carry_a_named_label_and_triple_counts(workspace):
    rec = _RecordingWorkspace(workspace.manager())
    svc = OntologyService(rec)
    svc.edit(
        [
            {"op": "add_class", "name": "Employee", "parent": "Person"},
            {"op": "add_class", "name": "Intern", "parent": "Employee"},
        ]
    )
    label, detail = rec.details[-1]
    assert label == "API: add_class Employee (+1)"
    assert detail.startswith("+") and "triples" in detail
    svc.edit([{"op": "add_class", "name": "Dry"}], dry_run=True)
    assert len(rec.details) == 1  # a dry run tells nobody
    svc.undo()
    assert rec.details[-1] == ("API: Undo", "API: add_class Employee (+1)")


def test_toast_text_names_a_few_and_counts_the_rest():
    from orionbelt_ontology_builder.api.bridge import AgentChange, toast_text

    one = [AgentChange(1, 0, "API: add_class Employee", "+3 / −0 triples")]
    assert toast_text(one) == (
        "Agent changed the ontology: add_class Employee (+3 / −0 triples). "
        "Undo is in the sidebar."
    )
    many = [AgentChange(i, 0, f"API: add_class C{i}") for i in range(1, 6)]
    text = toast_text(many)
    assert text.startswith(
        "Agent made 5 changes: add_class C3; add_class C4; add_class C5"
    )
    assert "and 2 earlier" in text


@pytest.fixture
def api_on(monkeypatch, tmp_path):
    """The bridge as the app runs it with the API on, minus the real server."""
    from streamlit.runtime.state.safe_session_state import SafeSessionState

    from orionbelt_ontology_builder.api import bridge, server

    monkeypatch.setenv(server.ENV_ENABLE, "1")
    # The real server is not needed: the bridge's workspace is what the API
    # would call, so drive it directly through a service.
    monkeypatch.setattr(server, "_status", server.ApiStatus(url="http://127.0.0.1:0"))
    monkeypatch.setattr(bridge, "WORKSPACE", bridge.StreamlitWorkspace())
    monkeypatch.setattr(server.local_store, "data_dir", lambda: tmp_path)
    # The bridge wraps a Streamlit method for the callbacks; unwrap it after.
    monkeypatch.setattr(
        SafeSessionState,
        "on_script_will_rerun",
        SafeSessionState.on_script_will_rerun,
    )
    return bridge


def _bridge_script():
    from orionbelt_ontology_builder.api import bridge
    from orionbelt_ontology_builder.ui import init_session_state

    with bridge.run_guard():
        init_session_state()
        bridge.absorb_api_writes()
        bridge.render_sidebar_status()


def test_ui_toasts_and_lists_an_agent_change(api_on):
    from streamlit.testing.v1 import AppTest

    bridge = api_on
    at = AppTest.from_function(_bridge_script, default_timeout=60)
    at.run()
    assert not at.exception
    assert not at.toast  # nothing changed yet

    OntologyService(bridge.WORKSPACE).edit([{"op": "add_class", "name": "FromAgent"}])
    at.run()
    assert not at.exception
    assert "add_class FromAgent" in at.toast[0].value
    assert any(
        "FromAgent" in c["name"] for c in at.session_state["ontology"].get_classes()
    )
    assert at.session_state["undo_manager"].undo_labels == ["API: add_class FromAgent"]
    listed = [c.value for c in at.sidebar.expander[0].caption]
    assert "add_class FromAgent" in listed[0]

    at.run()
    assert not at.toast  # shown once, not on every run


def _callback_script():
    import threading

    import streamlit as st

    from orionbelt_ontology_builder.api import bridge

    def lock_is_free() -> bool:
        free = []

        def probe():
            got = bridge.WORKSPACE.lock.acquire(blocking=False)
            if got:
                bridge.WORKSPACE.lock.release()
            free.append(got)

        t = threading.Thread(target=probe)
        t.start()
        t.join()
        return free[0]

    def on_click():
        st.session_state["free_in_callback"] = lock_is_free()

    with bridge.run_guard():
        st.button("Edit", on_click=on_click)


def test_widget_callbacks_hold_the_api_lock(api_on):
    """Streamlit runs callbacks before the body, outside run_guard's lock."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_callback_script, default_timeout=60)
    at.run()
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["free_in_callback"] is False


def test_sidebar_lines_shorten_home_but_copy_in_full():
    from pathlib import Path

    from orionbelt_ontology_builder.api.bridge import status_lines

    token_file = Path.home() / ".orionbelt_ontology_builder" / "api.json"
    api, token = status_lines("http://127.0.0.1:8765", token_file)
    assert (api["label"], api["value"]) == ("API:", "http://127.0.0.1:8765")
    assert token["label"] == "Token in:"
    assert token["value"] == str(token_file)
    assert token["shown"] == str(Path("~", ".orionbelt_ontology_builder", "api.json"))
    outside = Path("/srv/orionbelt/api.json")
    assert status_lines("u", outside)[1]["shown"] == str(outside)
    # A token the user set is not looked up, so there is no line for its file.
    assert [line["label"] for line in status_lines("u", None)] == ["API:"]


class _FakeUvicornServer:
    """Starts at once and serves nothing, so ensure_started can be run."""

    def __init__(self, config):
        self.started = False

    def run(self):
        self.started = True


@pytest.mark.parametrize("given", [None, "my-own-token"])
def test_the_status_knows_whether_the_token_was_given(monkeypatch, tmp_path, given):
    import uvicorn

    from orionbelt_ontology_builder.api import server

    monkeypatch.setattr(uvicorn, "Server", _FakeUvicornServer)
    monkeypatch.setattr(server, "_status", None)
    monkeypatch.setattr(server.local_store, "data_dir", lambda: tmp_path)
    if given:
        monkeypatch.setenv(server.ENV_TOKEN, given)
    else:
        monkeypatch.delenv(server.ENV_TOKEN, raising=False)

    status = server.ensure_started(LocalWorkspace())

    assert status.running
    assert status.token_given is bool(given)
    written = json.loads((tmp_path / server.DISCOVERY_NAME).read_text())["token"]
    assert written == given if given else written

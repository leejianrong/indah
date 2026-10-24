"""The opt-in X-Indah-Node header and ctx.conn.node (IND-203)."""

import ipaddress

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

import indah
from indah.node import resolve_node


def _factory(ctx: indah.Context):
    seen.append(ctx.conn.node)
    return indah.Session(indah.Text("hi"))


seen: list[str] = []


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("INDAH_NODE", "INDAH_NODE_HEADER", "FLY_MACHINE_ID", "HOSTNAME"):
        monkeypatch.delenv(name, raising=False)
    seen.clear()


@pytest.mark.unit
def test_the_order_is_indah_node_then_fly_then_hostname():
    env = {"INDAH_NODE": "a", "FLY_MACHINE_ID": "b", "HOSTNAME": "c"}
    assert resolve_node(env) == "a"
    assert resolve_node({"FLY_MACHINE_ID": "b", "HOSTNAME": "c"}) == "b"
    assert resolve_node({"HOSTNAME": "pod-7d9f-x2"}) == "pod-7d9f-x2"


@pytest.mark.unit
def test_without_any_variable_a_short_random_id_is_stable_for_the_process():
    first = resolve_node({})
    assert first == resolve_node({})
    assert 6 <= len(first) <= 16 and first.isalnum()


@pytest.mark.unit
@pytest.mark.parametrize("value", ["10.1.2.3", "172.16.1.226", "2a09:8280:1::1c9:9684:0", "::1"])
def test_an_address_is_never_used_as_the_id(value):
    node = resolve_node({"INDAH_NODE": value})
    assert node != value
    with pytest.raises(ValueError):
        ipaddress.ip_address(node)
    assert node == resolve_node({"INDAH_NODE": value})  # stable, so affinity can still be read


@pytest.mark.unit
@pytest.mark.parametrize("value", ["has space", "bad\r\nX-Evil: 1", "naïve", "x" * 200, "a/b"])
def test_an_unsafe_value_is_replaced_by_an_opaque_id(value):
    node = resolve_node({"INDAH_NODE": value})
    assert node and all(c.isalnum() or c in "._-" for c in node) and len(node) <= 64


@pytest.mark.unit
def test_the_header_is_off_by_default():
    client = TestClient(indah.create_app(session_factory=_factory))
    assert "x-indah-node" not in client.get("/").headers
    assert "x-indah-node" not in client.get("/health").headers


@pytest.mark.unit
def test_the_header_is_on_every_response_when_enabled(monkeypatch):
    monkeypatch.setenv("INDAH_NODE", "pod-a")
    app = indah.create_app(session_factory=_factory, node_header=True)
    client = TestClient(app)
    assert app.state.node == "pod-a"
    for path in ("/", "/health", "/ready", "/api/editor.js", "/no-such-route"):
        assert client.get(path).headers["x-indah-node"] == "pod-a", path
    assert client.post("/api/event", content=b"{}").headers["x-indah-node"] == "pod-a"


@pytest.mark.unit
def test_enabled_by_the_environment_and_overridden_by_the_argument(monkeypatch):
    monkeypatch.setenv("INDAH_NODE", "pod-a")
    monkeypatch.setenv("INDAH_NODE_HEADER", "1")
    on = indah.create_app(session_factory=_factory)
    assert TestClient(on).get("/").headers["x-indah-node"] == "pod-a"
    assert "INDAH_NODE_HEADER" in on.state.env_used
    off = indah.create_app(session_factory=_factory, node_header=False)
    assert "x-indah-node" not in TestClient(off).get("/").headers


@pytest.mark.unit
def test_a_bad_value_for_the_switch_names_the_variable(monkeypatch):
    monkeypatch.setenv("INDAH_NODE_HEADER", "sometimes")
    with pytest.raises(ValueError, match="INDAH_NODE_HEADER"):
        indah.create_app(session_factory=_factory)


@pytest.mark.unit
def test_connection_info_carries_the_node_with_the_header_off(monkeypatch):
    from starlette.requests import Request

    from indah.context import ConnectionInfo

    monkeypatch.setenv("FLY_MACHINE_ID", "e826010b63e458")
    app = indah.create_app(session_factory=_factory)
    assert app.state.node_header is False
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "app": app,
    }
    assert ConnectionInfo.from_request(Request(scope)).node == "e826010b63e458"
    assert ConnectionInfo().node == ""  # a bare Context, as in a test, has none


@pytest.mark.unit
def test_it_works_with_csp_compression_secure_and_a_mount(monkeypatch):
    monkeypatch.setenv("INDAH_NODE", "pod-a")
    app = indah.create_app(
        session_factory=_factory,
        node_header=True,
        csp="strict",
        compress=True,
        secure=True,
        secret="s" * 32,
    )
    client = TestClient(app)
    shell = client.get("/", headers={"accept-encoding": "gzip"})
    assert shell.headers["x-indah-node"] == "pod-a"
    refused = client.get("/api/stream?sid=x")  # secure and not logged in: refused, still tagged
    assert refused.status_code in (401, 403)
    assert refused.headers["x-indah-node"] == "pod-a"
    mounted = TestClient(Starlette(routes=[Mount("/ui", app=app)]))
    assert mounted.get("/ui/").headers["x-indah-node"] == "pod-a"


@pytest.mark.unit
def test_a_draining_process_still_names_itself(monkeypatch):
    monkeypatch.setenv("INDAH_NODE", "pod-a")
    app = indah.create_app(session_factory=_factory, node_header=True)
    app.state.drain.draining = True
    ready = TestClient(app).get("/ready")
    assert ready.status_code == 503
    assert ready.headers["x-indah-node"] == "pod-a"

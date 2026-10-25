"""The route hint on a real app (IND-197, ADR-0043): ``init.route``, file URLs, Fly replay."""

import json

import httpx
import pytest

from indah import create_app, launch
from indah.components import Button, Column, Download
from indah.reactive import Signal
from indah.session import Session

SECRET = "a-cluster-secret-of-some-length"
MACHINE = "e826010b63e458"
OTHER = "d8d1e2a5f3b7c9"


@pytest.fixture
def on_fly(monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", MACHINE)
    monkeypatch.setenv("INDAH_CLUSTER_SECRET", SECRET)
    monkeypatch.delenv("INDAH_ROUTE_HINT", raising=False)
    monkeypatch.delenv("INDAH_NODE", raising=False)


@pytest.fixture
def off_fly(monkeypatch):
    for name in ("FLY_MACHINE_ID", "INDAH_CLUSTER_SECRET", "INDAH_ROUTE_HINT", "INDAH_NODE"):
        monkeypatch.delenv(name, raising=False)


def _factory() -> Session:
    data = Signal(b"")

    def make():
        data.set(b"a,b\n1,2\n")

    return Session(
        Column(
            children=[
                Button("Make", on_click=make),
                Download(data, label="Get", filename="r.csv", media_type="text/csv"),
            ]
        )
    )


def _init_of(url: str, sid: str) -> dict:
    with httpx.stream("GET", url + "/api/stream", params={"sid": sid}, timeout=5) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    raise AssertionError("no message")


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
def test_init_carries_the_route_on_fly_with_a_cluster_secret(on_fly):
    handle = launch(create_app(session_factory=_factory), block=False, open_inline=False)
    try:
        init = _init_of(handle.url, "t1")
        assert init["type"] == "init"
        assert init["route"] == {"hint": MACHINE, "node": MACHINE, "transport": "fly"}
    finally:
        handle.stop()


@pytest.mark.integration
def test_init_has_no_route_when_the_hint_is_off(off_fly, monkeypatch):
    handle = launch(create_app(session_factory=_factory), block=False, open_inline=False)
    try:
        assert "route" not in _init_of(handle.url, "t1")
    finally:
        handle.stop()
    monkeypatch.setenv("FLY_MACHINE_ID", MACHINE)  # on Fly, but no cluster secret
    handle = launch(create_app(session_factory=_factory), block=False, open_inline=False)
    try:
        assert "route" not in _init_of(handle.url, "t2")
    finally:
        handle.stop()


@pytest.mark.integration
def test_the_arguments_beat_the_environment(off_fly, monkeypatch):
    monkeypatch.setenv("FLY_MACHINE_ID", MACHINE)
    app = create_app(session_factory=_factory, cluster_secret=SECRET)
    assert app.state.route_hint is not None
    app = create_app(session_factory=_factory, cluster_secret=SECRET, route_hint="off")
    assert app.state.route_hint is None


@pytest.mark.integration
def test_a_bad_setting_fails_when_the_app_is_made(off_fly):
    with pytest.raises(ValueError, match="route_hint="):
        create_app(session_factory=_factory, route_hint="sometimes")


@pytest.mark.integration
async def test_a_served_file_url_carries_the_hint(on_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        await client.post("/api/event", json={"sid": "t1", "component": "n1", "event": "click"})
        href = app.state.store.get("t1").session.snapshot()["children"][1]["props"]["href"]
        assert href.startswith("api/file/t1/")
        assert href.endswith(f"?r={MACHINE}")
        resp = await client.get("/" + href)  # the query is ignored by the owner
    assert resp.status_code == 200
    assert resp.content == b"a,b\n1,2\n"


@pytest.mark.integration
async def test_a_served_file_url_has_no_hint_when_it_is_off(off_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        await client.post("/api/event", json={"sid": "t1", "component": "n1", "event": "click"})
        href = app.state.store.get("t1").session.snapshot()["children"][1]["props"]["href"]
    assert "?" not in href


@pytest.mark.integration
async def test_a_misrouted_file_get_is_replayed_to_the_owner(on_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        resp = await client.get(f"/api/file/not-here/tok?r={OTHER}")
    assert resp.headers["fly-replay"] == f"instance={OTHER}"


@pytest.mark.integration
async def test_a_replayed_get_is_not_replayed_again_and_odd_hints_are_ignored(on_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        again = await client.get(
            f"/api/file/not-here/tok?r={OTHER}", headers={"fly-replay-src": "instance=x"}
        )
        mine = await client.get(f"/api/file/not-here/tok?r={MACHINE}")
        odd = await client.get("/api/file/not-here/tok?r=a%0d%0ab")
        none = await client.get("/api/file/not-here/tok")
    for resp in (again, mine, odd, none):
        assert "fly-replay" not in resp.headers
        assert resp.status_code == 404


@pytest.mark.integration
async def test_nothing_is_replayed_when_the_hint_is_off(off_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        resp = await client.get(f"/api/file/not-here/tok?r={OTHER}")
    assert "fly-replay" not in resp.headers
    assert resp.status_code == 404


@pytest.mark.integration
async def test_the_route_header_on_an_event_changes_nothing(on_fly):
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        ok = await client.post(
            "/api/event",
            json={"sid": "t1", "component": "n1", "event": "click"},
            headers={"X-Indah-Route": MACHINE, "fly-force-instance-id": MACHINE},
        )
    assert ok.status_code == 200

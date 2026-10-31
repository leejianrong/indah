"""``create_app(limits=, security_headers=)`` end to end (ADR-0037, IND-120).

The first test is the contract that matters most: with nothing set, nothing changes.
"""

import socket
import time

import httpx
import pytest

from indah import Limits, Rate, create_app, launch
from indah.components import Button, Column
from indah.session import Session


def _build():
    return Session(Column(children=[Button("go", on_click=lambda: None)]))


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


def _event(sid="t"):
    return {"sid": sid, "component": "n1", "event": "click"}


@pytest.mark.integration
async def test_unset_limits_and_headers_reproduce_todays_behaviour():
    app = create_app(session_factory=_build, limits=Limits())
    plain = create_app(session_factory=_build)
    assert app.state.max_event_bytes == plain.state.max_event_bytes
    assert app.state.max_upload_bytes == plain.state.max_upload_bytes
    assert app.state.store.max_sessions is None and app.state.store.idle_timeout_seconds is None
    async with _client(app) as client:
        replies = [await client.post("/api/event", json=_event()) for _ in range(150)]
        index = await client.get("/")
    assert {r.status_code for r in replies} == {200}  # no rate limit
    assert "x-frame-options" not in index.headers and "x-content-type-options" not in index.headers


@pytest.mark.integration
async def test_security_headers_on_a_page_a_json_reply_and_an_error():
    app = create_app(session_factory=_build, security_headers=True)
    async with _client(app) as client:
        replies = [
            await client.get("/"),
            await client.post("/api/event", json=_event()),
            await client.get("/nope"),
        ]
    for r in replies:
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    framed = create_app(session_factory=_build, security_headers={"X-Frame-Options": "SAMEORIGIN"})
    async with _client(framed) as client:
        assert (await client.get("/")).headers["x-frame-options"] == "SAMEORIGIN"


@pytest.mark.raw_events  # asserts what a refused request creates: no tab connects first
@pytest.mark.integration
async def test_rate_limit_returns_429_before_anything_is_created():
    limits = Limits(rate={"/api/event": Rate(per_second=0.001, burst=2)})
    app = create_app(session_factory=_build, limits=limits)
    async with _client(app) as client:
        codes = [
            (await client.post("/api/event", json=_event(f"s{i}"))).status_code for i in range(4)
        ]
    # the first two pass the limiter and reach the route (409: no tab holds those ids, IND-199);
    # the rest are refused by the limiter before anything else runs
    assert codes == [409, 409, 429, 429]
    assert len(app.state.store) == 0  # nothing was created, by either kind of refusal


@pytest.mark.integration
async def test_a_spoofed_x_forwarded_for_buys_no_fresh_bucket_unless_the_peer_is_trusted():
    limits = Limits(rate={"/api/event": Rate(per_second=0.001, burst=1)})

    async def hit(app, claimed):
        # ASGITransport's peer is 127.0.0.1
        async with _client(app) as client:
            headers = {"X-Forwarded-For": claimed}
            return (await client.post("/api/event", json=_event(), headers=headers)).status_code

    app = create_app(session_factory=_build, limits=limits)
    assert [await hit(app, "9.9.9.9"), await hit(app, "8.8.8.8")] == [200, 429]

    behind = create_app(session_factory=_build, limits=limits, trusted_proxies=["127.0.0.1"])
    assert [await hit(behind, "9.9.9.9"), await hit(behind, "8.8.8.8")] == [200, 200]  # real hops
    assert await hit(behind, "9.9.9.9") == 429


@pytest.mark.integration
async def test_event_and_upload_caps_in_limits_override_the_arguments():
    app = create_app(
        session_factory=_build, limits=Limits(max_event_bytes=500, max_upload_mb=0.001)
    )
    assert app.state.max_event_bytes == 500
    assert app.state.max_upload_bytes == int(0.001 * 1024 * 1024)
    async with _client(app) as client:
        big = {"sid": "t", "component": "n1", "event": "click", "payload": {"x": "y" * 2000}}
        assert (await client.post("/api/event", json=big)).status_code == 413
        up = await client.post(
            "/api/upload", data={"component": "n1", "sid": "t"}, files={"file": ("a", b"x" * 5000)}
        )
        assert up.status_code == 413


@pytest.mark.integration
def test_session_bounds_in_limits_reach_the_store():
    app = create_app(session_factory=_build, limits=Limits(max_sessions=7, session_idle_seconds=60))
    assert app.state.store.max_sessions == 7
    assert app.state.store.idle_timeout_seconds == 60


def _open_stream(port, sid):
    s = socket.create_connection(("127.0.0.1", port))
    s.settimeout(5)
    # the id rides in the tab cookie, as the shell sends it (a limited app refuses ?sid=, IND-238)
    request = (
        "GET /api/stream?k=tabkey0123 HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n"
        f"Cookie: indah_sid_tabkey0123={sid}\r\n\r\n"
    )
    s.sendall(request.encode())
    return s, s.recv(64)


@pytest.mark.integration
def test_a_third_stream_from_one_address_is_429_and_a_closed_one_frees_its_slot():
    app = create_app(session_factory=_build, limits=Limits(max_streams_per_ip=2))
    handle = launch(app, block=False, open_inline=False)
    socks = []
    try:
        for sid in ("a", "b"):
            s, head = _open_stream(handle.port, sid)
            socks.append(s)
            assert head.startswith(b"HTTP/1.1 200")
        s3, head3 = _open_stream(handle.port, "c")
        socks.append(s3)
        assert head3.startswith(b"HTTP/1.1 429")
        assert app.state.store.get("c") is None  # the refused stream made no session
        socks[0].close()  # the browser tab went away
        for _ in range(50):  # the server notices on its next heartbeat or write
            s4, head4 = _open_stream(handle.port, "d")
            socks.append(s4)
            if head4.startswith(b"HTTP/1.1 200"):
                break
            s4.close()
            time.sleep(0.1)
        else:
            raise AssertionError("the slot was never released")
    finally:
        for s in socks:
            s.close()
        handle.stop()

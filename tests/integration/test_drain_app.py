"""/ready and drain against a real launched server (IND-201)."""

import json
import socket
import time

import httpx
import pytest

from indah import create_app, launch


def _open_stream(port: int, sid: str) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    request = f"GET /api/stream?sid={sid} HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n"
    s.sendall(request.encode())
    return s


def _read_until(s: socket.socket, needle: bytes, seconds: float = 5.0) -> bytes:
    buf = b""
    end = time.monotonic() + seconds
    while needle not in buf and time.monotonic() < end:
        try:
            chunk = s.recv(65536)
        except TimeoutError:
            continue
        if not chunk:
            break
        buf += chunk
    return buf


@pytest.mark.integration
def test_ready_is_200_and_health_is_200():
    handle = launch(create_app(), block=False, open_inline=False)
    try:
        r = httpx.get(handle.url + "/ready")
        assert r.status_code == 200
        assert r.json() == {"ready": True}
        assert r.headers["cache-control"] == "no-store"
        assert httpx.get(handle.url + "/health").status_code == 200
    finally:
        handle.stop()


@pytest.mark.integration
def test_ready_flips_to_503_while_draining_and_health_stays_200():
    handle = launch(create_app(drain_seconds=5), block=False, open_inline=False)
    try:
        handle.drain(wait=False)
        r = httpx.get(handle.url + "/ready")
        assert r.status_code == 503
        assert r.json() == {"ready": False, "draining": True}
        assert "retry-after" in r.headers
        assert httpx.get(handle.url + "/health").status_code == 200  # liveness: still alive
    finally:
        handle.stop()


@pytest.mark.integration
def test_an_open_stream_gets_a_reconnect_and_a_new_stream_is_refused():
    handle = launch(create_app(drain_seconds=5), block=False, open_inline=False)
    tab = _open_stream(handle.port, "tab-1")
    try:
        assert b'"type": "init"' in _read_until(tab, b'"type": "init"')

        handle.drain(wait=False)

        got = _read_until(tab, b'"type": "reconnect"')
        assert b'"type": "reconnect"' in got
        text = got[got.rfind(b"data:") + 5 :].split(b"\n", 1)[0]
        assert json.loads(text)["after_ms"] >= 100

        refused = httpx.get(handle.url + "/api/stream", params={"sid": "tab-2"})
        assert refused.status_code == 503
        assert "retry-after" in refused.headers
    finally:
        tab.close()
        handle.stop()


@pytest.mark.integration
def test_events_for_an_existing_session_still_work_but_a_new_session_is_refused():
    handle = launch(create_app(drain_seconds=5), block=False, open_inline=False)
    tab = _open_stream(handle.port, "tab-1")
    try:
        _read_until(tab, b'"type": "init"')
        handle.drain(wait=False)

        body = {"sid": "tab-1", "component": "n0", "event": "noop", "payload": {}}
        known = httpx.post(handle.url + "/api/event", json=body)
        assert known.status_code != 503  # the session exists: the tab may finish what it did

        # An event never creates a session (IND-199): for an id this process does not hold it is
        # 409, and the shell answers by opening a stream, which a draining process refuses.
        new = httpx.post(handle.url + "/api/event", json={**body, "sid": "never-seen"})
        assert new.status_code == 409
        with httpx.stream("GET", handle.url + "/api/stream", params={"sid": "never-seen"}) as r:
            assert r.status_code == 503
            assert "retry-after" in r.headers
    finally:
        tab.close()
        handle.stop()


@pytest.mark.integration
def test_drain_waits_for_streams_then_ends_them_at_the_deadline():
    handle = launch(create_app(drain_seconds=0.5), block=False, open_inline=False)
    tab = _open_stream(handle.port, "tab-1")
    try:
        _read_until(tab, b'"type": "init"')
        started = time.monotonic()
        handle.drain()  # waits: the tab never closes, so it runs to the deadline
        took = time.monotonic() - started
        assert 0.4 <= took < 3
        # the server ended the stream: the socket reads to the end
        tail = _read_until(tab, b"never-appears", seconds=2)
        assert b'"type": "reconnect"' in tail
    finally:
        tab.close()
        handle.stop()


@pytest.mark.integration
def test_drain_with_no_streams_is_immediate_and_stop_stays_prompt():
    handle = launch(create_app(drain_seconds=30), block=False, open_inline=False)
    started = time.monotonic()
    handle.drain()
    assert time.monotonic() - started < 1
    handle.stop()
    assert time.monotonic() - started < 3
    assert not handle._thread.is_alive()


@pytest.mark.integration
def test_a_secure_app_still_mints_a_session_token_while_draining_but_refuses_its_stream():
    from indah import Principal
    from indah.components import Text
    from indah.session import Session

    app = create_app(
        secure=True,
        secret="s" * 32,
        auth=lambda request: Principal(id="u1", name="U One"),
        session_factory=lambda: Session(Text("hi")),
        drain_seconds=5,
    )
    handle = launch(app, block=False, open_inline=False)
    try:
        # the tab that is told to reconnect trades its login for a token again, on any process
        token = httpx.post(handle.url + "/api/session", json={"resume": None}).json()["token"]
        opened = _open_stream(handle.port, token)
        try:
            assert b'"type": "init"' in _read_until(opened, b'"type": "init"')
            handle.drain(wait=False)
            assert b'"type": "reconnect"' in _read_until(opened, b'"type": "reconnect"')
        finally:
            opened.close()

        again = httpx.post(handle.url + "/api/session", json={"resume": token})
        assert again.status_code == 200 and again.json()["token"] == token  # resumes the id
        refused = httpx.get(handle.url + "/api/stream", params={"sid": token})
        assert refused.status_code == 503
        assert refused.headers["retry-after"] == "1"
    finally:
        handle.stop()

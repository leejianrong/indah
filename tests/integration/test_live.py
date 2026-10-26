"""Tier 1 live media over a WebSocket (ADR-0045), in-process with Starlette's TestClient.

Covers the opt-in (off by default), the hello handshake, latest-frame-wins backpressure, the
caps, the origin and identity checks, the CSP and chrome changes, and the Colab fallback.
"""

import asyncio
import json
import threading

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from indah import Camera, Live, Microphone, Principal, Text, create_app
from indah.components import Column
from indah.context import ConnectionInfo
from indah.live import (
    CLOSE_BAD_HELLO,
    CLOSE_FORBIDDEN,
    CLOSE_GOING_AWAY,
    CLOSE_POLICY,
    CLOSE_TOO_BIG,
    CLOSE_TOO_MANY,
    CLOSE_UNAUTHENTICATED,
    CLOSE_UNKNOWN_SESSION,
    AudioChunk,
    pack_frame,
)
from indah.reactive import Signal
from indah.session import Session

SECRET = "a-long-random-secret-value-0123456789"
SID = "tab-aaaaaaaaaaaaaaaa"


class Probe:
    def __init__(self) -> None:
        self.seqs: list[int] = []
        self.got = threading.Event()
        self.release = threading.Event()


def _app(probe: Probe | None = None, *, slow: bool = False, **kw):
    probe = probe or Probe()

    def factory() -> Session:
        label = Signal("none")

        if slow:

            async def on_frame(frame):
                probe.seqs.append(frame.seq)
                probe.got.set()
                while not probe.release.is_set():
                    await asyncio.sleep(0.01)
                label.set(f"seq {frame.seq}")
        else:

            def on_frame(frame):
                probe.seqs.append(frame.seq)
                label.set(f"{frame.seq}:{frame.data.decode()}")
                probe.got.set()

        return Session(Column(children=[Camera(on_frame), Text(lambda: label.value)]))

    kw.setdefault("live", True)
    return create_app(session_factory=factory, **kw), probe


def _open(app, sid=SID, user: Principal | None = None):
    app.state.store.get_or_create(sid, ConnectionInfo(user=user))


def _hello(**over):
    msg = {"type": "hello", "v": 1, "sid": SID, "component": "n1", "kind": "video"}
    msg.update(over)
    return json.dumps(msg)


def _closed_with(ws) -> int:
    """Read until the server closes the socket; the close code it sent."""
    while True:
        message = ws.receive()
        if message["type"] == "websocket.close":
            return message["code"]


@pytest.mark.integration
def test_live_is_off_by_default():
    app, _ = _app(live=False)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/live"):
        pass
    assert "api/live" not in client.get("/").text


@pytest.mark.integration
def test_live_without_a_websocket_library_fails_at_build_time(monkeypatch):
    monkeypatch.setattr("indah.app.websocket_support", lambda: False)
    with pytest.raises(ImportError, match=r"indah\[live\]"):
        _app()


@pytest.mark.integration
def test_a_frame_reaches_the_handler_and_patches_the_page():
    app, probe = _app()
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(pack_frame(5, b"hello"))
        assert probe.got.wait(3)
    assert probe.seqs == [5]
    snap = app.state.store.get(SID).session.snapshot()
    assert snap["children"][1]["props"]["text"] == "5:hello"


@pytest.mark.integration
def test_a_stalled_handler_gets_the_first_then_only_the_newest_frame():
    app, probe = _app(slow=True, live=Live(stats_seconds=0.05))
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(pack_frame(1, b"a"))
        assert probe.got.wait(3)  # the handler is now holding frame 1
        for seq in (2, 3, 4):
            ws.send_bytes(pack_frame(seq, b"x"))
        stats = {}
        while stats.get("dropped", 0) < 2:
            msg = ws.receive_json()
            if msg["type"] == "stats":
                stats = msg
        probe.got.clear()
        probe.release.set()
        assert probe.got.wait(3)
    assert probe.seqs == [1, 4]
    assert stats["dropped"] == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    "hello",
    [
        "not json",
        json.dumps({"type": "hello", "v": 2, "sid": SID, "component": "n1", "kind": "video"}),
        json.dumps({"type": "hello", "v": 1, "sid": SID, "component": "n1", "kind": "midi"}),
        json.dumps({"type": "hello", "v": 1, "sid": SID, "kind": "video"}),
    ],
)
def test_a_bad_hello_is_closed_4400(hello):
    app, _ = _app()
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(hello)
        assert _closed_with(ws) == CLOSE_BAD_HELLO


@pytest.mark.integration
def test_binary_before_hello_is_a_bad_hello():
    app, _ = _app()
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_bytes(pack_frame(1, b"x"))
        assert _closed_with(ws) == CLOSE_BAD_HELLO


@pytest.mark.integration
def test_a_silent_socket_is_closed_after_the_hello_timeout():
    app, _ = _app(live=Live(hello_timeout=0.1))
    with TestClient(app).websocket_connect("/api/live") as ws:
        assert _closed_with(ws) == CLOSE_BAD_HELLO


@pytest.mark.integration
def test_an_unknown_session_is_4409_and_creates_nothing():
    app, _ = _app()
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        assert _closed_with(ws) == CLOSE_UNKNOWN_SESSION
    assert app.state.store.get(SID) is None


@pytest.mark.integration
def test_a_socket_cannot_drive_a_component_that_is_not_a_camera():
    app, probe = _app()
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello(component="n2"))  # the Text
        assert _closed_with(ws) == CLOSE_FORBIDDEN
    assert probe.seqs == []


@pytest.mark.integration
def test_an_oversize_frame_closes_the_socket_1009():
    app, probe = _app(live=Live(max_frame_bytes=64))
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        ws.receive_json()
        ws.send_bytes(pack_frame(1, b"x" * 200))
        assert _closed_with(ws) == CLOSE_TOO_BIG
    assert probe.seqs == []


@pytest.mark.integration
def test_a_socket_over_its_byte_budget_is_closed_for_policy():
    app, _ = _app(live=Live(max_bytes_per_second=100))
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        ws.receive_json()
        ws.send_bytes(pack_frame(1, b"x" * 90))
        ws.send_bytes(pack_frame(2, b"x" * 90))
        assert _closed_with(ws) == CLOSE_POLICY


@pytest.mark.integration
def test_a_garbled_binary_frame_is_a_policy_close():
    app, _ = _app()
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        ws.receive_json()
        ws.send_bytes(b"\x00")
        assert _closed_with(ws) == CLOSE_POLICY


@pytest.mark.integration
def test_the_socket_cap_is_per_address_and_freed_on_close():
    app, _ = _app(live=Live(max_sockets_per_address=1))
    _open(app)
    client = TestClient(app)
    with client.websocket_connect("/api/live") as first:
        first.send_text(_hello())
        assert first.receive_json()["type"] == "ready"
        with client.websocket_connect("/api/live") as second:
            second.send_text(_hello())
            assert _closed_with(second) == CLOSE_TOO_MANY
    with client.websocket_connect("/api/live") as again:
        again.send_text(_hello())
        assert again.receive_json()["type"] == "ready"


@pytest.mark.integration
def test_behind_a_trusted_proxy_the_cap_counts_the_forwarded_client():
    app, _ = _app(live=Live(max_sockets_per_address=1), trusted_proxies=["10.0.0.1"])
    _open(app)
    client = TestClient(app, client=("10.0.0.1", 5000))

    def headers(ip):
        return {"x-forwarded-for": ip, "x-forwarded-proto": "https", "x-forwarded-host": "t.test"}

    with client.websocket_connect("/api/live", headers=headers("9.9.9.1")) as a:
        a.send_text(_hello())
        assert a.receive_json()["type"] == "ready"
        with client.websocket_connect("/api/live", headers=headers("9.9.9.2")) as b:
            b.send_text(_hello())
            assert b.receive_json()["type"] == "ready"
        with client.websocket_connect("/api/live", headers=headers("9.9.9.1")) as c:
            c.send_text(_hello())
            assert _closed_with(c) == CLOSE_TOO_MANY


@pytest.mark.integration
def test_a_cross_site_upgrade_is_refused_even_on_an_app_that_is_not_secure():
    app, _ = _app()
    _open(app)
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/api/live", headers={"origin": "https://evil.example", "sec-fetch-site": "cross-site"}
        ),
    ):
        pass
    with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as ws:
        ws.send_text(_hello())
        assert ws.receive_json()["type"] == "ready"


@pytest.mark.integration
def test_an_allowed_origin_may_upgrade():
    app, _ = _app(allowed_origins=["https://app.example.com"])
    _open(app)
    headers = {"origin": "https://app.example.com", "sec-fetch-site": "same-site"}
    with TestClient(app).websocket_connect("/api/live", headers=headers) as ws:
        ws.send_text(_hello())
        assert ws.receive_json()["type"] == "ready"


@pytest.mark.integration
def test_a_draining_server_closes_live_sockets_going_away():
    app, _ = _app(live=Live(stats_seconds=0.05))
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello())
        ws.receive_json()
        app.state.drain.draining = True
        assert _closed_with(ws) == CLOSE_GOING_AWAY


def _who(conn):
    user = conn.headers.get("x-user")
    return Principal(id=user) if user else None


@pytest.mark.integration
def test_a_secure_app_needs_a_principal_and_a_signed_token():
    app, probe = _app(auth=_who, secure=True, secret=SECRET)
    alice = Principal(id="alice")
    token = app.state.signer.mint(alice)
    _open(app, token.split(".")[0], alice)
    client = TestClient(app)

    with client.websocket_connect("/api/live") as ws:  # no identity
        ws.send_text(_hello(sid=token))
        assert _closed_with(ws) == CLOSE_UNAUTHENTICATED

    with client.websocket_connect("/api/live", headers={"x-user": "alice"}) as ws:  # forged
        ws.send_text(_hello(sid=token.split(".")[0] + ".forged"))
        assert _closed_with(ws) == CLOSE_FORBIDDEN

    with client.websocket_connect("/api/live", headers={"x-user": "mallory"}) as ws:  # not hers
        ws.send_text(_hello(sid=token))
        assert _closed_with(ws) == CLOSE_FORBIDDEN

    with client.websocket_connect("/api/live", headers={"x-user": "alice"}) as ws:
        ws.send_text(_hello(sid=token))
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(pack_frame(1, b"ok"))
        assert probe.got.wait(3)


@pytest.mark.integration
def test_the_chrome_advertises_live_and_the_csp_names_the_socket():
    app, _ = _app(csp="strict")
    page = TestClient(app).get("/")
    assert '"live": {"path": "api/live", "v": 1}' in page.text
    csp = page.headers["content-security-policy"]
    assert "connect-src 'self' ws://testserver" in csp


@pytest.mark.integration
def test_the_csp_uses_wss_behind_an_https_proxy():
    app, _ = _app(csp="strict", trusted_proxies=["10.0.0.1"])
    client = TestClient(app, client=("10.0.0.1", 1))
    page = client.get("/", headers={"x-forwarded-proto": "https", "x-forwarded-host": "t.test"})
    assert "connect-src 'self' wss://t.test;" in page.headers["content-security-policy"]


@pytest.mark.integration
def test_with_live_off_the_csp_is_unchanged():
    app, _ = _app(csp="strict", live=False)
    csp = TestClient(app).get("/").headers["content-security-policy"]
    assert "connect-src 'self';" in csp


@pytest.mark.integration
def test_on_colab_live_is_not_offered(monkeypatch, caplog):
    from indah.env import Environment

    monkeypatch.setattr("indah.app.detect_environment", lambda: Environment.COLAB)
    with caplog.at_level("WARNING"):
        app, _ = _app()
    client = TestClient(app)
    assert "api/live" not in client.get("/").text
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/live"):
        pass
    assert any("Colab" in r.message for r in caplog.records)


# -- Microphone (IND-65) -------------------------------------------------------------------------


def _mic_app(chunks: list, *, slow: bool = False, release: threading.Event | None = None, **kw):
    got = threading.Event()

    def factory() -> Session:
        async def on_audio(chunk: AudioChunk):
            chunks.append(chunk)
            got.set()
            if slow and release is not None:
                while not release.is_set():
                    await asyncio.sleep(0.01)

        return Session(Column(children=[Microphone(on_audio, sample_rate=8000), Text("x")]))

    kw.setdefault("live", True)
    return create_app(session_factory=factory, **kw), got


@pytest.mark.integration
def test_audio_chunks_reach_the_handler_in_order_with_their_rate():
    chunks: list[AudioChunk] = []
    app, got = _mic_app(chunks)
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello(kind="audio"))
        assert ws.receive_json() == {"type": "ready"}
        for seq in (1, 2, 3):
            ws.send_bytes(pack_frame(seq, b"\x01\x00" * 10))
        deadline = threading.Event()
        for _ in range(100):
            if len(chunks) == 3:
                break
            deadline.wait(0.03)
    assert [c.seq for c in chunks] == [1, 2, 3]
    assert all(c.sample_rate == 8000 and c.size == 20 for c in chunks)
    assert all(c.dropped_before == 0 for c in chunks)


@pytest.mark.integration
def test_a_video_hello_cannot_drive_a_microphone_nor_the_reverse():
    chunks: list[AudioChunk] = []
    app, _ = _mic_app(chunks)
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello(kind="video"))  # n1 is the Microphone
        assert _closed_with(ws) == CLOSE_FORBIDDEN
    cam_app, _ = _app()
    _open(cam_app)
    with TestClient(cam_app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello(kind="audio"))  # n1 is a Camera
        assert _closed_with(ws) == CLOSE_FORBIDDEN


@pytest.mark.integration
def test_a_backed_up_audio_queue_drops_the_oldest_and_says_so():
    chunks: list[AudioChunk] = []
    release = threading.Event()
    # 8000 Hz * 2 bytes * 0.001 s budget is tiny: it holds only the newest chunk
    app, got = _mic_app(chunks, slow=True, release=release, live=Live(audio_buffer_seconds=0.01))
    _open(app)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_text(_hello(kind="audio"))
        ws.receive_json()
        ws.send_bytes(pack_frame(1, b"\x00" * 100))
        assert got.wait(3)  # the handler holds chunk 1
        for seq in (2, 3, 4):
            ws.send_bytes(pack_frame(seq, b"\x00" * 100))
        threading.Event().wait(0.3)
        release.set()
        for _ in range(100):
            if len(chunks) >= 2:
                break
            threading.Event().wait(0.03)
        release.set()
    assert chunks[0].seq == 1
    assert chunks[1].seq == 4 and chunks[1].dropped_before == 2


@pytest.mark.integration
def test_the_worklet_is_served_only_when_live_is_on():
    on, _ = _mic_app([])
    res = TestClient(on).get("/api/live-audio.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    assert "registerProcessor" in res.text
    off, _ = _mic_app([], live=False)
    assert TestClient(off).get("/api/live-audio.js").status_code == 404

"""The real HTTP forwarder (IND-209): the socket client, and two real servers talking.

The loopback forwarder of ``test_forwarding.py`` skips the network; this file does not.
"""

import asyncio
import socket
import time

import httpx
import pytest

from indah import create_app, launch
from indah.components import Button, Column, Text
from indah.context import ConnectionInfo
from indah.forward import HttpForwarder, PeerConfig, sign_hint
from indah.reactive import Signal
from indah.session import Session

pytestmark = [pytest.mark.integration, pytest.mark.raw_events]
SECRET = "a-cluster-secret-of-some-length"


async def _serve(reply: bytes, *, delay: float = 0.0):
    seen: list[bytes] = []

    async def handle(reader, writer):
        data = await reader.readuntil(b"\r\n\r\n")
        seen.append(data)
        await asyncio.sleep(delay)
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], seen


async def test_it_posts_and_reads_a_content_length_reply():
    body = b'{"ok":true}'
    server, port, seen = await _serve(
        b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\nContent-Type: application/json\r\n\r\n" + body
    )
    async with server:
        status, reply = await HttpForwarder(2).forward(
            "127.0.0.1", port, "/_indah/forward", {"X-Indah-Forward-Kind": "event"}, b"{}"
        )
    assert (status, reply) == (200, body)
    head = seen[0].decode()
    assert head.startswith("POST /_indah/forward HTTP/1.1")
    assert "X-Indah-Forward-Kind: event" in head and "Content-Length: 2" in head
    assert "Connection: close" in head


async def test_a_reply_that_arrives_in_pieces_is_read_whole():
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n")
        await writer.drain()
        await asyncio.sleep(0.1)  # the body is a separate packet
        writer.write(b'{"ok":true}')
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        status, reply = await HttpForwarder(2).forward("127.0.0.1", port, "/p", {}, b"")
    assert (status, reply) == (200, b'{"ok":true}')


async def test_it_reads_a_chunked_reply():
    server, port, _ = await _serve(
        b"HTTP/1.1 409 Conflict\r\nTransfer-Encoding: chunked\r\n\r\n"
        b'5\r\n{"ok"\r\n7\r\n:false}\r\n0\r\n\r\n'
    )
    async with server:
        status, reply = await HttpForwarder(2).forward("127.0.0.1", port, "/p", {}, b"")
    assert status == 409 and reply == b'{"ok":false}'


async def test_it_does_not_follow_redirects():
    server, port, seen = await _serve(
        b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/\r\nContent-Length: 0\r\n\r\n"
    )
    async with server:
        status, _ = await HttpForwarder(2).forward("127.0.0.1", port, "/p", {}, b"")
    assert status == 302 and len(seen) == 1


async def test_a_refused_connection_a_slow_peer_and_a_non_http_peer_all_raise():
    with socket.socket() as s:  # a port nothing listens on
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    with pytest.raises(OSError):
        await HttpForwarder(1).forward("127.0.0.1", closed, "/p", {}, b"")
    server, port, _ = await _serve(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", delay=2)
    async with server:
        with pytest.raises(asyncio.TimeoutError):
            await HttpForwarder(0.2).forward("127.0.0.1", port, "/p", {}, b"")
    server, port, _ = await _serve(b"not http at all")
    async with server:
        with pytest.raises(ValueError):
            await HttpForwarder(1).forward("127.0.0.1", port, "/p", {}, b"")


async def test_a_header_with_a_line_break_is_refused():
    with pytest.raises(ValueError):
        await HttpForwarder(1).forward("127.0.0.1", 9, "/p", {"X-A": "b\r\nX-Evil: 1"}, b"")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_two_real_servers_forward_an_event_over_http(monkeypatch):
    """Owner on 127.0.0.1 and receiver on 127.0.0.2, one port: real sockets, real signatures."""
    for name in ("FLY_MACHINE_ID", "INDAH_PEERS", "INDAH_CLUSTER_SECRET", "INDAH_ROUTE_HINT"):
        monkeypatch.delenv(name, raising=False)
    port = _free_port()
    log: list = []

    def build(ctx):
        n = Signal(0)

        def click():
            log.append(n.value)
            n.set(n.value + 1)

        return Session(Column(children=[Button("go", on_click=click), Text(lambda: str(n.value))]))

    def make(address):
        return create_app(
            session_factory=build,
            cluster_secret=SECRET,
            peers=PeerConfig(peers="self", address=address, port=port),
        )

    owner_app, recv_app = make("127.0.0.1"), make("127.0.0.2")
    try:
        owner = launch(owner_app, port=port, host="127.0.0.1", block=False, open_inline=False)
        receiver = launch(recv_app, port=port, host="127.0.0.2", block=False, open_inline=False)
    except OSError:
        pytest.skip("this machine cannot bind 127.0.0.2")
    try:
        handle = owner_app.state.store.get_or_create("tab-1", ConnectionInfo())
        queue = handle.hub.subscribe()
        hint = sign_hint(SECRET.encode(), "127.0.0.1", port, time.time())
        reply = httpx.post(
            f"{receiver.url}/api/event",
            json={"sid": "tab-1", "component": "n1", "event": "click"},
            headers={"X-Indah-Route": hint},
            timeout=5,
        )
        assert reply.status_code == 200 and reply.json() == {"ok": True}
        assert log == [0]  # the handler ran once, on the owner
        assert queue.get_nowait() is not None  # and its patch is on the owner's stream
        assert recv_app.state.store.get("tab-1") is None
        assert (
            recv_app.state.peers.stats["ok"] == 1 and owner_app.state.peers.stats["received"] == 1
        )
        owner.stop()  # now the owner is gone: a loud 409, no retry
        gone = httpx.post(
            f"{receiver.url}/api/event",
            json={"sid": "tab-1", "component": "n1", "event": "click"},
            headers={"X-Indah-Route": hint},
            timeout=5,
        )
        assert gone.status_code == 409 and gone.json()["error"] == "owner_unreachable"
    finally:
        owner.stop()
        receiver.stop()

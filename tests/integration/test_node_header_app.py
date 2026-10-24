"""The node header on an event stream of a real launched server (IND-203)."""

import socket

import pytest

from indah import create_app, launch


@pytest.mark.integration
def test_the_event_stream_carries_the_node_header(monkeypatch):
    monkeypatch.setenv("INDAH_NODE", "pod-a")
    handle = launch(create_app(node_header=True), block=False, open_inline=False)
    try:
        port = int(handle.url.rsplit(":", 1)[1].rstrip("/"))
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(
            b"GET /api/stream?sid=n1 HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n"
        )
        head = b""
        while b"\r\n\r\n" not in head:
            head += s.recv(4096)
        s.close()
        lines = head.split(b"\r\n\r\n")[0].lower().split(b"\r\n")
        assert b"x-indah-node: pod-a" in lines
        assert b"content-type: text/event-stream" in lines[1:] or any(
            b"text/event-stream" in line for line in lines
        )
    finally:
        handle.stop()


@pytest.mark.integration
def test_the_session_factory_sees_ctx_conn_node(monkeypatch):
    import indah

    monkeypatch.setenv("INDAH_NODE", "pod-b")
    seen: list[str] = []

    def factory(ctx: indah.Context):
        seen.append(ctx.conn.node)
        return indah.Session(indah.Text("hi"))

    handle = launch(create_app(session_factory=factory), block=False, open_inline=False)
    try:
        port = int(handle.url.rsplit(":", 1)[1].rstrip("/"))
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(
            b"GET /api/stream?sid=n2 HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n"
        )
        buf = b""
        while b'"type": "init"' not in buf and len(buf) < 200_000:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        assert seen == ["pod-b"]
    finally:
        handle.stop()

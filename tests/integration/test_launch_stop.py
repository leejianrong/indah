"""LaunchHandle.stop() really ends the server even with an SSE stream open (IND-123)."""

import logging
import socket
import time

import pytest

from indah import create_app, launch


@pytest.mark.integration
def test_stop_frees_the_port_and_ends_the_thread_with_an_open_sse_stream():
    handle = launch(create_app(), block=False, open_inline=False)
    port = handle.port
    # A browser tab's EventSource: a long-lived GET that is never read to the end.
    client = socket.create_connection(("127.0.0.1", port))
    try:
        client.sendall(
            b"GET /api/stream?sid=t HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n"
        )
        assert client.recv(64).startswith(b"HTTP/1.1 200")  # the stream is live

        started = time.monotonic()
        handle.stop()
        took = time.monotonic() - started

        assert not handle._thread.is_alive()
        assert took < 3  # a short grace, not the full join timeout
        with socket.socket() as s:  # the port is free to bind again, as a restart would
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
    finally:
        client.close()


@pytest.mark.integration
def test_stop_is_prompt_and_idempotent_with_no_clients():
    handle = launch(create_app(), block=False, open_inline=False)
    started = time.monotonic()
    handle.stop()
    handle.stop()
    assert time.monotonic() - started < 2
    assert not handle._thread.is_alive()


@pytest.mark.integration
def test_stop_with_an_open_stream_does_not_log_errors(caplog):
    handle = launch(create_app(), block=False, open_inline=False)
    client = socket.create_connection(("127.0.0.1", handle.port))
    try:
        client.sendall(
            b"GET /api/stream?sid=t HTTP/1.1\r\nHost: x\r\nAccept: text/event-stream\r\n\r\n"
        )
        client.recv(64)
        with caplog.at_level(logging.ERROR):
            handle.stop()
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    finally:
        client.close()

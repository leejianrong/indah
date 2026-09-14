"""Integration tests for async handlers and the error path.

These drive the session + hub (and the HTTP boundary via ASGITransport) without a
browser. The SSE response stream itself is exercised end to end in
tests/e2e/test_live_server.py, because httpx's ASGITransport buffers a streaming
response; here we assert against the hub the background task publishes to.
"""

import asyncio

import httpx
import pytest

from indah.app import create_app
from indah.components import Button, Column, StreamText
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _appends(hub: Hub) -> list[str]:
    """The ordered stream of appended text deltas seen by the hub."""
    deltas = []
    for _, msg in hub.history():
        if msg.get("type") != "patch":
            continue
        for change in msg.get("changes", []):
            if "append" in change:
                deltas.append(change["append"]["text"])
    return deltas


def _errors(hub: Hub) -> list[str]:
    return [msg["message"] for _, msg in hub.history() if msg.get("type") == "error"]


# -- async handler streams append patches in order ---------------------------


def _stream_session():
    stream = StreamText()

    async def generate():
        stream.reset()
        for token in ["one ", "two ", "three"]:
            await asyncio.sleep(0)  # yield to the loop, as real async work would
            stream.feed(token)

    session = Session(Column(children=[Button("go", on_click=generate), stream]))
    hub = Hub()
    session.bind_hub(hub)
    return session, stream, hub


@pytest.mark.integration
async def test_async_handler_emits_append_patches_in_order():
    session, stream, hub = _stream_session()

    result = session.dispatch("n1", "click", {})
    assert result.coro is not None  # detected as an async handler
    assert result.changes == []  # nothing mutated synchronously
    await result.coro

    assert stream.text == "one two three"
    # reset() clears first, then the three tokens arrive in order, no dupes.
    assert _appends(hub) == ["one ", "two ", "three"]


@pytest.mark.integration
async def test_post_returns_immediately_and_work_streams_over_the_hub():
    # Build an app around a fresh streaming session so the POST path is exercised.
    session, stream, _ = _stream_session()
    app = create_app(session=session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/event", json={"component": "n1", "event": "click"})
        # The POST returns before generation finishes: the work runs in the
        # background and streams over SSE (R3).
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    # Let the background task run to completion on the same loop.
    for _ in range(10):
        await asyncio.sleep(0)
    assert _appends(app.state.hub) == ["one ", "two ", "three"]


# -- error path: toast + traceback, UI stays live ---------------------------


@pytest.mark.integration
async def test_sync_handler_exception_becomes_a_toast_and_ui_stays_live():
    counter = Signal(0)

    def boom():
        raise ValueError("kaboom")

    def ok():
        counter.set(counter.value + 1)

    session = Session(Column(children=[Button("boom", on_click=boom), Button("ok", on_click=ok)]))
    hub = Hub()
    session.bind_hub(hub)

    result = session.dispatch("n1", "click", {})  # the failing button
    assert result is not None  # handled: the event was consumed, not a 400
    assert result.changes == []
    assert _errors(hub) == ["ValueError: kaboom"]

    # The rest of the UI still works: a later event dispatches normally.
    session.dispatch("n2", "click", {})
    assert counter.value == 1


@pytest.mark.integration
async def test_async_handler_exception_becomes_a_toast():
    async def boom():
        await asyncio.sleep(0)
        raise RuntimeError("async fail")

    session = Session(Column(children=[Button("boom", on_click=boom)]))
    hub = Hub()
    session.bind_hub(hub)

    result = session.dispatch("n1", "click", {})
    assert result.coro is not None
    await session._run_handler(result.coro)  # same path spawn() uses

    assert _errors(hub) == ["RuntimeError: async fail"]

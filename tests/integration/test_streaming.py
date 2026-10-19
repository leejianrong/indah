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


async def _first_frames(resp, *, want_data: int = 1) -> str:
    """Read an SSE StreamingResponse until ``want_data`` ``data:`` frames arrived."""
    seen, text = 0, ""
    async for chunk in resp.body_iterator:
        text += chunk if isinstance(chunk, str) else chunk.decode()
        seen = text.count("data: ")
        if seen >= want_data:
            break
    await resp.body_iterator.aclose()
    return text


def _stream_request(app, *, sid: str, last_event_id: str | None):
    from starlette.requests import Request

    headers = [(b"last-event-id", last_event_id.encode())] if last_event_id else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": f"sid={sid}".encode(),
        "headers": headers,
        "app": app,
    }
    return Request(scope)


@pytest.mark.integration
async def test_resume_after_server_restart_resends_the_init_snapshot():
    """IND-85: a restarted server has a fresh hub (offset 0). A tab reconnecting with
    a high Last-Event-Id must get an `init`, not silence with a stale tree."""
    from indah.app import _stream, create_app
    from indah.components import Column, Text
    from indah.session import Session

    app = create_app(session_factory=lambda: Session(Column(children=[Text("hello")])))
    resp = await _stream(_stream_request(app, sid="tab-a", last_event_id="deadbeef-500"))
    text = await _first_frames(resp)
    assert '"type": "init"' in text


@pytest.mark.integration
async def test_resume_with_the_current_epoch_replays_instead_of_re_init():
    from indah.app import _stream, create_app
    from indah.components import Column, Text
    from indah.session import Session

    app = create_app(session_factory=lambda: Session(Column(children=[Text("hello")])))
    handle = app.state.store.get_or_create("tab-a")
    handle.hub.publish({"v": 1, "type": "patch", "changes": [{"target": "n1", "props": {"x": 1}}]})
    last = f"{handle.hub.epoch}-0"  # saw nothing yet on *this* hub
    resp = await _stream(_stream_request(app, sid="tab-a", last_event_id=last))
    text = await _first_frames(resp)
    assert '"type": "patch"' in text and '"type": "init"' not in text
    assert f"id: {handle.hub.epoch}-1" in text  # ids carry the epoch

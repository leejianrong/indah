"""The single ASGI app: static shell + SSE stream + event endpoint on one port.

Slice 2 wires the reactive core (ADR-0003) to the transport (ADR-0002): the app
builds a component tree bound to signals, ships it as an ``init`` snapshot, and
broadcasts minimal patches when a client event mutates a signal. Everything is
served from one Starlette app to survive the Colab/Runpod proxies (ADR-0001).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from importlib.resources import files
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from .components import Column, Slider, Text
from .protocol import EventIn, init_message, patch_message, ping_message
from .reactive import Signal, computed
from .session import Session
from .transport import Hub

DEFAULT_HEARTBEAT_SECONDS = 15.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Tell intermediary proxies (e.g. Runpod's nginx) not to buffer the stream.
    "X-Accel-Buffering": "no",
}


def build_demo_session() -> Session:
    """The built-in Slice 2 demo: two sliders and a label computed from both.

    Dragging a slider mutates only its signal; the computed label recomputes and
    only the label node is patched.
    """
    a: Signal[float] = Signal(2)
    b: Signal[float] = Signal(3)
    total = computed(lambda: f"a + b = {a.value + b.value}")

    root = Column(
        children=[
            Slider(a, min=0, max=10, step=1, label="a"),
            Slider(b, min=0, max=10, step=1, label="b"),
            Text(total),
        ]
    )
    return Session(root)


def create_app(
    *,
    session: Session | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", _index, methods=["GET"]),
            Route("/health", _health, methods=["GET"]),
            Route("/api/stream", _stream, methods=["GET"]),
            Route("/api/event", _event, methods=["POST"]),
        ]
    )
    app.state.hub = Hub()
    app.state.heartbeat_seconds = heartbeat_seconds
    app.state.session = build_demo_session() if session is None else session
    return app


async def _index(request: Request) -> HTMLResponse:
    return HTMLResponse(_read_static("index.html"))


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def sse_events(
    queue: asyncio.Queue[dict[str, Any]],
    init_payload: dict[str, Any],
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    """Yield SSE-framed strings: the ``init`` payload, then messages from ``queue``.

    Emits a ``ping`` whenever ``heartbeat_seconds`` elapses with no message, so the
    connection survives idle-timeout proxies (ADR-0002). Framing is separated from
    the HTTP handler so it can be tested without a server.
    """
    yield _sse(init_payload)
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            message = ping_message()
        yield _sse(message)


async def _stream(request: Request) -> StreamingResponse:
    app = request.app
    hub: Hub = app.state.hub
    queue = hub.subscribe()
    init_payload = init_message(app.state.session.snapshot())

    async def event_source():
        try:
            async for chunk in sse_events(queue, init_payload, app.state.heartbeat_seconds):
                yield chunk
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(event_source(), media_type="text/event-stream", headers=_SSE_HEADERS)


async def _event(request: Request) -> JSONResponse:
    try:
        raw = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    try:
        event = EventIn.model_validate(raw)
    except ValidationError as exc:
        return JSONResponse(
            {"ok": False, "error": "validation", "detail": exc.errors()}, status_code=422
        )

    changes = request.app.state.session.dispatch(event.component, event.event, event.payload)
    if changes is None:
        return JSONResponse({"ok": False, "error": "unknown event"}, status_code=400)

    if changes:
        await request.app.state.hub.broadcast(patch_message(changes))
    return JSONResponse({"ok": True})


def _sse(message: dict[str, Any]) -> str:
    return f"data: {json.dumps(message)}\n\n"


def _read_static(name: str) -> str:
    return files("indah.static").joinpath(name).read_text(encoding="utf-8")

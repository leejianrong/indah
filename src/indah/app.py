"""The single ASGI app: static shell + SSE stream + event endpoint on one port.

This is the Slice 1 skeleton (see docs/SLICES.md V1). It wires the transport
(ADR-0002) end to end with a hardcoded counter, before the reactive core
(ADR-0003) exists. Everything is served from one Starlette app so it survives the
Colab and Runpod single-port proxies (ADR-0001).
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

from .protocol import EventIn, init_message, patch_message, ping_message
from .transport import Hub

DEFAULT_HEARTBEAT_SECONDS = 15.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Tell intermediary proxies (e.g. Runpod's nginx) not to buffer the stream.
    "X-Accel-Buffering": "no",
}


def create_app(*, heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS) -> Starlette:
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
    # Slice 1 demo state: a single counter node. Replaced by the reactive core.
    app.state.counter = 0
    app.state.nodes = {"counter": "0"}
    return app


async def _index(request: Request) -> HTMLResponse:
    return HTMLResponse(_read_static("index.html"))


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def sse_events(
    queue: asyncio.Queue[dict[str, Any]],
    nodes: dict[str, str],
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    """Yield SSE-framed strings: an ``init`` snapshot, then messages from ``queue``.

    Emits a ``ping`` whenever ``heartbeat_seconds`` elapses with no message, so the
    connection survives idle-timeout proxies (ADR-0002). Framing is separated from
    the HTTP handler so it can be tested without a server.
    """
    yield _sse(init_message(dict(nodes)))
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

    async def event_source():
        try:
            async for chunk in sse_events(queue, app.state.nodes, app.state.heartbeat_seconds):
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

    patches = _handle_event(request.app, event)
    if patches is None:
        return JSONResponse({"ok": False, "error": "unknown event"}, status_code=400)

    for patch in patches:
        await request.app.state.hub.broadcast(patch)
    return JSONResponse({"ok": True})


def _handle_event(app: Starlette, event: EventIn) -> list[dict[str, Any]] | None:
    """Apply a UI event to the demo state, returning the patches to broadcast.

    Returns ``None`` for an event the app does not know how to handle. Replaced
    by the reactive core in Slice 2 (ADR-0003).
    """
    if event.component == "counter" and event.event == "increment":
        app.state.counter += 1
        value = str(app.state.counter)
        app.state.nodes["counter"] = value
        return [patch_message("counter", value)]
    return None


def _sse(message: dict[str, Any]) -> str:
    return f"data: {json.dumps(message)}\n\n"


def _read_static(name: str) -> str:
    return files("indah.static").joinpath(name).read_text(encoding="utf-8")

"""The single ASGI app: static shell + SSE stream + event endpoint on one port.

Slice 3 adds async work and token streaming (ADR-0011) on top of Slice 2's
reactive core (ADR-0003) over the SSE transport (ADR-0002). An event may trigger
an async handler that streams tokens into a ``StreamText`` over the existing SSE
channel as append patches, and the stream survives a proxy timeout because the
hub sequences messages and a reconnecting client resumes via ``Last-Event-Id``.
Everything is served from one Starlette app to survive the Colab/Runpod proxies
(ADR-0001).
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

from .components import (
    Button,
    Column,
    DataFrame,
    Select,
    Slider,
    StreamText,
    Text,
    TextInput,
)
from .custom import custom, register_component
from .protocol import EventIn, init_message, patch_message, ping_message
from .reactive import Signal, computed
from .session import Session
from .transport import Hub, Item

DEFAULT_HEARTBEAT_SECONDS = 15.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Tell intermediary proxies (e.g. Runpod's nginx) not to buffer the stream.
    "X-Accel-Buffering": "no",
}


async def mock_llm(prompt: str) -> AsyncIterator[str]:
    """A stand-in LLM: a plain async generator yielding a reply token by token.

    It is deliberately an ordinary async generator with no indah imports, so a
    real model client drops straight in behind the same shape (ADR-0009).
    """
    asked = prompt.strip()
    reply = (
        "Sure -- "
        + (f"you asked '{asked}'. " if asked else "")
        + "here is a streamed reply, arriving token by token so the rest of the "
        + "page never blocks while it generates."
    )
    for word in reply.split(" "):
        await asyncio.sleep(0.06)
        yield word + " "


# A couple of tiny datasets the demo's Select switches between, to show a
# DataFrame re-rendering reactively.
_DATASETS: dict[str, dict[str, Any]] = {
    "squares": {"columns": ["n", "n^2"], "rows": [[n, n * n] for n in range(1, 6)]},
    "primes": {"columns": ["i", "prime"], "rows": [[1, 2], [2, 3], [3, 5], [4, 7], [5, 11]]},
}

# One worked custom component (ADR-0012): a native colour picker the shell renders
# from its declarative spec, with no shell rebuild. Registered once at import.
register_component(
    "colorpicker",
    render={
        "tag": "input",
        "attrs": {"type": "color"},
        "bind": {"value": "value"},
        "on": {"input": {"event": "input", "prop": "value"}},
    },
)


def build_demo_session() -> Session:
    """The built-in demo: async streaming plus the V4 starter + custom components.

    Clicking Generate runs an async handler that streams tokens into the output
    while the rest of the page stays fully responsive -- proving async work does not
    freeze the UI (R3). Below it, a Select switches a reactive DataFrame, and a
    registered colour picker (a custom component, ADR-0012) two-way binds a signal.
    """
    prompt: Signal[str] = Signal("")
    stream = StreamText(label="Response")

    async def on_generate() -> None:
        stream.reset()
        async for token in mock_llm(prompt.value):
            stream.feed(token)

    dataset: Signal[str] = Signal("squares")
    table = computed(lambda: _DATASETS[dataset.value])

    accent: Signal[str] = Signal("#5b5bd6")

    a: Signal[float] = Signal(3)
    doubled = computed(
        lambda: f"the slider stays live during streaming: 2 x {a.value} = {2 * a.value}"
    )

    root = Column(
        children=[
            Text("indah: starter components + async streaming"),
            TextInput(prompt, placeholder="Ask the mock LLM something...", label="Prompt"),
            Button("Generate", on_click=on_generate),
            stream,
            Select(
                dataset,
                options=[("squares", "Squares"), ("primes", "Primes")],
                label="Dataset",
            ),
            DataFrame(table, label="Data"),
            custom("colorpicker", value=accent),  # a worked custom component
            Text(lambda: f"accent = {accent.value}"),
            Slider(a, min=0, max=10, step=1, label="a"),
            Text(doubled),
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
    # Live (async/streaming) emits reach clients through the hub.
    app.state.session.bind_hub(app.state.hub)
    return app


async def _index(request: Request) -> HTMLResponse:
    return HTMLResponse(_read_static("index.html"))


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def sse_events(
    queue: asyncio.Queue[Item],
    init_payload: dict[str, Any] | None,
    heartbeat_seconds: float,
    *,
    replay: tuple[Item, ...] | list[Item] = (),
    skip_upto: int = 0,
) -> AsyncIterator[str]:
    """Yield SSE-framed strings for one browser connection.

    Emits ``init_payload`` first (a fresh connect, or a resume that fell back to a
    full snapshot), then any ``replay`` messages (a resume from the buffer), then
    live messages from ``queue``. Live messages with an offset at or below
    ``skip_upto`` are dropped -- those are already covered by the init snapshot or
    the replay, so forwarding them would double-apply an append (ADR-0011).

    A ``ping`` is emitted whenever ``heartbeat_seconds`` elapses idle, so the
    connection survives idle-timeout proxies (ADR-0002). State-bearing messages
    carry an SSE ``id:`` so a reconnecting client resumes from where it left off;
    init and ping do not. Framing is separated from the HTTP handler so it can be
    tested without a server.
    """
    if init_payload is not None:
        yield _sse(init_payload)
    for offset, message in replay:
        yield _sse(message, event_id=offset)
    while True:
        try:
            offset, message = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            yield _sse(ping_message())
            continue
        if offset <= skip_upto:
            continue
        yield _sse(message, event_id=offset)


async def _stream(request: Request) -> StreamingResponse:
    app = request.app
    hub: Hub = app.state.hub
    session: Session = app.state.session
    queue = hub.subscribe()

    # Subscribe first, then decide init-vs-resume against the current offset with
    # no await in between, so nothing published concurrently is missed or applied
    # twice. skip_upto = the offset the client is caught up to after init/replay;
    # queued messages already covered by that are dropped.
    last_event_id = _parse_last_event_id(request)
    replay = hub.replay_since(last_event_id)
    if last_event_id is None or replay is None:
        # Fresh connect, or a buffer gap: send a full snapshot (always correct
        # because a StreamText snapshot carries its full accumulated text).
        init_payload: dict[str, Any] | None = init_message(session.snapshot())
        replay = []
    else:
        # A clean resume: the client already has the tree; replay what it missed.
        init_payload = None
    skip_upto = hub.current_offset

    async def event_source() -> AsyncIterator[str]:
        try:
            async for chunk in sse_events(
                queue,
                init_payload,
                app.state.heartbeat_seconds,
                replay=replay,
                skip_upto=skip_upto,
            ):
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

    hub: Hub = request.app.state.hub
    session: Session = request.app.state.session
    result = session.dispatch(event.component, event.event, event.payload)
    if result is None:
        return JSONResponse({"ok": False, "error": "unknown event"}, status_code=400)

    if result.changes:
        hub.publish(patch_message(result.changes))
    if result.coro is not None:
        # Run the async handler in the background: the POST returns now and the
        # work streams over SSE, so it never holds the request open past the
        # proxy timeout, nor blocks the event loop or other sessions (R3).
        session.spawn(result.coro)
    return JSONResponse({"ok": True})


def _parse_last_event_id(request: Request) -> int | None:
    """The SSE resume offset, from the ``Last-Event-Id`` header (EventSource sets
    it natively on reconnect) or a ``?lastEventId=`` fallback. Invalid -> None."""
    raw = request.headers.get("last-event-id") or request.query_params.get("lastEventId")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _sse(message: dict[str, Any], event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(message)}\n\n"


def _read_static(name: str) -> str:
    return files("indah.static").joinpath(name).read_text(encoding="utf-8")

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
import math
import urllib.parse
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from importlib.resources import files
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

try:  # python-multipart raises this on a malformed / over-limit multipart body
    from starlette.datastructures import UploadFile
    from starlette.formparsers import MultiPartException
except Exception:  # pragma: no cover - starlette always ships these
    UploadFile = None  # type: ignore[assignment,misc]
    MultiPartException = Exception  # type: ignore[assignment,misc]

from .components import (
    Button,
    Card,
    Chat,
    Checkbox,
    Column,
    DataFrame,
    Date,
    Expander,
    Gallery,
    Grid,
    Image,
    List,
    MultiSelect,
    Number,
    Plot,
    Progress,
    Radio,
    Row,
    Select,
    Sidebar,
    Slider,
    Spinner,
    StreamText,
    Tabs,
    Text,
    TextInput,
    UploadedFile,
)
from .custom import custom, register_component
from .protocol import EventIn, init_message, patch_message, ping_message
from .reactive import Signal
from .session import Session
from .session_store import (
    InMemorySessionStore,
    SessionHandle,
    SessionStore,
    SharedSessionStore,
)
from .transport import Item

DEFAULT_HEARTBEAT_SECONDS = 15.0

# An id-less connection (a test, a curl, an old shell) shares this one session.
# The real shell mints a per-tab id, so real viewers never land here together.
DEFAULT_SESSION_ID = "default"

# The server-side hard cap on an uploaded file (ADR-0017 / Q-sec). The app author
# can raise or lower it with create_app(max_upload_mb=...); the route rejects a
# larger part with 413 rather than buffering it.
DEFAULT_MAX_UPLOAD_MB = 25.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Tell intermediary proxies (e.g. Runpod's nginx) not to buffer the stream.
    "X-Accel-Buffering": "no",
}

# Some proxies buffer a streamed response in fixed-size windows, forwarding a
# window to the client only once it fills, regardless of X-Accel-Buffering (Colab's
# front-end is the one that bit us). A small SSE frame (the `init`, a slider patch,
# one streamed token) lands in a window that never fills on its own, so the proxy
# holds it and the browser renders nothing -- even though the connection is "live".
#
# An SSE comment line (one starting with ":") is ignored by EventSource, so we
# flush past the window by emitting a block of comment padding: once on connect (so
# the stream opens even before any data), and again after every real frame (so each
# frame is pushed out of the proxy's buffer immediately instead of waiting for the
# next one). 8 KB clears the common window sizes (nginx's default proxy_buffer_size
# is 4-8 KB). This is the "proxy flush" path, enabled for the real HTTP stream and
# off for framing unit tests (ADR-0002, the R2 proxy risk).
_SSE_PADDING_BYTES = 8192
_SSE_FLUSH_PAD = ":" + " " * _SSE_PADDING_BYTES + "\n\n"


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


# The demo generates its "images" as inline SVG data URIs, so the showcase needs no
# image files, no network, and no extra dependency -- it runs on indah alone.
_STYLE_PALETTES: dict[str, list[str]] = {
    "Vivid": ["#b5296b", "#2e6d62", "#e0701a", "#3457d5", "#c0362c"],
    "Muted": ["#8a6d84", "#6e8b84", "#a98a6b", "#6b7a9a", "#7a9a6b"],
    "Mono": ["#241c22", "#4a3d48", "#6e6169", "#a9969f", "#d8ccd3"],
}


def _svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


def _solid(color: str) -> str:
    """A rounded solid-colour swatch (the live accent preview)."""
    return _svg_data_uri(
        "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>"
        f"<rect width='120' height='120' rx='16' fill='{color}'/></svg>"
    )


def _swatch(index: int, style: str) -> dict[str, str]:
    """A numbered colour tile for the gallery, coloured by the chosen style."""
    palette = _STYLE_PALETTES.get(style, _STYLE_PALETTES["Vivid"])
    color = palette[index % len(palette)]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>"
        f"<rect width='200' height='200' fill='{color}'/>"
        "<text x='100' y='120' font-size='64' fill='white' fill-opacity='0.9' "
        f"text-anchor='middle' font-family='sans-serif'>{index + 1}</text></svg>"
    )
    return {"src": _svg_data_uri(svg), "caption": f"{style} #{index + 1}"}


def _svg_chart(temperature: float) -> str:
    """A tiny bar sparkline whose bars scale with the temperature slider."""
    scale = 0.4 + float(temperature) / 3
    bars = []
    for i in range(9):
        height = int((14 + 46 * (0.5 + 0.5 * math.sin(i * 0.8))) * scale)
        bars.append(
            f"<rect x='{8 + i * 22}' y='{86 - height}' width='14' height='{height}' "
            "rx='3' fill='#b5296b'/>"
        )
    return _svg_data_uri(
        f"<svg xmlns='http://www.w3.org/2000/svg' width='210' height='90'>{''.join(bars)}</svg>"
    )


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


def _preview_chart(temperature: Signal[float]) -> Any:
    """A live chart of the temperature. A real Matplotlib ``Plot`` when matplotlib
    is installed (exercising that component), else an inline-SVG ``Image`` so the
    demo still runs on indah alone -- both render through the shell's <img>."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        def figure():
            fig = Figure(figsize=(3, 1.3))
            ax = fig.add_subplot(111)
            xs = [i * 0.4 for i in range(20)]
            ax.plot(xs, [math.sin(x) * (0.4 + temperature.value / 3) for x in xs], color="#b5296b")
            ax.set_axis_off()
            return fig

        return Plot(figure, alt="temperature chart")
    except Exception:
        return Image(lambda: _svg_chart(temperature.value), alt="temperature chart")


def build_demo_session() -> Session:
    """The built-in demo (``make demo``): "indah Studio", a mock prompt-to-content
    workbench that brings every component together in one page.

    A control panel on the left (the full input set + a custom colour picker) feeds
    a tabbed workspace on the right. One **Generate** runs an async handler that, in
    a single non-blocking pass, streams a reply into **Chat** bubbles, renders a
    **Gallery** of colour tiles while driving the **Progress** bar and **Spinner**,
    and updates the **Dashboard** (a DataFrame run history, a templated activity
    List, a streaming console, and Markdown settings) -- proving async work never
    freezes the UI (R3). Layout uses Sidebar/Tabs/Grid/Row/Expander (ADR-0015);
    the lists are data-driven over ``Signal[list]`` (ADR-0016).
    """
    # -- inputs (the left control panel) --
    prompt: Signal[str] = Signal("a serene mountain lake at dawn")
    model: Signal[str] = Signal("indah-mock-mini")
    temperature: Signal[float] = Signal(0.7)
    count: Signal[int] = Signal(3)
    style: Signal[str] = Signal("Vivid")
    tags: Signal[list] = Signal(["landscape"])
    include_notes: Signal[bool] = Signal(True)
    when: Signal[str] = Signal(datetime.now().strftime("%Y-%m-%d"))
    accent: Signal[str] = Signal("#b5296b")

    # -- output state (data-driven, ADR-0016) --
    busy: Signal[bool] = Signal(False)
    progress: Signal[float] = Signal(0.0)
    messages: Signal[list] = Signal([])
    pending: Signal[str] = Signal("")
    images: Signal[list] = Signal([])
    activity: Signal[list] = Signal([])
    history: Signal[list] = Signal([])
    runs: Signal[int] = Signal(0)
    console = StreamText(label="Run console")

    def log(text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        activity.set([{"time": stamp, "text": text}] + activity.value)

    async def generate() -> None:
        if busy.value:
            return
        question = prompt.value.strip() or "something interesting"
        busy.set(True)
        progress.set(0.0)
        console.reset()
        console.feed(f"> run #{runs.value + 1} on {model.value}\n")

        # 1) Chat: the user's turn, then a streamed assistant reply into a live bubble.
        messages.set(messages.value + [{"role": "user", "content": question}])
        pending.set("")
        parts: list[str] = []
        async for token in mock_llm(question):
            pending.set(pending.value + token)
            parts.append(token)
        messages.set(messages.value + [{"role": "assistant", "content": "".join(parts)}])
        pending.set("")
        console.feed("> reply streamed into bubbles\n")

        # 2) Gallery: render `count` tiles, driving the progress bar as it goes.
        n = max(1, int(count.value))
        for i in range(n):
            await asyncio.sleep(0.18)
            images.set(images.value + [_swatch(len(images.value), style.value)])
            progress.set((i + 1) / n)
            console.feed(f"> rendered tile {i + 1}/{n}\n")

        # 3) Dashboard: append to the run history and the activity log.
        runs.set(runs.value + 1)
        history.set(
            history.value
            + [
                {
                    "run": runs.value,
                    "prompt": question,
                    "model": model.value,
                    "style": style.value,
                    "images": n,
                }
            ]
        )
        log(f"Generated {n} {style.value.lower()} tiles for “{question}”")
        if include_notes.value:
            console.feed("> notes attached\n")
        busy.set(False)

    def clear() -> None:
        messages.set([])
        pending.set("")
        images.set([])
        history.set([])
        runs.set(0)
        progress.set(0.0)
        console.reset()
        log("Cleared the workspace")

    def settings_md() -> str:
        return (
            "### Settings\n\n"
            f"- **model** `{model.value}`\n"
            f"- **temperature** `{temperature.value}`\n"
            f"- **images** `{count.value}`\n"
            f"- **style** `{style.value}`\n"
            f"- **tags** `{', '.join(tags.value) or '-'}`\n"
            f"- **notes** `{include_notes.value}`\n"
            f"- **schedule** `{when.value}`\n"
            f"- **accent** `{accent.value}`"
        )

    intro = Text(
        "# indah Studio\n\n"
        "A mock prompt-to-content workbench that brings **every** indah component "
        "into one page. Type a prompt and hit **Generate** -- one click streams a "
        "chat reply, renders a gallery, and fills the dashboard, all without "
        "freezing the page.",
        markdown=True,
    )

    controls = Card(
        title="Controls",
        children=[
            TextInput(
                prompt, label="Prompt", placeholder="Describe something...", on_submit=generate
            ),
            Select(model, options=["indah-mock-mini", "indah-mock-pro"], label="Model"),
            Slider(temperature, min=0, max=2, step=0.1, label="Temperature"),
            Text(lambda: f"temperature = {temperature.value}"),
            Number(count, min=1, max=6, step=1, label="Images to render"),
            Radio(style, options=["Vivid", "Muted", "Mono"], label="Style"),
            MultiSelect(tags, options=["landscape", "portrait", "abstract", "retro"], label="Tags"),
            Checkbox(include_notes, label="Attach notes"),
            Date(when, label="Schedule"),
            Row(
                gap="0.75rem",
                children=[
                    custom("colorpicker", value=accent),
                    Image(lambda: _solid(accent.value), alt="accent preview"),
                ],
            ),
            Row(
                children=[
                    Button("Generate", on_click=generate),
                    Button("Clear", on_click=clear, variant="tonal"),
                ]
            ),
            Spinner(active=busy, label="Generating..."),
            Progress(progress, label="Progress"),
        ],
    )

    dashboard = Column(
        children=[
            Card(
                children=[
                    Grid(
                        columns=2,
                        children=[
                            Column(children=[Text("Runs"), Text(lambda: str(runs.value))]),
                            Column(children=[Text("Tiles"), Text(lambda: str(len(images.value)))]),
                        ],
                    ),
                ],
            ),
            Card(title="Temperature", children=[_preview_chart(temperature)]),
            Card(
                title="Run history",
                children=[
                    DataFrame(
                        lambda: (
                            history.value
                            or {
                                "columns": ["run", "prompt", "model", "style", "images"],
                                "rows": [],
                            }
                        )
                    ),
                ],
            ),
            Card(
                title="Activity",
                children=[
                    List(
                        activity,
                        empty="No activity yet -- hit Generate.",
                        item={
                            "tag": "div",
                            "class": "log-line",
                            "children": [
                                {"tag": "code", "text": "time"},
                                {"tag": "span", "text": "text"},
                            ],
                        },
                    ),
                ],
            ),
            Expander(label="Run console", children=[console]),
            Expander(label="Current settings", children=[Text(settings_md, markdown=True)]),
        ]
    )

    workspace = Sidebar(
        children=[
            controls,
            Tabs(
                labels=["Chat", "Gallery", "Dashboard"],
                children=[
                    Card(title="Conversation", children=[Chat(messages, pending=pending)]),
                    Card(title="Generated tiles", children=[Gallery(images, columns=3)]),
                    dashboard,
                ],
            ),
        ]
    )

    return Session(Column(children=[intro, workspace]))


def create_app(
    *,
    session: Session | None = None,
    session_factory: Callable[[], Session] | None = None,
    store: SessionStore | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    max_upload_mb: float = DEFAULT_MAX_UPLOAD_MB,
) -> Starlette:
    """Build the ASGI app.

    State is reached through a :class:`~indah.session_store.SessionStore` seam
    (ADR-0010), so each viewer gets an isolated session. Three ways to seed it,
    most specific first:

    - ``store=`` -- supply a ``SessionStore`` directly (a future external backend).
    - ``session_factory=`` -- a zero-arg callable that builds a fresh ``Session``
      (new signals) per viewer. The default is the built-in demo, so ``create_app()``
      already isolates viewers.
    - ``session=`` -- a single pre-built ``Session`` **shared** by every viewer (the
      pre-Slice-C behaviour; for single-user apps and introspection in tests).

    ``session``, ``session_factory``, and ``store`` are mutually exclusive.
    """
    given = [
        name
        for name, val in (
            ("session", session),
            ("session_factory", session_factory),
            ("store", store),
        )
        if val is not None
    ]
    if len(given) > 1:
        raise ValueError(f"pass at most one of session/session_factory/store, got {given}")

    if store is None:
        if session is not None:
            store = SharedSessionStore(session)
        else:
            store = InMemorySessionStore(session_factory or build_demo_session)

    app = Starlette(
        routes=[
            Route("/", _index, methods=["GET"]),
            Route("/health", _health, methods=["GET"]),
            Route("/api/stream", _stream, methods=["GET"]),
            Route("/api/event", _event, methods=["POST"]),
            Route("/api/upload", _upload, methods=["POST"]),
            Route("/api/file/{sid}/{token}", _file, methods=["GET"]),
        ]
    )
    app.state.store = store
    app.state.heartbeat_seconds = heartbeat_seconds
    app.state.max_upload_bytes = int(max_upload_mb * 1024 * 1024)
    # Back-compat: a single-shared app still exposes .session/.hub for callers and
    # tests that introspect the one graph. A per-session app has neither -- there is
    # no single session to name; go through the store (keyed by sid) instead.
    if isinstance(store, SharedSessionStore):
        app.state.session = store.handle.session
        app.state.hub = store.handle.hub
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
    proxy_flush: bool = False,
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

    ``proxy_flush`` interleaves ignored comment padding -- once on connect and after
    every frame -- so a window-buffering proxy flushes each frame immediately
    instead of holding it (Colab; see ``_SSE_FLUSH_PAD``).
    """
    if proxy_flush:
        yield _SSE_FLUSH_PAD  # open the stream even before any data (caught-up resume)
    if init_payload is not None:
        yield _sse(init_payload)
        if proxy_flush:
            yield _SSE_FLUSH_PAD
    for offset, message in replay:
        yield _sse(message, event_id=offset)
        if proxy_flush:
            yield _SSE_FLUSH_PAD
    while True:
        try:
            offset, message = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            yield _sse(ping_message())
            if proxy_flush:
                yield _SSE_FLUSH_PAD
            continue
        if offset <= skip_upto:
            continue
        yield _sse(message, event_id=offset)
        if proxy_flush:
            yield _SSE_FLUSH_PAD


async def _stream(request: Request) -> StreamingResponse:
    app = request.app
    store: SessionStore = app.state.store
    # One session per browser tab, keyed by the id the shell sends (?sid=...).
    # An id-less connection shares the default session (ADR-0010).
    sid = request.query_params.get("sid") or DEFAULT_SESSION_ID
    handle: SessionHandle = store.get_or_create(sid)
    hub = handle.hub
    session = handle.session
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
                proxy_flush=True,
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

    # Route the event to the sender's session (ADR-0010): its handler runs on its
    # own signals and its patches go only to its own hub -- never another viewer's.
    store: SessionStore = request.app.state.store
    handle: SessionHandle = store.get_or_create(event.sid or DEFAULT_SESSION_ID)
    hub = handle.hub
    session = handle.session
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


async def _upload(request: Request) -> JSONResponse:
    """Multipart file upload (ADR-0017), separate from the JSON event path.

    Reads the ``sid`` + ``component`` form fields and the uploaded file part(s),
    then dispatches a synthetic ``upload`` event carrying ``UploadedFile`` objects to
    the target ``Upload`` component in the sender's session. From there it is an
    ordinary event: sync mutations broadcast at once, an async handler streams in the
    background, and results flow back over that session's SSE stream. A part larger
    than the server cap is rejected with 413 rather than buffered.
    """
    max_bytes: int = request.app.state.max_upload_bytes
    try:
        async with request.form(max_part_size=max_bytes) as form:
            component_id = form.get("component")
            sid = form.get("sid") or DEFAULT_SESSION_ID
            if not isinstance(component_id, str) or not component_id:
                return JSONResponse({"ok": False, "error": "missing component"}, status_code=400)
            files: list[UploadedFile] = []
            for value in form.getlist("file"):
                if UploadFile is not None and isinstance(value, UploadFile):
                    data = await value.read()
                    if len(data) > max_bytes:
                        return JSONResponse(
                            {"ok": False, "error": "file too large"}, status_code=413
                        )
                    files.append(
                        UploadedFile(
                            filename=value.filename or "",
                            content_type=value.content_type or "application/octet-stream",
                            data=data,
                        )
                    )
    except MultiPartException:
        return JSONResponse({"ok": False, "error": "file too large"}, status_code=413)

    store: SessionStore = request.app.state.store
    handle: SessionHandle = store.get_or_create(sid)
    result = handle.session.dispatch(component_id, "upload", {"files": files})
    if result is None:
        return JSONResponse({"ok": False, "error": "unknown component"}, status_code=400)

    if result.changes:
        handle.hub.publish(patch_message(result.changes))
    if result.coro is not None:
        handle.session.spawn(result.coro)
    return JSONResponse({"ok": True, "files": [f.filename for f in files]})


async def _file(request: Request) -> Response:
    """Serve a file handed back to a viewer (ADR-0017): file-out over a blob URL.

    The path carries the session id and an unguessable token; the bytes live in that
    session's file store, so one viewer's download is not reachable from another's
    session. Unknown id or token is a 404.
    """
    store: SessionStore = request.app.state.store
    handle = store.get(request.path_params["sid"])
    if handle is None:
        return Response(status_code=404)
    found = handle.session.get_file(request.path_params["token"])
    if found is None:
        return Response(status_code=404)
    data, filename, media_type = found
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

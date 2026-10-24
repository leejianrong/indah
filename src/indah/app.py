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
import hashlib
import json
import logging
import math
import os
import re
import time
import urllib.parse
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
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

from .audit import AuditHook
from .audit import emit as emit_audit
from .auth import (
    Authenticator,
    Principal,
    TokenSigner,
    authenticate,
    default_authenticator,
)
from .authz import Policy, authz_scope
from .components import (
    DENSITIES,
    Button,
    Card,
    Chat,
    Checkbox,
    Column,
    Component,
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
from .compress import accepts_gzip, gzip_joined, gzip_static, matches_etag, variant_etag
from .context import ConnectionInfo, Context
from .csp import (
    add_nonce,
    add_nonce_parts,
    build_csp,
    known_img_hosts,
    new_nonce,
    render_custom,
)
from .custom import custom, register_component, registered
from .drain import Drain, chain_sigterm
from .guard import OriginGuard, normalize_origins
from .hardening import (
    Limits,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    StreamLimiter,
    peer_address,
)
from .protocol import EventIn, init_message, patch_message, ping_message, signed_out_message
from .proxy import ProxyHeaders, ProxyNotice, parse_trusted
from .reactive import Signal
from .session import DispatchResult, Session
from .session_store import (
    DEFAULT_FACTORY_TIMEOUT,
    InMemorySessionStore,
    SessionHandle,
    SessionStore,
    SharedSessionStore,
)
from .theme import Theme
from .transport import Hub, Item

DEFAULT_HEARTBEAT_SECONDS = 15.0
DEFAULT_DRAIN_SECONDS = 10.0

# An id-less connection (a test, a curl, an old shell) shares this one session.
# The real shell mints a per-tab id, so real viewers never land here together.
logger = logging.getLogger("indah")

DEFAULT_SESSION_ID = "default"

# The server-side hard cap on an uploaded file (ADR-0017 / Q-sec). The app author
# can raise or lower it with create_app(max_upload_mb=...); the route rejects a
# larger part with 413 rather than buffering it.
DEFAULT_MAX_UPLOAD_MB = 25.0
DEFAULT_MAX_WIDTH = "1080px"
_LENGTH = re.compile(r"\d+(\.\d+)?(px|rem|em|vw|%)")

# The hard cap on a JSON event body (IND-98). A text area can carry a long note, so
# this is generous; the route returns 413 rather than buffer an unbounded body.
DEFAULT_MAX_EVENT_BYTES = 1024 * 1024

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
# An SSE comment line (one starting with ":") is ignored by EventSource, so we flush
# past the window by emitting comment padding. The window size below (8 KB) clears
# the common proxy windows (nginx's default proxy_buffer_size is 4-8 KB). This is the
# "proxy flush" path, enabled for the real HTTP stream and off for framing unit tests
# (ADR-0002, the R2 proxy risk).
#
# KAN-1395: rather than a full window after *every* frame, we (1) coalesce a burst of
# frames already queued (streamed tokens, streamed chart points) into one flush, and
# (2) pad each flush only up to the next window boundary, tracking cumulative bytes --
# so a large frame or a coalesced burst pays only its tail, not a whole fresh window.
# A lone small frame still costs ~one window, which is irreducible for a
# window-buffering proxy, but the per-token amplification is gone. ``_SSE_FLUSH_PAD``
# is the connect lead-in (exactly one window) and doubles as the on/off knob: setting
# it to "" disables all padding (the negative proxy-buffering e2e relies on this).
_SSE_PADDING_BYTES = 8192


def _pad_chunk(nbytes: int) -> str:
    """An ignored SSE comment line of exactly ``nbytes`` bytes (``nbytes >= 3``)."""
    return ":" + " " * (nbytes - 3) + "\n\n"


def _boundary_pad(pending: int) -> str:
    """Padding that tops ``pending`` unflushed bytes up to the next window boundary,
    so the proxy releases the frame(s) already emitted. Empty when already aligned."""
    needed = (-pending) % _SSE_PADDING_BYTES
    if needed == 0:
        return ""
    if needed < 3:  # too small to form a comment line exactly; carry a whole window
        needed += _SSE_PADDING_BYTES
    return _pad_chunk(needed)


_SSE_FLUSH_PAD = _pad_chunk(_SSE_PADDING_BYTES)


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
                            Column(
                                children=[
                                    Text("Runs", variant="label"),
                                    Text(lambda: str(runs.value), variant="readout"),
                                ]
                            ),
                            Column(
                                children=[
                                    Text("Tiles", variant="label"),
                                    Text(lambda: str(len(images.value)), variant="readout"),
                                ]
                            ),
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
    session_factory: Callable[[], Session]
    | Callable[[Context], Session]
    | Callable[[], Awaitable[Session]]
    | Callable[[Context], Awaitable[Session]]
    | None = None,
    store: SessionStore | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    max_upload_mb: float = DEFAULT_MAX_UPLOAD_MB,
    max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    title: str | None = None,
    title_suffix: str = " - indah",
    home_url: str | None = None,
    source_url: str | None = None,
    spa: bool = False,
    proxy_flush: bool = True,
    theme: Theme | None = None,
    density: str = "comfortable",
    max_width: str = DEFAULT_MAX_WIDTH,
    auth: Authenticator | None = None,
    secure: bool = False,
    secret: str | bytes | Sequence[str | bytes] | None = None,
    allowed_origins: Sequence[str] = (),
    trusted_proxies: Sequence[str] = (),
    warn_untrusted_forwarding: bool = True,
    audit: AuditHook | None = None,
    audit_payloads: bool = False,
    policy: Policy | None = None,
    limits: Limits | None = None,
    csp: str | None = None,
    csp_media_hosts: Sequence[str] = (),
    security_headers: bool | Mapping[str, str] = False,
    logo: str | os.PathLike[str] | bytes | tuple[Any, Any] | None = None,
    favicons: Mapping[str, str | os.PathLike[str] | bytes] | None = None,
    factory_timeout: float = DEFAULT_FACTORY_TIMEOUT,
    factory_placeholder: Callable[[], Component] | None = None,
    compress: bool = True,
    drain_seconds: float = DEFAULT_DRAIN_SECONDS,
    drain_on_sigterm: bool = True,
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

    A ``session_factory`` may be ``async def`` (IND-153): it is awaited for up to
    ``factory_timeout`` seconds (default 1) before the first snapshot, so a fast one puts its
    data in the first paint. A slower one lets the tab start on ``factory_placeholder()`` (a
    ``Skeleton`` by default) and the real tree arrives on the same stream when it finishes. A
    factory that raises shows an error and the next connection tries again. Sync factories are
    unchanged. These two options apply to the built-in in-memory store, not a ``store=`` you pass.

    ``spa=True`` serves the shell for any non-``api/`` GET path, so an in-app URL
    (``/projects/auth/entries/01J``) can be opened directly or reloaded. The shell then
    gets a relative ``<base href>`` so its ``api/*`` calls still reach the app root,
    whatever prefix the app is mounted under (IND-86).

    ``max_event_bytes`` (default 1 MiB) caps one ``POST /api/event`` body; a larger one
    is rejected with ``413`` before it is parsed.

    ``proxy_flush`` (default on) pads the SSE stream so a window-buffering proxy such as
    Colab's releases each frame (ADR-0002); a deployment with no such proxy -- a local
    container -- can turn it off and pay only payload plus framing.

    ``density`` (``"comfortable"``, the default, or ``"compact"``) sets the row height and
    cell padding of tables across the app; a ``Table(density=)`` overrides it for one table.

    ``drain_seconds`` (default 10) is how long a draining process keeps serving the sessions it
    already holds before it ends the streams still open (IND-201). A drain starts on SIGTERM
    (``launch()`` and ``uvicorn app:app`` with ``drain_on_sigterm=True``, the default) or when your
    own shutdown code runs ``await app.state.drain.run()``. While draining, ``GET /ready`` answers
    ``503``, new streams and new sessions are refused with ``503`` and ``Retry-After``, and every
    open stream is sent a ``reconnect`` message so the tab moves to another process. ``GET /health``
    stays ``200`` (liveness). With no stream open a drain is over at once.

    ``auth`` (an :data:`~indah.auth.Authenticator`: request -> :class:`~indah.auth.Principal`
    or ``None``) says who each request is, so a session factory can read ``ctx.user`` and each
    session is owned by one principal. ``secure=True`` (ADR-0033) turns that into a rule: no
    principal is 401, another principal's session is 403, and an id-less request (the shared
    ``default`` session) is refused. With ``secure=True`` and no ``auth``, Starlette's
    ``scope["user"]`` (a parent app's ``AuthenticationMiddleware``) is used. It needs a
    per-viewer ``session_factory``: one shared ``Session`` cannot be secure.

    A secure app also refuses cross-origin requests (a multipart upload from another site is
    the classic CSRF): ``allowed_origins`` lists extra origins (``"https://app.example.com"``)
    that may call it, for a gateway on another origin. Same-origin browsers need nothing.

    ``trusted_proxies`` (IPs or CIDRs of your gateway) says whose ``X-Forwarded-For``, ``-Proto``,
    ``-Host`` and ``-Prefix`` headers to believe (ADR-0034); by default none are, so a client
    cannot pick its own address, scheme or prefix. If a forwarded header (``X-Forwarded-For``,
    ``Forwarded``, ``X-Forwarded-Proto``, ``Fly-Client-IP``, ``CF-Connecting-IP``) arrives while
    ``trusted_proxies`` is empty, one warning is logged (header names and the socket peer only)
    and ``app.state.proxy_warning_issued`` becomes true; ``warn_untrusted_forwarding=False``
    silences it for an app that really has no proxy in front. ``audit`` is called with an
    :class:`~indah.audit.AuditEvent` after each UI event (who, which component, which event,
    the payload keys; values only with ``audit_payloads=True``, never from a sensitive field).

    ``policy`` (a :class:`~indah.authz.Policy`: roles to permissions) backs ``ctx.can``,
    ``ctx.require`` and :func:`~indah.authz.guard` (ADR-0035). Without one a permission is a
    role name. A guarded handler is checked against the principal of the request that runs it,
    so a role revoked mid-session fails closed on the next action.

    ``limits`` (:class:`~indah.hardening.Limits`) bounds a public app: a per-address rate limit
    on ``api/event``/``api/upload``/``api/stream`` (``429``), a cap on open streams per address
    (``429``), the event and upload body caps (``413``), and session count/idle bounds. Every
    field defaults to unset, which leaves today's behaviour. ``security_headers=True`` adds
    ``nosniff``, a ``Referrer-Policy`` and ``X-Frame-Options: DENY`` to every response (a mapping
    replaces individual ones, ``""`` drops one). The address used is the socket peer, so behind a
    gateway also set ``trusted_proxies`` (ADR-0037).

    ``csp="strict"`` serves the shell with a Content-Security-Policy: a per-response nonce on
    its inline ``<script>``/``<style>`` tags and nothing else allowed to run (ADR-0038). Images
    and audio may come from ``'self'``, ``data:``, ``blob:`` and the tile hosts of any ``Map`` (plus
    ``csp_media_hosts``, a list of ``https://host`` sources). Violations are reported to
    ``POST api/csp-report`` and kept in ``app.state.csp_violations``. Any other string is used
    as the policy, with ``{nonce}`` replaced per response. Off by default, and in ``launch()``:
    a notebook frames the app, which a fixed policy would break.

    A secure app also needs ``secret`` (at least 16 random bytes; a list rotates: the first
    signs, any verifies). The shell trades its login for a signed session token with
    ``POST api/session`` and sends that token as its session id, so a client cannot choose an
    id or present another user's (ADR-0033).

    ``theme`` overrides the shell's design tokens for this app (IND-88, see
    :class:`~indah.theme.Theme`). ``max_width`` is the page frame's widest size (a CSS length
    such as ``"1400px"`` or ``"90rem"``, or ``"none"`` to fill the window); the default is
    ``"1080px"``. ``logo`` (an SVG/PNG/JPEG/WebP file path or bytes, up to
    512 KB) replaces the Bunga mark in the header and, with ``title``, the "indah"
    wordmark -- a rebranded app; ``title`` alone only renames the tab, as before. Pass
    ``(light, dark)`` for a mark per colour scheme: the header shows the one that matches
    indah's own light/dark toggle, so a dark mark does not vanish on the dark page. (An SVG
    that relies on ``currentColor`` does not work: the logo is shown in an ``<img>``, which
    cannot inherit the page's colour. Pass a pair instead.) The tab
    reads ``"<title> - indah"``; ``title_suffix`` replaces that suffix (``""`` gives the exact
    ``title``).

    ``favicons`` maps a name (lower-case words, up to 16 of them) to an icon (a PNG, SVG, ICO,
    JPEG or WebP path or bytes, up to 64 KB). A session switches its tab's icon to one by name
    with ``ctx.favicon.set("alert")`` and its title with ``ctx.title.set("(2) app")``; both
    go back to the app's own with ``None`` (IND-152).

    ``compress`` (on by default) gzips the shell, ``api/editor.js`` and module component files
    for a client that sends ``Accept-Encoding: gzip`` (ADR-0042, IND-189). The event stream and
    JSON routes are never compressed. Pass ``False`` behind a gateway that should do all of it.
    """
    if csp is not None and (not isinstance(csp, str) or not csp.strip()):
        raise ValueError("csp must be None, 'strict', or a policy string")
    if density not in DENSITIES:
        raise ValueError(f"density must be one of {DENSITIES}, got {density!r}")
    if max_width != "none" and not _LENGTH.fullmatch(max_width):
        raise ValueError(
            f"max_width must be 'none' or a CSS length like '1400px', got {max_width!r}"
        )
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

    signer: TokenSigner | None = None
    if secure:
        if secret is None:
            raise ValueError("secure=True needs secret= (a long random value, e.g. from the env)")
        signer = TokenSigner(secret)
        if auth is None:
            auth = default_authenticator
        if session is not None or isinstance(store, SharedSessionStore):
            raise ValueError(
                "secure=True needs a per-viewer session_factory (or store): a single shared "
                "Session would be one state for every user"
            )

    if store is None:
        if session is not None:
            store = SharedSessionStore(session)
        else:
            store = InMemorySessionStore(
                session_factory or build_demo_session,
                factory_timeout=factory_timeout,
                placeholder=factory_placeholder,
            )

    limits = limits or Limits()
    if limits.max_event_bytes is not None:
        max_event_bytes = limits.max_event_bytes
    if limits.max_upload_mb is not None:
        max_upload_mb = limits.max_upload_mb
    if isinstance(store, InMemorySessionStore):
        if limits.max_sessions is not None:
            store.max_sessions = limits.max_sessions
        if limits.session_idle_seconds is not None:
            store.idle_timeout_seconds = limits.session_idle_seconds

    # Outermost first: resolve the client address, then headers, then the rate limit, then
    # (secure apps) the origin guard, so a flood is turned away before it is parsed.
    proxy_notice = ProxyNotice(enabled=warn_untrusted_forwarding)
    middleware = [
        Middleware(ProxyHeaders, trusted=parse_trusted(trusted_proxies), notice=proxy_notice)
    ]
    if security_headers:
        middleware.append(
            Middleware(
                SecurityHeadersMiddleware,
                headers=None if security_headers is True else security_headers,
            )
        )
    if limits.rate:
        middleware.append(Middleware(RateLimitMiddleware, rates=limits.rate))
    if secure:
        middleware.append(
            Middleware(OriginGuard, allowed_origins=normalize_origins(allowed_origins))
        )
    drain = Drain(drain_seconds)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        drain.loop = asyncio.get_running_loop()
        restore = chain_sigterm(drain, drain.loop) if drain_on_sigterm else None
        try:
            yield
        finally:
            if restore is not None:
                restore()

    app = Starlette(
        middleware=middleware,
        lifespan=lifespan,
        routes=[
            Route("/", _index, methods=["GET"]),
            Route("/health", _health, methods=["GET"]),
            Route("/ready", _ready, methods=["GET"]),
            *([Route("/api/session", _session, methods=["POST"])] if secure else []),
            Route("/api/stream", _stream, methods=["GET"]),
            Route("/api/event", _event, methods=["POST"]),
            Route("/api/upload", _upload, methods=["POST"]),
            Route("/api/editor.js", _editor_js, methods=["GET"]),
            Route("/api/map.js", _map_js, methods=["GET"]),
            Route("/api/components/{name}.js", _component_js, methods=["GET"]),
            *([Route("/api/csp-report", _csp_report, methods=["POST"])] if csp == "strict" else []),
            Route("/api/file/{sid}/{token}", _file, methods=["GET"]),
            *([Route("/api/brand/logo", _logo, methods=["GET"])] if logo is not None else []),
            *([Route("/api/brand/favicon/{name}", _favicon, methods=["GET"])] if favicons else []),
            *([Route("/{path:path}", _spa_index, methods=["GET"])] if spa else []),
        ],
    )
    app.state.store = store
    app.state.drain = drain
    app.state.drain_on_sigterm = drain_on_sigterm
    app.state.auth = auth
    app.state.secure = secure
    app.state.signer = signer
    app.state.audit = audit
    app.state.audit_payloads = audit_payloads
    app.state.policy = policy
    proxy_notice.state = app.state
    app.state.proxy_notice = proxy_notice
    app.state.proxy_warning_issued = False
    app.state.csp = csp
    app.state.compress = compress
    app.state.csp_media_hosts = tuple(csp_media_hosts)
    app.state.csp_violations = deque(maxlen=100)
    app.state.stream_limiter = StreamLimiter(limits.max_streams_per_ip)
    if hasattr(store, "app"):
        store.app = app  # so each session's Context can reach its ASGI app
    app.state.heartbeat_seconds = heartbeat_seconds
    app.state.proxy_flush = proxy_flush
    app.state.max_upload_bytes = int(max_upload_mb * 1024 * 1024)
    app.state.max_event_bytes = max_event_bytes
    # Optional page chrome, injected into the served shell by ``_index``. The gallery
    # sets these per demo (a clickable logo back to the gallery, a view-source link,
    # a distinct tab title); a standalone app leaves them unset and gets the plain shell.
    app.state.page_title = title
    app.state.title_suffix = title_suffix
    app.state.home_url = home_url
    app.state.source_url = source_url
    app.state.density = density
    theme_css = theme.css() if theme is not None else ""
    if max_width != DEFAULT_MAX_WIDTH:
        theme_css += f"\n:root {{ --page-max: {max_width}; }}"
    app.state.theme_css = theme_css.strip()
    if isinstance(logo, tuple):
        if len(logo) != 2:
            raise ValueError("logo as a pair is (light, dark)")
        app.state.logo = _load_logo(logo[0])
        app.state.logo_dark = _load_logo(logo[1])
    else:
        app.state.logo = _load_logo(logo) if logo is not None else None
        app.state.logo_dark = None
    app.state.favicons = _load_favicons(favicons)
    # Back-compat: a single-shared app still exposes .session/.hub for callers and
    # tests that introspect the one graph. A per-session app has neither -- there is
    # no single session to name; go through the store (keyed by sid) instead.
    if isinstance(store, SharedSessionStore):
        app.state.session = store.handle.session
        app.state.hub = store.handle.hub
    return app


def _base_href(path: str, root_path: str = "") -> str | None:
    """A relative ``<base href>`` that points a deep in-app URL back at the app root.

    ``None`` at the root. Relative (``../../``) rather than absolute so it holds under a
    ``Mount`` and behind a proxy that strips a prefix the app never sees (ADR-0001).
    Starlette 1.x keeps the mount prefix in ``scope["path"]``; older versions do not, so
    the prefix is stripped only if present.
    """
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :]
    segments = [seg for seg in path.split("/") if seg]
    ups = len(segments) if path.endswith("/") else len(segments) - 1
    return "../" * ups if ups > 0 else None


def _chrome_html(state: Any, base_href: str | None = None) -> str:
    """Serve the shell, injecting optional per-app chrome.

    ``title`` renames the browser tab; ``home_url`` (a clickable logo) and
    ``source_url`` (a view-source link) are handed to the shell as a small JSON
    blob on ``window.__INDAH_CHROME__``. All three come from ``create_app`` via
    ``app.state``; unset means the plain shell. The blob is JSON with ``<`` escaped
    so a URL can never break out of the ``<script>``.
    """
    html_text = _read_static("index.html")
    if base_href:
        html_text = html_text.replace("<head>", f'<head><base href="{escape(base_href)}">', 1)
    title = getattr(state, "page_title", None)
    if title:
        html_text = html_text.replace(
            "<title>indah</title>",
            f"<title>{escape(title)}{escape(getattr(state, 'title_suffix', ' - indah'))}</title>",
            1,
        )
    chrome = {
        "homeUrl": getattr(state, "home_url", None),
        "sourceUrl": getattr(state, "source_url", None),
        "title": title,
        "logoUrl": "api/brand/logo" if getattr(state, "logo", None) else None,
        "logoDarkUrl": "api/brand/logo?scheme=dark" if getattr(state, "logo_dark", None) else None,
        "brandName": title if getattr(state, "logo", None) else None,
        "secure": True if getattr(state, "secure", False) else None,
    }
    if getattr(state, "density", "comfortable") != "comfortable":
        html_text = html_text.replace(
            '<html lang="en">', f'<html lang="en" data-density="{escape(state.density)}">', 1
        )
    theme_css = getattr(state, "theme_css", "")
    if theme_css:
        html_text = html_text.replace(
            "</head>", f'<style id="indah-theme">\n{theme_css}\n</style></head>', 1
        )
    if any(chrome.values()):
        payload = json.dumps(chrome).replace("<", "\\u003c")
        html_text = html_text.replace(
            "</head>", f"<script>window.__INDAH_CHROME__={payload}</script></head>", 1
        )
    return html_text


def _compression(request: Request) -> bool | None:
    """``None`` when compression is off for this app, else whether this client takes gzip."""
    if not getattr(request.app.state, "compress", True):
        return None
    return accepts_gzip(request.headers.get("accept-encoding"))


async def _html_response(
    request: Request, html_text: str, headers: dict[str, str], nonce: str | None = None
) -> Response:
    """The shell, gzipped when the client accepts it (ADR-0042). The page is a static template
    with the CSP nonce inserted after each ``<script`` and ``<style``, so it is compressed in
    cached pieces rather than once per response."""
    gz = _compression(request)
    if gz is None:
        return HTMLResponse(add_nonce(html_text, nonce) if nonce else html_text, headers=headers)
    headers = {**headers, "Vary": "Accept-Encoding"}
    if not gz:
        return HTMLResponse(add_nonce(html_text, nonce) if nonce else html_text, headers=headers)
    parts = add_nonce_parts(html_text) if nonce else [html_text]
    packed = await run_in_threadpool(gzip_joined, parts, f' nonce="{nonce}"' if nonce else "")
    return HTMLResponse(packed, headers={**headers, "Content-Encoding": "gzip"})


async def _index(request: Request) -> Response:
    state = request.app.state
    base = _base_href(request.scope.get("path", "/"), request.scope.get("root_path", ""))
    html_text = _chrome_html(state, base)
    if not state.csp:
        return await _html_response(request, html_text, {})
    nonce = new_nonce()
    if state.csp == "strict":
        policy = build_csp(
            nonce,
            img_hosts=[*known_img_hosts(), *state.csp_media_hosts],
            report_uri=f"{base or ''}api/csp-report",
        )
    else:
        policy = render_custom(state.csp, nonce)
    return await _html_response(
        request,
        html_text,
        {"Content-Security-Policy": policy, "Cache-Control": "no-store"},
        nonce=nonce,
    )


async def _csp_report(request: Request) -> Response:
    """Collect a browser's CSP violation report (``report-uri``). Untrusted input: capped,
    parsed leniently, kept in a bounded deque, and always answered ``204``."""
    body = await _read_capped(request, 8192)
    try:
        raw = json.loads(body) if body else {}
        report = raw.get("csp-report") if isinstance(raw, dict) else None
    except ValueError:
        report = None
    if isinstance(report, dict):
        keep = {
            k: str(v)[:300]
            for k, v in report.items()
            if k in ("violated-directive", "effective-directive", "blocked-uri", "document-uri")
        }
        request.app.state.csp_violations.append(keep)
        logger.warning("indah CSP violation reported: %s", keep)
    return Response(status_code=204)


async def _spa_index(request: Request) -> Response:
    """The ``spa=True`` fallback: the shell for any in-app path, never for ``api/``."""
    path = request.path_params["path"]
    if path == "api" or path.startswith("api/"):
        return Response(status_code=404)
    return await _index(request)


_LAZY_DIGESTS: dict[str, str] = {}


async def _static_js(request: Request, data: bytes, etag: str, key: str, cache: str) -> Response:
    """A static JavaScript file, gzipped once (cached under ``key``) when the client accepts it,
    with a validator per representation and ``Vary`` so a cache keeps the two apart."""
    gz = _compression(request)
    headers = {"Cache-Control": cache}
    if gz is not None:
        headers["Vary"] = "Accept-Encoding"
    etag = variant_etag(etag, bool(gz))
    headers["ETag"] = etag
    if matches_etag(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    if gz:
        data = await run_in_threadpool(gzip_static, key, data)
        headers["Content-Encoding"] = "gzip"
    return Response(data, media_type="text/javascript", headers=headers)


def _lazy_module(filename: str) -> Callable[[Request], Awaitable[Response]]:
    """A route serving one lazily loaded shell module from the wheel (ADR-0032 editor, ADR-0042
    map). The file name is fixed where the route is declared, so nothing the client sends becomes
    a path. A request that carries the module's content hash (``?v=``, as the shell builds it) is
    cached for good; any other is revalidated with the ETag, so a new indah version is picked up
    but never re-downloaded needlessly. Gzipped when the client accepts it (ADR-0042)."""

    async def handler(request: Request) -> Response:
        try:
            data = files("indah.static").joinpath(filename).read_bytes()
        except FileNotFoundError:
            return Response(status_code=404)
        digest = _LAZY_DIGESTS.get(filename)
        if digest is None:
            digest = _LAZY_DIGESTS[filename] = hashlib.sha1(data).hexdigest()[:16]
        pinned = request.query_params.get("v") == digest
        cache = "public, max-age=31536000, immutable" if pinned else "no-cache"
        return await _static_js(request, data, f'"{digest}"', f"{filename}:{digest}", cache)

    return handler


_editor_js = _lazy_module("editor.js")
_map_js = _lazy_module("map.js")


_COMPONENT_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


async def _component_js(request: Request) -> Response:
    """The ES module of a registered module component (ADR-0039), from memory. The name must
    match a strict pattern and be in the registry, so nothing the client sends becomes a path.
    A request that carries the module's content hash (``?v=``, as the snapshot's URL does) is
    cached for good; any other is revalidated."""
    name = request.path_params["name"]
    reg = registered(name) if _COMPONENT_NAME.match(name) else None
    if reg is None or reg.module is None:
        return Response(status_code=404)
    pinned = request.query_params.get("v") == reg.module_hash
    cache = "public, max-age=31536000, immutable" if pinned else "no-cache"
    return await _static_js(
        request, reg.module, f'"{reg.module_hash}"', "module:" + reg.module_hash, cache
    )


_MAX_LOGO_BYTES = 512 * 1024
_LOGO_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def _load_logo(logo: str | os.PathLike[str] | bytes) -> tuple[bytes, str]:
    """Read and sniff a custom logo. Fails at app creation, not on first request."""
    data = bytes(logo) if isinstance(logo, bytes) else Path(logo).read_bytes()
    if len(data) > _MAX_LOGO_BYTES:
        raise ValueError(f"logo is {len(data)} bytes; the limit is {_MAX_LOGO_BYTES}")
    try:
        return _sniff_image(data)
    except ValueError:
        raise ValueError("logo must be an SVG, PNG, JPEG or WebP image") from None


def _sniff_image(data: bytes) -> tuple[bytes, str]:
    """``(data, media type)`` for a PNG, JPEG, WebP or SVG, by its first bytes."""
    for magic, media_type in _LOGO_MAGIC:
        if data.startswith(magic):
            return data, media_type
    if data[:12].startswith(b"RIFF") and data[8:12] == b"WEBP":
        return data, "image/webp"
    if b"<svg" in data[:2048].lower():
        return data, "image/svg+xml"
    raise ValueError("not a PNG, JPEG, WebP or SVG image")


_MAX_FAVICON_BYTES = 64 * 1024
_MAX_FAVICONS = 16
_FAVICON_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def _load_favicons(
    favicons: Mapping[str, str | os.PathLike[str] | bytes] | None,
) -> dict[str, tuple[bytes, str]]:
    """Read and sniff the registered favicons. Fails at app creation, not on first request."""
    out: dict[str, tuple[bytes, str]] = {}
    if not favicons:
        return out
    if len(favicons) > _MAX_FAVICONS:
        raise ValueError(f"at most {_MAX_FAVICONS} favicons, got {len(favicons)}")
    for name, source in favicons.items():
        if not isinstance(name, str) or not _FAVICON_NAME.fullmatch(name):
            raise ValueError(f"favicon name {name!r} must be lower-case letters, digits, _ or -")
        data = bytes(source) if isinstance(source, bytes) else Path(source).read_bytes()
        if len(data) > _MAX_FAVICON_BYTES:
            raise ValueError(
                f"favicon {name!r} is {len(data)} bytes; the limit is {_MAX_FAVICON_BYTES}"
            )
        if data.startswith(b"\x00\x00\x01\x00"):
            out[name] = (data, "image/x-icon")
            continue
        try:
            out[name] = _sniff_image(data)
        except ValueError:
            raise ValueError(
                f"favicon {name!r} must be a PNG, SVG, ICO, JPEG or WebP image"
            ) from None
    return out


async def _favicon(request: Request) -> Response:
    """A registered favicon by name. The name must already be in the registry, so nothing from
    the client reaches a file path; ``sandbox`` stops script in an SVG opened directly."""
    name = request.path_params["name"]
    entry = request.app.state.favicons.get(name) if _FAVICON_NAME.fullmatch(name) else None
    if entry is None:
        return Response(status_code=404)
    data, media_type = entry
    return Response(
        data,
        media_type=media_type,
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        },
    )


async def _logo(request: Request) -> Response:
    """The custom logo. ``sandbox`` makes the browser refuse any script in an SVG that
    is opened directly; inside the shell's <img> it cannot run script anyway."""
    state = request.app.state
    dark = request.query_params.get("scheme") == "dark" and state.logo_dark is not None
    data, media_type = state.logo_dark if dark else state.logo
    return Response(
        data,
        media_type=media_type,
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=3600",
        },
    )


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _ready(request: Request) -> JSONResponse:
    """Readiness for a load balancer or Kubernetes: ``200`` while this process takes new tabs,
    ``503`` once it is draining (IND-201). Never touches a session, needs no login."""
    headers = {"Cache-Control": "no-store"}
    if request.app.state.drain.draining:
        headers["Retry-After"] = "1"
        return JSONResponse({"ready": False, "draining": True}, status_code=503, headers=headers)
    return JSONResponse({"ready": True}, headers=headers)


def _draining() -> JSONResponse:
    """The refusal for a new stream or session while this process drains: try again, and the
    platform (which has stopped routing here, see ``/ready``) sends the retry elsewhere."""
    return JSONResponse(
        {"ok": False, "error": "draining"}, status_code=503, headers={"Retry-After": "1"}
    )


async def sse_events(
    queue: asyncio.Queue[Item],
    init_payload: dict[str, Any] | None,
    heartbeat_seconds: float,
    *,
    replay: tuple[Item, ...] | list[Item] = (),
    skip_upto: int = 0,
    proxy_flush: bool = False,
    id_prefix: str = "",
    expires_at: float | None = None,
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

    ``proxy_flush`` interleaves ignored comment padding so a window-buffering proxy
    releases each frame immediately instead of holding it (Colab; see
    ``_SSE_FLUSH_PAD``). It coalesces a queued burst into one flush and pads only up
    to the next window boundary, so streaming does not pay a full window per frame
    (KAN-1395).

    ``id_prefix`` is prepended to each SSE ``id:`` (``"<hub epoch>-"`` on the real
    stream) so an id is only meaningful to the hub that issued it (IND-85).

    The stream ends after a ``signed_out`` message (``ctx.sign_out()``), and at ``expires_at``
    (epoch seconds, a secure app's ``Principal.expires_at``) it sends one and ends, so a login
    that lapses does not keep an open stream alive (ADR-0033).
    """
    # ``_SSE_FLUSH_PAD`` doubles as the on/off knob: "" disables all padding.
    flush_on = proxy_flush and bool(_SSE_FLUSH_PAD)
    pending = 0  # bytes emitted since the last window-boundary flush

    if flush_on:
        yield _SSE_FLUSH_PAD  # open the stream even before any data (caught-up resume)

    # Connect-time frames (a fresh init and/or a replay of missed messages) go out
    # back to back and share one trailing pad.
    connect_frames = 0
    if init_payload is not None:
        chunk = _sse(init_payload)
        pending += len(chunk)
        connect_frames += 1
        yield chunk
    for offset, message in replay:
        chunk = _sse(message, event_id=offset, id_prefix=id_prefix)
        pending += len(chunk)
        connect_frames += 1
        yield chunk
    if flush_on and connect_frames:
        pad = _boundary_pad(pending)
        pending = 0
        if pad:
            yield pad

    while True:
        timeout = heartbeat_seconds
        if expires_at is not None:
            timeout = min(timeout, max(0.0, expires_at - time.time()))
        try:
            offset, message = await asyncio.wait_for(queue.get(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            if expires_at is not None and time.time() >= expires_at:
                yield _sse(signed_out_message())
                return
            chunk = _sse(ping_message())
            pending += len(chunk)
            yield chunk
            if flush_on:
                pad = _boundary_pad(pending)
                pending = 0
                if pad:
                    yield pad
            continue

        # Coalesce a burst: drain everything already queued so a run of rapid
        # appends (streamed tokens, streamed chart points) shares one flush pad
        # instead of paying a whole window each (KAN-1395).
        batch = [(offset, message)]
        while True:
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        emitted = 0
        for off, msg in batch:
            kind = msg.get("type")
            if kind == "drain_end":  # the server is ending this stream: never sent to the tab
                return
            if kind == "reconnect":  # not state: no id, and never skipped as already seen
                chunk = _sse(msg)
                pending += len(chunk)
                emitted += 1
                yield chunk
                continue
            if off <= skip_upto:
                continue
            chunk = _sse(msg, event_id=off, id_prefix=id_prefix)
            pending += len(chunk)
            emitted += 1
            yield chunk
            if msg.get("type") == "signed_out":
                return
        if flush_on and emitted:
            pad = _boundary_pad(pending)
            pending = 0
            if pad:
                yield pad


def _audit(
    request: Request,
    handle: SessionHandle,
    principal: Principal | None,
    component_id: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Report a dispatched event to the app's audit hook (ADR-0034), if it set one."""
    state = request.app.state
    if state.audit is None:
        return
    component = handle.session.find(component_id)
    emit_audit(
        state.audit,
        sid=handle.session.session_id or "",
        user=principal.id if principal else None,
        component=component_id,
        event=event,
        payload=payload,
        include_payload=state.audit_payloads,
        sensitive=bool(component is not None and component.sensitive),
    )


def _publish_result(hub: Hub, result: DispatchResult) -> None:
    """Broadcast a dispatch's patches; secrets go out live but are kept out of the replay."""
    if result.changes:
        hub.publish(patch_message(result.changes))
    if result.transient:
        hub.publish(patch_message(result.transient), record=False)


def _denied(status: int, error: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error}, status_code=status)


async def _open_session(
    request: Request, sid: str | None, app_path: str | None = None
) -> tuple[SessionHandle | None, JSONResponse | None, Principal | None]:
    """The session this request is allowed to use, or the refusal to send (ADR-0033).

    Not secure: today's behaviour (an id-less request shares ``default``), plus the principal,
    when an authenticator is set, so the factory sees ``ctx.user``. Secure: no principal is 401,
    no session id is 401 (nothing falls back to a shared session), and a session owned by
    another principal is 403. Nothing is created for a refused request."""
    state = request.app.state
    store: SessionStore = state.store
    principal: Principal | None = await authenticate(request, state.auth)
    if state.secure:
        if principal is None:
            return None, _denied(401, "unauthenticated"), None
        if not sid:
            return None, _denied(401, "session id required"), None
        # The id the shell sends is a signed token: only the one minted for this principal
        # verifies, so a forged, replayed or other user's id never reaches the store.
        real_sid = state.signer.verify(sid, principal)
        if real_sid is None:
            return None, _denied(403, "forbidden"), None
        sid = real_sid
        existing = store.get(sid)
        if existing is not None and existing.owner != principal.id:
            return None, _denied(403, "forbidden"), None
    if state.drain.draining and store.get(sid or DEFAULT_SESSION_ID) is None:
        return None, _draining(), None  # a drain takes no new sessions (IND-201)
    info = ConnectionInfo.from_request(request, app_path, principal)
    aget = getattr(
        store, "aget_or_create", None
    )  # an async factory (IND-153); a custom store may lack it
    if aget is not None:
        handle = await aget(sid or DEFAULT_SESSION_ID, info)
    else:
        handle = store.get_or_create(sid or DEFAULT_SESSION_ID, info)
    return handle, None, principal


async def _session(request: Request) -> JSONResponse:
    """``POST api/session {resume}``: trade the caller's login for a signed session token.

    Only mounted on a secure app. A ``resume`` token that verifies for this same principal
    comes back unchanged, so a reload keeps its session; anything else gets a fresh one."""
    state = request.app.state
    principal = await authenticate(request, state.auth)
    if principal is None:
        return _denied(401, "unauthenticated")
    body = await _read_capped(request, 4096)
    if body is None:
        return _denied(413, "request too large")
    try:
        raw = json.loads(body) if body else {}
    except ValueError:
        return _denied(400, "invalid json")
    resume = raw.get("resume") if isinstance(raw, dict) else None
    sid = state.signer.verify(resume, principal) if resume else None
    token = state.signer.mint(principal, sid)
    return JSONResponse(
        {"ok": True, "token": token, "user": {"id": principal.id, "name": principal.name}},
        headers={"Cache-Control": "no-store"},
    )


async def _stream(request: Request) -> Response:
    """``GET api/stream``, within the per-address stream cap (ADR-0037, ``Limits``).

    A slot is taken before anything else (so a refused stream creates no session) and given
    back exactly once: on any refusal, when the stream ends, or if building it raises."""
    limiter: StreamLimiter = request.app.state.stream_limiter
    address = peer_address(request.scope)
    if not limiter.acquire(address):
        return _denied(429, "too many streams")
    freed = False

    def release() -> None:
        nonlocal freed
        if not freed:
            freed = True
            limiter.release(address)

    try:
        response = await _open_stream(request, release)
    except BaseException:
        release()
        raise
    if not isinstance(response, StreamingResponse):
        release()
    return response


async def _open_stream(request: Request, release: Callable[[], None]) -> Response:
    app = request.app
    if app.state.drain.draining:
        # A tab whose stream ended during a drain comes back here: refuse before any session is
        # built or resumed, so it retries (``Retry-After``) and lands on another process.
        return _draining()
    # One session per browser tab, keyed by the id the shell sends (?sid=...).
    # An id-less connection shares the default session (ADR-0010), unless the app is secure.
    # The in-app page the tab is on (``&path=``), so a deep link or reload starts there.
    handle, denied, principal = await _open_session(
        request, request.query_params.get("sid"), request.query_params.get("path")
    )
    if handle is None:
        return denied
    hub = handle.hub
    session = handle.session
    queue = hub.subscribe()
    app.state.drain.register(queue)
    epoch, last_event_id = _parse_last_event_id(request)
    ctx = session.ctx
    if last_event_id is None and ctx is not None and request.query_params.get("path"):
        # A fresh page load (the tab keeps its sid across full loads): the URL is the truth
        # about which in-app page it is on. An automatic reconnect carries a Last-Event-Id
        # and a path that was only right when the tab first connected, so it is left alone.
        try:
            ctx._client_navigated(request.query_params["path"])
        except ValueError:
            pass

    # Subscribe first, then decide init-vs-resume against the current offset with
    # no await in between, so nothing published concurrently is missed or applied
    # twice. skip_upto = the offset the client is caught up to after init/replay;
    # queued messages already covered by that are dropped.
    hub.flush()  # held stream appends first, so the snapshot/offset below cover them
    replay = hub.replay_since(last_event_id, epoch)
    if last_event_id is None or replay is None:
        # Fresh connect, or a buffer gap: send a full snapshot (always correct
        # because a StreamText snapshot carries its full accumulated text).
        session.forget_ephemeral()  # a secret shown earlier cannot be in this snapshot
        ctx = getattr(session, "ctx", None)
        init_payload: dict[str, Any] | None = init_message(
            session.snapshot(), chrome=ctx._chrome() if ctx is not None else None
        )
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
                proxy_flush=app.state.proxy_flush,
                id_prefix=f"{hub.epoch}-",
                expires_at=principal.expires_at if app.state.secure and principal else None,
            ):
                yield chunk
        finally:
            hub.unsubscribe(queue)
            app.state.drain.unregister(queue)
            release()

    return StreamingResponse(event_source(), media_type="text/event-stream", headers=_SSE_HEADERS)


async def _read_capped(request: Request, limit: int) -> bytes | None:
    """The request body, or ``None`` once it exceeds ``limit`` bytes (never buffers more)."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _is_json(request: Request) -> bool:
    """True for ``application/json`` (any case, any parameters) and ``+json`` types.

    A browser can send ``text/plain``, form and multipart bodies cross-site without a
    preflight; requiring JSON means a cross-site "simple" request cannot reach the handler."""
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


async def _event(request: Request) -> JSONResponse:
    if not _is_json(request):
        return _denied(415, "content type must be application/json")
    body = await _read_capped(request, request.app.state.max_event_bytes)
    if body is None:
        return JSONResponse({"ok": False, "error": "event too large"}, status_code=413)
    try:
        raw = json.loads(body)
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
    # An event with no session id never falls through to a shared ``default`` session: only
    # an app built on one explicit shared Session (``create_app(session=)``) has one. (A
    # secure app refuses it with 401 in ``_open_session``.)
    if not event.sid and not request.app.state.secure:
        if not isinstance(request.app.state.store, SharedSessionStore):
            return _denied(400, "session id required")
    handle, denied, principal = await _open_session(request, event.sid)
    if handle is None:
        return denied
    hub = handle.hub
    session = handle.session
    # The handler runs as *this request's* principal (re-authenticated just now), so a guard
    # sees a role revoked since the session was built. A spawned task copies this scope.
    with authz_scope(principal, request.app.state.policy):
        result = session.dispatch(event.component, event.event, event.payload)
        if result is not None and not result.forbidden and result.coro is not None:
            # Run the async handler in the background: the POST returns now and the
            # work streams over SSE, so it never holds the request open past the
            # proxy timeout, nor blocks the event loop or other sessions (R3).
            session.spawn(result.coro)
    if result is None:
        return JSONResponse({"ok": False, "error": "unknown event"}, status_code=400)
    if result.forbidden:
        return _denied(403, "forbidden")
    _audit(request, handle, principal, event.component, event.event, event.payload)
    _publish_result(hub, result)
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
            sid = form.get("sid")
            if sid is not None and not isinstance(sid, str):
                return JSONResponse({"ok": False, "error": "bad sid"}, status_code=400)
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

    handle, denied, principal = await _open_session(request, sid)
    if handle is None:
        return denied
    with authz_scope(principal, request.app.state.policy):
        result = handle.session.dispatch(component_id, "upload", {"files": files})
        if result is not None and not result.forbidden and result.coro is not None:
            handle.session.spawn(result.coro)
    if result is None:
        return JSONResponse({"ok": False, "error": "unknown component"}, status_code=400)
    if result.forbidden:
        return _denied(403, "forbidden")
    _audit(
        request, handle, principal, component_id, "upload", {"files": [f.filename for f in files]}
    )

    _publish_result(handle.hub, result)
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
    if request.app.state.secure:
        principal = await authenticate(request, request.app.state.auth)
        if principal is None:
            return _denied(401, "unauthenticated")
        if handle.owner != principal.id:
            return Response(status_code=404)  # not yours: indistinguishable from absent
    found = handle.session.get_file(request.path_params["token"])
    if found is None:
        return Response(status_code=404)
    data, filename, media_type = found
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_last_event_id(request: Request) -> tuple[str | None, int | None]:
    """The SSE resume point as ``(hub epoch, offset)``, from the ``Last-Event-Id``
    header (EventSource sets it natively on reconnect) or a ``?lastEventId=``
    fallback. A bare integer (legacy / tests) has no epoch; invalid -> ``(None, None)``."""
    raw = request.headers.get("last-event-id") or request.query_params.get("lastEventId")
    if raw is None:
        return None, None
    epoch, sep, offset = raw.rpartition("-")
    try:
        return (epoch or None) if sep else None, int(offset)
    except (TypeError, ValueError):
        return None, None


def _sse(message: dict[str, Any], event_id: int | None = None, id_prefix: str = "") -> str:
    prefix = f"id: {id_prefix}{event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(message)}\n\n"


def _read_static(name: str) -> str:
    return files("indah.static").joinpath(name).read_text(encoding="utf-8")

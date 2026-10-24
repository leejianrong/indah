"""A tiny indah app that shows what a gateway did to a request (IND-170, IND-171).

It answers two questions on a real network path:

* **Who does indah think the client is?** The page and ``GET /whoami`` show the socket peer, the
  address indah resolved after ``trusted_proxies``, the scheme and host, and the raw values of the
  forwarding headers a gateway may add (a fixed allowlist of names, never cookies or credentials).
* **Which machine answered?** Every response carries ``X-Probe-Machine``, and the page shows the
  machine that built the session, so a second machine answering a request is visible.

``INDAH_TRUSTED_PROXIES`` (comma-separated IPs or CIDRs, default none; ``PROBE_TRUSTED_PROXIES`` is
an alias) is read at startup, so a
variant is a restart, not a rebuild. Start uvicorn with ``--no-proxy-headers`` so only indah's own
rules are under test. Nothing here is a secret and nothing is stored.

    PROBE_TRUSTED_PROXIES=172.16.0.0/12 uvicorn probe_app:app --no-proxy-headers
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import indah
from indah.proxy import ProxyHeaders, parse_trusted

# Header names worth looking at on this path. Only these are ever echoed.
ECHOED = (
    "fly-client-ip",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-ssl",
    "forwarded",
    "via",
    "cf-connecting-ip",
    "cf-ray",
    "cf-ipcountry",
    "cf-visitor",
    "true-client-ip",
    "fly-forwarded-proto",
    "fly-forwarded-port",
    "fly-forwarded-ssl",
    "fly-request-id",
    "host",
    "user-agent",
)

# INDAH_TRUSTED_PROXIES is the setting indah itself reads (IND-202); PROBE_TRUSTED_PROXIES stays as
# an alias so the deploy scripts keep working. The probe passes the list explicitly because it
# shows it on the page.
_RAW_TRUSTED = os.environ.get("INDAH_TRUSTED_PROXIES") or os.environ.get(
    "PROBE_TRUSTED_PROXIES", ""
)
TRUSTED = [e.strip() for e in _RAW_TRUSTED.split(",") if e.strip()]
try:  # indah 0.9.0 and later: presets such as "fly" expand to explicit entries (IND-204)
    from indah.proxy_presets import expand_trusted

    TRUSTED = list(expand_trusted(TRUSTED).entries)
except ImportError:
    pass
MACHINE = os.environ.get("FLY_MACHINE_ID", "local")
REGION = os.environ.get("FLY_REGION", "")
BOOTED = time.time()
_requests = 0  # every request this process has answered (a per-machine counter)


class RawPeer:
    """Outermost: note the real socket peer and scheme before any proxy rule runs, and stamp
    every response with the machine that produced it. Any client-sent ``x-probe-*`` is dropped."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        _requests += 1
        client = scope.get("client")
        raw = [(k, v) for k, v in scope["headers"] if not k.startswith(b"x-probe-")]
        raw.append((b"x-probe-raw-peer", (client[0] if client else "unknown").encode()))
        raw.append((b"x-probe-raw-scheme", str(scope.get("scheme", "")).encode()))
        scope = dict(scope, headers=raw)

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-probe-machine", MACHINE.encode()),
                    (b"x-probe-region", REGION.encode()),
                ]
            await send(message)

        await self.app(scope, receive, stamped)


def facts(headers: Mapping[str, str], client: str | None, scheme: str, host: str) -> dict[str, Any]:
    """What this request looked like, after the proxy rules that ran before the caller."""
    return {
        "resolved_client": client,
        "resolved_scheme": scheme,
        "resolved_host": host,
        "socket_peer": headers.get("x-probe-raw-peer"),
        "socket_scheme": headers.get("x-probe-raw-scheme"),
        "trusted_proxies": TRUSTED,
        "headers": {name: headers[name] for name in ECHOED if name in headers},
        "machine": MACHINE,
        "region": REGION,
        "requests_answered_by_this_process": _requests,
        "process_age_seconds": round(time.time() - BOOTED),
    }


class WhoAmI:
    """``GET /whoami`` as JSON, behind the same trusted-proxy rules the indah app uses."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        headers = {k.lower(): v for k, v in request.headers.items()}
        client = request.client.host if request.client else None
        body = facts(headers, client, request.url.scheme, headers.get("host", ""))
        await JSONResponse(body, headers={"Cache-Control": "no-store"})(scope, receive, send)


def build_ui() -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        hits = indah.Signal(0)
        answered_by = indah.Signal(MACHINE)
        headers = dict(ctx.conn.headers)
        info = facts(headers, ctx.conn.client, "(not captured)", headers.get("host", ""))
        lines = [
            f"resolved client : {info['resolved_client']}",
            f"socket peer     : {info['socket_peer']}",
            f"host            : {info['resolved_host']}",
            f"prefix          : {ctx.conn.prefix or '(none)'}",
            f"trusted_proxies : {', '.join(TRUSTED) or '(none)'}",
            "",
            *[f"{name:<19} {value}" for name, value in info["headers"].items()],
        ]

        def ping() -> None:
            hits.set(hits.value + 1)
            answered_by.set(MACHINE)  # runs on whichever process received the event

        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("Proxy probe", variant="title"),
                    indah.Text("What the gateway did to the request that opened this page."),
                    indah.Code("\n".join(lines), label="request"),
                    indah.Text(lambda: f"session {ctx.sid}", variant="mono"),
                    indah.Text(
                        lambda: (
                            f"built by machine {MACHINE}, last event handled by "
                            f"{answered_by.value}, {hits.value} event(s)"
                        ),
                        variant="mono",
                    ),
                    indah.Button("Send an event", ping),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="Proxy probe",
        trusted_proxies=TRUSTED,
        spa=True,
    )


def build_app() -> Starlette:
    trusted = parse_trusted(TRUSTED)
    app = Starlette(
        routes=[
            Route("/whoami", endpoint=ProxyHeaders(WhoAmI(), trusted)),
            Mount("/", app=build_ui()),
        ]
    )
    return RawPeer(app)  # type: ignore[return-value]


app = build_app()

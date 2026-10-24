"""A tiny indah app that shows what a gateway did to a request (IND-170, IND-171).

The inspection is indah's own deploy doctor (``indah.doctor``, IND-205). This file only keeps what
the probe needs on top of it, as a deliberately public throwaway:

* ``GET /whoami``: the doctor's request facts as flat JSON, open to anyone (the owner opens it from
  a phone). It shows the address indah resolved after ``trusted_proxies``, the real socket peer, and
  a fixed allowlist of forwarding headers by name; never cookies or credentials.
* ``X-Probe-Machine`` on every response, and a page with a "Send an event" button, so
  ``sticky_check.py`` can see which machine answered a stream and its events.
* The full doctor page at ``/_indah/doctor`` when ``INDAH_DOCTOR_TOKEN`` is set (a Fly secret).

``INDAH_TRUSTED_PROXIES`` (comma-separated IPs or CIDRs, default none; ``PROBE_TRUSTED_PROXIES`` is
an alias) is read at startup, so a variant is a restart, not a rebuild. Start uvicorn with
``--no-proxy-headers`` so only indah's own rules are under test. Nothing here is a secret and
nothing is stored.

    INDAH_TRUSTED_PROXIES=172.16.0.0/12 uvicorn probe_app:app --no-proxy-headers
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import indah
from indah.doctor import Counter, DoctorTap, collect_facts
from indah.proxy import ProxyHeaders, parse_trusted

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
COUNTER = Counter()  # every request this process has answered (a per-machine counter)


class Stamp:
    """Stamp every response with the machine that produced it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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


def whoami(request: Request) -> dict[str, Any]:
    """The doctor's facts for this request, in the flat shape the probe's scripts and notes use."""
    state = SimpleNamespace(
        doctor_counter=COUNTER, trusted_proxies=parse_trusted(TRUSTED), node=MACHINE
    )
    facts = collect_facts(request, state)
    req = facts["request"]
    return {
        "resolved_client": req["resolved_client"],
        "resolved_scheme": req["resolved_scheme"],
        "resolved_host": req["resolved_host"],
        "socket_peer": req["socket_peer"],
        "socket_scheme": req["socket_scheme"],
        "trusted_proxies": TRUSTED,
        "headers": facts["headers"],
        "machine": MACHINE,
        "region": REGION,
        "requests_answered_by_this_process": facts["process"]["requests_answered"],
        "process_age_seconds": facts["process"]["age_seconds"],
    }


class WhoAmI:
    """``GET /whoami`` as JSON, behind the same trusted-proxy rules the indah app uses."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = whoami(Request(scope, receive))
        await JSONResponse(body, headers={"Cache-Control": "no-store"})(scope, receive, send)


def build_ui() -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        hits = indah.Signal(0)
        answered_by = indah.Signal(MACHINE)

        def ping() -> None:
            hits.set(hits.value + 1)
            answered_by.set(MACHINE)  # runs on whichever process received the event

        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("Proxy probe", variant="title"),
                    indah.Text("What the gateway did to the request that opened this page."),
                    indah.Text(
                        f"resolved client {ctx.conn.client}, node {ctx.conn.node}, "
                        f"trusted_proxies {', '.join(TRUSTED) or '(none)'}",
                        variant="mono",
                    ),
                    indah.Text(lambda: f"session {ctx.sid}", variant="mono"),
                    indah.Text(
                        lambda: (
                            f"built by machine {MACHINE}, last event handled by "
                            f"{answered_by.value}, {hits.value} event(s)"
                        ),
                        variant="mono",
                    ),
                    indah.Button("Send an event", ping),
                    indah.Text("Open /whoami for the request facts.", variant="caption"),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="Proxy probe",
        trusted_proxies=TRUSTED,
        node_header=True,
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
    return DoctorTap(Stamp(app), COUNTER)  # type: ignore[return-value]


app = build_app()

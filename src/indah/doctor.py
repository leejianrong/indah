"""The deploy doctor: what a gateway did to this request, and what indah made of it (IND-205).

The probe app of IND-170 and IND-171 showed how useful an echo page is when an app moves behind
Fly, a Cloudflare Worker or a Kubernetes ingress. This is that page, built in and **off by
default**: ``create_app(doctor=...)`` mounts ``GET /_indah/doctor``.

Who may see it (anyone else gets the same plain ``404`` a missing route gives, so the page does not
advertise itself):

- ``doctor="a-long-token"`` (or ``INDAH_DOCTOR_TOKEN``): a request carrying it as
  ``Authorization: Bearer <token>`` or ``?token=<token>``. A query token ends up in access logs and
  browser history, so use a header for scripts and a throwaway token for a browser. Ten wrong tries
  from one address lock that address out for a minute.
- ``doctor=True``: a logged-in principal holding the ``doctor`` permission (``secure=True`` or
  ``auth=``, and usually a :class:`~indah.authz.Policy`). A token app with an ``auth=`` accepts
  either door.

It shows the indah version, the node, the process, the address and scheme indah resolved for this
request next to the real socket peer, the forwarded headers from a fixed allowlist of *names*
(never cookies or credentials), session and stream counts, the drain state, the settings in force
(booleans and names, never a secret) and plain-language warnings. ``?format=json`` returns the same
facts for scripts. The page never contains the token or any secret.
"""

from __future__ import annotations

import asyncio
import hmac
import html
import ipaddress
import json
import os
import platform
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import authenticate
from .authz import can
from .proxy import forwarded_prefix

PATH = "/_indah/doctor"
MIN_TOKEN = 16
PERMISSION = "doctor"

# Header names worth looking at behind a gateway. Only these are ever shown, whatever the request
# carries: never cookies, authorization or anything else.
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

# Seeing one of these while ``trusted_proxies`` is empty means a gateway is in front (IND-200).
_FORWARDING = (
    "x-forwarded-for",
    "forwarded",
    "x-forwarded-proto",
    "fly-client-ip",
    "cf-connecting-ip",
)

# Environment names that say where the process runs. Values are platform identifiers, not secrets.
_ENV_NAMES = ("FLY_APP_NAME", "FLY_REGION", "FLY_MACHINE_ID", "HOSTNAME")

_NOT_FOUND = "Not Found"


class Counter:
    """Requests this process has answered, and when it started."""

    def __init__(self) -> None:
        self.requests = 0
        self.started = time.time()


class DoctorTap:
    """Outermost middleware (only when the doctor is on): count every HTTP request and remember
    the real socket peer and scheme before any trusted-proxy rule rewrites them."""

    def __init__(self, app: ASGIApp, counter: Counter) -> None:
        self.app = app
        self.counter = counter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            self.counter.requests += 1
            client = scope.get("client")
            scope = dict(
                scope,
                indah_raw_peer=client[0] if client else None,
                indah_raw_scheme=scope.get("scheme"),
            )
        await self.app(scope, receive, send)


class Gate:
    """The two doors: a bearer token, and a principal holding ``doctor``."""

    MAX_FAILURES = 10
    WINDOW_SECONDS = 60.0
    MAX_TRACKED = 1024

    def __init__(
        self,
        *,
        token: str | None,
        permission: bool,
        auth: Any = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.token = token
        self.permission = permission
        self.auth = auth
        self._now = now
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def token_ok(self, given: str | None) -> bool:
        if not self.token or not given:
            return False
        return hmac.compare_digest(given.encode("utf-8", "replace"), self.token.encode("utf-8"))

    def blocked(self, address: str) -> bool:
        hits = self._failures.get(address)
        if not hits:
            return False
        cutoff = self._now() - self.WINDOW_SECONDS
        while hits and hits[0] < cutoff:
            hits.popleft()
        if not hits:
            del self._failures[address]
            return False
        return len(hits) >= self.MAX_FAILURES

    def record_failure(self, address: str) -> None:
        hits = self._failures.get(address)
        if hits is None:
            hits = self._failures[address] = deque()
            while len(self._failures) > self.MAX_TRACKED:
                self._failures.popitem(last=False)
        else:
            self._failures.move_to_end(address)
        hits.append(self._now())

    async def allows(self, request: Request) -> bool:
        address = request.client.host if request.client else "unknown"
        if self.blocked(address):
            return False
        if self.token:
            header = request.headers.get("authorization", "")
            bearer = header[7:].strip() if header[:7].lower() == "bearer " else None
            if self.token_ok(bearer) or self.token_ok(request.query_params.get("token")):
                return True
        if self.permission:
            principal = await authenticate(request, self.auth)
            if principal is not None and can(
                principal, PERMISSION, getattr(request.app.state, "policy", None)
            ):
                return True
        # Only a request that offered a token and was wrong counts toward the lockout.
        if self.token and (
            request.query_params.get("token") or request.headers.get("authorization")
        ):
            self.record_failure(address)
        return False


def make_gate(
    arg: Any,
    *,
    auth: Any,
    secure: bool,
    source: str = "doctor=",
    now: Callable[[], float] = time.monotonic,
) -> Gate | None:
    """The gate for ``create_app(doctor=arg)``; ``None`` when the doctor is off."""
    if arg is None or arg is False:
        return None
    if arg is True:
        if not (secure or auth is not None):
            raise ValueError(
                "doctor=True admits a logged-in principal holding the 'doctor' permission, so it "
                "needs secure=True (or auth=). To use a shared token instead pass "
                "doctor='a-long-random-token' or set INDAH_DOCTOR_TOKEN."
            )
        return Gate(token=None, permission=True, auth=auth, now=now)
    if isinstance(arg, str):
        if len(arg) < MIN_TOKEN:
            raise ValueError(
                f"{source}: the doctor token must be at least {MIN_TOKEN} characters "
                f'(try: python -c "import secrets; print(secrets.token_urlsafe(24))")'
            )
        return Gate(token=arg, permission=auth is not None, auth=auth, now=now)
    raise ValueError(f"{source} must be a token string, True, False or None, got {arg!r}")


# --- facts


def _address(text: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((text or "").strip())
    except ValueError:
        return None


def _in(address: str | None, networks: Any) -> bool:
    addr = _address(address)
    return addr is not None and any(addr in net for net in networks or ())


def collect_facts(request: Request, state: Any = None) -> dict[str, Any]:
    """What this request looked like, and how this process is set up. ``state`` is an app's
    ``app.state``; without one only the request facts are given (the probe uses that)."""
    scope = request.scope
    counter: Counter | None = getattr(state, "doctor_counter", None)
    raw_peer = scope.get("indah_raw_peer")
    if raw_peer is None and request.client:
        raw_peer = request.client.host
    headers = {k: request.headers[k] for k in ECHOED if k in request.headers}
    networks = getattr(state, "trusted_proxies", ()) or ()
    resolved = request.client.host if request.client else None
    started = counter.started if counter else None
    store = getattr(state, "store", None)
    drain = getattr(state, "drain", None)
    limits = getattr(state, "limits", None)
    csp = getattr(state, "csp", None)

    facts: dict[str, Any] = {
        "indah_version": _version(),
        "python": platform.python_version(),
        "node": getattr(state, "node", None),
        "environment": {n: os.environ[n] for n in _ENV_NAMES if os.environ.get(n)},
        "process": {
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(
                timespec="seconds"
            )
            if started
            else None,
            "age_seconds": round(time.time() - started) if started else None,
            "requests_answered": counter.requests if counter else None,
        },
        "request": {
            "resolved_client": resolved,
            "resolved_scheme": request.url.scheme,
            "resolved_host": request.headers.get("host", ""),
            "prefix": forwarded_prefix(scope),
            "socket_peer": raw_peer,
            "socket_scheme": scope.get("indah_raw_scheme", scope.get("scheme")),
            "resolved_client_is_trusted": _in(resolved, networks),
            "cookie_sent": "cookie" in request.headers,
        },
        "trusted_proxies": [str(n) for n in networks],
        "trusted_proxies_presets": list(getattr(state, "trusted_proxies_presets", ()) or ()),
        "headers": headers,
        "sessions": {
            "open": _open_sessions(store),
            "open_streams": getattr(drain, "open_streams", None),
            "max_sessions": getattr(store, "max_sessions", None),
        },
        "drain": {
            "draining": bool(getattr(drain, "draining", False)),
            "seconds": getattr(drain, "seconds", None),
        },
        "settings": {
            "secure": bool(getattr(state, "secure", False)),
            "csp": "off" if not csp else ("strict" if csp == "strict" else "custom"),
            "compress": bool(getattr(state, "compress", False)),
            "state_store": type(getattr(state, "state_store", None)).__name__,
            "node_header": bool(getattr(state, "node_header", False)),
            "route_hint": getattr(getattr(state, "route_hint", None), "transport", None) or "off",
            "rate_limit": bool(limits and limits.rate),
            "stream_cap_per_address": getattr(limits, "max_streams_per_ip", None),
            "security_headers": bool(getattr(state, "security_headers", False)),
            "proxy_warning_issued": bool(getattr(state, "proxy_warning_issued", False)),
            "environment_variables_used": list(getattr(state, "env_used", ()) or ()),
        },
    }
    facts["warnings"] = diagnose(facts)
    return facts


def _version() -> str:
    from . import __version__

    return __version__


def _open_sessions(store: Any) -> int | None:
    count = getattr(store, "open_sessions", None)
    return count if isinstance(count, int) else None


def _warn(text: str) -> dict[str, str]:
    return {"level": "warn", "text": text}


def _info(text: str) -> dict[str, str]:
    return {"level": "info", "text": text}


def diagnose(facts: dict[str, Any]) -> list[dict[str, str]]:
    """Plain-language findings about ``facts``: warnings first, then hints."""
    req = facts["request"]
    headers = facts["headers"]
    trusted = facts["trusted_proxies"]
    peer = req.get("socket_peer")
    resolved = req.get("resolved_client")
    seen = [name for name in _FORWARDING if name in headers]
    out: list[dict[str, str]] = []

    if seen and not trusted:
        out.append(
            _warn(
                f"Forwarding headers arrived ({', '.join(seen)}) but trusted_proxies is empty, so "
                f"indah ignores them. Behind a proxy every visitor resolves to {peer} and shares "
                "one rate-limit bucket. Set trusted_proxies to your gateway's addresses."
            )
        )
    elif seen and trusted and resolved == peer and not req.get("resolved_client_is_trusted"):
        out.append(
            _warn(
                f"Forwarding headers arrived ({', '.join(seen)}) but the socket peer {peer} is not "
                "in trusted_proxies, so indah ignored them. Add the gateway's address to "
                "trusted_proxies."
            )
        )
    if req.get("resolved_client_is_trusted") and trusted:
        out.append(
            _warn(
                f"indah resolved the client as {resolved}, an address inside trusted_proxies, so "
                "the real visitor is hidden behind another proxy that is not listed (or every hop "
                "in X-Forwarded-For is trusted)."
            )
        )
    for name in ("cf-connecting-ip", "fly-client-ip"):
        said = headers.get(name)
        if said and trusted and _address(said) and resolved and said != resolved:
            out.append(
                _warn(
                    f"{name} names {said} as the visitor but indah resolved {resolved}. If no "
                    "other proxy sits in front, add the gateway's own addresses to "
                    "trusted_proxies (on Fly: the app's public IPs from `fly ips list`)."
                )
            )
            break
    if facts["drain"]["draining"]:
        out.append(
            _warn(
                "This process is draining: it is refusing new tabs and telling open ones to "
                "reconnect (GET /ready answers 503)."
            )
        )

    answered = facts["process"].get("requests_answered")
    count = (
        f" This process has answered {answered} request(s) so far." if answered is not None else ""
    )
    out.append(
        _info(
            "Several processes? Reload this page a few times. If the node changes between reloads "
            "more than one process answers, and a tab's events must reach the process that holds "
            "its session: see 'Sticky sessions' in the hosting guide." + count
        )
    )
    if not facts["settings"].get("node_header"):
        out.append(
            _info(
                "Turn on create_app(node_header=True) to see which process answered every "
                "response (X-Indah-Node)."
            )
        )
    if not req.get("cookie_sent"):
        out.append(
            _info(
                "This request carried no cookie. Cookie affinity at a gateway only works when the "
                "gateway sets one on the first response; reload and check again."
            )
        )
    out.sort(key=lambda w: w["level"] != "warn")
    return out


# --- the page


def _nothing() -> Response:
    return Response(_NOT_FOUND, status_code=404, media_type="text/plain")


_STYLE = """
:root { color-scheme: light dark; --edge: color-mix(in srgb, CanvasText 22%, Canvas); }
* { box-sizing: border-box; }
body { margin: 0; padding: 20px max(16px, env(safe-area-inset-right, 0px)) 40px
  max(16px, env(safe-area-inset-left, 0px)); background: Canvas; color: CanvasText;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; display: flex; flex-direction: column; gap: 22px; }
h1 { font-size: 1.5rem; margin: 0; } h2 { font-size: 1rem; margin: 0 0 8px; }
p, li { max-width: 70ch; } .muted { opacity: .72; }
code, pre, dd { font-size: .86rem;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
section { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 14px; min-width: 0; }
dl { display: grid; margin: 0; gap: 4px 14px;
  grid-template-columns: minmax(8rem, 14rem) minmax(0, 1fr); }
dt { opacity: .72; } dd { margin: 0; overflow-wrap: anywhere; }
ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
li.warn { border-left: 4px solid #b3261e; padding-left: 8px; list-style: none; margin-left: -18px; }
li.info { opacity: .85; }
pre { margin: 0; overflow-x: auto; padding: 10px; border-radius: 6px;
  border: 1px solid var(--edge); }
button { font: inherit; padding: 4px 10px; border: 1px solid var(--edge); border-radius: 6px;
  background: transparent; color: inherit; cursor: pointer; }
button:focus-visible { outline: 2px solid Highlight; outline-offset: 2px; }
@media (max-width: 560px) { dl { grid-template-columns: minmax(0, 1fr); } dt { margin-top: 6px; } }
"""

_SCRIPT = """
const b = document.getElementById('copy-json');
if (b) {
  b.hidden = false;
  b.addEventListener('click', async () => {
    const text = document.getElementById('facts-json').textContent;
    try { await navigator.clipboard.writeText(text); b.textContent = 'Copied'; }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents(document.getElementById('facts-json'));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r); b.textContent = 'Press Ctrl+C';
    }
  });
}
"""


def _row(label: str, value: Any) -> str:
    shown = "(none)" if value in (None, "", [], {}) else value
    if isinstance(shown, bool):
        shown = "yes" if shown else "no"
    if isinstance(shown, list):
        shown = ", ".join(str(v) for v in shown)
    return f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(shown))}</dd>"


def _dl(rows: list[tuple[str, Any]]) -> str:
    return "<dl>" + "".join(_row(label, value) for label, value in rows) + "</dl>"


def render(facts: dict[str, Any], *, nonce: str) -> str:
    req, proc, sess, drain, st = (
        facts["request"],
        facts["process"],
        facts["sessions"],
        facts["drain"],
        facts["settings"],
    )
    warnings = "".join(
        f'<li class="{w["level"]}"><b>{"Warning" if w["level"] == "warn" else "Hint"}:</b> '
        f"{html.escape(w['text'])}</li>"
        for w in facts["warnings"]
    )
    script_hint = (
        "<p class=\"muted\">For scripts: <code>curl -H 'Authorization: Bearer $INDAH_DOCTOR_TOKEN' "
        "'&lt;this url&gt;?format=json'</code></p>"
    )
    raw = json.dumps({k: v for k, v in facts.items()}, indent=2, sort_keys=False)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Deploy doctor</title>
<style nonce="{nonce}">{_STYLE}</style></head>
<body><main>
<header><h1>Deploy doctor</h1>
<p class="muted">indah {html.escape(facts["indah_version"])} on Python {
        html.escape(facts["python"])
    }.
This page is for whoever runs the app. It shows what the gateway did to <b>this</b>
request.</p></header>
<section><h2>Findings</h2><ul>{warnings}</ul></section>
<section><h2>This request</h2>{
        _dl(
            [
                ("Resolved client", req["resolved_client"]),
                ("Socket peer", req["socket_peer"]),
                ("Resolved scheme", req["resolved_scheme"]),
                ("Socket scheme", req["socket_scheme"]),
                ("Resolved host", req["resolved_host"]),
                ("Forwarded prefix", req["prefix"]),
                ("Cookie sent", req["cookie_sent"]),
            ]
        )
    }</section>
<section><h2>Forwarded headers (an allowlist of names)</h2>{
        _dl(sorted(facts["headers"].items())) if facts["headers"] else "<p class='muted'>None.</p>"
    }</section>
<section><h2>trusted_proxies</h2>{
        _dl([("Presets", facts["trusted_proxies_presets"]), ("Networks", facts["trusted_proxies"])])
    }</section>
<section><h2>Process</h2>{
        _dl(
            [
                ("Node", facts["node"]),
                ("Started", proc["started_at"]),
                ("Age (seconds)", proc["age_seconds"]),
                ("Requests answered", proc["requests_answered"]),
                *sorted(facts["environment"].items()),
            ]
        )
    }</section>
<section><h2>Sessions and drain</h2>{
        _dl(
            [
                ("Open sessions", sess["open"]),
                ("Open streams", sess["open_streams"]),
                ("Session limit", sess["max_sessions"]),
                ("Drain", "draining" if drain["draining"] else "not draining"),
                ("Drain seconds", drain["seconds"]),
            ]
        )
    }</section>
<section><h2>Settings in force</h2>{
        _dl(
            [
                ("secure", st["secure"]),
                ("csp", st["csp"]),
                ("state store", f"{st['state_store']}: {st['state_store_health']}")
                if "state_store_health" in st
                else ("state store", st["state_store"]),
                ("compress", st["compress"]),
                ("node_header", st["node_header"]),
                ("route hint", st["route_hint"]),
                ("rate limit", st["rate_limit"]),
                ("streams per address", st["stream_cap_per_address"]),
                ("security headers", st["security_headers"]),
                ("proxy warning logged", st["proxy_warning_issued"]),
                ("INDAH_* variables used", st["environment_variables_used"]),
            ]
        )
    }</section>
<section><h2>As JSON</h2>
<p><button id="copy-json" type="button" hidden>Copy as JSON</button></p>
<pre id="facts-json">{html.escape(raw)}</pre>
{script_hint}
</section>
<script nonce="{nonce}">{_SCRIPT}</script>
</main></body></html>"""


async def _add_store_health(facts: dict[str, Any], store: Any) -> None:
    """A store that can be down (Redis) says whether it answers: ``ok`` or ``unreachable``."""
    check = getattr(store, "health", None)
    if not callable(check):
        return
    try:
        up = await asyncio.wait_for(check(), 3.0)
    except Exception:
        up = False
    facts["settings"]["state_store_health"] = "ok" if up else "unreachable"
    if not up:
        facts["warnings"].insert(
            0,
            _warn(
                "The state store does not answer. ctx.persist starts from defaults and drops "
                "writes until it does. Check INDAH_STATE_STORE, the network path and the "
                "credentials."
            ),
        )


async def handler(request: Request) -> Response:
    """``GET /_indah/doctor``: gated; ``404`` for everyone else."""
    state = request.app.state
    gate: Gate | None = getattr(state, "doctor", None)
    if gate is None or not await gate.allows(request):
        return _nothing()
    facts = collect_facts(request, state)
    await _add_store_health(facts, getattr(state, "state_store", None))
    headers = {
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if request.query_params.get("format") == "json":
        return JSONResponse(facts, headers=headers)
    nonce = secrets.token_urlsafe(16)
    headers["Content-Security-Policy"] = (
        f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    page = render(facts, nonce=nonce)
    return Response(page, media_type="text/html", headers=headers)

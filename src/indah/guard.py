"""Cross-origin request guard for secure apps (ADR-0033, IND-115).

A multipart upload is a "simple" cross-site request: a page on another site can make the
victim's browser POST it with the victim's cookies and no CORS preflight. The signed session
token already stops that from reaching a session (an attacker page does not have it), but
the guard refuses the request before anything is parsed or created, and also covers the
stream and the file download.

The rule, for every state-changing request plus ``api/stream`` and ``api/file``:

1. ``Sec-Fetch-Site`` (set by the browser, not forgeable from page script):
   ``same-origin`` or ``none`` passes; ``same-site`` or ``cross-site`` passes only when the
   ``Origin`` is in ``allowed_origins``.
2. Without it (an older browser, or a non-browser client), an ``Origin`` header must equal this
   server's own origin or be in ``allowed_origins``. No ``Origin`` at all passes: a browser
   always sends one on a cross-site POST, so only a non-browser client omits it.

Behind a proxy that rewrites ``Host`` (a Worker, some gateways) the own-origin comparison can
fail; browsers still send ``Sec-Fetch-Site: same-origin``, and ``allowed_origins`` covers the
rest.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

_ORIGIN = re.compile(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?")
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
_GUARDED_GETS = ("/api/stream", "/api/file/")


def normalize_origins(origins: Iterable[str] | None) -> frozenset[str]:
    """Validate and normalise ``allowed_origins`` (``scheme://host[:port]``, no path)."""
    out = set()
    for raw in origins or ():
        origin = str(raw).strip().rstrip("/").lower()
        if not _ORIGIN.fullmatch(origin):
            raise ValueError(f"allowed_origins entry {raw!r} must look like https://host[:port]")
        out.add(origin)
    return frozenset(out)


def origin_allowed(
    *,
    sec_fetch_site: str | None,
    origin: str | None,
    own_origin: str,
    allowed: frozenset[str] = frozenset(),
) -> bool:
    """Whether a request with these headers may proceed (see the module docstring)."""
    origin = origin.strip().rstrip("/").lower() if origin else None
    if sec_fetch_site:
        site = sec_fetch_site.strip().lower()
        if site in ("same-origin", "none"):
            return True
        return origin is not None and origin in allowed
    if origin is None:
        return True
    return origin == own_origin.lower() or origin in allowed


class OriginGuard:
    """ASGI middleware that applies :func:`origin_allowed` to the guarded requests."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str] | None = None) -> None:
        self.app = app
        self.allowed = normalize_origins(allowed_origins)

    def _guarded(self, scope: Scope) -> bool:
        if scope["method"] not in _SAFE_METHODS:
            return True
        path = scope.get("path", "")
        return any(marker in path for marker in _GUARDED_GETS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._guarded(scope):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        own = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
        if origin_allowed(
            sec_fetch_site=headers.get("sec-fetch-site"),
            origin=headers.get("origin"),
            own_origin=own,
            allowed=self.allowed,
        ):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"ok": False, "error": "cross-origin request refused"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

"""Hardening for apps on the public internet (ADR-0037).

Everything here is opt-in and unset means "as before": ``create_app(limits=Limits())`` changes
nothing. ``Limits.public()`` is a sensible starting point for a hosted app::

    create_app(
        session_factory=build,
        limits=Limits.public(),
        security_headers=True,
        trusted_proxies=["10.0.0.0/8"],   # so the address below is the real client's
    )

The middleware are plain ASGI (not ``BaseHTTPMiddleware``, which can misbehave on the
long-lived SSE response). The client address is the socket peer as ``ProxyHeaders`` resolved it
(``X-Forwarded-For`` only from a trusted proxy, ADR-0034); nothing here reads a forwarded header.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_SECURITY_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}
LIMITED_SUFFIXES = ("/api/event", "/api/upload", "/api/stream")


@dataclass(frozen=True)
class Rate:
    """A token bucket: ``burst`` requests at once, refilled at ``per_second``."""

    per_second: float
    burst: int


@dataclass(frozen=True)
class Limits:
    """Optional bounds for a public app. ``None`` (the default) leaves that bound as it was.

    ``rate`` maps a route suffix (``"/api/event"``) to its per-address :class:`Rate`.
    ``max_event_bytes`` and ``max_upload_mb`` override ``create_app``'s arguments of the same
    name. ``max_streams_per_ip`` caps open SSE streams per address. ``max_sessions`` and
    ``session_idle_seconds`` bound an in-memory session store (least recently used goes first)."""

    rate: Mapping[str, Rate] | None = None
    max_event_bytes: int | None = None
    max_upload_mb: float | None = None
    max_streams_per_ip: int | None = None
    max_sessions: int | None = None
    session_idle_seconds: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_event_bytes", "max_upload_mb", "max_streams_per_ip", "max_sessions"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"Limits.{name} must be positive, got {value!r}")
        if self.session_idle_seconds is not None and self.session_idle_seconds <= 0:
            raise ValueError("Limits.session_idle_seconds must be positive")
        for suffix, rate in (self.rate or {}).items():
            if not suffix.startswith("/"):
                raise ValueError(f"Limits.rate keys look like '/api/event', got {suffix!r}")
            if rate.per_second <= 0 or rate.burst < 1:
                raise ValueError(f"Limits.rate[{suffix!r}] needs per_second > 0 and burst >= 1")

    @classmethod
    def public(cls) -> Limits:
        """The public gallery's setting (ADR-0024): a modest per-address rate on the three
        routes, 200 sessions, 30 minutes idle."""
        rate = Rate(per_second=2.0, burst=30)
        return cls(
            rate={suffix: rate for suffix in LIMITED_SUFFIXES},
            max_sessions=200,
            session_idle_seconds=30 * 60,
        )


class SecurityHeadersMiddleware:
    """Add baseline security headers to every response. ``headers`` replaces the defaults
    (``DEFAULT_SECURITY_HEADERS``) per name; a value of ``""`` drops that header."""

    def __init__(self, app: ASGIApp, headers: Mapping[str, str] | None = None) -> None:
        self.app = app
        merged = dict(DEFAULT_SECURITY_HEADERS)
        for name, value in (headers or {}).items():
            canonical = next((k for k in merged if k.lower() == name.lower()), name)
            merged[canonical] = value
        self._headers = [
            (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in merged.items() if v
        ]
        self._names = {k for k, _ in self._headers}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                kept = [h for h in message.get("headers", []) if h[0].lower() not in self._names]
                message["headers"] = kept + self._headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def peer_address(scope: Scope) -> str:
    """The socket peer (after ``ProxyHeaders``), or ``"unknown"``."""
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Per-address, per-route token buckets (ADR-0024, ADR-0037).

    ``rates`` maps a route suffix to a :class:`Rate`; a request whose path ends with one is
    counted against that bucket, anything else is untouched. Over the limit is ``429`` with
    ``Retry-After``. ``client_ip`` may name the address from the scope (a platform header you
    trust, such as Fly's); the default is the socket peer. One process, one dict, no lock."""

    def __init__(
        self,
        app: ASGIApp,
        rates: Mapping[str, Rate],
        *,
        client_ip: Callable[[Scope], str] = peer_address,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = 10_000,
        prune_every: int = 256,
    ) -> None:
        self.app = app
        self.rates = dict(rates)
        self._client_ip = client_ip
        self._clock = clock
        self._max_buckets = max_buckets
        self._prune_every = prune_every
        self._calls = 0
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}  # -> (tokens, last)

    def _rate_for(self, path: str) -> tuple[str, Rate] | None:
        for suffix, rate in self.rates.items():
            if path.endswith(suffix):
                return suffix, rate
        return None

    def _take(self, key: tuple[str, str], rate: Rate) -> float:
        """Take a token; ``0`` if allowed, else the seconds until one is available."""
        now = self._clock()
        tokens, last = self._buckets.get(key, (float(rate.burst), now))
        tokens = min(float(rate.burst), tokens + (now - last) * rate.per_second)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / rate.per_second
        self._buckets[key] = (tokens - 1, now)
        return 0.0

    def _prune(self) -> None:
        now = self._clock()
        for key, (tokens, last) in list(self._buckets.items()):
            rate = self.rates[key[0]]
            if tokens + (now - last) * rate.per_second >= rate.burst:
                del self._buckets[key]  # full again: indistinguishable from a fresh bucket

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        found = self._rate_for(scope["path"]) if scope["type"] == "http" else None
        if found is None:
            await self.app(scope, receive, send)
            return
        suffix, rate = found
        self._calls += 1
        if self._calls % self._prune_every == 0 and len(self._buckets) > self._max_buckets:
            self._prune()
        wait = self._take((suffix, self._client_ip(scope)), rate)
        if wait:
            response = PlainTextResponse(
                "Too many requests.",
                status_code=429,
                headers={"Retry-After": str(max(1, int(wait + 0.999)))},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class StreamLimiter:
    """Count open SSE streams per address; ``acquire`` is ``False`` at the cap.

    A token bucket cannot bound a stream (a held-open connection costs nothing per second), so
    this is a plain count. ``cap=None`` never refuses."""

    def __init__(self, cap: int | None) -> None:
        self.cap = cap
        self._open: dict[str, int] = {}

    def count(self, address: str) -> int:
        return self._open.get(address, 0)

    def acquire(self, address: str) -> bool:
        if self.cap is not None and self.count(address) >= self.cap:
            return False
        self._open[address] = self.count(address) + 1
        return True

    def release(self, address: str) -> None:
        left = self.count(address) - 1
        if left > 0:
            self._open[address] = left
        else:
            self._open.pop(address, None)

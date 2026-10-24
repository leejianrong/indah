"""Trusted-proxy handling: believe ``X-Forwarded-*`` only from peers you named (ADR-0034).

Behind a gateway the socket peer is the gateway, so the real client address, the scheme and
the public path prefix arrive in headers. Anyone can send those headers, so they are believed
only when the *peer* is in ``create_app(trusted_proxies=[...])``; by default nothing is. From a
trusted peer indah reads:

- ``X-Forwarded-For``: the client is the rightmost address that is not itself a trusted proxy,
  so addresses a client prepended are never believed;
- ``X-Forwarded-Proto`` (``http``/``https``) and ``X-Forwarded-Host``: so the origin guard
  compares against the public origin, not the internal one;
- ``X-Forwarded-Prefix``: the public path prefix, for apps that build absolute links
  (``ctx.conn.prefix``). The routing path is never touched.

It is a small subset of uvicorn's ``--proxy-headers``; use that too if you also want access
logs to show the real client.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from collections.abc import Iterable
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

logger = logging.getLogger("indah")

# Headers a gateway adds. Seeing one while ``trusted_proxies`` is empty usually means the app is
# behind a proxy and every visitor will resolve to the proxy's address (IND-200).
_FORWARDING_HEADERS = (
    b"x-forwarded-for",
    b"forwarded",
    b"x-forwarded-proto",
    b"fly-client-ip",
    b"cf-connecting-ip",
)


class ProxyNotice:
    """Whether to warn, once per app, that forwarded headers arrived with no ``trusted_proxies``.

    ``enabled`` can be turned off (``create_app(warn_untrusted_forwarding=False)``, or
    ``launch()`` in a notebook, where the host's proxy is expected). ``issued`` is set after the
    warning is logged and mirrored to ``app.state.proxy_warning_issued`` once ``state`` is set.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.issued = False
        self.state: Any = None

    def check(self, scope: Scope) -> None:
        """Log the warning the first time a forwarding header is seen; a boolean test after that."""
        if self.issued or not self.enabled:
            return
        seen = sorted(
            {k.decode("latin-1") for k, _ in scope.get("headers", ()) if k in _FORWARDING_HEADERS}
        )
        if not seen:
            return
        self.issued = True
        if self.state is not None:
            self.state.proxy_warning_issued = True
        peer = (scope.get("client") or ("unknown", 0))[0]
        if os.environ.get("FLY_APP_NAME"):
            hint = (
                "On Fly set trusted_proxies=[\"fly\"] (it trusts Fly's proxy range and this app's "
                "public IPs, looked up at startup; `fly ips list` shows them)."
            )
        else:
            hint = (
                'Name your gateway with a preset (trusted_proxies=["cloudflare"], ["k8s"], '
                '["private"], ["fly"]) or its IPs or CIDRs.'
            )
        logger.warning(
            "Forwarded header(s) %s arrived from %s but trusted_proxies is empty, so indah ignores "
            "them: behind a proxy every visitor resolves to the proxy's address and shares one "
            "rate-limit bucket. %s See 'Behind a proxy' in the hosting guide, or pass "
            "warn_untrusted_forwarding=False if no proxy is in front. This is logged once.",
            ", ".join(seen),
            peer,
            hint,
        )


_SEGMENT = re.compile(r"[A-Za-z0-9._~\-]+")
_HOST = re.compile(r"[A-Za-z0-9.\-]+(:\d{1,5})?|\[[0-9A-Fa-f:]+\](:\d{1,5})?")
_MAX_PREFIX = 200


def parse_trusted(entries: Iterable[str] | None) -> tuple[Network, ...]:
    """Parse ``trusted_proxies`` (IPs or CIDRs). Refuses ``*`` and any network that would
    trust the whole internet: a wildcard would make every forwarded header believable."""
    out: list[Network] = []
    for raw in entries or ():
        try:
            net = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError:
            raise ValueError(
                f"trusted_proxies entry {raw!r} is not an IP address or CIDR"
            ) from None
        if net.prefixlen == 0:
            raise ValueError(f"trusted_proxies entry {raw!r} would trust every address")
        out.append(net)
    return tuple(out)


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def is_trusted(host: str | None, trusted: tuple[Network, ...]) -> bool:
    addr = _ip(host) if host else None
    return addr is not None and any(addr in net for net in trusted)


def client_from_forwarded(xff: str | None, trusted: tuple[Network, ...]) -> str | None:
    """The rightmost ``X-Forwarded-For`` hop that is not a trusted proxy, or ``None`` when
    the header is empty, all trusted, or has an unparseable hop before one is found."""
    if not xff:
        return None
    for hop in reversed(xff.split(",")):
        addr = _ip(hop)
        if addr is None:
            return None
        if not any(addr in net for net in trusted):
            return str(addr)
    return None


def safe_prefix(raw: str | None) -> str:
    """A forwarded prefix as ``/a/b`` (no trailing slash), or ``""`` when it is not a plain
    absolute path. Never repaired: a prefix that needs fixing is a prefix not to trust."""
    if not raw or len(raw) > _MAX_PREFIX:
        return ""
    if raw == "/":
        return ""
    segments = raw.rstrip("/").split("/")
    if segments[0] != "" or len(segments) < 2:
        return ""
    if not all(_SEGMENT.fullmatch(seg) and seg not in (".", "..") for seg in segments[1:]):
        return ""
    return "/".join(segments)


class ProxyHeaders:
    """ASGI middleware applying the trusted-proxy rules above to each HTTP request."""

    def __init__(
        self, app: ASGIApp, trusted: tuple[Network, ...], notice: ProxyNotice | None = None
    ) -> None:
        self.app = app
        self.trusted = trusted
        self.notice = notice

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self.trusted and self.notice is not None:
            self.notice.check(scope)
        if scope["type"] == "http" and self.trusted:
            peer = (scope.get("client") or (None, 0))[0]
            if is_trusted(peer, self.trusted):
                scope = self._believe(scope)
        await self.app(scope, receive, send)

    def _believe(self, scope: Scope) -> Scope:
        headers: dict[str, str] = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
        }
        scope = dict(scope)  # never mutate the server's scope in place
        client = client_from_forwarded(headers.get("x-forwarded-for"), self.trusted)
        if client:
            scope["client"] = (client, 0)
        proto = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if proto in ("http", "https"):
            scope["scheme"] = proto
        host = headers.get("x-forwarded-host", "").split(",")[0].strip()
        if host and _HOST.fullmatch(host):
            raw: list[tuple[bytes, bytes]] = [(k, v) for k, v in scope["headers"] if k != b"host"]
            raw.append((b"host", host.encode("latin-1")))
            scope["headers"] = raw
        prefix = safe_prefix(headers.get("x-forwarded-prefix"))
        if prefix:
            scope["indah_prefix"] = prefix
        return scope


def forwarded_prefix(scope: dict[str, Any]) -> str:
    """The believed public prefix for this request (``""`` unless a trusted proxy set it)."""
    return str(scope.get("indah_prefix", ""))

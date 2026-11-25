"""Peer forwarding for Kubernetes without cookie affinity (ADR-0043 Tier C, IND-209).

When an ingress cannot pin a tab to one pod (a Cloudflare Tunnel pointing at a ClusterIP
Service, for example), an event can reach a pod that does not hold the tab's session. The owner
is where the tab's **stream** is open, and the tab already knows it: the owner puts a signed
*hint* in ``init`` (``route: {hint, node, transport: "peers"}``) and indah's shell sends it back
on every event as ``X-Indah-Route``. The receiving pod forwards the request to the owner with
one HTTP call to ``POST /_indah/forward``; the owner runs the normal event path and publishes to
its own stream. Nothing about a session moves, and no registry or bus is needed.

It is off unless ``INDAH_CLUSTER_SECRET`` and ``INDAH_PEERS`` (or the ``create_app`` arguments) are
set. The secret is never derived from ``secret=`` (ADR-0043, Q5), so it does one job.

Two signatures, both HMAC-SHA256 with the cluster secret and a domain-separated message:

- the **hint** ``base64url("address|port|issued_at").base64url(mac)``. The address is a capability
  (it says where to connect), so it must be unforgeable (no SSRF): it has to be a private or
  link-local address, the port has to be this app's own, and it has to be less than a day old.
  A hint that fails any of these is ignored, which means the event is tried locally and becomes
  the usual ``409 unknown_session`` if this pod does not hold the session. It never causes an
  outgoing connection.
- the **forward**: a MAC over the timestamp, a fresh nonce (so two identical clicks in one second
  are two forwards, not a replay), the sender, the kind, the content type, the body hash
  and the principal blob. The owner accepts it within 30 seconds of the timestamp and only once
  (a small cache of recent signatures), and the principal it carries is the receiver's fresh
  authentication, so a role revoked a second ago still fails at the owner.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .auth import Principal

logger = logging.getLogger("indah")

HINT_MAX_AGE = 24 * 3600.0
FORWARD_WINDOW = 30.0
FORWARD_PATH = "/_indah/forward"
DEFAULT_PORT = 8000
DEFAULT_TIMEOUT = 2.0
MAX_REPLY = 1_000_000  # a reply is a few bytes of JSON; refuse anything larger
_HINT_TAG = b"indah-route-v1\n"
_FORWARD_TAG = b"indah-forward-v1\n"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(key: bytes, tag: bytes, message: bytes) -> bytes:
    return hmac.new(key, tag + message, hashlib.sha256).digest()


def is_peer_address(address: str) -> bool:
    """True for a private or link-local IP literal: where a pod can be, never the internet."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.is_unspecified or ip.is_multicast:
        return False
    return bool(ip.is_private or ip.is_link_local)


def sign_hint(key: bytes, address: str, port: int, issued_at: float) -> str:
    payload = f"{address}|{port}|{int(issued_at)}".encode()
    return f"{_b64e(payload)}.{_b64e(_mac(key, _HINT_TAG, payload))}"


def verify_hint(
    key: bytes, hint: str, *, own_port: int, now: float | None = None
) -> tuple[str, int] | None:
    """The ``(address, port)`` a good hint names, or ``None`` for any bad one (see the module)."""
    try:
        body, mac = hint.split(".", 1)
        payload = _b64d(body)
        sent = _b64d(mac)
        address, port_text, issued_text = payload.decode("ascii").split("|")
        port, issued = int(port_text), int(issued_text)
    except (ValueError, UnicodeDecodeError, TypeError):
        return None
    if not hmac.compare_digest(sent, _mac(key, _HINT_TAG, payload)):
        return None
    age = (time.time() if now is None else now) - issued
    if age > HINT_MAX_AGE or age < -FORWARD_WINDOW:
        return None
    if port != own_port or not is_peer_address(address):
        return None
    return address, port


def principal_blob(principal: Principal | None) -> str:
    """The caller as a signed-over string: ``""`` for nobody."""
    if principal is None:
        return ""
    data = {
        "id": principal.id,
        "name": principal.name,
        "email": principal.email,
        "roles": sorted(principal.roles),
        "workspace": principal.workspace,
        "claims": dict(principal.claims),
        "expires_at": principal.expires_at,
    }
    return _b64e(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode())


def principal_from_blob(blob: str) -> Principal | None:
    if not blob:
        return None
    data = json.loads(_b64d(blob))
    return Principal(
        id=data["id"],
        name=data.get("name") or "",
        email=data.get("email") or "",
        roles=frozenset(data.get("roles") or ()),
        workspace=data.get("workspace"),
        claims=data.get("claims") or {},
        expires_at=data.get("expires_at"),
    )


def forward_signature(
    key: bytes,
    *,
    timestamp: str,
    nonce: str,
    sender: str,
    kind: str,
    content_type: str,
    body: bytes,
    blob: str,
) -> str:
    message = "\n".join(
        [timestamp, nonce, sender, kind, content_type, hashlib.sha256(body).hexdigest(), blob]
    ).encode()
    return _mac(key, _FORWARD_TAG, message).hex()


class ReplayCache:
    """Signatures seen in the last ``window`` seconds, so a captured forward works once."""

    def __init__(self, window: float = FORWARD_WINDOW * 2, limit: int = 10_000) -> None:
        self.window = window
        self.limit = limit
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen(self, signature: str, now: float | None = None) -> bool:
        """True if it was already used; otherwise remember it and return False."""
        t = time.monotonic() if now is None else now
        while self._seen and (
            len(self._seen) >= self.limit or next(iter(self._seen.values())) < t - self.window
        ):
            self._seen.popitem(last=False)
        if signature in self._seen:
            return True
        self._seen[signature] = t
        return False


class Forwarder(Protocol):
    """Sends one request to a peer and returns ``(status, body)``; raises when it cannot."""

    async def forward(
        self, address: str, port: int, path: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]: ...


class HttpForwarder:
    """One HTTP/1.1 ``POST`` over a plain socket, ``Connection: close``, no redirects, no retry.

    Standard library only (indah's base install has no HTTP client). The whole call, connect to last
    byte, is bounded by ``timeout`` seconds."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not timeout > 0:
            raise ValueError("the forward timeout must be more than 0 seconds")
        self.timeout = timeout

    async def forward(
        self, address: str, port: int, path: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        return await asyncio.wait_for(self._post(address, port, path, headers, body), self.timeout)

    async def _post(
        self, address: str, port: int, path: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        host = f"[{address}]" if ":" in address else address
        lines = [f"POST {path} HTTP/1.1", f"Host: {host}:{port}", "Connection: close"]
        lines.append(f"Content-Length: {len(body)}")
        for name, value in headers.items():
            if "\r" in value or "\n" in value or "\r" in name or "\n" in name:
                raise ValueError("a header may not hold a line break")
            lines.append(f"{name}: {value}")
        reader, writer = await asyncio.open_connection(address, port)
        try:
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)
            await writer.drain()
            raw = b""
            while chunk := await reader.read(65536):  # read() is "what has arrived", not "to EOF"
                raw += chunk
                if len(raw) > MAX_REPLY:
                    raise ValueError("the peer's reply is too large")
        finally:
            writer.close()
        head, _, rest = raw.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        parts = status_line.split()
        if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
            raise ValueError("the peer did not answer with HTTP")
        reply = {
            k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in header_lines)
        }
        if reply.get("transfer-encoding", "").lower() == "chunked":
            rest = _dechunk(rest)
        return int(parts[1]), rest


def _dechunk(data: bytes) -> bytes:
    out, rest = b"", data
    while rest:
        size_line, _, rest = rest.partition(b"\r\n")
        size = int(size_line.split(b";")[0] or b"0", 16)
        if size == 0:
            break
        out, rest = out + rest[:size], rest[size + 2 :]
    return out


def private_address() -> str | None:
    """This pod's own private address: the one the kernel would use to reach a private network."""
    for probe in ("10.255.255.255", "172.31.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                found = s.getsockname()[0]
        except OSError:
            continue
        if is_peer_address(found):
            return found
    return None


@dataclass
class PeerConfig:
    """``create_app(peers=PeerConfig(...))``; a ``None`` falls back to its variable, then a default.

    ``peers`` is a DNS name that resolves to the replicas (a headless Service), used for the doctor
    page's count, or ``"self"``. ``address`` is this pod's address as the others reach it
    (``INDAH_ADVERTISE_ADDRESS``, in Kubernetes the downward API's ``status.podIP``), ``port`` the
    app's port (``INDAH_PEER_PORT``, default 8000) and ``timeout`` the forward call's limit in
    seconds (``INDAH_FORWARD_TIMEOUT``, default 2). ``forwarder`` replaces the HTTP call (tests)."""

    peers: str | None = None
    address: str | None = None
    port: int | None = None
    timeout: float | None = None
    forwarder: Forwarder | None = None


@dataclass
class PeerForwarding:
    """The live settings of a process that forwards, held on ``app.state.peers``."""

    key: bytes
    address: str
    port: int
    peers: str
    forwarder: Forwarder
    timeout: float
    replay: ReplayCache = field(default_factory=ReplayCache)
    stats: dict[str, int] = field(
        default_factory=lambda: {"forwarded": 0, "ok": 0, "failed": 0, "refused": 0, "received": 0}
    )
    _count: tuple[float, int | None] = (0.0, None)

    def hint(self) -> str:
        return sign_hint(self.key, self.address, self.port, time.time())

    def target(self, hint: str) -> tuple[str, int] | None:
        """Where to forward for this hint, or ``None`` to handle it here (bad, ours, or absent)."""
        found = verify_hint(self.key, hint, own_port=self.port)
        if found is None or found == (self.address, self.port):
            return None
        return found

    async def peer_count(self) -> int | None:
        """How many addresses ``peers`` resolves to (cached 30 s), for the doctor page."""
        when, count = self._count
        if time.monotonic() - when < 30 and count is not None:
            return count
        if self.peers == "self":
            count = 1
        else:
            try:
                found = await asyncio.get_running_loop().getaddrinfo(
                    self.peers, None, type=socket.SOCK_STREAM
                )
                count = len({item[4][0] for item in found})
            except OSError:
                count = None
        self._count = (time.monotonic(), count)
        return count


def resolve_peers(
    arg: PeerConfig | str | None,
    cluster_secret: str | None,
    environ: Mapping[str, str] | None = None,
) -> PeerForwarding | None:
    """The forwarding settings, or ``None`` when it is off (no peers, or no cluster secret)."""
    env = os.environ if environ is None else environ
    config = PeerConfig(peers=arg) if isinstance(arg, str) else (arg or PeerConfig())
    peers = config.peers if config.peers is not None else (env.get("INDAH_PEERS") or "").strip()
    if not peers:
        return None
    secret = (env.get("INDAH_CLUSTER_SECRET") or "") if cluster_secret is None else cluster_secret
    if not secret.strip():
        logger.warning(
            "INDAH_PEERS is set but there is no INDAH_CLUSTER_SECRET, so forwarding is off"
        )
        return None
    address = config.address or (env.get("INDAH_ADVERTISE_ADDRESS") or "").strip()
    address = address or private_address() or ""
    if not is_peer_address(address):
        raise ValueError(
            "peer forwarding needs this pod's private address: set INDAH_ADVERTISE_ADDRESS "
            f"(the pod IP), got {address!r}"
        )
    port = config.port
    if port is None:
        text = (env.get("INDAH_PEER_PORT") or "").strip()
        try:
            port = int(text) if text else DEFAULT_PORT
        except ValueError:
            raise ValueError(f"INDAH_PEER_PORT must be a port number, got {text!r}") from None
    if not 0 < port < 65536:
        raise ValueError(f"the peer port must be between 1 and 65535, got {port}")
    timeout = config.timeout
    if timeout is None:
        text = (env.get("INDAH_FORWARD_TIMEOUT") or "").strip()
        try:
            timeout = float(text) if text else DEFAULT_TIMEOUT
        except ValueError:
            raise ValueError(f"INDAH_FORWARD_TIMEOUT must be seconds, got {text!r}") from None
    if not timeout > 0:
        raise ValueError("the forward timeout must be more than 0 seconds")
    return PeerForwarding(
        key=secret.encode(),
        address=address,
        port=port,
        peers=peers,
        forwarder=config.forwarder or HttpForwarder(timeout),
        timeout=timeout,
    )

"""Identity for hosted apps: who is this request, and who owns this session (ADR-0033).

indah does not log anyone in. A parent app (semula's core, an auth library, a reverse proxy)
does that, and tells indah who the caller is through an :data:`Authenticator`: a function from
the request to a :class:`Principal`, or ``None`` for "nobody"::

    def who(request) -> Principal | None:
        user = my_session_lookup(request.cookies.get("session"))
        return Principal(id=user.id, name=user.name, roles=frozenset(user.roles)) if user else None

    create_app(session_factory=build, auth=who, secure=True)

Each session is then built for one principal (``ctx.user`` in the factory) and owned by it.
``secure=True`` makes that a rule: a request with no principal is refused (401), and a request
for another principal's session is refused (403). Everything here fails closed: an
authenticator that raises, or returns something that is not a ``Principal``, is "nobody".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection, Request

logger = logging.getLogger("indah")


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Only ``id`` is required, and it is what owns sessions.

    ``roles`` and ``workspace`` feed authorization (a later slice). ``claims`` holds anything
    else the app wants from the identity provider. ``expires_at`` (epoch seconds) is when the
    login ends; a principal past it counts as nobody."""

    id: str
    name: str = ""
    email: str = ""
    roles: frozenset[str] = frozenset()
    workspace: str | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)
    expires_at: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Principal.id must be a non-empty string")
        object.__setattr__(self, "roles", frozenset(self.roles))

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at


Authenticator = Callable[["Request"], "Principal | None | Awaitable[Principal | None]"]


def default_authenticator(request: Request) -> Principal | None:
    """Read Starlette's ``scope["user"]`` (set by ``AuthenticationMiddleware`` in a parent
    app), so a mounted indah needs no indah-specific glue."""
    user = request.scope.get("user")
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    for attr in ("identity", "username", "display_name"):
        try:
            ident = getattr(user, attr, None)
        except NotImplementedError:  # BaseUser.identity
            continue
        if isinstance(ident, str) and ident:
            return Principal(id=ident, name=getattr(user, "display_name", "") or "")
    return None


async def authenticate(request: HTTPConnection, auth: Authenticator | None) -> Principal | None:
    """Run ``auth`` for ``request``; ``None`` for no authenticator, no identity, an expired
    one, or any failure. On the live route ``request`` is a ``WebSocket`` (ADR-0045): an
    authenticator should read only ``headers``, ``cookies`` and ``client``, which both have."""
    if auth is None:
        return None
    try:
        result = auth(request)  # type: ignore[arg-type]
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        logger.exception("indah authenticator raised; treating the request as unauthenticated")
        return None
    if result is None:
        return None
    if not isinstance(result, Principal):
        logger.error("indah authenticator returned %r, not a Principal", type(result).__name__)
        return None
    return None if result.expired else result


_SID = re.compile(r"[A-Za-z0-9_-]{16,64}")
_MIN_SECRET_BYTES = 16


class TokenSigner:
    """Signed session tokens: ``<sid>.<HMAC-SHA256(secret, sid | principal | workspace)>``.

    The ``sid`` is 128 random bits and keys the session store. The signature binds it to one
    principal (and workspace), so a client can neither choose an id nor present another
    user's. ``secret`` may be a list for rotation: new tokens use the first, any verifies, so
    a deploy can add a new secret in front and drop the old one later."""

    def __init__(self, secret: str | bytes | Sequence[str | bytes]) -> None:
        raw = [secret] if isinstance(secret, (str, bytes)) else list(secret)
        keys = [s.encode() if isinstance(s, str) else bytes(s) for s in raw]
        if not keys or any(len(k) < _MIN_SECRET_BYTES for k in keys):
            raise ValueError(
                f"secret must be at least {_MIN_SECRET_BYTES} bytes (use a long random value)"
            )
        self._keys = keys

    @staticmethod
    def _message(sid: str, principal: Principal) -> bytes:
        return f"indah-session-v1|{sid}|{principal.id}|{principal.workspace or ''}".encode()

    def _sign(self, key: bytes, sid: str, principal: Principal) -> str:
        digest = hmac.new(key, self._message(sid, principal), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def mint(self, principal: Principal, sid: str | None = None) -> str:
        sid = sid or secrets.token_urlsafe(16)
        return f"{sid}.{self._sign(self._keys[0], sid, principal)}"

    def verify(self, token: object, principal: Principal) -> str | None:
        """The ``sid`` if ``token`` was signed for exactly this principal, else ``None``."""
        if not isinstance(token, str) or token.count(".") != 1 or len(token) > 200:
            return None
        sid, _, signature = token.partition(".")
        if not _SID.fullmatch(sid):
            return None
        ok = False
        for key in self._keys:  # check every key, so timing does not reveal which matched
            ok |= hmac.compare_digest(self._sign(key, sid, principal), signature)
        return sid if ok else None

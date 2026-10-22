"""The per-session ``Context`` handed to a session factory (IND-87).

A session factory may take no arguments (every app so far) or one ``Context``::

    def build(ctx: Context) -> Session:
        ctx.on_close(lambda: print("tab gone", ctx.sid))
        ...

It is the one place per-session facilities hang: later slices add push
subscriptions, toasts, the route and the authenticated user to it. For now it
carries the session id, a frozen snapshot of the connection that created the
session, the (future) ``user``, and a close hook. ``ConnectionInfo`` is a copy,
not the live ``Request``, which is dead once its response is sent.

Keep the context in the UI-building layer: domain logic stays plain functions
that take plain values (ADR-0009). ``conn`` can hold credentials (cookies, an
``Authorization`` header) for the session's lifetime, so do not log it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from .auth import Principal
from .authz import Forbidden, Policy, current_principal
from .authz import can as _can
from .protocol import navigate_message, signed_out_message, toast_message
from .proxy import forwarded_prefix
from .reactive import Computed, Signal
from .routes import Route, match_routes, normalize_path
from .stream import Stream

if TYPE_CHECKING:
    from starlette.requests import Request

    from .push import Topic
    from .transport import Hub

logger = logging.getLogger("indah")

T = TypeVar("T")
_MISSING: Any = object()


@dataclass(frozen=True)
class ConnectionInfo:
    """What the request that created a session looked like (a frozen copy)."""

    headers: Mapping[str, str] = field(default_factory=dict)  # lower-cased names
    cookies: Mapping[str, str] = field(default_factory=dict)
    client: str | None = None  # peer address as the ASGI server reports it
    path: str = ""
    prefix: str = ""  # the public path prefix a trusted proxy forwarded (ADR-0034), else ""
    app_path: str = "/"  # the in-app page the tab was on when it connected (ADR-0029)
    user: Principal | None = None  # who the request authenticated as (ADR-0033)

    @classmethod
    def from_request(
        cls, request: Request, app_path: str | None = None, user: Principal | None = None
    ) -> ConnectionInfo:
        return cls(
            app_path=app_path or "/",
            user=user,
            headers={k.lower(): v for k, v in request.headers.items()},
            cookies=dict(request.cookies),
            client=request.client.host if request.client else None,
            path=request.url.path,
            prefix=forwarded_prefix(request.scope),
        )


class Context:
    """Per-session facilities for a session factory. See the module docstring."""

    def __init__(
        self,
        sid: str,
        conn: ConnectionInfo | None = None,
        *,
        app: Any = None,
        user: Any = None,
    ) -> None:
        self.sid = sid
        self.conn = conn if conn is not None else ConnectionInfo()
        self.app = app  # the ASGI app serving this session, once create_app has bound it
        # The authenticated principal (ADR-0033), or None when the app has no authenticator.
        self.user: Principal | None = user if user is not None else self.conn.user
        self._on_close: list[Callable[[], None]] = []
        self._closed = False
        self._hub: Hub | None = None
        try:
            start = normalize_path(self.conn.app_path)
        except ValueError:
            start = "/"
        # The in-app path this tab is showing (``/projects/auth``), a signal a ``Router``
        # reads. Set it with ``navigate``; the browser sets it on a link click or Back.
        self.path: Signal[str] = Signal(start)
        self._routes: Signal[list[Route] | None] = Signal(None)  # set by the one Router
        # The matched route's params (``{"project": "auth", "entry_id": "01J"}``), or ``{}``
        # when nothing matches or there is no router. A computed, so a page that derives its
        # data from one param is not recomputed when an unrelated param or page changes.
        self.params: Computed[dict[str, Any]] = Computed(self._current_params)

    def _bind_hub(self, hub: Hub) -> None:
        self._hub = hub

    def toast(self, message: str, *, kind: str = "info", ttl: float = 4.0) -> None:
        """Show a transient message in *this session's* tab(s) only: ``kind`` is
        ``info``/``success``/``warn``/``error``, ``ttl`` seconds (0 = until dismissed).

        Call it from the event loop (a handler), like a signal write. Never put a
        secret in one. A no-op before the session has a connection hub."""
        message_ = toast_message(message, kind, ttl)  # validate even when unbound
        if self._hub is not None:
            self._hub.publish(message_)

    @property
    def workspace(self) -> str | None:
        """The workspace this session belongs to (``Principal.workspace``), or ``None``. The
        session token is signed for it, so another workspace never reaches this session."""
        return self.user.workspace if self.user is not None else None

    def can(self, perm: str) -> bool:
        """Whether the user holds ``perm`` (a role name, or a permission the app's ``Policy``
        grants one of their roles). While a handler runs this is the principal of *that*
        request, so a role revoked since the session was built is honoured; while the tree is
        built it is ``ctx.user``. No user, or an empty ``perm``, is ``False``.

        Use it to **omit** restricted components when building the tree (hidden is still sent),
        and :func:`~indah.authz.guard` or :meth:`require` to refuse an action."""
        principal = current_principal() or self.user
        policy: Policy | None = getattr(getattr(self.app, "state", None), "policy", None)
        return _can(principal, perm, policy)

    def require(self, perm: str) -> None:
        """Raise :class:`~indah.authz.Forbidden` unless :meth:`can`. In a handler this answers
        the event ``403`` and shows the tab a "not allowed" toast."""
        if not self.can(perm):
            raise Forbidden(f"not allowed: {perm}")

    def only(self, perm: str, build: Callable[[], T]) -> list[T]:
        """``[build()]`` if the user holds ``perm``, else ``[]``, so a restricted component is
        never even constructed for someone who may not see it::

            children=[Overview(), *ctx.only("admin", lambda: AdminPanel())]"""
        return [build()] if self.can(perm) else []

    def sign_out(self) -> int:
        """End every session this user holds (every open tab), and show each a signed-out page.

        The parent app still has to end its own login (clear its cookie), or the next request
        simply signs in again. Returns how many sessions were ended. A no-op for an app with
        no authenticated user."""
        store = getattr(getattr(self.app, "state", None), "store", None)
        discard_where = getattr(store, "discard_where", None)
        if self.user is None or discard_where is None:
            return 0
        return int(discard_where(owner=self.user.id, farewell=signed_out_message()))

    def _current_params(self) -> dict[str, Any]:
        routes = self._routes.value
        found = match_routes(routes, self.path.value) if routes else None
        return dict(found[1]) if found else {}

    def _set_routes(self, routes: list[Route]) -> None:
        if self._routes.value is not None:
            raise ValueError(
                "a session can have only one Router: the address bar is one path per tab, so "
                "two Routers would both answer it. Build one Router at the top of the session "
                "and give each page its own route; for a switcher inside a page that is not "
                "an address, use Tabs or a Signal and a computed instead"
            )
        self._routes.set(routes)

    def navigate(self, path: str, *, replace: bool = False) -> None:
        """Go to in-app ``path`` from server code: updates ``ctx.path`` and moves this tab's
        address bar (a new history entry, or ``replace`` the current one). Raises
        ``ValueError`` for anything that is not a plain in-app path."""
        path = normalize_path(path)
        self.path.set(path)
        if self._hub is not None:
            self._hub.publish(navigate_message(path, replace))

    def _client_navigated(self, path: str) -> None:
        """The browser already moved (a link click, Back/Forward): record it, no echo."""
        self.path.set(normalize_path(path))

    def on_close(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` when the session ends (discard, eviction, idle reaping).

        Registered after the session has already closed, it runs immediately."""
        if self._closed:
            self._run(fn)
        else:
            self._on_close.append(fn)

    def latest(self, topic: Topic[T], *, initial: Any = _MISSING) -> Signal[T | None]:
        """A signal holding the newest item published to ``topic`` (for a badge count, a
        status line). Starts at ``initial``, else the topic's latest retained item, else
        ``None``. Released when the session ends."""
        if initial is _MISSING:
            recent = topic.recent(1)
            initial = recent[0] if recent else None
        signal: Signal[T | None] = Signal(initial)
        self.on_close(topic.subscribe(signal.set))
        return signal

    def tail(self, topic: Topic[T], *, limit: int = 1000) -> Stream:
        """A bounded :class:`~indah.stream.Stream` of ``topic``'s items, seeded from its
        retained history and appended to on every publish. Released when the session
        ends."""
        stream = Stream(topic.recent(limit), limit=limit)
        self.on_close(topic.subscribe(stream.append))
        return stream

    def close(self) -> None:
        """Run the close callbacks once, each isolated from the others' failures."""
        if self._closed:
            return
        self._closed = True
        callbacks, self._on_close = self._on_close, []
        for fn in callbacks:
            self._run(fn)

    @staticmethod
    def _run(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            logger.exception("indah session close callback raised")

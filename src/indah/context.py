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

``ctx.every(seconds, fn)`` and ``ctx.spawn(coro)`` run background work that ends with the
session (IND-154).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from .auth import Principal
from .authz import Forbidden, Policy, current_principal
from .authz import can as _can
from .protocol import chrome_message, navigate_message, signed_out_message, toast_message
from .proxy import forwarded_prefix
from .reactive import Computation, Computed, Signal, effect
from .routes import Route, match_routes, normalize_path
from .state import _Persistence, persistence_for
from .stream import Stream

if TYPE_CHECKING:
    from starlette.requests import Request

    from .push import Topic
    from .transport import Hub

logger = logging.getLogger("indah")

T = TypeVar("T")
_MAX_TITLE = 200
_MISSING: Any = object()


class _ToastActions:
    """The handlers behind toast action buttons (IND-160), one table per session.

    The shell posts ``action`` with an id to ``TOAST_TARGET``; the handler is removed as it runs,
    so it runs once. The table is bounded: a toast that expires unclicked leaves its handler here
    until newer ones push it out."""

    MAX_PENDING = 32

    def __init__(self) -> None:
        self._fns: dict[str, Callable[[], Any]] = {}
        self._seq = 0

    def add(self, fn: Callable[[], Any]) -> str:
        self._seq += 1
        aid = f"t{self._seq}"
        self._fns[aid] = fn
        while len(self._fns) > self.MAX_PENDING:
            del self._fns[next(iter(self._fns))]
        return aid

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event != "action":
            return False
        aid = payload.get("id")
        fn = self._fns.pop(aid, None) if isinstance(aid, str) else None
        if fn is None:
            return True  # already run, expired or never ours: nothing to do, nothing wrong
        result = fn()
        return result if asyncio.iscoroutine(result) else True


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
    node: str = ""  # which process built this session (IND-203); an opaque id, never an address

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
            node=str(getattr(request.app.state, "node", "")),
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
        self._spawned: set[asyncio.Task[Any]] = set()  # ctx.spawn / ctx.every, cancelled on close
        self._hub: Hub | None = None
        self._toast_actions = _ToastActions()
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
        # The tab's title and icon (IND-152). ``None`` is the app's own. ``favicon`` names one
        # registered with ``create_app(favicons=)``. A change is sent to this session's tab(s)
        # only, and a fresh init carries the current values.
        self.title: Signal[str | None] = Signal(None)
        self.favicon: Signal[str | None] = Signal(None)
        self._chrome_sent: tuple[str | None, str | None] = (None, None)
        self._bad_favicons: set[str] = set()
        self._chrome_effect: Computation = effect(self._sync_chrome)
        self._persistence: _Persistence | None = None  # built by the first ctx.persist

    def _bind_hub(self, hub: Hub) -> None:
        self._hub = hub

    def _chrome_state(self) -> tuple[str | None, str | None]:
        """The title and favicon URL to show now, validated. Reads the signals (tracked)."""
        title = self.title.value
        if title is not None:
            title = str(title)[:_MAX_TITLE]
        name = self.favicon.value
        url: str | None = None
        if name is not None:
            favicons = getattr(getattr(self.app, "state", None), "favicons", None) or {}
            if name in favicons:
                url = f"api/brand/favicon/{name}"
            elif name not in self._bad_favicons:
                self._bad_favicons.add(name)
                logger.warning("ctx.favicon %r is not registered with create_app(favicons=)", name)
        return title, url

    def _chrome(self) -> dict[str, Any] | None:
        """What a fresh ``init`` should carry: the title and icon, or ``None`` when both are the
        app's own."""
        title, url = self._chrome_state()
        return {"title": title, "favicon": url} if title is not None or url is not None else None

    def _sync_chrome(self) -> None:
        state = self._chrome_state()
        if state == self._chrome_sent:
            return
        self._chrome_sent = state
        if self._hub is not None and not self._closed:
            self._hub.publish(chrome_message(*state))

    def toast(
        self,
        message: str,
        *,
        kind: str = "info",
        ttl: float = 4.0,
        action: tuple[str, Callable[[], Any]] | None = None,
    ) -> None:
        """Show a transient message in *this session's* tab(s) only: ``kind`` is
        ``info``/``success``/``warn``/``error``, ``ttl`` seconds (0 = until dismissed).

        ``action=("Undo", fn)`` adds a button. Clicking it runs ``fn`` once (a plain function
        or ``async def``, as a handler: ``guard()`` is checked when it is clicked) and dismisses
        the toast. Give an undo a longer ``ttl`` than the default. After a dropped stream the
        toast may be shown again; its button then does nothing if it already ran.

        Call it from the event loop (a handler), like a signal write. Never put a
        secret in one. A no-op before the session has a connection hub."""
        wire_action: dict[str, str] | None = None
        if action is not None:
            if not isinstance(action, tuple) or len(action) != 2:
                raise TypeError("toast action must be a (label, callable) pair")
            label, fn = action
            if not callable(fn):
                raise TypeError("toast action must be a (label, callable) pair")
            toast_message(message, kind, ttl, {"id": "x", "label": label})  # validate first
            wire_action = {"id": "", "label": label}
        else:
            toast_message(message, kind, ttl)  # validate even when unbound
        if self._hub is None:
            return
        if wire_action is not None:
            wire_action["id"] = self._toast_actions.add(fn)
        self._hub.publish(toast_message(message, kind, ttl, wire_action))

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

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any] | None:
        """Run ``coro`` in the background for the life of this session.

        The task is cancelled when the session ends (discard, eviction, idle reaping), and an
        exception it raises is logged once rather than lost. Call it from the event loop (the
        session factory or a handler). On a session that has already closed the coroutine is
        dropped and ``None`` is returned."""
        if self._closed:
            coro.close()
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            raise RuntimeError(
                "ctx.spawn needs a running event loop: call it from the session factory or a "
                "handler"
            ) from None
        task = loop.create_task(coro)
        self._spawned.add(task)
        task.add_done_callback(self._spawn_done)
        return task

    def _spawn_done(self, task: asyncio.Task[Any]) -> None:
        self._spawned.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("indah ctx.spawn task failed", exc_info=task.exception())

    def every(
        self,
        seconds: float,
        fn: Callable[[], Any],
        *,
        immediately: bool = False,
    ) -> asyncio.Task[Any] | None:
        """Call ``fn`` every ``seconds`` for the life of this session (a refresh loop).

        ``fn`` may be a plain function or ``async def``; it runs on the event loop, so keep it
        short or await. The first call is after ``seconds``, or now with ``immediately=True``.
        An exception is logged once and the loop carries on; it logs again only if the call
        succeeds in between. The loop is cancelled when the session ends."""
        if not seconds > 0:
            raise ValueError("every(): seconds must be greater than 0")
        return self.spawn(self._every_loop(float(seconds), fn, immediately))

    @staticmethod
    async def _every_loop(seconds: float, fn: Callable[[], Any], immediately: bool) -> None:
        failing = False
        skip_wait = immediately
        while True:
            if not skip_wait:
                await asyncio.sleep(seconds)
            skip_wait = False
            try:
                result = fn()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                if not failing:
                    logger.exception("indah ctx.every callback raised")
                failing = True
            else:
                failing = False

    def persist(
        self,
        name: str,
        signal: Signal[Any],
        *,
        version: int = 1,
        ttl: float | None = None,
        max_bytes: int | None = None,
        validate: Callable[[Any], bool] | None = None,
    ) -> None:
        """Keep ``signal``'s value across a restart, a rollout or a move to another replica.

        Call it in the session factory, after creating the signal. If a value was saved for this
        tab (same session id, same user), the signal is set to it now, before the first paint.
        After that the value is saved whenever it changes (a burst of changes is one write).
        ``name`` identifies it within the session. Only a ``Signal`` the app writes is accepted.

        The value must be plain JSON: ``str``, ``int``, ``float``, ``bool``, ``None``, ``list``
        and ``dict`` with string keys; anything else raises ``ValueError`` here. A value over
        ``max_bytes`` (default 16 KB; 128 KB for the session) is not saved, with one warning.
        ``ttl`` is how long a saved value lives after its last write (default 24 hours).
        ``version`` goes with the value: bump it when the signal's shape changes, and old data is
        ignored. ``validate(value)`` may veto a restored value (return ``False``).

        Never persist a secret. A signal shown in an ephemeral prop (``SecretReveal``) is
        refused and anything stored for it is removed. Keep it to small UI state (filters, the
        selected tab, a draft); durable data belongs in your own database. Values are per
        browser tab: a new tab, another device or another user starts from the defaults. With
        the default in-memory store, a restart of the process still starts blank; use
        ``create_app(state_store="sqlite:///state.db")`` or your own ``StateStore``.

        ``guard`` and ``Policy`` are unaffected: restoring a value runs no handler."""
        if self._persistence is None:
            self._persistence = persistence_for(self)
        self._persistence.add(
            name, signal, version=version, ttl=ttl, max_bytes=max_bytes, validate=validate
        )

    def _session_ready(self, session: Any) -> None:
        """The store calls this once the session's tree exists: saving starts."""
        if self._persistence is not None:
            self._persistence.session_ready(session)

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
        self._chrome_effect.dispose()
        if self._persistence is not None:
            self._persistence.close()
        for task in list(self._spawned):
            task.cancel()
        self._spawned.clear()
        callbacks, self._on_close = self._on_close, []
        for fn in callbacks:
            self._run(fn)

    @staticmethod
    def _run(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            logger.exception("indah session close callback raised")

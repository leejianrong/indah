"""The session-store seam: state access behind a small interface (ADR-0010).

Slices 1-3 kept one shared :class:`~indah.session.Session` (and one
:class:`~indah.transport.Hub`) for the whole app, so every browser tab drove -- and
saw -- the same reactive graph. That is right for a single-user notebook prototype
but wrong for even two viewers: an honest multi-user app gives each viewer its own
signals and its own patch stream.

This module is that seam. A :class:`SessionStore` maps a **session id** (one per
browser tab, minted by the shell) to a :class:`SessionHandle` -- the pair of
objects one connection needs: its own ``Session`` (an isolated reactive graph) and
its own ``Hub`` (so a patch reaches only that viewer's SSE stream). The reactive
core reaches state only through this seam; ``app.py`` never assumes a single global
session.

Per ADR-0010 only the **in-memory** backend ships here. The interface is
deliberately narrow -- id in, handle out -- so a later external backend (e.g. Redis,
for state that outlives the process and is shared across replicas) is a drop-in
that implements the same ``SessionStore`` protocol. That backend owns its own
concerns (serialising signal values, eviction, locking); those are deferred with
the backend, not designed now.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .context import ConnectionInfo, Context
from .protocol import error_message, init_message
from .session import Session
from .transport import Hub

if TYPE_CHECKING:
    from .components import Component

logger = logging.getLogger("indah")

# How long a request waits for an ``async`` session factory before the tab is given a skeleton.
DEFAULT_FACTORY_TIMEOUT = 1.0


def _takes_context(factory: Callable[..., Session]) -> bool:
    """Whether ``factory`` wants a ``Context``: it has a required positional parameter.

    A zero-arg factory (every app before IND-87) or one whose parameters all have
    defaults is called with no arguments."""
    try:
        params = inspect.signature(factory).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        for p in params
    )


def _is_async_factory(factory: Callable[..., object]) -> bool:
    """Whether ``factory`` is an ``async def`` (or an object whose ``__call__`` is one)."""
    return inspect.iscoroutinefunction(factory) or inspect.iscoroutinefunction(
        getattr(factory, "__call__", None)  # noqa: B004
    )


@dataclass
class _Build:
    """One ``async`` factory run that has not finished (IND-153)."""

    task: asyncio.Task[Session]
    ctx: Context
    hub: Hub
    owner: str | None
    completed: bool = False


@dataclass
class SessionHandle:
    """One viewer's isolated state: its own reactive ``Session`` and ``Hub``.

    The ``Hub`` is bound to the ``Session`` when the handle is created, so the
    session's live (async/streaming) emits reach exactly this viewer's stream.
    """

    session: Session
    hub: Hub
    # The id of the principal that owns this session (ADR-0033), or None for an app with no
    # authenticator. A secure app refuses any other principal; a store can drop a user's sessions.
    owner: str | None = None


@runtime_checkable
class SessionStore(Protocol):
    """The seam. Given a session id, hand back that session's isolated state.

    An implementation must return the *same* handle for repeated calls with the
    same id (so a reconnecting tab resumes its own state) and distinct handles for
    distinct ids (so viewers stay isolated).
    """

    def get_or_create(
        self, session_id: str, ctx_info: ConnectionInfo | None = None
    ) -> SessionHandle:
        """Return the handle for ``session_id``, creating it on first sight.

        ``ctx_info`` describes the request that is creating it (used only on first
        sight, to build the session's ``Context``)."""
        ...

    def get(self, session_id: str) -> SessionHandle | None:
        """Return the handle for ``session_id`` if it exists, else ``None``."""
        ...

    def discard(self, session_id: str) -> None:
        """Drop ``session_id``'s state and close its session; a no-op if unknown."""
        ...


class InMemorySessionStore:
    """The v1 backend: per-session state held in a process-local dict (ADR-0010).

    Each new id builds a fresh ``Session`` from ``factory`` (which must construct a
    new reactive graph -- new signals -- every call, so sessions never share state)
    and binds it to a fresh ``Hub``. State lives only in this process and does not
    outlive it; surviving a restart or spanning replicas is a later backend's job.

    ``max_sessions`` and ``idle_timeout_seconds`` are optional bounds (ADR-0024) for
    a public deployment: both default to ``None`` (unbounded), which is today's
    behaviour and what every notebook/test use keeps. When set, ``get_or_create``
    lazily reaps -- on each call, idle-timed-out entries are dropped first, then the
    least-recently-used entry if the store is still over ``max_sessions`` -- so an
    abandoned browser tab does not grow the store forever. There is no background
    sweep: an idle deployment with no incoming requests will not reap until the next
    one arrives, which is fine since there is no resource pressure without traffic.
    Eviction calls ``discard``, which cancels the session's background tasks too.

    An ``async def`` factory is awaited by :meth:`aget_or_create` for up to ``factory_timeout``
    seconds, so a fast one has its data in the first snapshot. A slower one lets the tab start
    on a placeholder (``placeholder()``, default a ``Skeleton``); the real tree follows as a
    fresh ``init`` on the same stream when the factory finishes (ADR-0025 amendment).
    """

    def __init__(
        self,
        factory: Callable[[], Session]
        | Callable[[Context], Session]
        | Callable[[], Awaitable[Session]]
        | Callable[[Context], Awaitable[Session]],
        *,
        max_sessions: int | None = None,
        idle_timeout_seconds: float | None = None,
        factory_timeout: float = DEFAULT_FACTORY_TIMEOUT,
        placeholder: Callable[[], Component] | None = None,
    ) -> None:
        if not factory_timeout > 0:
            raise ValueError("factory_timeout must be a positive number of seconds")
        self._factory = factory
        self._wants_ctx = _takes_context(factory)
        self._is_async = _is_async_factory(factory)
        self.factory_timeout = factory_timeout
        self._placeholder = placeholder
        self._building: dict[str, _Build] = {}
        self._placeholders: dict[str, SessionHandle] = {}
        self.app: object | None = None  # bound by create_app; handed to each Context
        self.max_sessions = max_sessions
        self.idle_timeout_seconds = idle_timeout_seconds
        self._handles: OrderedDict[str, SessionHandle] = OrderedDict()
        self._last_seen: dict[str, float] = {}

    @property
    def open_sessions(self) -> int:
        """Sessions held by this process right now (the deploy doctor shows it)."""
        return len(self._handles)

    def _touch(self, session_id: str) -> None:
        if session_id in self._handles:  # not true if max_sessions evicted it below
            self._handles.move_to_end(session_id)
        self._last_seen[session_id] = time.monotonic()

    def _reap_idle(self) -> None:
        if self.idle_timeout_seconds is None:
            return
        now = time.monotonic()
        # Oldest-touched first (front of the OrderedDict); stop at the first entry
        # still within the timeout, since everything after it is more recent.
        for session_id in list(self._handles):
            if now - self._last_seen[session_id] <= self.idle_timeout_seconds:
                break
            self.discard(session_id)

    def get_or_create(
        self, session_id: str, ctx_info: ConnectionInfo | None = None
    ) -> SessionHandle:
        if self._is_async:
            raise RuntimeError(
                "this store's session factory is async: call `await store.aget_or_create(...)`"
            )
        self._reap_idle()
        handle = self._handles.get(session_id)
        if handle is None:
            ctx = Context(session_id, ctx_info, app=self.app)
            owner = ctx.user.id if ctx.user is not None else None
            hub = Hub()
            ctx._bind_hub(hub)
            session = self._factory(ctx) if self._wants_ctx else self._factory()
            handle = self._register(session_id, ctx, hub, session, owner)
        self._touch(session_id)
        return handle

    def _register(
        self,
        session_id: str,
        ctx: Context,
        hub: Hub,
        session: Session,
        owner: str | None,
        *,
        ready: bool = True,
    ) -> SessionHandle:
        session.ctx = ctx
        session.session_id = session_id  # so served file URLs route back here
        session.bind_hub(hub)
        if ready:  # not for a placeholder: the real tree is checked when it arrives
            ctx._session_ready(session)  # ctx.persist: the tree exists, saving may start
        handle = SessionHandle(session=session, hub=hub, owner=owner)
        self._handles[session_id] = handle
        if self.max_sessions is not None:
            while len(self._handles) > self.max_sessions:
                self.discard(next(iter(self._handles)))  # least-recently-used
        return handle

    # -- async factories (IND-153) --------------------------------------------

    async def aget_or_create(
        self, session_id: str, ctx_info: ConnectionInfo | None = None
    ) -> SessionHandle:
        """:meth:`get_or_create` for an ``async def`` factory (a sync factory runs as before).

        Waits up to ``factory_timeout`` for the factory. If it finishes, the handle holds the
        real session. If not, the handle holds a placeholder session and the real one replaces
        it, through the same hub, when the factory completes. Concurrent callers for one id
        share one factory run. A factory that raises before the timeout raises here."""
        if not self._is_async:
            return self.get_or_create(session_id, ctx_info)
        self._reap_idle()
        handle = self._handles.get(session_id)
        if handle is None:
            build = self._building.get(session_id)
            if build is None:
                build = self._start_build(session_id, ctx_info)
            await asyncio.wait({build.task}, timeout=self.factory_timeout)
            handle = self._handles.get(session_id)
            if handle is None:
                if build.task.done():
                    self._complete(session_id, build)
                    if build.task.cancelled():
                        raise RuntimeError("the session was closed while it was starting")
                    build.task.result()  # a factory error is the caller's error
                    handle = self._handles.get(session_id)
                else:
                    handle = self._show_placeholder(session_id, build)
            if handle is None:
                raise RuntimeError("the session was closed while it was starting")
        self._touch(session_id)
        return handle

    def _start_build(self, session_id: str, ctx_info: ConnectionInfo | None) -> _Build:
        ctx = Context(session_id, ctx_info, app=self.app)
        owner = ctx.user.id if ctx.user is not None else None
        hub = Hub()
        ctx._bind_hub(hub)
        coro = self._factory(ctx) if self._wants_ctx else self._factory()
        task = asyncio.ensure_future(coro)
        build = _Build(task=task, ctx=ctx, hub=hub, owner=owner)
        self._building[session_id] = build
        task.add_done_callback(lambda _t: self._complete(session_id, build))
        return build

    def _show_placeholder(self, session_id: str, build: _Build) -> SessionHandle:
        from .components import Column, Skeleton

        root = self._placeholder() if self._placeholder is not None else Skeleton(lines=4)
        handle = self._register(
            session_id,
            build.ctx,
            build.hub,
            Session(Column(children=[root])),
            build.owner,
            ready=False,
        )
        self._placeholders[session_id] = handle
        return handle

    def _complete(self, session_id: str, build: _Build) -> None:
        """The factory run ended: install the real session, swap it in for the placeholder, or
        report the failure. Idempotent (a waiting request and the done-callback both call it)."""
        if build.completed:
            return
        build.completed = True
        if self._building.get(session_id) is build:
            del self._building[session_id]
        task = build.task
        if task.cancelled():
            return
        error = task.exception()  # also marks it retrieved
        placeholder = self._placeholders.pop(session_id, None)
        if error is not None:
            if placeholder is not None:
                logger.error("indah session factory failed", exc_info=error)
                build.hub.publish(error_message(f"{type(error).__name__}: {error}"))
                self.discard(session_id)
            return  # no handle yet: the waiting request raises it
        session = task.result()
        if placeholder is None:
            self._register(session_id, build.ctx, build.hub, session, build.owner)
            return
        session.ctx = build.ctx
        session.session_id = session_id
        session.bind_hub(build.hub)
        placeholder.session = session
        build.ctx._session_ready(session)
        session.forget_ephemeral()
        build.hub.publish(init_message(session.snapshot(), chrome=build.ctx._chrome()))

    def get(self, session_id: str) -> SessionHandle | None:
        handle = self._handles.get(session_id)
        if handle is not None:
            self._touch(session_id)
        return handle

    def discard(self, session_id: str) -> None:
        handle = self._handles.pop(session_id, None)
        self._last_seen.pop(session_id, None)
        self._placeholders.pop(session_id, None)
        build = self._building.pop(session_id, None)
        if build is not None:
            build.completed = True
            if build.task.done():
                if not build.task.cancelled() and build.task.exception() is None:
                    build.task.result().close()  # finished, but nobody will ever use it
            else:
                build.task.cancel()  # the factory stops where it is
            if handle is None:
                build.ctx.close()  # no session yet to run its on_close callbacks
        if handle is not None:
            handle.session.close()

    def discard_where(self, *, owner: str, farewell: dict | None = None) -> int:
        """Discard every session owned by ``owner`` (sign-out, a revoked login); returns how
        many. ``farewell`` is published to each session's stream first (the signed-out
        message). Not part of the ``SessionStore`` protocol: a store that lacks it just cannot
        be signed out this way."""
        mine = [sid for sid, h in self._handles.items() if h.owner == owner]
        mine += [sid for sid, b in self._building.items() if b.owner == owner and sid not in mine]
        for sid in mine:
            if farewell is not None and sid in self._handles:
                self._handles[sid].hub.publish(farewell)
            self.discard(sid)
        return len(mine)

    def __len__(self) -> int:
        return len(self._handles)


class SharedSessionStore:
    """One shared ``Session`` for every connection, whatever the id -- the
    pre-Slice-C behaviour.

    Used when an app is built from a single pre-constructed ``Session``
    (``create_app(session=...)``): there is one reactive graph and one ``Hub``, and
    every viewer drives and sees it. This is a genuine ``SessionStore`` (so
    ``app.py`` treats both stores identically), kept for single-user apps and for
    the tests and examples that introspect one shared session.
    """

    def __init__(self, session: Session) -> None:
        hub = Hub()
        session.bind_hub(hub)
        self.handle = SessionHandle(session=session, hub=hub)

    @property
    def open_sessions(self) -> int:
        return 1

    def get_or_create(
        self, session_id: str, ctx_info: ConnectionInfo | None = None
    ) -> SessionHandle:
        return self.handle

    def get(self, session_id: str) -> SessionHandle | None:
        return self.handle

    def discard(self, session_id: str) -> None:  # nothing to drop: it is shared
        pass

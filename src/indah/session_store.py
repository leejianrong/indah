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

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .session import Session
from .transport import Hub


@dataclass
class SessionHandle:
    """One viewer's isolated state: its own reactive ``Session`` and ``Hub``.

    The ``Hub`` is bound to the ``Session`` when the handle is created, so the
    session's live (async/streaming) emits reach exactly this viewer's stream.
    """

    session: Session
    hub: Hub


@runtime_checkable
class SessionStore(Protocol):
    """The seam. Given a session id, hand back that session's isolated state.

    An implementation must return the *same* handle for repeated calls with the
    same id (so a reconnecting tab resumes its own state) and distinct handles for
    distinct ids (so viewers stay isolated).
    """

    def get_or_create(self, session_id: str) -> SessionHandle:
        """Return the handle for ``session_id``, creating it on first sight."""
        ...

    def get(self, session_id: str) -> SessionHandle | None:
        """Return the handle for ``session_id`` if it exists, else ``None``."""
        ...

    def discard(self, session_id: str) -> None:
        """Drop ``session_id``'s state; a no-op if it is unknown."""
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
    """

    def __init__(
        self,
        factory: Callable[[], Session],
        *,
        max_sessions: int | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self._factory = factory
        self.max_sessions = max_sessions
        self.idle_timeout_seconds = idle_timeout_seconds
        self._handles: OrderedDict[str, SessionHandle] = OrderedDict()
        self._last_seen: dict[str, float] = {}

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

    def get_or_create(self, session_id: str) -> SessionHandle:
        self._reap_idle()
        handle = self._handles.get(session_id)
        if handle is None:
            session = self._factory()
            session.session_id = session_id  # so served file URLs route back here
            hub = Hub()
            session.bind_hub(hub)
            handle = SessionHandle(session=session, hub=hub)
            self._handles[session_id] = handle
            if self.max_sessions is not None:
                while len(self._handles) > self.max_sessions:
                    self.discard(next(iter(self._handles)))  # least-recently-used
        self._touch(session_id)
        return handle

    def get(self, session_id: str) -> SessionHandle | None:
        handle = self._handles.get(session_id)
        if handle is not None:
            self._touch(session_id)
        return handle

    def discard(self, session_id: str) -> None:
        handle = self._handles.pop(session_id, None)
        self._last_seen.pop(session_id, None)
        if handle is not None:
            handle.session.cancel_tasks()

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

    def get_or_create(self, session_id: str) -> SessionHandle:
        return self.handle

    def get(self, session_id: str) -> SessionHandle | None:
        return self.handle

    def discard(self, session_id: str) -> None:  # nothing to drop: it is shared
        pass

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
    """

    def __init__(self, factory: Callable[[], Session]) -> None:
        self._factory = factory
        self._handles: dict[str, SessionHandle] = {}

    def get_or_create(self, session_id: str) -> SessionHandle:
        handle = self._handles.get(session_id)
        if handle is None:
            session = self._factory()
            session.session_id = session_id  # so served file URLs route back here
            hub = Hub()
            session.bind_hub(hub)
            handle = SessionHandle(session=session, hub=hub)
            self._handles[session_id] = handle
        return handle

    def get(self, session_id: str) -> SessionHandle | None:
        return self._handles.get(session_id)

    def discard(self, session_id: str) -> None:
        self._handles.pop(session_id, None)

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

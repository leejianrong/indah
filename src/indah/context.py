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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger("indah")


@dataclass(frozen=True)
class ConnectionInfo:
    """What the request that created a session looked like (a frozen copy)."""

    headers: Mapping[str, str] = field(default_factory=dict)  # lower-cased names
    cookies: Mapping[str, str] = field(default_factory=dict)
    client: str | None = None  # peer address as the ASGI server reports it
    path: str = ""

    @classmethod
    def from_request(cls, request: Request) -> ConnectionInfo:
        return cls(
            headers={k.lower(): v for k, v in request.headers.items()},
            cookies=dict(request.cookies),
            client=request.client.host if request.client else None,
            path=request.url.path,
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
        self.user = user  # the authenticated principal; always None until identity lands
        self._on_close: list[Callable[[], None]] = []
        self._closed = False

    def on_close(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` when the session ends (discard, eviction, idle reaping).

        Registered after the session has already closed, it runs immediately."""
        if self._closed:
            self._run(fn)
        else:
            self._on_close.append(fn)

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

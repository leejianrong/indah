"""``Topic``: an app-level channel any task can publish to and any session can follow
(IND-89, ADR-0026).

A ``Hub`` is per session, so nothing outside a session could reach every open tab. A
``Topic`` is the other half: it lives at app level, a background task publishes to it,
and each session that subscribed (through ``ctx.latest`` / ``ctx.tail``) updates its own
signals, so every tab updates while per-tab state stays per tab::

    log = Topic("log", replay=1000)                    # app level

    def build(ctx):
        rows = ctx.tail(log, limit=1000)               # a Stream, seeded from log.recent()
        ...

    log.publish({"id": "01J...", "result": "hit"})     # from a task on the event loop
    log.publish_threadsafe({...})                      # from any other thread

Delivery runs on the event loop with no dispatch in flight, so it takes the same live
path an async handler does. A session releases its subscriptions through
``ctx.on_close``, so an evicted tab leaves nothing behind.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")

logger = logging.getLogger("indah")


class Topic(Generic[T]):
    def __init__(self, name: str, *, replay: int = 0) -> None:
        """``replay`` is how many recent items to keep for late subscribers (0 = none)."""
        self.name = name
        self._recent: deque[T] = deque(maxlen=replay) if replay > 0 else deque(maxlen=0)
        self._subscribers: list[Callable[[T], None]] = []
        # The event loop subscribers live on, learned at first subscribe, so a publish from
        # another thread can be marshalled onto it.
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def recent(self, n: int | None = None) -> list[T]:
        """The newest ``n`` retained items (all of them by default), oldest first."""
        items = list(self._recent)
        return items if n is None else items[-n:] if n > 0 else []

    def subscribe(self, callback: Callable[[T], None]) -> Callable[[], None]:
        """Call ``callback(item)`` on every publish; returns the unsubscribe function.

        Callbacks run on the event loop. Prefer ``ctx.latest`` / ``ctx.tail``, which also
        release the subscription when the session ends."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        self._subscribers.append(callback)

        def off() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return off

    def publish(self, item: T) -> None:
        """Deliver ``item`` to every subscriber. Call it on the event loop; from another
        thread use :meth:`publish_threadsafe`."""
        self._recent.append(item)
        for callback in list(self._subscribers):
            try:
                callback(item)
            except Exception:
                logger.exception("indah topic %r subscriber raised", self.name)

    def publish_threadsafe(self, item: T) -> None:
        """Publish from any thread: marshalled onto the subscribers' event loop, in order.

        With no subscriber yet there is no loop to wait for, so the item is just recorded
        (for ``replay``)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self._recent.append(item)
            return
        loop.call_soon_threadsafe(self.publish, item)

"""SSE transport: a hub that fans server-generated messages out to browsers.

Each connected browser holds one SSE stream backed by an ``asyncio.Queue``. The
hub broadcasts a message by putting it on every subscriber's queue. This is the
server->client half of ADR-0002; the client->server half is a plain HTTP POST
handled in ``app.py``.

Slice 1 keeps one shared hub for the whole app. Per-session isolation arrives
with the reactive core (ADR-0003), at which point each session gets its own hub.
"""

from __future__ import annotations

import asyncio
from typing import Any


class Hub:
    def __init__(self, *, queue_maxsize: int = 1024) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_maxsize = queue_maxsize

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send ``message`` to every current subscriber.

        A subscriber whose queue is full (a stalled or dead client) is dropped
        rather than allowed to block the broadcast.
        """
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.unsubscribe(queue)

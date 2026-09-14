"""SSE transport: a hub that fans server-generated messages out to browsers.

Each connected browser holds one SSE stream backed by an ``asyncio.Queue``. The
hub broadcasts a message by putting it on every subscriber's queue. This is the
server->client half of ADR-0002; the client->server half is a plain HTTP POST
handled in ``app.py``.

Slice 3 makes the hub the sequencer for resume (ADR-0011): every published
message is tagged with a monotonically increasing offset and kept in a bounded
history buffer, so a client that reconnects with a ``Last-Event-Id`` can be
replayed the messages it missed (``replay_since``). Queue items are
``(offset, message)`` tuples; the stream handler emits the offset as the SSE
``id:`` field. Publishing is synchronous (only ``put_nowait``), which keeps
streamed tokens strictly ordered even when emitted from between an async
handler's awaits.

Slice 1 kept one shared hub for the whole app; that still holds in v0. Per-session
isolation for multiple concurrent users arrives with the state seam (ADR-0010).
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

Message = dict[str, Any]
Item = tuple[int, Message]


class Hub:
    def __init__(self, *, queue_maxsize: int = 1024, history_size: int = 512) -> None:
        self._subscribers: set[asyncio.Queue[Item]] = set()
        self._queue_maxsize = queue_maxsize
        self._history: deque[Item] = deque(maxlen=history_size)
        self._offset = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def current_offset(self) -> int:
        """The offset of the most recently published message (0 before any)."""
        return self._offset

    def subscribe(self) -> asyncio.Queue[Item]:
        queue: asyncio.Queue[Item] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Item]) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: Message) -> int:
        """Assign the next offset, buffer the message, and fan it out. Synchronous.

        A subscriber whose queue is full (a stalled or dead client) is dropped
        rather than allowed to block the broadcast. Returns the assigned offset.
        """
        self._offset += 1
        item: Item = (self._offset, message)
        self._history.append(item)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                self.unsubscribe(queue)
        return self._offset

    async def broadcast(self, message: Message) -> int:
        """Async wrapper over :meth:`publish` for callers already in async code."""
        return self.publish(message)

    def history(self) -> list[Item]:
        """A copy of the buffered ``(offset, message)`` items, oldest first."""
        return list(self._history)

    def replay_since(self, last_event_id: int | None) -> list[Item] | None:
        """Buffered messages with offset > ``last_event_id`` (a resume).

        Returns ``[]`` when the client is already current (or has no last id to
        resume from), and ``None`` when the next needed message has been evicted
        from the buffer -- a gap the caller must recover from by resending a full
        ``init`` snapshot rather than a partial, corrupt replay.
        """
        if last_event_id is None or last_event_id >= self._offset:
            return []
        if not self._history:
            return None
        oldest = self._history[0][0]
        if last_event_id < oldest - 1:
            return None  # a gap: messages before the buffer were dropped
        return [item for item in self._history if item[0] > last_event_id]

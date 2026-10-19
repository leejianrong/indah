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

Slices 1-3 kept one shared hub for the whole app. Slice C gives each viewer its own
hub, paired with its own session behind the session-store seam (``session_store.py``,
ADR-0010), so a patch fans out only to that viewer's stream, never another's.
"""

from __future__ import annotations

import asyncio
import secrets
from collections import deque
from typing import Any

from .protocol import PROTOCOL_VERSION

Message = dict[str, Any]
Item = tuple[int, Message]


class Hub:
    def __init__(
        self,
        *,
        queue_maxsize: int = 1024,
        history_size: int = 512,
        coalesce_seconds: float = 0.1,
    ) -> None:
        self._subscribers: set[asyncio.Queue[Item]] = set()
        self._queue_maxsize = queue_maxsize
        self._history: deque[Item] = deque(maxlen=history_size)
        self._offset = 0
        # Identifies this hub instance. Offsets only mean something within one hub, so
        # the SSE ``id:`` is ``<epoch>-<offset>``: a client resuming against a restarted
        # server (a fresh hub) presents a foreign epoch and is sent a full snapshot
        # instead of being told it is "already current" (IND-85).
        self.epoch: str = secrets.token_hex(4)
        # Stream appends (IND-90) are held for ``coalesce_seconds`` and sent as one patch,
        # so tens of rows a second make ~10 frames a second, not tens. Pending rows are
        # flushed before any other message so the stream stays strictly ordered.
        self._coalesce = coalesce_seconds
        self._pending: dict[tuple[str, str], list[Any]] = {}
        self._pending_trim: dict[tuple[str, str], int | None] = {}
        self._timer: asyncio.TimerHandle | None = None

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

    def queue_append(self, target: str, prop: str, rows: list[Any], *, trim: int | None) -> None:
        """Hold an append for the coalescing window (``trim`` = rows the client keeps)."""
        key = (target, prop)
        self._pending.setdefault(key, []).extend(rows)
        self._pending_trim[key] = trim
        if self._timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop to wait on (sync caller, a test): send now
            self.flush()
            return
        self._timer = loop.call_later(self._coalesce, self.flush)

    def flush(self) -> None:
        """Publish any held appends as one patch now. A no-op when nothing is pending."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._pending:
            return
        pending, trims = self._pending, self._pending_trim
        self._pending, self._pending_trim = {}, {}
        changes: dict[str, dict[str, Any]] = {}
        for (target, prop), rows in pending.items():
            change = changes.setdefault(target, {"target": target, "append": {}})
            change["append"][prop] = rows
            if trims[(target, prop)] is not None:
                change.setdefault("trim", {})[prop] = trims[(target, prop)]
        self._publish({"v": PROTOCOL_VERSION, "type": "patch", "changes": list(changes.values())})

    def publish(self, message: Message) -> int:
        """Flush held appends, then assign the next offset, buffer the message, and fan
        it out. Synchronous.

        A subscriber whose queue is full (a stalled or dead client) is dropped
        rather than allowed to block the broadcast. Returns the assigned offset.
        """
        self.flush()
        return self._publish(message)

    def _publish(self, message: Message) -> int:
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

    def replay_since(
        self, last_event_id: int | None, epoch: str | None = None
    ) -> list[Item] | None:
        """Buffered messages with offset > ``last_event_id`` (a resume).

        ``epoch`` is the hub instance the client's id came from; a mismatch means the
        offset belongs to a different (e.g. pre-restart) hub, so return ``None`` to force
        a snapshot. ``None`` (a legacy integer id) skips the check.

        Returns ``[]`` when the client is already current (or has no last id to
        resume from), and ``None`` when the next needed message has been evicted
        from the buffer -- a gap the caller must recover from by resending a full
        ``init`` snapshot rather than a partial, corrupt replay.
        """
        if epoch is not None and last_event_id is not None and epoch != self.epoch:
            return None
        if last_event_id is None or last_event_id >= self._offset:
            return []
        if not self._history:
            return None
        oldest = self._history[0][0]
        if last_event_id < oldest - 1:
            return None  # a gap: messages before the buffer were dropped
        return [item for item in self._history if item[0] > last_event_id]

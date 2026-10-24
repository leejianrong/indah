"""Drain: stop taking new tabs, tell open ones to reconnect, then let the process go (IND-201).

A rolling deploy (Kubernetes, Fly) stops the old process while tabs are still connected to it.
Without this a tab sees its stream drop and retries against whichever process answers. With it,
the process first turns away *new* sessions and streams (``GET /ready`` answers ``503`` so the
platform stops routing to it), sends every open stream a ``reconnect`` message with a spread-out
delay, keeps answering events for sessions it already holds, and after ``seconds`` ends whatever
streams are left so the server can exit cleanly.

State is per process and loop-bound: call :meth:`Drain.begin` on the event loop (or use
:meth:`Drain.begin_threadsafe` from another thread).
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from .protocol import reconnect_message

log = logging.getLogger("indah")

# The first reconnect goes out no sooner than this, and no later than this after the drain starts,
# so a pod with many tabs does not send them all to the next pod in the same instant.
_MIN_AFTER_MS = 100
_MAX_AFTER_MS = 5000

# Queue items are ``(offset, message)``. A drain message is not state, so it carries an offset
# no hub ever uses and must never be dropped as "already seen" (see ``sse_events``).
DRAIN_OFFSET = -1


class Drain:
    """Whether this process is draining, and the open streams to tell about it."""

    def __init__(self, seconds: float = 10.0) -> None:
        self.seconds = float(seconds)
        self.draining = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue[Any]] = set()
        self._began_at: float | None = None

    @property
    def open_streams(self) -> int:
        return len(self._queues)

    def register(self, queue: asyncio.Queue[Any]) -> None:
        """Track an open stream's queue (a no-op if it is already tracked)."""
        self._queues.add(queue)
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:  # registered from plain code (a test): no loop to remember
                pass

    def unregister(self, queue: asyncio.Queue[Any]) -> None:
        self._queues.discard(queue)

    def begin(self) -> None:
        """Start draining. Idempotent. Runs on the event loop."""
        if self.draining:
            return
        self.draining = True
        self._began_at = time.monotonic()
        spread = self.seconds * 1000 * 0.5
        for queue in list(self._queues):
            after = int(random.uniform(0.2, 1.0) * spread)
            after = max(_MIN_AFTER_MS, min(_MAX_AFTER_MS, after))
            queue.put_nowait((DRAIN_OFFSET, reconnect_message(after)))

    def end(self) -> None:
        """Close the streams still open: they get a clean end, not a cancel."""
        for queue in list(self._queues):
            queue.put_nowait((DRAIN_OFFSET, {"v": 1, "type": "drain_end"}))

    async def wait(self) -> None:
        """Return when no stream is open, or ``seconds`` after :meth:`begin`, whichever is first.

        Streams still open at the deadline are ended."""
        began = self._began_at if self._began_at is not None else time.monotonic()
        while self._queues and time.monotonic() - began < self.seconds:
            await asyncio.sleep(0.05)
        if self._queues:
            self.end()
            await asyncio.sleep(0.05)  # let the end markers reach their streams

    async def run(self) -> None:
        """:meth:`begin`, then :meth:`wait`."""
        self.begin()
        await self.wait()


def chain_sigterm(drain: Drain, loop: asyncio.AbstractEventLoop) -> Callable[[], None] | None:
    """Under ``uvicorn app:app``, drain on SIGTERM before uvicorn begins its own shutdown.

    uvicorn closes its listening sockets first and then waits for connections, and an event
    stream never ends by itself, so without this a SIGTERM with a tab open waits for the
    platform's kill. The handler runs the drain, then calls uvicorn's own handler, so exit
    behaves as before once the drain is over. Only uvicorn's own handler is wrapped; any other
    server (gunicorn workers, a custom one) is left alone: call ``await app.state.drain.run()``
    from its shutdown hook instead. Returns a function that puts the old handler back, or
    ``None`` when nothing was installed.
    """
    if threading.current_thread() is not threading.main_thread():
        return None
    previous = signal.getsignal(signal.SIGTERM)
    owner = getattr(previous, "__self__", None)
    if not callable(previous) or not hasattr(owner, "should_exit"):
        return None

    def handler(signum: int, frame: Any) -> None:
        if drain.draining:  # a second SIGTERM: stop waiting
            previous(signum, frame)  # type: ignore[operator]
            return

        async def drain_then_exit() -> None:
            log.info("indah: SIGTERM, draining for up to %.0f s", drain.seconds)
            await drain.run()
            previous(signum, frame)  # type: ignore[operator]

        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(drain_then_exit()))

    signal.signal(signal.SIGTERM, handler)

    def restore() -> None:
        if signal.getsignal(signal.SIGTERM) is handler:
            signal.signal(signal.SIGTERM, previous)

    return restore

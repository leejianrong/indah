"""Tier 1 live media: the pieces of the WebSocket route that need no ASGI (ADR-0045).

The route itself (``/api/live``) lives in ``app.py`` next to the session, auth and audit helpers
it reuses. This module holds the options, the frame type, the latest-frame-wins mailbox and the
binary frame parser, so each can be tested alone.

The socket carries client -> server binary media only. Results go back to the page as ordinary
SSE patches (Tier 0), so resume, replay and multi-tab behave as they always have.
"""

from __future__ import annotations

import asyncio
import importlib.util
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

LIVE_PROTOCOL_VERSION = 1
LIVE_PATH = "api/live"
KINDS = ("video",)  # "audio" is reserved for the Microphone slice (ADR-0045)

# WebSocket close codes the route uses (documented in docs/protocol.md).
CLOSE_GOING_AWAY = 1001
CLOSE_POLICY = 1008
CLOSE_TOO_BIG = 1009
CLOSE_BAD_HELLO = 4400
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_UNKNOWN_SESSION = 4409
CLOSE_TOO_MANY = 4429

_SEQ = struct.Struct(">I")


@dataclass(frozen=True)
class Live:
    """Options for ``create_app(live=Live(...))``. ``live=True`` uses these defaults.

    ``max_frame_bytes`` closes the socket (1009) on a larger binary frame.
    ``max_sockets_per_address`` refuses a further socket (4429). ``max_bytes_per_second``
    closes (1008) a socket that sends more than that within one second. ``stats_seconds`` is how
    often the server reports ``dropped`` / ``processed`` counts. ``hello_timeout`` is how long a
    new socket may stay silent.
    """

    max_frame_bytes: int = 1 << 20
    max_sockets_per_address: int = 4
    max_bytes_per_second: int = 8 << 20
    stats_seconds: float = 1.0
    hello_timeout: float = 5.0

    def __post_init__(self) -> None:
        for name in ("max_frame_bytes", "max_sockets_per_address", "max_bytes_per_second"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"Live.{name} must be at least 1")
        if self.stats_seconds <= 0 or self.hello_timeout <= 0:
            raise ValueError("Live.stats_seconds and Live.hello_timeout must be positive")


@dataclass(frozen=True)
class Frame:
    """One captured video frame handed to a ``Camera`` handler.

    ``data`` is the encoded image (JPEG from the live socket, or whatever the browser sent on the
    Tier 0 snapshot fallback); decode it with your own imaging library. ``seq`` counts frames the
    browser captured, so a gap between two frames you see is a drop. ``ts`` is the server clock
    when it arrived.
    """

    data: bytes
    content_type: str = "image/jpeg"
    seq: int = 0
    ts: float = 0.0

    @property
    def size(self) -> int:
        return len(self.data)


def parse_frame(raw: bytes) -> tuple[int, bytes]:
    """Split a binary live frame into ``(seq, payload)``. Raises ``ValueError`` if it is not one."""
    if len(raw) <= _SEQ.size:
        raise ValueError("live frame too short")
    return _SEQ.unpack_from(raw)[0], raw[_SEQ.size :]


def pack_frame(seq: int, payload: bytes) -> bytes:
    """The inverse of :func:`parse_frame` (used by tests and Python clients)."""
    return _SEQ.pack(seq & 0xFFFFFFFF) + payload


class Mailbox:
    """A one-slot, latest-wins queue: the backpressure rule for live video (ADR-0045).

    ``put`` never blocks. A frame put while another still waits replaces it, and the replaced
    frame counts as dropped, so a slow handler sees the newest frame and a bounded delay.
    """

    def __init__(self) -> None:
        self._item: Frame | None = None
        self._event = asyncio.Event()
        self._closed = False
        self.dropped = 0
        self.processed = 0

    def put(self, frame: Frame) -> bool:
        """Store ``frame``; ``True`` when it replaced one that had not been taken."""
        replaced = self._item is not None
        if replaced:
            self.dropped += 1
        self._item = frame
        self._event.set()
        return replaced

    def close(self) -> None:
        self._closed = True
        self._event.set()

    async def get(self) -> Frame | None:
        """The waiting frame, or ``None`` once closed and empty."""
        while True:
            if self._item is not None:
                frame, self._item = self._item, None
                self._event.clear()
                self.processed += 1
                return frame
            if self._closed:
                return None
            self._event.clear()
            await self._event.wait()


class ByteBudget:
    """A per-socket byte rate cap: ``allow(n)`` is ``False`` once more than ``per_second`` bytes
    arrived within the current one-second window."""

    def __init__(self, per_second: int, clock: Callable[[], float] | None = None) -> None:
        self._per_second = per_second
        self._clock = clock or time.monotonic
        self._start = self._clock()
        self._used = 0

    def allow(self, nbytes: int) -> bool:
        now = self._clock()
        if now - self._start >= 1.0:
            self._start, self._used = now, 0
        self._used += nbytes
        return self._used <= self._per_second


def websocket_support() -> bool:
    """Whether uvicorn can serve a WebSocket here (``websockets`` or ``wsproto`` is installed)."""
    return any(importlib.util.find_spec(name) is not None for name in ("websockets", "wsproto"))

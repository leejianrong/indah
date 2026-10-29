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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

LIVE_PROTOCOL_VERSION = 1
LIVE_PATH = "api/live"
KINDS = ("video", "audio")

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
    new socket may stay silent. ``audio_buffer_seconds`` is how much audio a ``Microphone`` socket
    may have waiting for a slow handler before the oldest chunks are dropped.
    """

    max_frame_bytes: int = 1 << 20
    max_sockets_per_address: int = 4
    max_bytes_per_second: int = 8 << 20
    stats_seconds: float = 1.0
    hello_timeout: float = 5.0
    audio_buffer_seconds: float = 2.0

    def __post_init__(self) -> None:
        for name in ("max_frame_bytes", "max_sockets_per_address", "max_bytes_per_second"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"Live.{name} must be at least 1")
        if self.stats_seconds <= 0 or self.hello_timeout <= 0 or self.audio_buffer_seconds <= 0:
            raise ValueError(
                "Live.stats_seconds, Live.hello_timeout and Live.audio_buffer_seconds "
                "must be positive"
            )


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


@dataclass(frozen=True)
class AudioChunk:
    """One piece of microphone audio handed to a ``Microphone`` handler.

    From the live socket ``data`` is 16-bit little-endian mono PCM (``content_type``
    ``"audio/pcm"``) at ``sample_rate``; ``np.frombuffer(chunk.data, dtype="<i2")`` gives the
    samples. ``seq`` counts chunks the browser captured, and ``dropped_before`` is how many chunks
    were discarded just before this one because the handler fell behind (0 when none), so a
    transcriber knows the audio has a gap. Without a live socket the browser records, and on stop
    sends the whole take once as ``"audio/wav"`` bytes.
    """

    data: bytes
    content_type: str = "audio/pcm"
    seq: int = 0
    ts: float = 0.0
    sample_rate: int = 16000
    dropped_before: int = 0

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def seconds(self) -> float:
        """Duration of PCM audio (0.0 for any other content type)."""
        if self.content_type != "audio/pcm" or self.sample_rate <= 0:
            return 0.0
        return len(self.data) / 2 / self.sample_rate


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


class AudioQueue:
    """A bounded, ordered queue for live audio (ADR-0045): audio cannot be thinned like video
    without damaging a transcript, so the oldest chunks are dropped only once more than
    ``max_bytes`` wait, and the next chunk delivered says how many went missing."""

    def __init__(self, max_bytes: int) -> None:
        self._max = max_bytes
        self._items: deque[AudioChunk] = deque()
        self._bytes = 0
        self._lost = 0
        self._event = asyncio.Event()
        self._closed = False
        self.dropped = 0
        self.processed = 0

    def put(self, chunk: AudioChunk) -> bool:
        """Queue ``chunk``; ``True`` when older chunks were dropped to make room."""
        self._items.append(chunk)
        self._bytes += chunk.size
        shed = False
        while self._bytes > self._max and len(self._items) > 1:
            self._bytes -= self._items.popleft().size
            self.dropped += 1
            self._lost += 1
            shed = True
        self._event.set()
        return shed

    def close(self) -> None:
        self._closed = True
        self._event.set()

    async def get(self) -> AudioChunk | None:
        """The oldest waiting chunk, or ``None`` once closed and empty."""
        while True:
            if self._items:
                chunk = self._items.popleft()
                self._bytes -= chunk.size
                self.processed += 1
                lost, self._lost = self._lost, 0
                return replace(chunk, dropped_before=lost) if lost else chunk
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

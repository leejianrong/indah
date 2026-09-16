"""Unit tests for the SSE framing generator, with no HTTP or server involved."""

import asyncio
import json

import pytest

from indah.app import _SSE_FLUSH_PAD, _SSE_PADDING_BYTES, sse_events


def _is_pad(chunk: str) -> bool:
    """A flush pad: an SSE comment line (ignored by EventSource), no data."""
    return chunk.startswith(":") and "data:" not in chunk


async def _drain(gen, timeout: float = 0.2) -> list[str]:
    """Every chunk the generator yields until it next blocks (queue empty)."""
    out: list[str] = []
    try:
        while True:
            out.append(await asyncio.wait_for(gen.__anext__(), timeout))
    except (asyncio.TimeoutError, TimeoutError):
        pass
    return out


def _patch(offset: int, text: str) -> tuple[int, dict]:
    return (
        offset,
        {"v": 1, "type": "patch", "changes": [{"target": "n1", "append": {"text": text}}]},
    )


def _parse(chunk: str) -> tuple[int | None, dict]:
    """Return (event_id, data) from an SSE chunk; event_id is None if no id line."""
    event_id = None
    line, _, rest = chunk.partition("\n")
    if line.startswith("id: "):
        event_id = int(line[len("id: ") :])
        line, _, rest = rest.partition("\n")
    assert line.startswith("data: ")
    assert chunk.endswith("\n\n")
    return event_id, json.loads(line[len("data: ") :].strip())


def _init_payload() -> dict:
    return {
        "v": 1,
        "type": "init",
        "root": {"id": "n0", "type": "column", "props": {}, "children": []},
    }


@pytest.mark.unit
async def test_first_chunk_is_the_init_payload_with_no_id():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60)
    event_id, data = _parse(await gen.__anext__())
    assert event_id is None  # init is not a resume point
    assert data == _init_payload()
    await gen.aclose()


@pytest.mark.unit
async def test_proxy_flush_pads_the_stream_open_and_after_the_init_frame():
    """With proxy_flush, the stream opens with a full-window SSE comment pad and the
    init frame is flushed by padding out to the next window boundary, so a
    window-buffering proxy (Colab) releases it immediately. Pads are ignored by
    EventSource."""
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60, proxy_flush=True)

    lead = await gen.__anext__()  # opens the stream even before any data
    assert lead is _SSE_FLUSH_PAD
    assert lead.startswith(":")  # an SSE comment line -> ignored by the client
    assert "data:" not in lead  # carries no protocol payload
    assert len(lead) == _SSE_PADDING_BYTES  # exactly one window, so it aligns cleanly
    assert lead.endswith("\n\n")

    init_chunk = await gen.__anext__()  # the real init frame
    event_id, data = _parse(init_chunk)
    assert event_id is None
    assert data == _init_payload()

    pad = await gen.__anext__()  # boundary pad after the init flushes it
    assert _is_pad(pad)
    # init + pad lands on a window boundary; the pad is only the tail, < a full window.
    assert (len(init_chunk) + len(pad)) % _SSE_PADDING_BYTES == 0
    assert len(pad) < _SSE_PADDING_BYTES
    await gen.aclose()


@pytest.mark.unit
async def test_proxy_flush_coalesces_a_burst_into_one_pad():
    """A run of frames already waiting on the queue (streamed tokens / chart points)
    is drained and emitted back to back, then flushed with a *single* pad -- not one
    ~8 KB window per frame. This is the KAN-1395 win: the per-token pad no longer
    scales with the token rate."""
    queue: asyncio.Queue = asyncio.Queue()
    for i in range(1, 6):
        queue.put_nowait(_patch(i, "x"))

    gen = sse_events(queue, None, heartbeat_seconds=60, proxy_flush=True)
    chunks = await _drain(gen)
    await gen.aclose()

    data_frames = [c for c in chunks if "data:" in c]
    pads = [c for c in chunks if _is_pad(c)]
    assert len(data_frames) == 5  # all five delivered
    # One lead-in pad opens the stream; the five-frame burst shares one trailing pad.
    # The old per-frame padding would have produced six pads here.
    assert len(pads) == 2


@pytest.mark.unit
async def test_proxy_flush_pads_only_up_to_the_window_boundary():
    """A frame larger than one window is flushed by padding out only its tail to the
    next window boundary, not by appending a whole fresh window every time."""
    queue: asyncio.Queue = asyncio.Queue()
    big = {"v": 1, "type": "patch", "changes": [{"target": "n1", "props": {"text": "z" * 10000}}]}
    queue.put_nowait((1, big))

    gen = sse_events(queue, None, heartbeat_seconds=60, proxy_flush=True)
    chunks = await _drain(gen)
    await gen.aclose()

    frame = next(c for c in chunks if "data:" in c)
    trailing = chunks[chunks.index(frame) + 1]
    assert _is_pad(trailing)
    # frame + pad lands on a window boundary, so the pad is < a full window.
    assert (len(frame) + len(trailing)) % _SSE_PADDING_BYTES == 0
    assert len(trailing) < _SSE_PADDING_BYTES


@pytest.mark.unit
async def test_queued_message_is_forwarded_with_its_offset_as_id():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60)
    await gen.__anext__()  # init

    patch = {"v": 1, "type": "patch", "changes": [{"target": "n3", "props": {"text": "11"}}]}
    await queue.put((7, patch))
    event_id, data = _parse(await gen.__anext__())
    assert event_id == 7  # the SSE id lets a reconnecting client resume from here
    assert data == patch
    await gen.aclose()


@pytest.mark.unit
async def test_heartbeat_emitted_when_idle():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=0.05)
    await gen.__anext__()  # init

    event_id, data = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.0))
    assert event_id is None  # a ping carries no id
    assert data == {"v": 1, "type": "ping"}
    await gen.aclose()


@pytest.mark.unit
async def test_replay_messages_precede_live_and_carry_ids():
    queue: asyncio.Queue = asyncio.Queue()
    replay = [
        (3, {"v": 1, "type": "patch", "changes": [{"target": "n1", "append": {"text": "a"}}]})
    ]
    # No init on a clean resume; replay comes first, then live queue messages.
    gen = sse_events(queue, None, heartbeat_seconds=60, replay=replay, skip_upto=3)
    event_id, data = _parse(await gen.__anext__())
    assert event_id == 3
    assert data == replay[0][1]
    await gen.aclose()


@pytest.mark.unit
async def test_queued_message_at_or_below_skip_upto_is_dropped():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, None, heartbeat_seconds=60, skip_upto=5)
    # Offset 5 is already covered by init/replay -> must not be re-applied (dup append).
    await queue.put(
        (5, {"v": 1, "type": "patch", "changes": [{"target": "n1", "append": {"text": "x"}}]})
    )
    await queue.put(
        (6, {"v": 1, "type": "patch", "changes": [{"target": "n1", "append": {"text": "y"}}]})
    )
    event_id, data = _parse(await gen.__anext__())
    assert event_id == 6  # 5 was skipped, 6 forwarded
    assert data["changes"][0]["append"] == {"text": "y"}
    await gen.aclose()

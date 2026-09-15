"""Unit tests for the SSE framing generator, with no HTTP or server involved."""

import asyncio
import json

import pytest

from indah.app import _SSE_FLUSH_PAD, sse_events


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
async def test_proxy_flush_pads_the_stream_open_and_after_each_frame():
    """With proxy_flush, the stream opens with a large SSE comment pad AND repeats
    one after every real frame, so a window-buffering proxy (Colab) flushes each
    frame immediately instead of holding it. The pad is ignored by EventSource."""
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60, proxy_flush=True)

    lead = await gen.__anext__()  # opens the stream even before any data
    assert lead is _SSE_FLUSH_PAD
    assert lead.startswith(":")  # an SSE comment line -> ignored by the client
    assert "data:" not in lead  # carries no protocol payload
    assert len(lead) >= 8192  # big enough to fill a proxy's buffer window
    assert lead.endswith("\n\n")

    event_id, data = _parse(await gen.__anext__())  # the real init frame
    assert event_id is None
    assert data == _init_payload()

    assert await gen.__anext__() is _SSE_FLUSH_PAD  # pad after the init flushes it
    await gen.aclose()


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

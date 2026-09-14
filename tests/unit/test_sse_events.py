"""Unit tests for the SSE framing generator, with no HTTP or server involved."""

import asyncio
import json

import pytest

from indah.app import sse_events


def _parse(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: ") :].strip())


@pytest.mark.unit
async def test_first_chunk_is_init_snapshot():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, {"counter": "0"}, heartbeat_seconds=60)
    first = _parse(await gen.__anext__())
    assert first == {"v": 0, "type": "init", "nodes": {"counter": "0"}}
    await gen.aclose()


@pytest.mark.unit
async def test_queued_message_is_forwarded_after_init():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, {"counter": "0"}, heartbeat_seconds=60)
    await gen.__anext__()  # init

    await queue.put({"v": 0, "type": "patch", "target": "counter", "value": "1"})
    second = _parse(await gen.__anext__())
    assert second == {"v": 0, "type": "patch", "target": "counter", "value": "1"}
    await gen.aclose()


@pytest.mark.unit
async def test_heartbeat_emitted_when_idle():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, {"counter": "0"}, heartbeat_seconds=0.05)
    await gen.__anext__()  # init

    ping = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.0))
    assert ping == {"v": 0, "type": "ping"}
    await gen.aclose()

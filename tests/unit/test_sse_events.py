"""Unit tests for the SSE framing generator, with no HTTP or server involved."""

import asyncio
import json

import pytest

from indah.app import sse_events


def _parse(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    return json.loads(chunk[len("data: ") :].strip())


def _init_payload() -> dict:
    return {
        "v": 0,
        "type": "init",
        "root": {"id": "n0", "type": "column", "props": {}, "children": []},
    }


@pytest.mark.unit
async def test_first_chunk_is_the_init_payload():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60)
    first = _parse(await gen.__anext__())
    assert first == _init_payload()
    await gen.aclose()


@pytest.mark.unit
async def test_queued_message_is_forwarded_after_init():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=60)
    await gen.__anext__()  # init

    patch = {"v": 0, "type": "patch", "changes": [{"target": "n3", "props": {"text": "11"}}]}
    await queue.put(patch)
    second = _parse(await gen.__anext__())
    assert second == patch
    await gen.aclose()


@pytest.mark.unit
async def test_heartbeat_emitted_when_idle():
    queue: asyncio.Queue = asyncio.Queue()
    gen = sse_events(queue, _init_payload(), heartbeat_seconds=0.05)
    await gen.__anext__()  # init

    ping = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.0))
    assert ping == {"v": 0, "type": "ping"}
    await gen.aclose()

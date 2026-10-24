"""Drain: the process stops taking new tabs and tells open ones to reconnect (IND-201)."""

import asyncio
import json

import pytest

from indah.app import sse_events
from indah.drain import Drain


def _data(chunk: str) -> dict:
    return json.loads(next(line for line in chunk.split("\n") if line.startswith("data:"))[5:])


async def _frames(gen, timeout: float = 0.3) -> list[str]:
    out: list[str] = []
    try:
        while True:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout)
            if "data:" in chunk:
                out.append(chunk)
    except (asyncio.TimeoutError, TimeoutError, StopAsyncIteration):
        pass
    return out


@pytest.mark.unit
def test_a_fresh_drain_is_not_draining_and_has_no_streams():
    drain = Drain(seconds=10)
    assert drain.draining is False
    assert drain.open_streams == 0
    assert drain.seconds == 10


@pytest.mark.unit
def test_begin_marks_draining_and_sends_each_open_stream_a_reconnect():
    drain = Drain(seconds=10)
    queues = [asyncio.Queue(), asyncio.Queue()]
    for q in queues:
        drain.register(q)
    assert drain.open_streams == 2

    drain.begin()

    assert drain.draining is True
    for q in queues:
        offset, message = q.get_nowait()
        assert message["type"] == "reconnect"
        assert message["v"] == 1
        # spread over the first half of the drain period, never zero (see Drain.begin)
        assert 100 <= message["after_ms"] <= 5000
        assert offset == -1  # not a hub offset: it must never be skipped as already seen


@pytest.mark.unit
def test_begin_twice_sends_one_reconnect():
    drain = Drain(seconds=10)
    q = asyncio.Queue()
    drain.register(q)
    drain.begin()
    drain.begin()
    assert q.qsize() == 1


@pytest.mark.unit
def test_unregister_lowers_the_open_count_and_a_late_stream_is_not_registered_twice():
    drain = Drain(seconds=1)
    q = asyncio.Queue()
    drain.register(q)
    drain.register(q)
    assert drain.open_streams == 1
    drain.unregister(q)
    drain.unregister(q)
    assert drain.open_streams == 0


@pytest.mark.unit
async def test_wait_returns_at_once_with_no_streams():
    drain = Drain(seconds=30)
    drain.begin()
    await asyncio.wait_for(drain.wait(), 1)


@pytest.mark.unit
async def test_wait_returns_when_the_last_stream_goes_away():
    drain = Drain(seconds=30)
    q = asyncio.Queue()
    drain.register(q)
    drain.begin()
    waiter = asyncio.create_task(drain.wait())
    await asyncio.sleep(0.05)
    assert not waiter.done()
    drain.unregister(q)
    await asyncio.wait_for(waiter, 1)


@pytest.mark.unit
async def test_wait_gives_up_at_the_deadline_and_ends_the_streams_still_open():
    drain = Drain(seconds=0.2)
    q = asyncio.Queue()
    drain.register(q)
    drain.begin()
    q.get_nowait()  # the reconnect
    await asyncio.wait_for(drain.wait(), 2)
    offset, message = q.get_nowait()
    assert message["type"] == "drain_end"


@pytest.mark.unit
async def test_sse_events_sends_reconnect_without_an_id_and_ends_on_drain_end():
    queue: asyncio.Queue = asyncio.Queue()
    # skip_upto above every offset: an ordinary message would be dropped as already seen
    gen = sse_events(queue, None, 60, skip_upto=10**9)
    queue.put_nowait((-1, {"v": 1, "type": "reconnect", "after_ms": 250}))
    frames = await _frames(gen)
    assert [_data(f)["type"] for f in frames] == ["reconnect"]
    assert _data(frames[0])["after_ms"] == 250
    assert "id:" not in frames[0]  # a reconnect is not state: nothing to resume from

    queue.put_nowait((-1, {"v": 1, "type": "drain_end"}))
    with pytest.raises(StopAsyncIteration):
        while True:
            chunk = await asyncio.wait_for(gen.__anext__(), 1)
            assert "drain_end" not in chunk  # the end marker is never sent to the browser

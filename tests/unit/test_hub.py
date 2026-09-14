import asyncio

import pytest

from indah.transport import Hub


@pytest.mark.unit
async def test_broadcast_reaches_all_subscribers():
    hub = Hub()
    a = hub.subscribe()
    b = hub.subscribe()

    offset = await hub.broadcast({"hello": "world"})

    # Queue items are (offset, message) tuples so the stream can emit an SSE id.
    assert a.get_nowait() == (offset, {"hello": "world"})
    assert b.get_nowait() == (offset, {"hello": "world"})


@pytest.mark.unit
async def test_unsubscribe_stops_delivery():
    hub = Hub()
    q = hub.subscribe()
    hub.unsubscribe(q)

    await hub.broadcast({"x": 1})

    assert hub.subscriber_count == 0
    assert q.empty()


@pytest.mark.unit
async def test_full_queue_subscriber_is_dropped_not_blocking():
    hub = Hub(queue_maxsize=1)
    q = hub.subscribe()

    await hub.broadcast({"n": 1})  # fills the queue
    # Second broadcast would block a naive impl; instead the stalled client is dropped.
    await asyncio.wait_for(hub.broadcast({"n": 2}), timeout=1.0)

    assert hub.subscriber_count == 0
    assert q.get_nowait() == (1, {"n": 1})


@pytest.mark.unit
def test_publish_assigns_increasing_offsets():
    hub = Hub()
    assert hub.current_offset == 0
    assert hub.publish({"a": 1}) == 1
    assert hub.publish({"a": 2}) == 2
    assert hub.current_offset == 2

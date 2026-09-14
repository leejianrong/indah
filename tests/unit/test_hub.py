import asyncio

import pytest

from indah.transport import Hub


@pytest.mark.unit
async def test_broadcast_reaches_all_subscribers():
    hub = Hub()
    a = hub.subscribe()
    b = hub.subscribe()

    await hub.broadcast({"hello": "world"})

    assert a.get_nowait() == {"hello": "world"}
    assert b.get_nowait() == {"hello": "world"}


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
    assert q.get_nowait() == {"n": 1}

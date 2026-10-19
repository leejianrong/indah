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


@pytest.mark.unit
def test_each_hub_has_its_own_epoch():
    assert isinstance(Hub().epoch, str) and Hub().epoch
    assert Hub().epoch != Hub().epoch


@pytest.mark.unit
def test_replay_from_another_epoch_forces_a_snapshot():
    # A restarted server builds a fresh hub (offset 0). A client that last saw offset
    # 500 on the *old* hub must not be told it is "already current" (IND-85).
    hub = Hub()
    assert hub.replay_since(500, epoch="some-old-epoch") is None
    assert hub.replay_since(500, epoch=hub.epoch) == []  # same hub: genuinely current


@pytest.mark.unit
def test_replay_without_an_epoch_keeps_the_legacy_integer_behaviour():
    hub = Hub()
    hub.publish({"n": 1})
    hub.publish({"n": 2})
    assert hub.replay_since(1) == [(2, {"n": 2})]
    assert hub.replay_since(2) == []

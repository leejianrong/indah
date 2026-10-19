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


# -- append coalescing (IND-90) -------------------------------------------------


def _changes(item):
    return item[1]["changes"]


@pytest.mark.unit
async def test_queued_appends_to_one_target_merge_into_a_single_patch():
    hub = Hub(coalesce_seconds=0.02)
    q = hub.subscribe()
    hub.queue_append("n1", "items", [1, 2], trim=10)
    hub.queue_append("n1", "items", [3], trim=10)
    assert q.empty()  # held back until the window closes
    await asyncio.sleep(0.06)
    (item,) = [q.get_nowait()]
    assert q.empty()
    assert _changes(item) == [
        {"target": "n1", "append": {"items": [1, 2, 3]}, "trim": {"items": 10}}
    ]


@pytest.mark.unit
async def test_different_targets_and_props_share_one_patch_message():
    hub = Hub(coalesce_seconds=0.02)
    q = hub.subscribe()
    hub.queue_append("n1", "items", ["a"], trim=5)
    hub.queue_append("n2", "rows", ["b"], trim=7)
    await asyncio.sleep(0.06)
    item = q.get_nowait()
    assert q.empty()
    assert {c["target"] for c in _changes(item)} == {"n1", "n2"}


@pytest.mark.unit
async def test_any_other_publish_flushes_pending_appends_first_to_keep_order():
    hub = Hub(coalesce_seconds=10)  # would never flush on its own in this test
    q = hub.subscribe()
    hub.queue_append("n1", "items", [1], trim=5)
    hub.publish({"v": 1, "type": "patch", "changes": [{"target": "n9", "props": {"x": 1}}]})
    first, second = q.get_nowait(), q.get_nowait()
    assert _changes(first)[0]["append"] == {"items": [1]}
    assert _changes(second)[0]["target"] == "n9"
    assert first[0] < second[0]


@pytest.mark.unit
def test_without_a_running_loop_appends_publish_immediately():
    hub = Hub()
    hub.queue_append("n1", "items", [1], trim=5)
    assert hub.current_offset == 1


@pytest.mark.unit
async def test_explicit_flush_publishes_pending_now():
    hub = Hub(coalesce_seconds=10)
    hub.queue_append("n1", "items", [1], trim=5)
    assert hub.current_offset == 0
    hub.flush()
    assert hub.current_offset == 1
    hub.flush()  # nothing pending: no empty patch
    assert hub.current_offset == 1


@pytest.mark.unit
async def test_a_burst_at_40_events_per_second_makes_about_ten_frames_per_second():
    hub = Hub()  # default window
    for i in range(40):
        hub.queue_append("n1", "items", [i], trim=100)
        await asyncio.sleep(0.025)
    hub.flush()
    assert 8 <= hub.current_offset <= 12
    rows = [r for _, m in hub.history() for c in m["changes"] for r in c["append"]["items"]]
    assert rows == list(range(40))

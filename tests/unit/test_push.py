"""``Topic``: an app-level channel any task can publish to and any session subscribe to
(IND-89, ADR-0026)."""

import asyncio
import threading

import pytest

from indah.components import Column, Text
from indah.context import Context
from indah.push import Topic
from indah.session import Session
from indah.session_store import InMemorySessionStore


@pytest.mark.unit
def test_publish_delivers_to_every_subscriber_in_order():
    t: Topic[int] = Topic("x")
    a, b = [], []
    t.subscribe(a.append)
    t.subscribe(b.append)
    for i in range(3):
        t.publish(i)
    assert a == b == [0, 1, 2]


@pytest.mark.unit
def test_replay_keeps_only_the_newest_items():
    t: Topic[int] = Topic("x", replay=3)
    for i in range(5):
        t.publish(i)
    assert t.recent() == [2, 3, 4]
    assert t.recent(2) == [3, 4]
    assert Topic("none").recent() == []  # replay=0 keeps nothing


@pytest.mark.unit
def test_unsubscribe_stops_delivery_and_updates_the_count():
    t: Topic[int] = Topic("x")
    got = []
    off = t.subscribe(got.append)
    assert t.subscriber_count == 1
    off()
    off()  # idempotent
    t.publish(1)
    assert got == [] and t.subscriber_count == 0


@pytest.mark.unit
def test_a_raising_subscriber_does_not_stop_the_others(caplog):
    t: Topic[int] = Topic("x")
    got = []

    def boom(_):
        raise RuntimeError("nope")

    t.subscribe(boom)
    t.subscribe(got.append)
    with caplog.at_level("ERROR", logger="indah"):
        t.publish(1)
    assert got == [1] and "subscriber" in caplog.text


@pytest.mark.unit
def test_a_subscriber_may_unsubscribe_while_being_called():
    t: Topic[int] = Topic("x")
    got = []
    offs = []
    offs.append(t.subscribe(lambda v: (got.append(v), offs[0]())))
    t.publish(1)
    t.publish(2)
    assert got == [1]


@pytest.mark.unit
async def test_publish_threadsafe_delivers_in_order_on_the_event_loop():
    t: Topic[int] = Topic("x", replay=10)
    loop_thread = threading.get_ident()
    seen: list[tuple[int, int]] = []
    t.subscribe(lambda v: seen.append((v, threading.get_ident())))  # binds the loop

    def worker():
        for i in range(5):
            t.publish_threadsafe(i)

    th = threading.Thread(target=worker)
    th.start()
    th.join()
    await asyncio.sleep(0.05)
    assert [v for v, _ in seen] == [0, 1, 2, 3, 4]
    assert {tid for _, tid in seen} == {loop_thread}


@pytest.mark.unit
def test_publish_threadsafe_with_no_subscribers_still_records_history():
    t: Topic[int] = Topic("x", replay=2)
    t.publish_threadsafe(1)
    t.publish_threadsafe(2)
    assert t.recent() == [1, 2]


# -- the Context side: ctx.latest / ctx.tail ----------------------------------------


@pytest.mark.unit
def test_latest_holds_the_last_item_and_follows_publishes():
    t: Topic[str] = Topic("x", replay=5)
    t.publish("old")
    ctx = Context("s")
    sig = ctx.latest(t)
    assert sig.value == "old"
    t.publish("new")
    assert sig.value == "new"
    assert ctx.latest(Topic("empty")).value is None
    assert ctx.latest(Topic("empty"), initial="dflt").value == "dflt"


@pytest.mark.unit
def test_tail_is_seeded_from_recent_bounded_and_follows_publishes():
    t: Topic[int] = Topic("x", replay=10)
    for i in range(6):
        t.publish(i)
    ctx = Context("s")
    rows = ctx.tail(t, limit=4)
    assert rows.value == [2, 3, 4, 5]
    t.publish(6)
    assert rows.value == [3, 4, 5, 6]


@pytest.mark.unit
def test_closing_the_context_unsubscribes():
    t: Topic[int] = Topic("x")
    ctx = Context("s")
    ctx.latest(t)
    ctx.tail(t)
    assert t.subscriber_count == 2
    ctx.close()
    assert t.subscriber_count == 0


@pytest.mark.unit
def test_store_eviction_releases_subscriptions():
    t: Topic[int] = Topic("x")

    def factory(ctx: Context) -> Session:
        ctx.tail(t)
        return Session(Column(children=[Text("x")]))

    store = InMemorySessionStore(factory, max_sessions=1)
    store.get_or_create("a")
    store.get_or_create("b")  # evicts a
    assert t.subscriber_count == 1
    store.discard("b")
    assert t.subscriber_count == 0

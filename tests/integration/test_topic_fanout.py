"""A ``Topic`` fanned out to many sessions through the app (IND-89, ADR-0026)."""

import asyncio

import httpx
import pytest

from indah.app import create_app
from indah.components import Button, Column, List, Text
from indah.context import Context
from indah.push import Topic
from indah.reactive import Signal
from indah.session import Session


def _app(topic: Topic, **kwargs):
    def factory(ctx: Context) -> Session:
        rows = ctx.tail(topic, limit=50)
        newest = ctx.latest(topic)
        picked = Signal(0)  # per-tab UI state: must NOT be shared
        root = Column(
            children=[
                List(rows, item={"tag": "span", "text": "t"}),
                Text(lambda: f"newest={newest.value and newest.value['t']}"),
                Button("pick", on_click=lambda: picked.set(picked.value + 1)),
                Text(lambda: f"picked={picked.value}"),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory, **kwargs)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _appended(hub):
    return [
        row
        for _, m in hub.history()
        for c in m["changes"]
        if "append" in c
        for row in c["append"]["items"]
    ]


@pytest.mark.integration
async def test_a_publish_reaches_every_session_and_only_per_tab_state_stays_separate():
    topic: Topic[dict] = Topic("log", replay=10)
    app = _app(topic)
    store = app.state.store
    a, b = store.get_or_create("a"), store.get_or_create("b")
    for h in (a, b):
        h.hub._coalesce = 0.02

    async with _client(app) as c:
        await c.post("/api/event", json={"sid": "a", "component": "n3", "event": "click"})

    topic.publish({"t": "one"})
    topic.publish({"t": "two"})
    await asyncio.sleep(0.08)

    assert _appended(a.hub) == _appended(b.hub) == [{"t": "one"}, {"t": "two"}]
    snap = lambda h: h.session.snapshot()["children"]  # noqa: E731
    assert snap(a)[1]["props"]["text"] == snap(b)[1]["props"]["text"] == "newest=two"
    assert snap(a)[3]["props"]["text"] == "picked=1"  # a clicked ...
    assert snap(b)[3]["props"]["text"] == "picked=0"  # ... b did not


@pytest.mark.integration
async def test_a_late_session_is_seeded_from_the_topics_recent_history():
    topic: Topic[dict] = Topic("log", replay=3)
    for i in range(5):
        topic.publish({"t": f"r{i}"})
    app = _app(topic)
    late = app.state.store.get_or_create("late")
    items = late.session.snapshot()["children"][0]["props"]["items"]
    assert items == [{"t": "r2"}, {"t": "r3"}, {"t": "r4"}]


@pytest.mark.integration
async def test_evicting_sessions_releases_their_topic_subscriptions():
    topic: Topic[dict] = Topic("log")
    app = _app(
        topic,
    )
    store = app.state.store
    store.max_sessions = 2
    for sid in ("a", "b", "c", "d"):
        store.get_or_create(sid)
    assert len(store) == 2
    assert topic.subscriber_count == 4  # two live sessions x (tail + latest)
    for sid in ("c", "d"):
        store.discard(sid)
    assert topic.subscriber_count == 0

"""Shared rate limits and stream caps across replicas (IND-213, ADR-0043).

Two apps stand for two replicas; they share one in-process fake Redis. Needs ``fakeredis`` and
``lupa`` (the bucket is a Lua script), so it is skipped where they are not installed.
"""

import asyncio
import logging

import httpx
import pytest

fakeredis = pytest.importorskip("fakeredis")
pytest.importorskip("lupa")

from indah import Limits, Rate, create_app  # noqa: E402
from indah.components import Button, Column  # noqa: E402
from indah.session import Session  # noqa: E402
from indah.shared_limits import SharedLimits  # noqa: E402

pytestmark = pytest.mark.integration


def _build():
    return Session(Column(children=[Button("go", on_click=lambda: None)]))


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


def _event(sid="t"):
    return {"sid": sid, "component": "n1", "event": "click"}


def _shared(server, **kw):
    return SharedLimits(client=fakeredis.FakeAsyncRedis(server=server), **kw)


def _replica(server, **limits):
    return create_app(
        session_factory=_build,
        limits=Limits(rate={"/api/event": Rate(per_second=0.001, burst=3)}, **limits),
        limits_shared=_shared(server),
    )


async def _codes(asgi, n):
    async with _client(asgi) as client:
        return [(await client.post("/api/event", json=_event())).status_code for _ in range(n)]


async def test_two_replicas_share_one_budget():
    server = fakeredis.FakeServer()
    one, two = _replica(server), _replica(server)
    first = await _codes(one, 2)
    second = await _codes(two, 3)
    # burst 3 in all: two on the first replica, then one more on the second, then 429
    assert first == [200, 200]
    assert second == [200, 429, 429]


async def test_without_sharing_each_replica_has_its_own_budget():
    mk = lambda: create_app(  # noqa: E731
        session_factory=_build, limits=Limits(rate={"/api/event": Rate(0.001, 3)})
    )
    assert await _codes(mk(), 3) == [200, 200, 200]
    assert await _codes(mk(), 3) == [200, 200, 200]


async def test_a_429_carries_retry_after_from_the_shared_bucket():
    server = fakeredis.FakeServer()
    app = _replica(server)
    async with _client(app) as client:
        for _ in range(3):
            await client.post("/api/event", json=_event())
        refused = await client.post("/api/event", json=_event())
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1


async def test_redis_down_falls_back_to_the_local_bucket_and_warns_once(caplog):
    class Broken:
        async def eval(self, *a, **k):
            raise ConnectionError("boom")

    shared = SharedLimits(client=Broken(), cooldown=60)
    app = create_app(
        session_factory=_build,
        limits=Limits(rate={"/api/event": Rate(per_second=0.001, burst=3)}),
        limits_shared=shared,
    )
    with caplog.at_level(logging.WARNING, logger="indah"):
        codes = await _codes(app, 5)
    assert codes == [200, 200, 200, 429, 429]  # the local limit still holds
    assert shared.failures == 1  # the cooldown stopped it asking again for every request
    assert sum("shared limits" in r.message for r in caplog.records) == 1


async def test_a_slow_redis_costs_one_timeout_not_one_per_request():
    class Slow:
        calls = 0

        async def eval(self, *a, **k):
            Slow.calls += 1
            await asyncio.sleep(5)

    shared = SharedLimits(client=Slow(), timeout=0.05, cooldown=60)
    assert await shared.take("k", 1.0, 3) is None
    assert await shared.take("k", 1.0, 3) is None
    assert Slow.calls == 1
    assert shared.available() is False


async def test_the_stream_cap_is_shared_and_a_slot_comes_back():
    server = fakeredis.FakeServer()
    one, two = _shared(server), _shared(server)
    from indah.hardening import StreamLimiter

    a, b = StreamLimiter(2, one), StreamLimiter(2, two)
    ok1, m1 = await a.open("1.2.3.4")
    ok2, m2 = await b.open("1.2.3.4")
    ok3, _ = await a.open("1.2.3.4")  # the third, on either replica, is refused
    assert (ok1, ok2, ok3) == (True, True, False)
    assert a.count("1.2.3.4") == 1  # the refused one left no local slot behind
    a.close("1.2.3.4", m1)
    await asyncio.sleep(0.05)
    assert (await b.open("1.2.3.4"))[0] is True
    assert m2 is not None


async def test_a_dead_replicas_stream_slots_expire():
    server = fakeredis.FakeServer()
    dead = _shared(server, stream_ttl=0.2)
    assert await dead.acquire("9.9.9.9", 1) is not False
    dead._renewer.cancel()  # the process is gone: nothing renews
    other = _shared(server)
    assert await other.acquire("9.9.9.9", 1) is False  # still held
    await asyncio.sleep(0.3)
    assert await other.acquire("9.9.9.9", 1) not in (False, None)


async def test_a_live_stream_keeps_its_slot_past_the_ttl():
    server = fakeredis.FakeServer()
    holder = _shared(server, stream_ttl=0.3)
    assert await holder.acquire("8.8.8.8", 1) not in (False, None)
    await asyncio.sleep(0.7)  # more than two ttls: the renewer has refreshed it
    assert await _shared(server).acquire("8.8.8.8", 1) is False
    await holder.close()


async def test_the_environment_turns_it_on(monkeypatch):
    monkeypatch.setenv("INDAH_LIMITS_SHARED", "redis")
    monkeypatch.setenv("INDAH_REDIS_URL", "redis://localhost:1/0")
    app = create_app(session_factory=_build, limits=Limits.public())
    assert isinstance(app.state.shared_limits, SharedLimits)
    monkeypatch.delenv("INDAH_REDIS_URL")
    with pytest.raises(ValueError, match="INDAH_REDIS_URL"):
        create_app(session_factory=_build, limits=Limits.public())
    monkeypatch.setenv("INDAH_LIMITS_SHARED", "memcached")
    with pytest.raises(ValueError, match="INDAH_LIMITS_SHARED"):
        create_app(session_factory=_build)


async def test_default_is_per_process():
    app = create_app(session_factory=_build, limits=Limits.public())
    assert app.state.shared_limits is None


async def test_the_doctor_page_says_how_shared_limits_are_doing():
    from indah.doctor import _shared_limits_facts, _shared_text

    assert _shared_text(None) == "off (per process)"
    shared = _shared(fakeredis.FakeServer())
    assert _shared_text(_shared_limits_facts(shared)).startswith("redis: ok")
    shared._failed(ConnectionError("x"))
    assert "unavailable" in _shared_text(_shared_limits_facts(shared))

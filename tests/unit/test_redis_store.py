"""The Redis store beyond the shared contract (IND-210): what the contract cannot say."""

import asyncio
import builtins
import logging

import pytest

fakeredis = pytest.importorskip("fakeredis")

from indah.redis_store import RedisStateStore, _escape_glob  # noqa: E402
from indah.state import state_store_from_spec  # noqa: E402

pytestmark = pytest.mark.unit


def make(**kw):
    return RedisStateStore(client=fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer()), **kw)


async def test_a_prefix_with_redis_glob_characters_matches_literally():
    store = make()
    for key in ("a*b", "axb", "a[1]", "a1", "a?b", "a\\b"):
        await store.set(key, b"x", None)
    for prefix in ("a*", "a[", "a?", "a\\"):
        await store.delete_prefix(prefix)
    assert await store.get("axb") == b"x"
    assert await store.get("a1") == b"x"
    for key in ("a*b", "a[1]", "a?b", "a\\b"):
        assert await store.get(key) is None
    assert _escape_glob("a*[b]\\") == "a\\*\\[b\\]\\\\"


async def test_delete_prefix_handles_more_keys_than_one_scan_batch():
    store = make()
    for n in range(1200):
        await store.set(f"u:t:{n}", b"x", None)
    await store.set("u:other", b"x", None)
    await store.delete_prefix("u:t:")
    assert await store.get("u:t:7") is None
    assert await store.get("u:other") == b"x"


async def test_the_key_prefix_keeps_two_apps_on_one_redis_apart():
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer())
    one, two = (
        RedisStateStore(client=client, key_prefix="one:"),
        RedisStateStore(client=client, key_prefix="two:"),
    )
    await one.set("k", b"1", None)
    await two.set("k", b"2", None)
    await one.delete_prefix("")
    assert await one.get("k") is None
    assert await two.get("k") == b"2"
    assert await client.get("two:k") == b"2"


async def test_health_is_true_when_redis_answers_and_false_when_it_does_not():
    store = make()
    assert await store.health() is True

    class Down:
        async def ping(self):
            raise ConnectionError("down")

    assert await RedisStateStore(client=Down()).health() is False


async def test_a_client_you_pass_in_is_left_open():
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer())
    await RedisStateStore(client=client).close()
    assert await client.ping()


async def test_a_store_made_from_a_url_closes_its_own_client():
    store = RedisStateStore("redis://localhost:6399/0")
    await store.close()


def test_a_url_or_a_client_is_needed_but_not_both():
    with pytest.raises(ValueError):
        RedisStateStore()
    with pytest.raises(ValueError):
        RedisStateStore("redis://x", client=object())
    with pytest.raises(ValueError, match="timeout"):
        RedisStateStore("redis://x", timeout=0)


def test_the_repr_never_shows_the_password():
    store = RedisStateStore("redis://user:hunter2@localhost:6399/0")
    assert "hunter2" not in repr(store)


def test_a_missing_redis_package_says_how_to_install_it(monkeypatch):
    real = builtins.__import__

    def refuse(name, *args, **kw):
        if name == "redis" or name.startswith("redis."):
            raise ImportError("no redis")
        return real(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ImportError, match=r"indah\[redis\]"):
        state_store_from_spec("redis://localhost")


def test_rediss_urls_and_acl_users_are_accepted():
    store = state_store_from_spec("rediss://app:secret@cache.example.com:6380/1")
    pool = store._client.connection_pool
    assert pool.connection_kwargs["username"] == "app"
    assert pool.connection_kwargs["db"] == 1
    assert "SSL" in pool.connection_class.__name__.upper()


async def test_a_down_redis_degrades_ctx_persist_to_defaults(caplog, monkeypatch):
    """The ADR-0043 degraded mode: reads start from defaults, writes drop, one log line."""
    from indah import Signal, state
    from indah.state import _Persistence

    monkeypatch.setattr(state, "_warned", {})  # the log is rate limited per process

    class Broken:
        async def get(self, *a):
            raise ConnectionError("down")

        async def set(self, *a, **kw):
            raise ConnectionError("down")

        async def delete(self, *a):
            raise ConnectionError("down")

    store = RedisStateStore(client=Broken())

    class Ctx:
        user = None
        sid = "tab"

        def spawn(self, coro):
            return asyncio.get_running_loop().create_task(coro)

    persistence = _Persistence(
        ctx=Ctx(),
        store=store,
        namespace="indah",
        ttl=60,
        max_bytes=1024,
        session_bytes=4096,
        delay=0,
    )
    value = Signal("default")
    with caplog.at_level(logging.WARNING, logger="indah"):
        persistence.add("a", value, version=1, ttl=None, max_bytes=None, validate=None)
        persistence.ready = True
        value.set("changed")
        await asyncio.sleep(0.05)
    assert value.peek() == "changed"  # nothing blocked or raised
    assert any("state store" in r.message for r in caplog.records)

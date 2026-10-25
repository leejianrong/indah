"""The state store contract against a real Redis (IND-210). Opt-in: set INDAH_TEST_REDIS_URL
(CI runs a Redis service container; locally ``docker run --rm -p 6379:6379 redis:7``)."""

import asyncio
import os
import uuid

import pytest

from indah.redis_store import RedisStateStore

URL = os.environ.get("INDAH_TEST_REDIS_URL")
pytestmark = [
    pytest.mark.redis,
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="INDAH_TEST_REDIS_URL is not set"),
]


@pytest.fixture
async def store():
    s = RedisStateStore(URL, key_prefix=f"test-{uuid.uuid4().hex}:")
    yield s
    await s.delete_prefix("")
    await s.close()


async def test_set_get_delete_and_prefix(store):
    assert await store.get("a") is None
    await store.set("u1:t1:a", b"one", None)
    await store.set("u1:t1:b", b"two", None)
    await store.set("u1:t2:a", b"three", None)
    assert await store.get("u1:t1:a") == b"one"
    await store.delete_prefix("u1:t1:")
    assert await store.get("u1:t1:a") is None and await store.get("u1:t1:b") is None
    assert await store.get("u1:t2:a") == b"three"
    await store.delete("u1:t2:a")
    assert await store.get("u1:t2:a") is None


async def test_native_expiry_and_a_write_renews_it(store):
    await store.set("a", b"x", 0.4)
    await asyncio.sleep(0.2)
    await store.set("a", b"y", 0.4)  # renewed
    await asyncio.sleep(0.3)
    assert await store.get("a") == b"y"
    await asyncio.sleep(0.4)
    assert await store.get("a") is None
    await store.set("keep", b"x", None)
    await asyncio.sleep(0.3)
    assert await store.get("keep") == b"x"


async def test_a_value_survives_a_new_store_object(store):
    await store.set("k", b"kept", None)
    other = RedisStateStore(URL, key_prefix=store.key_prefix)
    try:
        assert await other.get("k") == b"kept"
    finally:
        await other.close()


class Proxy:
    """A TCP forwarder to Redis that can cut every open connection, as a failover or a proxy
    restart does."""

    def __init__(self, host, port):
        self.target = (host, port)
        self.writers = []
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _serve(self, reader, writer):
        up_r, up_w = await asyncio.open_connection(*self.target)
        self.writers += [writer, up_w]

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except Exception:
                pass
            finally:
                dst.close()

        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))

    def cut(self):
        for w in self.writers:
            w.close()
        self.writers = []

    async def stop(self):
        self.cut()
        self.server.close()
        await self.server.wait_closed()


async def test_the_store_reconnects_after_the_connection_is_cut():
    from urllib.parse import urlparse

    parts = urlparse(URL)
    proxy = Proxy(parts.hostname or "localhost", parts.port or 6379)
    port = await proxy.start()
    store = RedisStateStore(f"redis://127.0.0.1:{port}/{(parts.path or '/0')[1:] or 0}")
    key = f"reconnect-{uuid.uuid4().hex}"
    try:
        await store.set(key, b"before", 30)
        proxy.cut()
        await asyncio.sleep(0.05)
        assert await store.get(key) == b"before"  # a new connection, no error
        await store.delete(key)
    finally:
        await store.close()
        await proxy.stop()


async def test_an_unreachable_redis_fails_fast_and_reports_unhealthy():
    store = RedisStateStore("redis://127.0.0.1:1/0", timeout=0.3)
    try:
        assert await store.health() is False
        with pytest.raises(ConnectionError):  # redis.ConnectionError is one
            await asyncio.wait_for(store.get("k"), 3)
    finally:
        await store.close()

"""A Redis ``StateStore`` for ``ctx.persist`` (ADR-0043, IND-210; install ``indah[redis]``).

Redis is the way to share restorable state between replicas: a value written by one replica is
read by another after a rollout or a move. indah never runs or bundles a Redis, you provide it (a
Deployment, Upstash, a Fly Redis). The ``redis`` package is imported when a store is made, so the
base install does not need it.

Every method is ``async def``, so a read happens in the background after the first paint and a
write never waits on the event path. Timeouts are short (one second by default): a Redis that is
down or slow makes ``ctx.persist`` start from defaults and drop writes, with one log line a minute
(the degraded mode of ADR-0043), never a stuck tab. Keys are the ones ``ctx.persist`` builds,
``<namespace>:<user>:<session>:<name>`` with each part percent-encoded, so ``indah:*`` by default.
Expiry is Redis's own (``PSETEX``). ``rediss://`` is TLS and ``redis://user:password@host`` an ACL
user: the user needs ``GET``, ``SET``, ``DEL``, ``UNLINK``, ``SCAN`` and ``PING`` on ``indah:*``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("indah")

_SCAN_COUNT = 500
_GLOB_SPECIAL = "\\*?[]"


def _import_redis() -> Any:
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        raise ImportError(
            "the Redis state store needs the redis package: pip install 'indah[redis]'"
        ) from None
    return redis_asyncio


def _escape_glob(text: str) -> str:
    """``text`` as a literal for ``SCAN MATCH`` (a prefix with ``*`` or ``[`` means itself)."""
    return "".join("\\" + c if c in _GLOB_SPECIAL else c for c in text)


class RedisStateStore:
    """``RedisStateStore("redis://host:6379/0")`` or ``RedisStateStore(client=my_async_client)``.

    ``key_prefix`` is put in front of every key (``ctx.persist`` already starts its keys with the
    app's ``state_namespace``, so this is for a Redis shared with something else). A client you
    pass in is yours: ``close`` leaves it open."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: Any = None,
        key_prefix: str = "",
        timeout: float = 1.0,
    ) -> None:
        if (url is None) == (client is None):
            raise ValueError("RedisStateStore takes a url or a client, not both and not neither")
        if not timeout > 0:
            raise ValueError("timeout must be more than 0 seconds")
        self.key_prefix = key_prefix
        self._owns = client is None
        if client is None:
            redis_asyncio = _import_redis()
            from redis.asyncio.retry import Retry
            from redis.backoff import ConstantBackoff
            from redis.exceptions import ConnectionError as RedisConnectionError

            client = redis_asyncio.Redis.from_url(
                url,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                health_check_interval=15,
                # One quick retry reconnects a connection that Redis, a proxy or a failover closed.
                retry=Retry(ConstantBackoff(0.05), 1),
                retry_on_error=[RedisConnectionError],
            )
        self._client = client
        self._timeout = timeout

    def _key(self, key: str) -> str:
        return self.key_prefix + key

    async def get(self, key: str) -> bytes | None:
        value = await self._client.get(self._key(key))
        return None if value is None else bytes(value)

    async def set(self, key: str, value: bytes, ttl: float | None) -> None:
        if ttl is None:
            await self._client.set(self._key(key), bytes(value))
        else:
            await self._client.set(self._key(key), bytes(value), px=max(1, round(ttl * 1000)))

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def delete_prefix(self, prefix: str) -> None:
        match = _escape_glob(self._key(prefix)) + "*"
        batch: list[Any] = []
        async for found in self._client.scan_iter(match=match, count=_SCAN_COUNT):
            batch.append(found)
            if len(batch) >= _SCAN_COUNT:
                await self._client.unlink(*batch)
                batch = []
        if batch:
            await self._client.unlink(*batch)

    async def health(self) -> bool:
        """True when Redis answers ``PING`` within the timeout (the deploy doctor shows it)."""
        try:
            await asyncio.wait_for(self._client.ping(), self._timeout + 1.0)
        except Exception:
            return False
        return True

    async def close(self) -> None:
        if not self._owns:
            return
        closer = getattr(self._client, "aclose", None) or self._client.close
        await closer()

    def __repr__(self) -> str:  # never the URL: it may hold a password
        return f"RedisStateStore(key_prefix={self.key_prefix!r})"

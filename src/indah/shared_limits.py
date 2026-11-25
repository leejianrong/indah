"""Rate limits and stream caps shared by every replica, held in Redis (ADR-0043, IND-213).

``Limits`` are per process (ADR-0037), so N replicas multiply them. ``SharedLimits`` keeps the same
two controls in Redis so a visitor gets one budget however the balancer spreads them: a token bucket
per ``(route, address)`` and a count of open streams per address. It is **opt-in**
(``create_app(limits_shared="redis")`` or ``INDAH_LIMITS_SHARED=redis``, with ``INDAH_REDIS_URL``)
because it costs one Redis round trip per limited request, and install ``indah[redis]`` for it.

The local limiters stay the default and the fallback. Every call here has a short timeout and, when
Redis fails or is slow, answers ``None``, meaning "use the local limiter for this one". After a
failure the store is not tried again for a few seconds, so a dead Redis adds one timeout, not one
per
request, and a warning is logged at most once a minute. A limit is a backstop, so failing over to
the per-process limit is the right direction (never a refusal because Redis is down).

The bucket is one Lua script, so a take is atomic across replicas and uses Redis's own clock (a
replica with a wrong clock cannot skew it). It needs Redis 5 or later. A stream is a member of a
sorted set per address, scored by when it expires; a background task renews this process's members,
so a replica that dies stops holding slots after ``stream_ttl`` seconds. Keys start with
``indah:limits:`` by default and the ACL user needs ``EVAL``, ``EVALSHA``, ``ZADD``, ``ZREM``,
``ZCARD``, ``ZREMRANGEBYSCORE``, ``PEXPIRE``, ``PING`` on them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger("indah")

_BUCKET = """
local t = redis.call('TIME')
local now = t[1] + t[2] / 1000000
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local d = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(d[1])
local ts = tonumber(d[2])
if tokens == nil then tokens = burst; ts = now end
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens >= 1 then tokens = tokens - 1 else wait = (1 - tokens) / rate end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], math.ceil(burst / rate * 1000) + 1000)
return tostring(wait)
"""

_ACQUIRE = """
local t = redis.call('TIME')
local now = t[1] + t[2] / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[2])
redis.call('PEXPIRE', KEYS[1], math.ceil(tonumber(ARGV[3]) * 1000) + 1000)
return 1
"""

_RENEW = """
local t = redis.call('TIME')
local now = t[1] + t[2] / 1000000
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
  redis.call('PEXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) * 1000) + 1000)
end
return 1
"""


def _import_redis() -> Any:
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        raise ImportError(
            "shared limits need the redis package: pip install 'indah[redis]'"
        ) from None
    return redis_asyncio


class SharedLimits:
    """``SharedLimits("redis://host:6379/0")`` or ``SharedLimits(client=my_async_client)``.

    ``take`` and ``acquire`` answer ``None`` when Redis is unavailable (the caller then uses its
    local limiter). A client you pass in is yours: ``close`` leaves it open."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: Any = None,
        key_prefix: str = "indah:limits:",
        timeout: float = 0.25,
        cooldown: float = 5.0,
        stream_ttl: float = 60.0,
        clock: Any = time.monotonic,
    ) -> None:
        if (url is None) == (client is None):
            raise ValueError("SharedLimits takes a url or a client, not both and not neither")
        if not timeout > 0 or not cooldown >= 0 or not stream_ttl > 0:
            raise ValueError("timeout and stream_ttl must be more than 0, cooldown 0 or more")
        self.key_prefix = key_prefix
        self._owns = client is None
        if client is None:
            redis_asyncio = _import_redis()
            client = redis_asyncio.Redis.from_url(
                url, socket_timeout=timeout, socket_connect_timeout=timeout
            )
        self._client = client
        self._timeout = timeout
        self._cooldown = cooldown
        self._stream_ttl = stream_ttl
        self._clock = clock
        self._down_until = 0.0
        self._last_warned = -1e9
        self._held: dict[tuple[str, str], None] = {}  # (key, member) of this process's streams
        self._renewer: asyncio.Task[None] | None = None
        self.failures = 0  # for the doctor page
        self.shared_calls = 0

    # -- failure handling ------------------------------------------------------------------

    def available(self) -> bool:
        return self._clock() >= self._down_until

    def _failed(self, exc: BaseException) -> None:
        self.failures += 1
        now = self._clock()
        self._down_until = now + self._cooldown
        if now - self._last_warned >= 60:
            self._last_warned = now
            logger.warning(
                "shared limits: Redis failed (%s), using per-process limits for %.0f s",
                type(exc).__name__,
                self._cooldown,
            )

    async def _call(self, script: str, keys: int, *args: Any) -> Any:
        if not self.available():
            return None
        try:
            result = await asyncio.wait_for(
                self._client.eval(script, keys, *args), self._timeout + 0.05
            )
        except Exception as exc:  # a limit never fails a request because Redis did
            self._failed(exc)
            return None
        self.shared_calls += 1
        return result

    # -- the token bucket ------------------------------------------------------------------

    async def take(self, name: str, per_second: float, burst: int) -> float | None:
        """Take a token from the shared bucket ``name``: ``0.0`` allowed, else the seconds to wait,
        or ``None`` when Redis is unavailable (use the local bucket)."""
        got = await self._call(_BUCKET, 1, self.key_prefix + "rate:" + name, per_second, burst)
        return None if got is None else float(got)

    # -- the stream cap --------------------------------------------------------------------

    async def acquire(self, address: str, cap: int) -> str | bool | None:
        """Take a stream slot for ``address``: a member id (hand it to ``release``) when granted,
        ``False`` when the shared count is at ``cap``, ``None`` when Redis is unavailable."""
        key = self.key_prefix + "streams:" + address
        member = uuid.uuid4().hex
        got = await self._call(_ACQUIRE, 1, key, cap, member, self._stream_ttl)
        if got is None:
            return None
        if not int(got):
            return False
        self._held[(key, member)] = None
        self._start_renewer()
        return member

    async def release(self, address: str, member: str) -> None:
        key = self.key_prefix + "streams:" + address
        self._held.pop((key, member), None)
        if not self.available():
            return  # the member expires by itself
        try:
            await asyncio.wait_for(self._client.zrem(key, member), self._timeout + 0.05)
        except Exception as exc:
            self._failed(exc)

    def _start_renewer(self) -> None:
        if self._renewer is None or self._renewer.done():
            self._renewer = asyncio.get_running_loop().create_task(self._renew_loop())

    async def _renew_loop(self) -> None:
        while self._held:
            await asyncio.sleep(self._stream_ttl / 3)
            for key, member in list(self._held):
                await self._call(_RENEW, 1, key, member, self._stream_ttl)

    # -- housekeeping ----------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            await asyncio.wait_for(self._client.ping(), self._timeout + 1.0)
        except Exception:
            return False
        return True

    async def close(self) -> None:
        if self._renewer is not None:
            self._renewer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renewer
        if not self._owns:
            return
        closer = getattr(self._client, "aclose", None) or self._client.close
        await closer()

    def __repr__(self) -> str:  # never the URL: it may hold a password
        return f"SharedLimits(key_prefix={self.key_prefix!r})"

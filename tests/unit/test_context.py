"""The per-session Context and the factory-arity seam (IND-87, ADR-0025 to come).

A session factory may take no arguments (every existing app) or one ``Context``.
``Session.close()`` -- run by ``discard``, LRU eviction and the idle reaper -- cancels
tasks and runs the callbacks registered with ``ctx.on_close``.
"""

import logging

import pytest

from indah.components import Column, Text
from indah.context import ConnectionInfo, Context
from indah.session import Session
from indah.session_store import InMemorySessionStore, SharedSessionStore


def _session() -> Session:
    return Session(Column(children=[Text("x")]))


@pytest.mark.unit
def test_zero_arg_factories_still_work():
    store = InMemorySessionStore(_session)
    assert store.get_or_create("a").session is not None


@pytest.mark.unit
def test_one_arg_factory_receives_a_context_with_sid_and_connection():
    seen: list[Context] = []

    def factory(ctx: Context) -> Session:
        seen.append(ctx)
        return _session()

    store = InMemorySessionStore(factory)
    info = ConnectionInfo(headers={"x-test": "1"}, client="10.0.0.1", path="/ui/")
    handle = store.get_or_create("tab-1", info)

    assert seen[0].sid == "tab-1"
    assert seen[0].conn.headers["x-test"] == "1" and seen[0].conn.client == "10.0.0.1"
    assert seen[0].user is None
    assert handle.session.ctx is seen[0]
    store.get_or_create("tab-1")  # same id: the factory is not called again
    assert len(seen) == 1


@pytest.mark.unit
def test_factory_with_only_optional_params_is_called_with_none():
    def factory(flavour="plain") -> Session:
        assert flavour == "plain"
        return _session()

    InMemorySessionStore(factory).get_or_create("a")


@pytest.mark.unit
def test_missing_connection_info_gives_an_empty_connection():
    seen: list[Context] = []
    InMemorySessionStore(lambda ctx: seen.append(ctx) or _session()).get_or_create("a")
    assert seen[0].conn.headers == {} and seen[0].conn.client is None


@pytest.mark.unit
def test_on_close_runs_once_on_discard():
    calls: list[str] = []

    def factory(ctx: Context) -> Session:
        ctx.on_close(lambda: calls.append("closed"))
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    store.discard("a")
    store.discard("a")  # unknown now: a no-op
    assert calls == ["closed"]


@pytest.mark.unit
def test_on_close_runs_on_lru_eviction_and_idle_reaping(monkeypatch):
    calls: list[str] = []

    def factory(ctx: Context) -> Session:
        ctx.on_close(lambda sid=ctx.sid: calls.append(sid))
        return _session()

    store = InMemorySessionStore(factory, max_sessions=1)
    store.get_or_create("a")
    store.get_or_create("b")  # evicts a
    assert calls == ["a"]

    clock = [1000.0]
    monkeypatch.setattr("indah.session_store.time.monotonic", lambda: clock[0])
    idle = InMemorySessionStore(factory, idle_timeout_seconds=10)
    idle.get_or_create("c")
    clock[0] += 60
    idle.get_or_create("d")  # reaps c
    assert calls == ["a", "c"]


@pytest.mark.unit
def test_a_failing_close_callback_does_not_block_the_others(caplog):
    calls: list[str] = []

    def factory(ctx: Context) -> Session:
        def boom():
            raise RuntimeError("nope")

        ctx.on_close(boom)
        ctx.on_close(lambda: calls.append("second"))
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    with caplog.at_level(logging.ERROR, logger="indah"):
        store.discard("a")
    assert calls == ["second"] and "close callback" in caplog.text


@pytest.mark.unit
def test_close_is_idempotent_and_late_callbacks_run_immediately():
    ctx = Context(sid="a")
    calls: list[int] = []
    ctx.on_close(lambda: calls.append(1))
    ctx.close()
    ctx.close()
    ctx.on_close(lambda: calls.append(2))  # registered after close: runs now
    assert calls == [1, 2]


@pytest.mark.unit
def test_shared_store_accepts_connection_info_and_handles_have_no_owner():
    store = SharedSessionStore(_session())
    handle = store.get_or_create("any", ConnectionInfo())
    assert handle.owner is None


# -- ctx.every and ctx.spawn (IND-154) -----------------------------------------------------------


@pytest.mark.unit
async def test_every_repeats_and_stops_when_the_session_is_discarded():
    import asyncio

    ticks: list[int] = []

    def factory(ctx: Context) -> Session:
        ctx.every(0.01, lambda: ticks.append(1))
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    await asyncio.sleep(0.12)
    assert len(ticks) >= 3
    store.discard("a")
    seen = len(ticks)
    await asyncio.sleep(0.05)
    assert len(ticks) == seen  # cancelled, not merely paused


@pytest.mark.unit
async def test_every_is_cancelled_on_eviction():
    import asyncio

    ticks: dict[str, int] = {"a": 0, "b": 0}

    def factory(ctx: Context) -> Session:
        ctx.every(0.01, lambda sid=ctx.sid: ticks.__setitem__(sid, ticks[sid] + 1))
        return _session()

    store = InMemorySessionStore(factory, max_sessions=1)
    store.get_or_create("a")
    store.get_or_create("b")  # evicts a
    await asyncio.sleep(0.03)
    frozen = ticks["a"]
    await asyncio.sleep(0.05)
    assert ticks["a"] == frozen
    assert ticks["b"] > frozen or ticks["b"] >= 3
    store.discard("b")


@pytest.mark.unit
async def test_every_awaits_a_coroutine_function():
    import asyncio

    ticks: list[int] = []

    async def refresh() -> None:
        await asyncio.sleep(0)
        ticks.append(1)

    def factory(ctx: Context) -> Session:
        ctx.every(0.01, refresh)
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    await asyncio.sleep(0.08)
    store.discard("a")
    assert len(ticks) >= 2


@pytest.mark.unit
async def test_a_failing_every_callback_does_not_stop_the_loop_and_is_logged_once(caplog):
    import asyncio

    calls: list[int] = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) < 4:
            raise RuntimeError("refresh failed")

    def factory(ctx: Context) -> Session:
        ctx.every(0.01, flaky)
        return _session()

    store = InMemorySessionStore(factory)
    with caplog.at_level(logging.ERROR, logger="indah"):
        store.get_or_create("a")
        await asyncio.sleep(0.15)
    store.discard("a")
    assert len(calls) >= 5  # it kept going past the three failures
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1  # three failures in a row, one log line


@pytest.mark.unit
async def test_every_logs_again_after_it_recovers_and_fails_again(caplog):
    import asyncio

    state = {"n": 0}

    def sometimes() -> None:
        state["n"] += 1
        if state["n"] in (1, 3):
            raise RuntimeError("boom")

    def factory(ctx: Context) -> Session:
        ctx.every(0.01, sometimes)
        return _session()

    store = InMemorySessionStore(factory)
    with caplog.at_level(logging.ERROR, logger="indah"):
        store.get_or_create("a")
        await asyncio.sleep(0.12)
    store.discard("a")
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 2


@pytest.mark.unit
async def test_every_can_run_once_immediately():
    import asyncio

    ticks: list[int] = []

    def factory(ctx: Context) -> Session:
        ctx.every(10, lambda: ticks.append(1), immediately=True)
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    await asyncio.sleep(0.05)
    store.discard("a")
    assert ticks == [1]


@pytest.mark.unit
async def test_spawn_runs_a_coroutine_and_cancels_it_on_close():
    import asyncio

    started = asyncio.Event()
    cancelled: list[bool] = []

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    def factory(ctx: Context) -> Session:
        ctx.spawn(forever())
        return _session()

    store = InMemorySessionStore(factory)
    store.get_or_create("a")
    await asyncio.wait_for(started.wait(), 1)
    store.discard("a")
    await asyncio.sleep(0.02)
    assert cancelled == [True]


@pytest.mark.unit
async def test_a_failing_spawned_task_is_logged_once_and_does_not_hurt_the_session(caplog):
    import asyncio

    async def boom() -> None:
        raise RuntimeError("background failed")

    def factory(ctx: Context) -> Session:
        ctx.spawn(boom())
        return _session()

    store = InMemorySessionStore(factory)
    with caplog.at_level(logging.ERROR, logger="indah"):
        store.get_or_create("a")
        await asyncio.sleep(0.03)
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1
    assert store.get("a") is not None
    store.discard("a")


@pytest.mark.unit
async def test_spawn_after_close_drops_the_coroutine_without_a_warning():
    import warnings

    ctx = Context("a")
    ctx.close()

    async def never() -> None:  # pragma: no cover - must not run
        raise AssertionError

    coro = never()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # "coroutine was never awaited" would fail here
        assert ctx.spawn(coro) is None
        del coro


@pytest.mark.unit
def test_spawn_and_every_need_a_running_loop_and_a_positive_interval():
    ctx = Context("a")

    async def noop() -> None: ...

    coro = noop()
    with pytest.raises(RuntimeError, match="running event loop"):
        ctx.spawn(coro)
    coro.close()
    with pytest.raises(RuntimeError, match="running event loop"):
        ctx.every(1, lambda: None)


@pytest.mark.unit
async def test_every_rejects_a_non_positive_interval():
    ctx = Context("a")
    with pytest.raises(ValueError, match="seconds"):
        ctx.every(0, lambda: None)
    with pytest.raises(ValueError, match="seconds"):
        ctx.every(-1, lambda: None)

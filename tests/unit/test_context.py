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

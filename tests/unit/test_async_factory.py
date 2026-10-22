"""An ``async def`` session factory, awaited with a time limit (IND-153, ADR-0025 amendment).

A fast factory puts its data in the first snapshot. A slow one lets the tab start on a
``Skeleton`` and swaps the real tree in with a fresh ``init`` when it finishes. A sync factory
behaves exactly as before.
"""

import asyncio

import pytest

from indah.components import Column, Skeleton, Text
from indah.session import Session
from indah.session_store import InMemorySessionStore


def _types(snapshot: dict) -> list[str]:
    out = [snapshot["type"]]
    for child in snapshot.get("children", []):
        out.extend(_types(child))
    return out


def _texts(snapshot: dict) -> list[str]:
    found = [snapshot["props"]["text"]] if snapshot["type"] == "text" else []
    for child in snapshot.get("children", []):
        found.extend(_texts(child))
    return found


def _real(label: str) -> Session:
    return Session(Column(children=[Text(label)]))


def _store(factory, timeout: float = 0.05, **kw) -> InMemorySessionStore:
    return InMemorySessionStore(factory, factory_timeout=timeout, **kw)


@pytest.mark.unit
async def test_a_fast_async_factory_has_its_data_in_the_first_snapshot():
    async def build() -> Session:
        await asyncio.sleep(0)
        return _real("loaded")

    store = _store(build, timeout=1.0)
    handle = await store.aget_or_create("a")
    assert _texts(handle.session.snapshot()) == ["loaded"]
    assert handle.hub.current_offset == 0  # no swap message: the first snapshot is the real one
    assert handle.session.session_id == "a"
    assert handle.session.ctx is not None


@pytest.mark.unit
async def test_a_slow_async_factory_times_out_to_a_skeleton_then_swaps_in_the_real_tree():
    release = asyncio.Event()

    async def build() -> Session:
        await release.wait()
        return _real("late")

    store = _store(build)
    handle = await store.aget_or_create("a")
    assert "skeleton" in _types(handle.session.snapshot())
    assert handle.hub.current_offset == 0

    release.set()
    await asyncio.sleep(0.05)

    assert same(store.get("a"), handle)  # the same handle: streams and events keep working
    assert _texts(handle.session.snapshot()) == ["late"]
    history = handle.hub.history()
    assert [m["type"] for _, m in history] == ["init"]
    assert _texts(history[0][1]["root"]) == ["late"]
    assert handle.session.session_id == "a"
    assert handle.session.ctx is not None


def same(a, b) -> bool:
    return a is b


@pytest.mark.unit
async def test_a_custom_placeholder_is_used_instead_of_the_default_skeleton():
    release = asyncio.Event()

    async def build() -> Session:
        await release.wait()
        return _real("late")

    store = _store(build, placeholder=lambda: Text("one moment"))
    handle = await store.aget_or_create("a")
    assert _texts(handle.session.snapshot()) == ["one moment"]
    release.set()
    await asyncio.sleep(0.05)


@pytest.mark.unit
async def test_concurrent_requests_for_one_session_run_the_factory_once():
    calls = 0
    release = asyncio.Event()

    async def build() -> Session:
        nonlocal calls
        calls += 1
        await release.wait()
        return _real("once")

    store = _store(build)
    first, second = await asyncio.gather(store.aget_or_create("a"), store.aget_or_create("a"))
    assert first is second
    release.set()
    await asyncio.sleep(0.05)
    assert calls == 1
    assert len(store) == 1


@pytest.mark.unit
async def test_discarding_while_the_factory_runs_cancels_it_and_runs_on_close():
    cancelled = asyncio.Event()
    closed: list[str] = []

    async def build(ctx) -> Session:
        ctx.on_close(lambda: closed.append("closed"))
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _real("never")

    store = _store(build)
    handle = await store.aget_or_create("a")  # times out to the skeleton
    assert "skeleton" in _types(handle.session.snapshot())

    store.discard("a")
    await asyncio.sleep(0.05)

    assert cancelled.is_set()
    assert closed == ["closed"]
    assert store.get("a") is None
    assert len(store) == 0


@pytest.mark.unit
async def test_discarding_before_the_first_timeout_also_cancels_the_factory():
    cancelled = asyncio.Event()

    async def build() -> Session:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _real("never")

    store = _store(build, timeout=5.0)
    waiter = asyncio.ensure_future(store.aget_or_create("a"))
    await asyncio.sleep(0.02)
    store.discard("a")
    with pytest.raises(RuntimeError, match="closed"):
        await waiter
    assert cancelled.is_set()
    assert store.get("a") is None


@pytest.mark.unit
async def test_a_factory_that_fails_fast_raises_and_leaves_nothing_behind():
    async def build() -> Session:
        raise ValueError("no database")

    store = _store(build, timeout=1.0)
    with pytest.raises(ValueError, match="no database"):
        await store.aget_or_create("a")
    assert store.get("a") is None
    assert len(store) == 0
    with pytest.raises(ValueError, match="no database"):  # a retry runs the factory again
        await store.aget_or_create("a")


@pytest.mark.unit
async def test_a_factory_that_fails_after_the_skeleton_shows_an_error_and_drops_the_session():
    release = asyncio.Event()

    async def build() -> Session:
        await release.wait()
        raise ValueError("no database")

    store = _store(build)
    handle = await store.aget_or_create("a")
    release.set()
    await asyncio.sleep(0.05)

    kinds = [m["type"] for _, m in handle.hub.history()]
    assert kinds == ["error"]
    assert "no database" in handle.hub.history()[0][1]["message"]
    assert store.get("a") is None  # the next connection builds afresh


@pytest.mark.unit
async def test_a_sync_factory_is_unchanged():
    def build() -> Session:
        return _real("sync")

    store = InMemorySessionStore(build)
    handle = store.get_or_create("a")
    assert _texts(handle.session.snapshot()) == ["sync"]
    assert (await store.aget_or_create("a")) is handle  # the async entry point is the same thing
    assert (await store.aget_or_create("b")) is not handle
    assert "skeleton" not in _types(handle.session.snapshot())


@pytest.mark.unit
async def test_the_sync_entry_point_refuses_an_async_factory_with_a_clear_message():
    async def build() -> Session:
        return _real("x")

    store = _store(build)
    with pytest.raises(RuntimeError, match="aget_or_create"):
        store.get_or_create("a")


@pytest.mark.unit
async def test_the_session_limit_still_evicts_the_oldest_with_a_pending_factory():
    release = asyncio.Event()

    async def build() -> Session:
        await release.wait()
        return _real("x")

    store = _store(build, max_sessions=1)
    await store.aget_or_create("a")
    await store.aget_or_create("b")
    assert store.get("a") is None
    assert store.get("b") is not None
    release.set()
    await asyncio.sleep(0.05)
    assert len(store) == 1


@pytest.mark.unit
def test_factory_timeout_must_be_positive():
    with pytest.raises(ValueError, match="factory_timeout"):
        InMemorySessionStore(lambda: _real("x"), factory_timeout=0)


@pytest.mark.unit
def test_skeleton_wire_props_are_minimal_and_defaults_are_omitted():
    assert Skeleton().static_props() == {}
    assert Skeleton(lines=5).static_props() == {"lines": 5}
    assert Skeleton(height="8rem").static_props() == {"height": "8rem"}
    assert Skeleton.type == "skeleton"
    with pytest.raises(ValueError):
        Skeleton(lines=0)

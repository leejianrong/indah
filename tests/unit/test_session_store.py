"""Unit tests for the session-store seam (ADR-0010).

The seam maps a session id to a per-viewer handle (its own Session + Hub). These
prove the two properties the seam must guarantee: the same id resumes the same
state, and distinct ids are isolated -- neither a signal write nor a hub patch in
one leaks into another.
"""

import asyncio

import pytest

from indah.components import Column, Text
from indah.reactive import Signal
from indah.session import Session
from indah.session_store import (
    InMemorySessionStore,
    SessionStore,
    SharedSessionStore,
)


def _counter_factory():
    """A fresh single-signal graph per call; returns (factory, reader)."""

    def factory() -> Session:
        n = Signal(0)
        root = Column(children=[Text(lambda: str(n.value))])
        session = Session(root)
        session.count = n  # stash the signal so a test can read/write it
        return session

    return factory


@pytest.mark.unit
def test_in_memory_store_satisfies_the_protocol():
    store = InMemorySessionStore(_counter_factory())
    assert isinstance(store, SessionStore)


@pytest.mark.unit
def test_same_id_returns_the_same_handle():
    store = InMemorySessionStore(_counter_factory())
    first = store.get_or_create("tab-a")
    again = store.get_or_create("tab-a")
    assert first is again
    assert store.get("tab-a") is first


@pytest.mark.unit
def test_distinct_ids_get_distinct_handles_and_hubs():
    store = InMemorySessionStore(_counter_factory())
    a = store.get_or_create("tab-a")
    b = store.get_or_create("tab-b")
    assert a is not b
    assert a.session is not b.session
    assert a.hub is not b.hub  # a patch in one can never reach the other's stream


@pytest.mark.unit
def test_a_signal_write_in_one_session_is_invisible_to_another():
    store = InMemorySessionStore(_counter_factory())
    a = store.get_or_create("tab-a")
    b = store.get_or_create("tab-b")

    a.session.count.set(5)

    # The graphs are independent: A moved, B did not.
    assert a.session.snapshot()["children"][0]["props"]["text"] == "5"
    assert b.session.snapshot()["children"][0]["props"]["text"] == "0"


@pytest.mark.unit
def test_get_returns_none_for_unknown_and_discard_drops():
    store = InMemorySessionStore(_counter_factory())
    assert store.get("nope") is None
    store.get_or_create("tab-a")
    assert store.get("tab-a") is not None
    assert len(store) == 1
    store.discard("tab-a")
    assert store.get("tab-a") is None
    assert len(store) == 0
    store.discard("tab-a")  # discarding an unknown id is a no-op


@pytest.mark.unit
def test_a_handle_binds_its_own_hub_to_its_own_session():
    store = InMemorySessionStore(_counter_factory())
    handle = store.get_or_create("tab-a")
    # A live emit from the session lands on the handle's hub, not elsewhere.
    handle.session.emit_props("n0", {"text": "hi"})
    assert handle.hub.current_offset == 1


@pytest.mark.unit
def test_bounds_default_to_unbounded_like_before_adr_0024():
    """No behaviour change for notebook/test use: nothing evicts unless a public
    deployment opts in (ADR-0024)."""
    store = InMemorySessionStore(_counter_factory())
    for i in range(50):
        store.get_or_create(f"tab-{i}")
    assert len(store) == 50


@pytest.mark.unit
def test_idle_timeout_evicts_sessions_idle_longer_than_the_limit(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("indah.session_store.time.monotonic", lambda: now[0])
    store = InMemorySessionStore(_counter_factory(), idle_timeout_seconds=60)
    store.get_or_create("tab-a")

    now[0] += 61
    store.get_or_create("tab-b")  # any call lazily reaps first

    assert store.get("tab-a") is None
    assert store.get("tab-b") is not None
    assert len(store) == 1


@pytest.mark.unit
def test_idle_timeout_resets_on_access(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("indah.session_store.time.monotonic", lambda: now[0])
    store = InMemorySessionStore(_counter_factory(), idle_timeout_seconds=60)

    store.get_or_create("tab-a")
    now[0] += 30
    store.get("tab-a")  # touched before the timeout -> the clock resets
    now[0] += 40  # 40s since the touch, still < 60s
    store.get_or_create("tab-b")

    assert store.get("tab-a") is not None


@pytest.mark.unit
def test_max_sessions_evicts_the_least_recently_used():
    store = InMemorySessionStore(_counter_factory(), max_sessions=2)
    store.get_or_create("tab-a")
    store.get_or_create("tab-b")
    store.get("tab-a")  # touch a, so b becomes the LRU

    store.get_or_create("tab-c")  # over the cap: evicts b

    assert store.get("tab-b") is None
    assert store.get("tab-a") is not None
    assert store.get("tab-c") is not None
    assert len(store) == 2


@pytest.mark.unit
async def test_evicting_a_session_cancels_its_running_tasks():
    """ADR-0024: dropping the dict entry alone would leave an abandoned session's
    background loop (chatbot generation, a diffusion/training loop) running with
    nowhere to deliver patches -- eviction must cancel it."""
    store = InMemorySessionStore(_counter_factory())
    handle = store.get_or_create("tab-a")
    started = asyncio.Event()

    async def forever():
        started.set()
        await asyncio.sleep(100)

    task = handle.session.spawn(forever())
    await started.wait()

    store.discard("tab-a")
    await asyncio.sleep(0)  # let the cancellation land

    assert task.cancelled()


@pytest.mark.unit
def test_shared_store_returns_one_handle_for_every_id():
    session = Session(Column(children=[Text("shared")]))
    store = SharedSessionStore(session)
    assert isinstance(store, SessionStore)
    assert store.get_or_create("a") is store.get_or_create("b")
    assert store.get_or_create("a").session is session
    store.discard("a")  # a no-op; the shared session stays
    assert store.get_or_create("a").session is session

"""The StateStore contract, run against every store (ADR-0043, IND-208).

One suite, so a later adapter (Redis, IND-210) has to behave exactly like these two.
"""

import asyncio
import inspect

import pytest

from indah.state import MemoryStateStore, SqliteStateStore, StateStore, state_store_from_spec


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(params=["memory", "sqlite", "sqlite-file"])
def made(request, tmp_path):
    clock = Clock()
    if request.param == "memory":
        store = MemoryStateStore(clock=clock)
    elif request.param == "sqlite":
        store = SqliteStateStore(":memory:", clock=clock)
    else:
        store = SqliteStateStore(str(tmp_path / "state.db"), clock=clock)
    yield store, clock
    store.close()


async def _call(value):
    return await value if inspect.isawaitable(value) else value


@pytest.mark.unit
async def test_a_stored_value_comes_back_and_a_missing_one_is_none(made):
    store, _ = made
    assert isinstance(store, StateStore)
    assert await _call(store.get("a")) is None
    await _call(store.set("a", b"one", None))
    assert await _call(store.get("a")) == b"one"
    await _call(store.set("a", b"two", None))
    assert await _call(store.get("a")) == b"two"


@pytest.mark.unit
async def test_a_value_expires_after_its_ttl_and_a_write_renews_it(made):
    store, clock = made
    await _call(store.set("a", b"x", 10))
    clock.now += 9
    assert await _call(store.get("a")) == b"x"
    await _call(store.set("a", b"y", 10))  # renewed from now
    clock.now += 9
    assert await _call(store.get("a")) == b"y"
    clock.now += 2
    assert await _call(store.get("a")) is None


@pytest.mark.unit
async def test_no_ttl_means_it_stays(made):
    store, clock = made
    await _call(store.set("a", b"x", None))
    clock.now += 10**9
    assert await _call(store.get("a")) == b"x"


@pytest.mark.unit
async def test_delete_and_delete_prefix(made):
    store, _ = made
    for key in ("u1:t1:a", "u1:t1:b", "u1:t2:a", "u2:t1:a"):
        await _call(store.set(key, key.encode(), None))
    await _call(store.delete("u2:t1:a"))
    assert await _call(store.get("u2:t1:a")) is None
    await _call(store.delete_prefix("u1:t1:"))
    assert await _call(store.get("u1:t1:a")) is None
    assert await _call(store.get("u1:t1:b")) is None
    assert await _call(store.get("u1:t2:a")) == b"u1:t2:a"  # a sibling prefix is untouched
    await _call(store.delete("never-there"))  # no error


@pytest.mark.unit
async def test_a_prefix_with_sql_wildcards_matches_literally(made):
    store, _ = made
    await _call(store.set("a%b", b"1", None))
    await _call(store.set("axb", b"2", None))
    await _call(store.delete_prefix("a%"))
    assert await _call(store.get("a%b")) is None
    assert await _call(store.get("axb")) == b"2"


@pytest.mark.unit
def test_the_sqlite_store_survives_a_restart(tmp_path):
    path = str(tmp_path / "state.db")
    first = SqliteStateStore(path)
    first.set("k", b"kept", None)
    first.set("gone", b"x", 0.001)
    first.close()
    second = SqliteStateStore(path)  # a new process, in effect
    assert second.get("k") == b"kept"
    second.close()


@pytest.mark.unit
def test_the_sqlite_store_sweeps_expired_rows_on_open(tmp_path):
    path = str(tmp_path / "state.db")
    clock = Clock()
    first = SqliteStateStore(path, clock=clock)
    first.set("old", b"x", 5)
    first.close()
    clock.now += 60
    second = SqliteStateStore(path, clock=clock)
    assert second._conn.execute("select count(*) from indah_state").fetchone()[0] == 0
    second.close()


@pytest.mark.unit
def test_the_memory_store_is_bounded():
    store = MemoryStateStore(max_entries=3)
    for n in range(5):
        store.set(f"k{n}", b"x", None)
    assert store.get("k0") is None and store.get("k1") is None
    assert store.get("k4") == b"x"


@pytest.mark.unit
def test_the_memory_store_drops_expired_entries_when_it_writes():
    clock = Clock()
    store = MemoryStateStore(clock=clock)
    store.set("a", b"x", 1)
    clock.now += 5
    store.set("b", b"y", None)
    assert list(store._data) == ["b"]


@pytest.mark.unit
def test_spec_strings():
    assert isinstance(state_store_from_spec("memory"), MemoryStateStore)
    store = state_store_from_spec("sqlite:///:memory:")
    assert isinstance(store, SqliteStateStore)
    store.close()
    with pytest.raises(ValueError, match="INDAH_STATE_STORE"):
        state_store_from_spec("redis://localhost")
    with pytest.raises(ValueError, match="INDAH_STATE_STORE"):
        state_store_from_spec("bogus")
    with pytest.raises(ValueError, match="INDAH_STATE_STORE"):
        state_store_from_spec("sqlite://")


@pytest.mark.unit
async def test_a_client_held_store_fits_the_interface():
    """ADR-0043: the interface must admit a store whose values the request carried.

    A browser-held store is built per request from what the shell sent back, and an async
    method that never touches a disk is as valid as a sync one."""

    class Carried:
        def __init__(self, carried: dict[str, bytes]) -> None:
            self.carried = dict(carried)
            self.out: dict[str, bytes] = {}

        async def get(self, key):
            return self.carried.get(key)

        async def set(self, key, value, ttl):
            self.out[key] = value  # to be sent to the tab, not kept here

        async def delete(self, key):
            self.out.pop(key, None)

        async def delete_prefix(self, prefix):
            for key in [k for k in self.out if k.startswith(prefix)]:
                del self.out[key]

        async def close(self):
            pass

    store = Carried({"k": b"from the tab"})
    assert isinstance(store, StateStore)
    assert await store.get("k") == b"from the tab"
    assert asyncio.iscoroutinefunction(store.get)

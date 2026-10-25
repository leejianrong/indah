"""``ctx.persist``: a tab's small state survives a rebuild (ADR-0043, Tier B, IND-208)."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from indah import Computed, Signal, state
from indah.auth import Principal
from indah.components import Column, SecretReveal, Text
from indah.context import ConnectionInfo, Context
from indah.session import Session
from indah.state import MemoryStateStore


class Spy(MemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.sets: list[tuple[str, bytes, float | None]] = []
        self.deletes: list[str] = []

    def set(self, key, value, ttl):
        self.sets.append((key, value, ttl))
        super().set(key, value, ttl)

    def delete(self, key):
        self.deletes.append(key)
        super().delete(key)


def _app(store, **state):
    base = {
        "state_store": store,
        "state_namespace": "t",
        "persist_ttl": 3600.0,
        "persist_max_bytes": 16384,
        "persist_delay": 0,
    }
    return SimpleNamespace(state=SimpleNamespace(**{**base, **state}))


def _ctx(store, sid="tab-1", user=None, **state) -> Context:
    conn = ConnectionInfo(user=user)
    return Context(sid, conn, app=_app(store, **state))


def _ready(ctx: Context, root=None) -> None:
    ctx._session_ready(Session(root or Column(children=[Text("x")])))


def _alice() -> Principal:
    return Principal(id="alice")


@pytest.mark.unit
def test_a_value_is_restored_in_a_rebuilt_session():
    store = Spy()
    first = _ctx(store)
    tab = Signal("overview")
    first.persist("tab", tab)
    _ready(first)
    tab.set("billing")
    assert len(store.sets) == 1

    second = _ctx(store)  # the same tab, rebuilt after a restart
    tab2 = Signal("overview")
    second.persist("tab", tab2)
    assert tab2.value == "billing"  # applied inside the factory, before the first snapshot


@pytest.mark.unit
def test_restoring_does_not_write_it_back_and_nothing_is_written_before_ready():
    store = Spy()
    first = _ctx(store)
    n = Signal(1)
    first.persist("n", n)
    n.set(2)  # still inside the factory: held until the session is ready
    assert store.sets == []
    _ready(first)
    assert len(store.sets) == 1
    store.sets.clear()

    second = _ctx(store)
    n2 = Signal(0)
    second.persist("n", n2)
    _ready(second)
    assert n2.value == 2
    assert store.sets == []


@pytest.mark.unit
def test_a_new_tab_starts_fresh_and_so_does_another_principal():
    store = Spy()
    a = _ctx(store, sid="tab-1", user=_alice())
    sig = Signal("a")
    a.persist("k", sig)
    _ready(a)
    sig.set("saved")

    other_tab = Signal("fresh")
    _ctx(store, sid="tab-2", user=_alice()).persist("k", other_tab)
    assert other_tab.value == "fresh"

    other_user = Signal("fresh")
    _ctx(store, sid="tab-1", user=Principal(id="bob")).persist("k", other_user)
    assert other_user.value == "fresh"  # bob presents alice's sid and gets nothing

    same = Signal("fresh")
    _ctx(store, sid="tab-1", user=_alice()).persist("k", same)
    assert same.value == "saved"


@pytest.mark.unit
def test_the_owner_is_checked_again_on_read():
    """A value filed under another principal's key (a bad store, a copied key) is ignored."""
    store = Spy()
    alice = _ctx(store, user=_alice())
    sig = Signal(0)
    alice.persist("k", sig)
    _ready(alice)
    sig.set(7)
    ((key, raw, _),) = store.sets
    forged = json.loads(raw)
    forged["o"] = "mallory"  # the envelope names someone else
    MemoryStateStore.set(store, key, json.dumps(forged).encode(), None)

    again = Signal(0)
    _ctx(store, user=_alice()).persist("k", again)
    assert again.value == 0


@pytest.mark.unit
def test_a_changed_version_or_a_failed_check_is_ignored():
    store = Spy()
    first = _ctx(store)
    sig = Signal({"a": 1})
    first.persist("f", sig, version=1)
    _ready(first)
    sig.set({"a": 2})

    v2 = Signal({"b": 0})
    _ctx(store).persist("f", v2, version=2)
    assert v2.value == {"b": 0}

    checked = Signal({"b": 0})
    _ctx(store).persist("f", checked, validate=lambda v: "a" not in v)
    assert checked.value == {"b": 0}

    raising = Signal({"b": 0})

    def boom(_v):
        raise RuntimeError("x")

    _ctx(store).persist("f", raising, validate=boom)
    assert raising.value == {"b": 0}

    ok = Signal({})
    _ctx(store).persist("f", ok, validate=lambda v: "a" in v)
    assert ok.value == {"a": 2}


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [object(), {1: "x"}, (1, 2), {"a": {1, 2}}, float("nan"), b"bytes", {"k": float("inf")}],
)
def test_only_plain_json_is_accepted(value):
    ctx = _ctx(Spy())
    with pytest.raises(ValueError, match="persist"):
        ctx.persist("bad", Signal(value))


@pytest.mark.unit
def test_a_later_non_json_value_is_refused_not_stored(caplog):
    store = Spy()
    ctx = _ctx(store)
    sig = Signal(1)
    ctx.persist("k", sig)
    _ready(ctx)
    with caplog.at_level(logging.WARNING, logger="indah"):
        sig.set({1, 2})  # a set is not JSON
    assert store.sets == []
    assert "not JSON" in caplog.text or "JSON" in caplog.text


@pytest.mark.unit
def test_bad_arguments():
    ctx = _ctx(Spy())
    ctx.persist("a", Signal(1))
    with pytest.raises(ValueError, match="already"):
        ctx.persist("a", Signal(2))
    with pytest.raises(TypeError, match="Signal"):
        ctx.persist("c", Computed(lambda: 1))
    with pytest.raises(TypeError, match="Signal"):
        ctx.persist("d", 5)
    for name in ("", "x" * 65, 3):
        with pytest.raises(ValueError, match="name"):
            ctx.persist(name, Signal(1))
    with pytest.raises(ValueError, match="ttl"):
        ctx.persist("e", Signal(1), ttl=0)
    with pytest.raises(ValueError, match="max_bytes"):
        ctx.persist("f", Signal(1), max_bytes=0)


@pytest.mark.unit
def test_a_value_over_the_cap_is_skipped_with_one_warning_and_the_old_copy_goes(caplog):
    store = Spy()
    ctx = _ctx(store)
    sig = Signal("small")
    ctx.persist("note", sig, max_bytes=50)
    _ready(ctx)
    sig.set("fine")
    assert len(store.sets) == 1
    with caplog.at_level(logging.WARNING, logger="indah"):
        sig.set("x" * 200)
        sig.set("y" * 300)
    assert len(store.sets) == 1  # nothing bigger was written
    assert caplog.text.count("note") == 1  # warned once, not per keystroke
    fresh = Signal("default")
    _ctx(store).persist("note", fresh, max_bytes=50)
    assert fresh.value == "default"  # a stale value is not restored over a newer, unsaved one


@pytest.mark.unit
def test_the_session_cap_is_enforced_across_names(caplog):
    store = Spy()
    ctx = _ctx(store, persist_session_bytes=100)
    a, b = Signal(""), Signal("")
    ctx.persist("a", a)
    ctx.persist("b", b)
    _ready(ctx)
    with caplog.at_level(logging.WARNING, logger="indah"):
        a.set("a" * 60)
        b.set("b" * 60)
    keys = [k for k, _, _ in store.sets]
    assert len(keys) == 1 and keys[0].endswith(":a")  # b would take the session over 100 bytes


@pytest.mark.unit
def test_ttl_comes_from_the_call_then_the_app():
    store = Spy()
    ctx = _ctx(store)
    a, b = Signal(1), Signal(1)
    ctx.persist("a", a)
    ctx.persist("b", b, ttl=60)
    _ready(ctx)
    a.set(2)
    b.set(2)
    assert [t for _, _, t in store.sets] == [3600.0, 60]


@pytest.mark.unit
def test_a_signal_shown_in_an_ephemeral_prop_is_never_stored(caplog):
    store = Spy()
    ctx = _ctx(store)
    secret = Signal(None)
    shown = Computed(lambda: secret.value)  # even through a computed
    ctx.persist("secret", secret)
    sig2 = Signal("x")
    ctx.persist("ok", sig2)
    with caplog.at_level(logging.ERROR, logger="indah"):
        _ready(ctx, Column(children=[SecretReveal(shown)]))
    secret.set("tok_live_abc")
    sig2.set("y")
    stored = b"".join(v for _, v, _ in store.sets)
    assert b"tok_live_abc" not in stored
    assert [k for k, _, _ in store.sets] == [k for k, _, _ in store.sets if k.endswith(":ok")]
    assert "ephemeral" in caplog.text and "secret" in caplog.text
    assert any(k.endswith(":secret") for k in store.deletes)  # and any old copy is removed


@pytest.mark.unit
def test_an_older_stored_secret_is_removed_not_restored_into_the_ephemeral_prop():
    store = Spy()
    first = _ctx(store)
    leaked = Signal("old")
    first.persist("tok", leaked)  # an app that persisted it before it showed it
    _ready(first)
    leaked.set("tok_abc")  # written, because nothing yet says it is secret
    assert store.sets

    second = _ctx(store)
    tok = Signal(None)
    second.persist("tok", tok)
    _ready(second, Column(children=[SecretReveal(tok)]))
    assert any(k.endswith(":tok") for k in store.deletes)
    third = Signal("none")
    _ctx(store).persist("tok", third)
    assert third.value == "none"


@pytest.mark.unit
async def test_writes_are_coalesced():
    store = Spy()
    ctx = _ctx(store, persist_delay=0.05)
    text = Signal("")
    ctx.persist("draft", text)
    _ready(ctx)
    for part in ("h", "he", "hel", "hell", "hello"):
        text.set(part)
    assert store.sets == []
    await asyncio.sleep(0.15)
    assert len(store.sets) == 1
    assert json.loads(store.sets[0][1])["d"] == "hello"


@pytest.mark.unit
async def test_closing_the_session_flushes_a_pending_write_and_stops_saving():
    store = Spy()
    ctx = _ctx(store, persist_delay=10)
    text = Signal("")
    ctx.persist("draft", text)
    _ready(ctx)
    text.set("typed just now")
    assert store.sets == []
    ctx.close()
    assert len(store.sets) == 1
    text.set("after close")
    await asyncio.sleep(0)
    assert len(store.sets) == 1


@pytest.mark.unit
def test_a_store_that_fails_never_breaks_the_session(caplog):
    class Broken(MemoryStateStore):
        def get(self, key):
            raise OSError("down")

        def set(self, key, value, ttl):
            raise OSError("down")

    state._warned.clear()
    ctx = _ctx(Broken())
    sig = Signal("default")
    with caplog.at_level(logging.WARNING, logger="indah"):
        ctx.persist("k", sig)
        _ready(ctx)
        sig.set("changed")
        sig.set("again")
    assert sig.value == "again"
    assert 1 <= caplog.text.count("state store") <= 2  # rate limited, not one line per change


@pytest.mark.unit
async def test_an_async_store_restores_a_moment_later():
    class Slow:
        def __init__(self, inner):
            self.inner = inner

        async def get(self, key):
            await asyncio.sleep(0.01)
            return self.inner.get(key)

        async def set(self, key, value, ttl):
            self.inner.set(key, value, ttl)

        async def delete(self, key):
            self.inner.delete(key)

        async def delete_prefix(self, prefix):
            self.inner.delete_prefix(prefix)

        async def close(self):
            pass

    inner = Spy()
    first = _ctx(inner)
    sig = Signal(1)
    first.persist("k", sig)
    _ready(first)
    sig.set(5)

    slow = Slow(inner)
    second = _ctx(slow)
    sig2 = Signal(1)
    second.persist("k", sig2)
    assert sig2.value == 1  # not yet: the read is awaited in the background
    _ready(second)
    await asyncio.sleep(0.1)
    assert sig2.value == 5
    inner.sets.clear()
    sig2.set(6)  # and an async set works
    await asyncio.sleep(0.05)
    assert len(inner.sets) == 1


@pytest.mark.unit
def test_a_bare_context_has_a_private_store_and_does_not_fail():
    ctx = Context("x")
    sig = Signal(1)
    ctx.persist("k", sig)
    _ready(ctx)
    sig.set(2)
    again = Signal(1)
    Context("x").persist("k", again)
    assert again.value == 1  # nothing shared between bare contexts

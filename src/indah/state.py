"""Restorable sessions: the ``StateStore`` interface and ``ctx.persist`` (ADR-0043, Tier B).

A tab's session is a graph of closures in one process, so it cannot be moved. What can survive a
restart, a rollout or a move to another replica is the **small state** an app chooses to keep:
a selected tab, filters, a half-typed note. ``ctx.persist(name, signal)`` saves that signal's
JSON value into a :class:`StateStore`, keyed by principal and session id, and puts it back when
the session is built again::

    def build(ctx):
        tab = Signal("overview")
        ctx.persist("tab", tab)  # restores the saved value, then saves on change

Stores here: :class:`MemoryStateStore` (the default, process-local), :class:`SqliteStateStore`
(stdlib, one file) and, in ``indah.redis_store``, ``RedisStateStore`` (``indah[redis]``, shared
between replicas). A store method may be a plain function or ``async def``, so a networked or a
client-held store fits the same interface.

What is never stored: a signal the app did not register, a value that is not plain JSON, a signal
shown in an *ephemeral prop* (a ``SecretReveal``, ADR-0036), and anything over the size caps.
Treat a store as sensitive as the app's own database: it holds what the app persisted.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import quote

from .reactive import Computation, Computed, Signal

if TYPE_CHECKING:
    from .context import Context
    from .session import Session

logger = logging.getLogger("indah")

DEFAULT_NAMESPACE = "indah"
DEFAULT_TTL = 24 * 3600.0  # seconds from the last write
DEFAULT_MAX_BYTES = 16 * 1024  # per value
DEFAULT_SESSION_BYTES = 128 * 1024  # per session, across names
DEFAULT_DELAY = 0.25  # seconds a burst of changes is coalesced for
_MAX_NAME = 64
_MAX_DEPTH = 32
_WARN_EVERY = 60.0


@runtime_checkable
class StateStore(Protocol):
    """Where persisted values live. Keys and values are opaque: ``ctx.persist`` builds the key
    and a small JSON envelope. Each method may be ``def`` or ``async def`` (the stores below are
    plain functions, a networked one is async).

    ``set`` replaces the value and (re)starts its ``ttl`` in seconds (``None``: no expiry);
    an expired value reads as ``None``. ``delete_prefix`` drops every key that starts with
    ``prefix`` (a tab's or a user's whole state)."""

    def get(self, key: str) -> bytes | None | Awaitable[bytes | None]: ...

    def set(self, key: str, value: bytes, ttl: float | None) -> None | Awaitable[None]: ...

    def delete(self, key: str) -> None | Awaitable[None]: ...

    def delete_prefix(self, prefix: str) -> None | Awaitable[None]: ...

    def close(self) -> None | Awaitable[None]: ...


class MemoryStateStore:
    """The default: a bounded dict in this process. State survives a tab being rebuilt (an
    idle session reaped, a stream that dropped) but not the process. ``max_entries`` bounds
    memory: the oldest-written entries go first."""

    def __init__(
        self, *, max_entries: int = 10_000, clock: Callable[[], float] = time.time
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[str, tuple[bytes, float | None]] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        found = self._data.get(key)
        if found is None:
            return None
        value, expires = found
        if expires is not None and expires <= self._clock():
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: bytes, ttl: float | None) -> None:
        now = self._clock()
        for stale in [k for k, (_, e) in self._data.items() if e is not None and e <= now]:
            del self._data[stale]
        self._data.pop(key, None)
        self._data[key] = (bytes(value), None if ttl is None else now + ttl)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self._data if k.startswith(prefix)]:
            del self._data[key]

    def close(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class SqliteStateStore:
    """One SQLite file (stdlib, no dependency). Right for one replica that restarts. Do not
    share the file between replicas over a network filesystem: SQLite locking there is
    unreliable. Reads and writes are small and run on the event loop thread. Expired rows are
    deleted when the store opens and, at most once a minute, when it writes."""

    _SWEEP_EVERY = 60.0

    def __init__(self, path: str, *, clock: Callable[[], float] = time.time) -> None:
        self.path = str(path)
        self._clock = clock
        self._conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None, timeout=2.0
        )
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS indah_state "
            "(key TEXT PRIMARY KEY, value BLOB NOT NULL, expires REAL)"
        )
        self._swept = float("-inf")
        self._sweep()

    def _sweep(self) -> None:
        now = self._clock()
        self._conn.execute(
            "DELETE FROM indah_state WHERE expires IS NOT NULL AND expires <= ?", (now,)
        )
        self._swept = now

    def get(self, key: str) -> bytes | None:
        row = self._conn.execute(
            "SELECT value FROM indah_state WHERE key = ? AND (expires IS NULL OR expires > ?)",
            (key, self._clock()),
        ).fetchone()
        return None if row is None else bytes(row[0])

    def set(self, key: str, value: bytes, ttl: float | None) -> None:
        now = self._clock()
        self._conn.execute(
            "INSERT OR REPLACE INTO indah_state (key, value, expires) VALUES (?, ?, ?)",
            (key, bytes(value), None if ttl is None else now + ttl),
        )
        if now - self._swept >= self._SWEEP_EVERY:
            self._sweep()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM indah_state WHERE key = ?", (key,))

    def delete_prefix(self, prefix: str) -> None:
        self._conn.execute(
            "DELETE FROM indah_state WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
        )

    def close(self) -> None:
        self._conn.close()


def state_store_from_spec(spec: str) -> StateStore:
    """``memory``, ``sqlite:///relative.db``, ``sqlite:////absolute.db``, ``sqlite:///:memory:``,
    ``redis://host:6379/0`` or ``rediss://`` for TLS (needs ``indah[redis]``). These are what
    ``INDAH_STATE_STORE`` and ``create_app(state_store="...")`` accept."""
    text = spec.strip()
    if text == "memory":
        return MemoryStateStore()
    if text.startswith("sqlite:///"):
        path = text[len("sqlite:///") :]
        if path:
            return SqliteStateStore(path)
        raise ValueError(
            "INDAH_STATE_STORE: sqlite:/// needs a file path, for example sqlite:///state.db"
        )
    if text.startswith(("redis://", "rediss://")):
        from .redis_store import RedisStateStore

        try:
            return RedisStateStore(text)  # ImportError names indah[redis] when it is missing
        except ValueError as exc:
            raise ValueError(f"INDAH_STATE_STORE: not a Redis URL ({exc})") from None
    raise ValueError(
        "INDAH_STATE_STORE must be 'memory', 'sqlite:///path' or 'redis://host:6379/0', "
        f"got {text.split(':')[0]!r}"
    )


# -- ctx.persist ----------------------------------------------------------------------------------

_warned: dict[str, float] = {}
_background: set[asyncio.Task[Any]] = set()


def _warn(key: str, message: str, *args: object, exc_info: bool = False) -> None:
    """Log a warning at most once a minute per ``key``, so a store that is down is one line."""
    now = time.monotonic()
    if now - _warned.get(key, float("-inf")) >= _WARN_EVERY:
        _warned[key] = now
        logger.warning(message, *args, exc_info=exc_info)


def _check_json(value: Any, depth: int = 0) -> None:
    """Raise ``ValueError`` unless ``value`` is plain JSON that reads back as itself."""
    if depth > _MAX_DEPTH:
        raise ValueError("nested too deeply")
    kind = type(value)
    if value is None or kind in (bool, int, str):
        return
    if kind is float:
        if not math.isfinite(value):
            raise ValueError("NaN and infinity are not JSON")
        return
    if kind is list:
        for item in value:
            _check_json(item, depth + 1)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("dict keys must be strings")
            _check_json(item, depth + 1)
        return
    raise ValueError(f"{kind.__name__} is not JSON (use str, int, float, bool, None, list, dict)")


def _encode(name: str, value: Any) -> bytes:
    try:
        _check_json(value)
    except ValueError as exc:
        raise ValueError(f"ctx.persist({name!r}): {exc}") from None
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _closure(signal: Signal[Any]) -> set[Signal[Any]]:
    """``signal`` and every signal a computed among them reads, transitively."""
    seen: set[Signal[Any]] = set()
    todo = [signal]
    while todo:
        item = todo.pop()
        if item in seen:
            continue
        seen.add(item)
        if isinstance(item, Computed):
            todo.extend(item._computation.deps)
    return seen


@dataclass
class _Item:
    name: str
    signal: Signal[Any]
    key: str
    version: int
    ttl: float
    max_bytes: int
    validate: Callable[[Any], bool] | None
    effect: Computation | None = None
    dirty: bool = False
    applying: bool = False
    size: int = 0
    warned: bool = False


@dataclass
class _Persistence:
    """The ``ctx.persist`` registrations of one session."""

    ctx: Context
    store: StateStore
    namespace: str
    ttl: float
    max_bytes: int
    session_bytes: int
    delay: float
    items: dict[str, _Item] = field(default_factory=dict)
    ready: bool = False
    closed: bool = False
    _timer: asyncio.TimerHandle | None = None

    # -- keys -----------------------------------------------------------------------------------

    @property
    def _principal(self) -> str:
        user = self.ctx.user
        return user.id if user is not None else ""

    def _key(self, name: str) -> str:
        parts = (self.namespace, self._principal, self.ctx.sid, name)
        return ":".join(quote(part, safe="") for part in parts)

    # -- register -------------------------------------------------------------------------------

    def add(
        self,
        name: str,
        signal: Signal[Any],
        *,
        version: int,
        ttl: float | None,
        max_bytes: int | None,
        validate: Callable[[Any], bool] | None,
    ) -> None:
        if not isinstance(name, str) or not name or len(name) > _MAX_NAME:
            raise ValueError(f"ctx.persist: name must be a string of 1 to {_MAX_NAME} characters")
        if not isinstance(signal, Signal) or isinstance(signal, Computed):
            raise TypeError(
                "ctx.persist takes a Signal the app writes, not a computed or another value"
            )
        if name in self.items:
            raise ValueError(f"ctx.persist: {name!r} is already persisted in this session")
        if ttl is not None and not ttl > 0:
            raise ValueError("ctx.persist: ttl must be more than 0 seconds")
        if max_bytes is not None and not max_bytes > 0:
            raise ValueError("ctx.persist: max_bytes must be more than 0")
        _encode(name, signal.peek())  # a value that can never be saved fails here, loudly
        item = _Item(
            name=name,
            signal=signal,
            key=self._key(name),
            version=int(version),
            ttl=self.ttl if ttl is None else float(ttl),
            max_bytes=self.max_bytes if max_bytes is None else int(max_bytes),
            validate=validate,
        )
        self.items[name] = item
        self._restore(item)
        self._watch(item)

    def _watch(self, item: _Item) -> None:
        first = True

        def run() -> None:
            nonlocal first
            item.signal.value  # noqa: B018 - the read subscribes this effect
            if first:
                first = False
                return
            if not item.applying:
                item.dirty = True
                self._schedule()

        item.effect = Computation(run)

    # -- restore --------------------------------------------------------------------------------

    def _restore(self, item: _Item) -> None:
        try:
            raw = self.store.get(item.key)
        except Exception:
            _warn(
                "get",
                "indah state store read failed (ctx.persist starts from defaults)",
                exc_info=True,
            )
            return
        if inspect.isawaitable(raw):
            self._restore_later(item, raw)
        else:
            self._apply(item, raw)

    def _restore_later(self, item: _Item, pending: Awaitable[bytes | None]) -> None:
        async def run() -> None:
            try:
                raw = await pending
            except Exception:
                _warn(
                    "get",
                    "indah state store read failed (ctx.persist starts from defaults)",
                    exc_info=True,
                )
                return
            if not self.closed and self.items.get(item.name) is item:
                self._apply(item, raw)

        try:
            self.ctx.spawn(run())
        except RuntimeError:  # no event loop to await it on
            _warn("get", "indah ctx.persist: an async state store needs a running event loop")

    def _apply(self, item: _Item, raw: bytes | None) -> None:
        if raw is None:
            return
        try:
            envelope = json.loads(raw)
            if (
                not isinstance(envelope, dict)
                or envelope.get("v") != item.version
                or envelope.get("o") != self._principal
            ):
                return  # another shape (a deploy), or another principal's value: never ours
            value = envelope["d"]
            _check_json(value)
            if item.validate is not None and not item.validate(value):
                return
        except Exception:
            return
        item.applying = True
        try:
            item.signal.set(value)
        finally:
            item.applying = False

    # -- save -----------------------------------------------------------------------------------

    def _schedule(self) -> None:
        if not self.ready or self.closed:
            return
        if self.delay <= 0:
            self.flush()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush()
            return
        if self._timer is None:
            self._timer = loop.call_later(self.delay, self._timed)

    def _timed(self) -> None:
        self._timer = None
        self.flush()

    def flush(self) -> None:
        """Write every changed value now."""
        for item in list(self.items.values()):
            if item.dirty:
                item.dirty = False
                self._write(item)

    def _write(self, item: _Item) -> None:
        try:
            body = _encode(item.name, item.signal.peek())
        except ValueError as exc:
            _warn(f"json:{item.key}", "indah %s: not saved", exc)
            self._drop_stored(item)
            return
        envelope = b'{"v":%d,"o":%s,"d":%s}' % (
            item.version,
            json.dumps(self._principal).encode(),
            body,
        )
        others = sum(i.size for i in self.items.values() if i is not item)
        if len(body) > item.max_bytes or others + len(body) > self.session_bytes:
            item.size = 0
            if not item.warned:
                item.warned = True
                logger.warning(
                    "indah ctx.persist(%r): value of %d bytes is over the limit "
                    "(%d per value, %d per session), so it is not saved",
                    item.name,
                    len(body),
                    item.max_bytes,
                    self.session_bytes,
                )
            self._drop_stored(item)  # never restore an older value over this newer one
            return
        item.warned = False
        item.size = len(body)
        self._call(self.store.set, item.key, envelope, item.ttl)

    def _drop_stored(self, item: _Item) -> None:
        self._call(self.store.delete, item.key)

    def _call(self, method: Callable[..., Any], *args: Any) -> None:
        """Run a store call. A failure is logged (rate limited) and dropped, never raised."""
        try:
            result = method(*args)
        except Exception:
            _warn("write", "indah state store write failed (state not saved)", exc_info=True)
            return
        if inspect.isawaitable(result):
            self._background(result)

    @staticmethod
    def _background(pending: Awaitable[Any]) -> None:
        async def run() -> None:
            try:
                await pending
            except Exception:
                _warn("write", "indah state store write failed (state not saved)", exc_info=True)

        try:
            task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:  # no loop to run it on
            if inspect.iscoroutine(pending):
                pending.close()
            return
        _background.add(task)
        task.add_done_callback(_background.discard)

    # -- lifecycle ------------------------------------------------------------------------------

    def session_ready(self, session: Session) -> None:
        """The tree is built: drop anything shown in an ephemeral prop, then start saving."""
        from .components import walk

        if self.ready:
            return
        refused = self._ephemeral_signals(walk(session.root))
        for item in list(self.items.values()):
            if _closure(item.signal) & refused:
                logger.error(
                    "indah ctx.persist(%r): this signal is shown in an ephemeral prop "
                    "(a secret), so it is never stored. Remove the persist call.",
                    item.name,
                )
                self._forget(item)
                self._drop_stored(item)
        self.ready = True
        if any(i.dirty for i in self.items.values()):
            self._schedule()

    def _forget(self, item: _Item) -> None:
        if item.effect is not None:
            item.effect.dispose()
        item.dirty = False
        self.items.pop(item.name, None)

    @staticmethod
    def _ephemeral_signals(components: Any) -> set[Signal[Any]]:
        found: set[Signal[Any]] = set()
        for component in components:
            if not component.ephemeral:
                continue
            for prop, getter in component.reactive_props().items():
                if prop not in component.ephemeral:
                    continue
                probe: Computation | None = None
                try:
                    probe = Computation(getter)  # reading inside one records what it reads
                    for dep in probe.deps:
                        found |= _closure(dep)
                except Exception:
                    logger.debug(
                        "indah ctx.persist could not probe an ephemeral prop", exc_info=True
                    )
                finally:
                    if probe is not None:
                        probe.dispose()
        return found

    def close(self) -> None:
        """The session ended: save what is pending, stop watching."""
        if self.closed:
            return
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self.ready:
            self.flush()
        self.closed = True
        for item in self.items.values():
            if item.effect is not None:
                item.effect.dispose()


def persistence_for(ctx: Context) -> _Persistence:
    """The persistence of ``ctx``, built from the app's settings on first use."""
    state_obj = getattr(ctx.app, "state", None)

    def setting(name: str, default: Any) -> Any:
        value = getattr(state_obj, name, default) if state_obj is not None else default
        return default if value is None else value

    store = setting("state_store", None)
    if store is None:
        store = MemoryStateStore()  # a bare Context: private, so nothing leaks between sessions
    return _Persistence(
        ctx=ctx,
        store=store,
        namespace=setting("state_namespace", DEFAULT_NAMESPACE),
        ttl=float(setting("persist_ttl", DEFAULT_TTL)),
        max_bytes=int(setting("persist_max_bytes", DEFAULT_MAX_BYTES)),
        session_bytes=int(setting("persist_session_bytes", DEFAULT_SESSION_BYTES)),
        delay=float(setting("persist_delay", DEFAULT_DELAY)),
    )

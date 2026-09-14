"""Fine-grained reactivity: signals, computeds, and effects (ADR-0003).

This is the answer to Streamlit's full-script rerun. State lives in ``Signal``s.
Reading a signal inside a computation auto-subscribes that computation; setting a
signal reruns only the computations that read it. A ``Computed`` is a derived
signal that recomputes when its inputs change and notifies its own readers only
when its result actually changes. An ``effect`` runs a side effect (in indah, it
emits a UI patch) when its tracked signals change.

Because updates flow only along real dependencies, a change produces the minimal
set of downstream work — no tree diffing needed. The runtime is single-threaded:
indah mutates signals inside asyncio event-loop callbacks, so no locking is used.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

# The computation currently running, so signal reads can auto-subscribe it.
_current: Computation | None = None

# Scheduler state: invalidated computations run in FIFO order, coalesced within a
# batch so one event flushes once.
_pending: list[Computation] = []
_scheduled: set[Computation] = set()
_batch_depth = 0
_flushing = False


class Signal(Generic[T]):
    """A reactive value. Read ``.value`` to subscribe; set it to notify readers."""

    def __init__(self, value: T) -> None:
        self._value = value
        self._subscribers: set[Computation] = set()

    @property
    def value(self) -> T:
        if _current is not None:
            self._subscribers.add(_current)
            _current.deps.add(self)
        return self._value

    @value.setter
    def value(self, new: T) -> None:
        self.set(new)

    def set(self, new: T) -> None:
        if new == self._value:
            return
        self._value = new
        self._notify()

    def peek(self) -> T:
        """Read without subscribing the current computation."""
        return self._value

    def _notify(self) -> None:
        for computation in list(self._subscribers):
            computation.invalidate()


class Computation:
    """A tracked side effect. Reruns when any signal it read has changed."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.deps: set[Signal] = set()
        self._run()

    def _run(self) -> None:
        global _current
        for dep in self.deps:
            dep._subscribers.discard(self)
        self.deps.clear()
        prev = _current
        _current = self
        try:
            self.fn()
        finally:
            _current = prev

    def invalidate(self) -> None:
        _schedule(self)

    def dispose(self) -> None:
        for dep in self.deps:
            dep._subscribers.discard(self)
        self.deps.clear()


class Computed(Signal[T]):
    """A signal derived from other signals; recomputes lazily-eagerly on change."""

    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__(value=None)  # type: ignore[arg-type]
        self._fn = fn
        self._computation = Computation(self._recompute)

    def _recompute(self) -> None:
        new = self._fn()
        if new != self._value:
            self._value = new
            self._notify()


def effect(fn: Callable[[], Any]) -> Computation:
    """Run ``fn`` now and again whenever a signal it read changes."""
    return Computation(fn)


def computed(fn: Callable[[], T]) -> Computed[T]:
    """A memoized derived signal."""
    return Computed(fn)


def batch(fn: Callable[[], Any]) -> None:
    """Run ``fn``, deferring all reruns until it returns (one coalesced flush)."""
    global _batch_depth
    _batch_depth += 1
    try:
        fn()
    finally:
        _batch_depth -= 1
        if _batch_depth == 0:
            _flush()


def _schedule(computation: Computation) -> None:
    if computation not in _scheduled:
        _scheduled.add(computation)
        _pending.append(computation)
    if _batch_depth == 0:
        _flush()


def _flush() -> None:
    # A computation may schedule more work as it runs; the running loop picks it
    # up rather than starting a nested flush.
    global _flushing
    if _flushing:
        return
    _flushing = True
    try:
        while _pending:
            computation = _pending.pop(0)
            _scheduled.discard(computation)
            computation._run()
    finally:
        _flushing = False

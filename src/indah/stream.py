"""``Stream``: an append-only reactive list, bounded by ``limit`` (IND-90, ADR-0026).

A ``Signal[list]`` re-sends the whole list on every change. For a growing log that is
O(n) per row, so a component bound to a ``Stream`` instead sends only the new rows as an
``append`` patch (plus a ``trim`` so the browser keeps just the newest ``limit``)::

    rows = Stream(limit=1000)
    List(rows, item={...})
    rows.append({"id": 1, "text": "hello"})      # one small append patch, coalesced

Everything else reads a stream like any signal: ``stream.value`` is the bounded list and
a ``computed`` over it updates on every append. ``set`` and ``clear`` are replaces.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .reactive import Signal

# A listener hears ("append", new_rows) or ("replace", full_list).
StreamListener = Callable[[str, list[Any]], None]


class Stream(Signal[list]):
    def __init__(self, items: Iterable[Any] = (), *, limit: int = 1000) -> None:
        if limit < 1:
            raise ValueError("Stream limit must be at least 1")
        super().__init__(list(items)[-limit:])
        self.limit = limit
        self._listeners: list[StreamListener] = []

    def listen(self, fn: StreamListener) -> Callable[[], None]:
        """Subscribe to changes; returns the function that unsubscribes."""
        self._listeners.append(fn)

        def off() -> None:
            if fn in self._listeners:
                self._listeners.remove(fn)

        return off

    def append(self, *rows: Any) -> None:
        """Add rows at the end, dropping the oldest beyond ``limit``."""
        if not rows:
            return
        self._value = (self._value + list(rows))[-self.limit :]
        self._notify()
        for fn in list(self._listeners):
            fn("append", list(rows))

    def set(self, new: list) -> None:
        self._value = list(new)[-self.limit :]
        self._notify()
        for fn in list(self._listeners):
            fn("replace", list(self._value))

    def clear(self) -> None:
        self.set([])

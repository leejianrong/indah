"""UI components: a tree of nodes, each serialisable to JSON (ADR-0005).

A component holds static props and, where a prop is bound to a signal, a getter
that reads it. The session (session.py) assigns each node a stable id, serialises
the tree for the ``init`` message, and wires an effect per reactive prop so a
signal change emits a minimal patch for exactly that node.

Domain logic stays out of here: a Button's ``on_click`` is a plain callable the
caller supplies, and a Slider writes to a plain Signal (ADR-0009).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .reactive import Computed, Signal

# A prop value may be static, a signal/computed, or a zero-arg callable.
Source = Any


def _read(source: Source) -> Any:
    if isinstance(source, (Signal, Computed)):
        return source.value
    if callable(source):
        return source()
    return source


class Component:
    type: str = "component"

    def __init__(self, children: list[Component] | None = None) -> None:
        self.id: str | None = None
        self.children: list[Component] = children or []

    def static_props(self) -> dict[str, Any]:
        return {}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        """Prop name -> getter. Getters read signals, so effects can track them."""
        return {}

    def handle(self, event: str, payload: dict[str, Any]) -> bool:
        """Apply a client event. Return True if handled, False otherwise."""
        return False

    def to_json(self) -> dict[str, Any]:
        props = dict(self.static_props())
        for name, getter in self.reactive_props().items():
            props[name] = getter()
        return {
            "id": self.id,
            "type": self.type,
            "props": props,
            "children": [child.to_json() for child in self.children],
        }


class Column(Component):
    type = "column"


class Text(Component):
    type = "text"

    def __init__(self, source: Source) -> None:
        super().__init__()
        self._source = source

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"text": lambda: str(_read(self._source))}


class Button(Component):
    type = "button"

    def __init__(self, label: Source, on_click: Callable[[], Any] | None = None) -> None:
        super().__init__()
        self._label = label
        self._on_click = on_click

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"label": lambda: str(_read(self._label))}

    def handle(self, event: str, payload: dict[str, Any]) -> bool:
        if event == "click" and self._on_click is not None:
            self._on_click()
            return True
        return False


class Slider(Component):
    type = "slider"

    def __init__(
        self,
        value: Signal[float],
        *,
        min: float = 0,
        max: float = 100,
        step: float = 1,
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        self._min = min
        self._max = max
        self._step = step
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"min": self._min, "max": self._max, "step": self._step, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool:
        if event == "input" and "value" in payload:
            self._value.set(payload["value"])
            return True
        return False


def walk(root: Component):
    """Yield every component in the tree, pre-order."""
    yield root
    for child in root.children:
        yield from walk(child)

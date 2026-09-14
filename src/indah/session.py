"""A session ties a component tree to the reactive graph and the wire protocol.

It assigns stable node ids, produces the ``init`` snapshot, wires one effect per
reactive prop (so a signal change emits a patch for exactly that node), and
dispatches client events back into the graph.

Slice 2 keeps a single shared session per app. Per-session isolation for multiple
concurrent users arrives with the state seam (ADR-0010).
"""

from __future__ import annotations

from typing import Any

from .components import Component, walk
from .reactive import Computation, batch, effect


class Session:
    def __init__(self, root: Component) -> None:
        self.root = root
        self._by_id: dict[str, Component] = {}
        self._effects: list[Computation] = []
        # When set (during event dispatch), reactive updates collect here as
        # {node_id: {prop: value}} instead of being ignored.
        self._sink: dict[str, dict[str, Any]] | None = None

        self._assign_ids()
        self._wire()

    def _assign_ids(self) -> None:
        for index, component in enumerate(walk(self.root)):
            component.id = f"n{index}"
            self._by_id[component.id] = component

    def _wire(self) -> None:
        for component in walk(self.root):
            for prop_name, getter in component.reactive_props().items():
                self._effects.append(self._make_effect(component.id, prop_name, getter))

    def _make_effect(self, node_id: str, prop_name: str, getter):
        state = {"initialised": False}

        def run() -> None:
            value = getter()  # reads signals -> subscribes this effect
            if state["initialised"]:
                self._emit(node_id, prop_name, value)
            else:
                state["initialised"] = True

        return effect(run)

    def _emit(self, node_id: str, prop_name: str, value: Any) -> None:
        if self._sink is None:
            return
        self._sink.setdefault(node_id, {})[prop_name] = value

    def snapshot(self) -> dict[str, Any]:
        """The full component tree as JSON, for the ``init`` message."""
        return self.root.to_json()

    def dispatch(self, component_id: str, event: str, payload: dict[str, Any]) -> list[dict] | None:
        """Apply a client event; return the patch changes, or None if unhandled."""
        component = self._by_id.get(component_id)
        if component is None:
            return None

        self._sink = {}
        handled = {"ok": False}

        def apply() -> None:
            handled["ok"] = component.handle(event, payload or {})

        try:
            batch(apply)
        finally:
            collected = self._sink
            self._sink = None

        if not handled["ok"]:
            return None
        return [{"target": node_id, "props": props} for node_id, props in collected.items()]

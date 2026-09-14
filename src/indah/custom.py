"""Custom components: register a new UI type without forking the framework (R7).

The pre-built Svelte shell (ADR-0004) cannot gain a new hand-written component at
runtime -- that would need a Node build. Instead a custom component ships a small,
declarative *render spec* (protocol.RenderSpec) that the shell's generic renderer
interprets at runtime. The spec is keyed off the public JSON protocol (ADR-0005)
and travels on the wire as the reserved ``_spec`` prop, so no shell rebuild and no
runtime Node are involved (ADR-0012).

Usage::

    import indah

    indah.register_component(
        "colorpicker",
        render={
            "tag": "input",
            "attrs": {"type": "color"},
            "bind": {"value": "value"},          # element value <- node prop "value"
            "on": {"input": {"event": "input", "prop": "value"}},  # round-trip
        },
    )

    colour = indah.Signal("#ff8800")
    picker = indah.custom("colorpicker", value=colour)   # value-bearing, two-way

Set ``colour`` from Python and the swatch updates; pick a colour in the UI and
``colour.value`` reflects it -- the same round-trip as a built-in input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .components import Component, _read
from .protocol import BUILTIN_TYPES, RenderSpec
from .reactive import Computed, Signal


@dataclass
class Registration:
    """A registered custom component type."""

    type: str
    render: dict[str, Any]  # the render spec as it travels on the wire
    events: dict[str, str] = field(default_factory=dict)  # indah event -> bound prop


_REGISTRY: dict[str, Registration] = {}


def register_component(component_type: str, *, render: dict[str, Any]) -> Registration:
    """Register a custom component type against the public protocol (ADR-0012).

    ``component_type`` is the wire ``type`` (and must not collide with a built-in);
    ``render`` is a :class:`~indah.protocol.RenderSpec` describing how the shell's
    generic renderer builds it. Raises ``ValueError`` if the type is invalid or the
    render spec violates the protocol schema (e.g. a disallowed tag).
    """
    if not isinstance(component_type, str) or not component_type:
        raise ValueError("component_type must be a non-empty string")
    if component_type in BUILTIN_TYPES:
        raise ValueError(f"{component_type!r} is a built-in component type")

    spec = RenderSpec.model_validate(render).validated()

    # Derive the round-trip map: indah event name -> the node prop it writes.
    events = {ev.event: ev.prop for ev in spec.on.values() if ev.prop is not None}

    registration = Registration(type=component_type, render=spec.wire(), events=events)
    _REGISTRY[component_type] = registration
    return registration


def registered(component_type: str) -> Registration | None:
    return _REGISTRY.get(component_type)


def clear_registry() -> None:
    """Drop all registrations (used by tests to stay isolated)."""
    _REGISTRY.clear()


def custom(component_type: str, **props: Any) -> CustomComponent:
    """Instantiate a registered custom component, binding props to signals or values."""
    registration = _REGISTRY.get(component_type)
    if registration is None:
        raise ValueError(f"{component_type!r} is not registered; call register_component() first")
    return CustomComponent(registration, props)


class CustomComponent(Component):
    """An instance of a registered custom type.

    Props bound to a ``Signal`` are reactive (patched when the signal changes) and
    can be written back from the UI; other props are static. The render spec rides
    along once as the static ``_spec`` prop so the shell can render the node.
    """

    def __init__(self, registration: Registration, bindings: dict[str, Any]) -> None:
        super().__init__()
        self.type = registration.type
        self._reg = registration
        self._bindings = bindings

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"_spec": self._reg.render}
        for name, source in self._bindings.items():
            if not isinstance(source, (Signal, Computed)):
                props[name] = _read(source)
        return props

    def reactive_props(self):
        return {
            name: (lambda s=source: s.value)
            for name, source in self._bindings.items()
            if isinstance(source, (Signal, Computed))
        }

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        prop = self._reg.events.get(event)
        if prop is not None and "value" in payload:
            target = self._bindings.get(prop)
            if isinstance(target, Signal):
                target.set(payload["value"])
                return True
        return False

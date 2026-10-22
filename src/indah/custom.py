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

A component that needs more than one allow-listed element (a drawing, per-item state, its own
events) ships an ES module instead (ADR-0039)::

    indah.register_component(
        "tier-rail",
        module="static/tier-rail.js",         # a file or bytes, read once; never a URL
        events=["pick"],                      # CustomEvents forwarded to Python
        two_way={"value": "change"},          # prop <- CustomEvent detail.value
        fallback="steps",                     # a prop shown as text if the module cannot run
    )
    rail = indah.custom("tier-rail", steps=steps, value=picked, on_pick=handle_pick)

The module's default export is an ``HTMLElement`` class; the shell defines it as
``indah-x-tier-rail``, sets the props as properties and forwards the declared events.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .components import Component, _read
from .protocol import BUILTIN_TYPES, RenderSpec
from .reactive import Computed, Signal

MAX_MODULE_BYTES = 1024 * 1024  # 1 MB per module (ADR-0039)
MAX_MODULES = 64  # registered module types per process

_TYPE_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_PROP_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_URL_LIKE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]+:|//)")


@dataclass
class Registration:
    """A registered custom component type: a render spec, or an ES module (ADR-0039)."""

    type: str
    render: dict[str, Any] | None = None  # the render spec as it travels on the wire
    events: dict[str, str] = field(default_factory=dict)  # indah event -> bound prop (spec)
    module: bytes | None = None  # the ES module's source, held in memory
    module_hash: str = ""
    forward: tuple[str, ...] = ()  # CustomEvent names forwarded to Python (module)
    two_way: dict[str, str] = field(default_factory=dict)  # prop -> CustomEvent (module)
    fallback: str | None = None  # prop shown as text when the module cannot run

    def module_wire(self) -> dict[str, Any]:
        """The reserved static ``_module`` prop: how the shell loads and wires the module."""
        wire: dict[str, Any] = {
            "url": f"api/components/{self.type}.js?v={self.module_hash}",
            "tag": f"indah-x-{self.type}",
            "events": list(self.forward),
        }
        if self.two_way:
            wire["twoWay"] = list(self.two_way)
        if self.fallback:
            wire["fallback"] = self.fallback
        return wire


_REGISTRY: dict[str, Registration] = {}


def _read_module(module: str | os.PathLike[str] | bytes) -> bytes:
    """The module's bytes, from a file (read once, now) or given directly. Never a URL."""
    if isinstance(module, (bytes, bytearray)):
        data = bytes(module)
    else:
        if isinstance(module, str) and _URL_LIKE.match(module):
            raise ValueError(
                "module must be a file path or bytes, not a URL: the shell loads only code "
                "the app serves itself (ADR-0039); vendor the file"
            )
        try:
            data = Path(module).read_bytes()
        except FileNotFoundError:
            raise ValueError(f"module file not found: {module}") from None
        except OSError as exc:
            raise ValueError(f"module file cannot be read: {module} ({exc})") from None
    if not data:
        raise ValueError("module is empty")
    if len(data) > MAX_MODULE_BYTES:
        raise ValueError(f"module is too large ({len(data)} bytes; the limit is 1 MB)")
    return data


def register_component(
    component_type: str,
    *,
    render: dict[str, Any] | None = None,
    module: str | os.PathLike[str] | bytes | None = None,
    events: list[str] | tuple[str, ...] = (),
    two_way: dict[str, str] | None = None,
    fallback: str | None = None,
) -> Registration:
    """Register a custom component type against the public protocol (ADR-0012, ADR-0039).

    ``component_type`` is the wire ``type`` (and must not collide with a built-in). Give exactly
    one of:

    * ``render`` -- a :class:`~indah.protocol.RenderSpec` describing how the shell's generic
      renderer builds it;
    * ``module`` -- an ES module (a file path or bytes, read once now, at most 1 MB) whose default
      export is an ``HTMLElement`` class. ``events`` names the CustomEvents forwarded to Python
      (``custom(..., on_<event>=handler)``), ``two_way`` maps a prop to the CustomEvent whose
      ``detail.value`` is written back to the bound signal, and ``fallback`` names a prop shown
      as text if the module cannot load or run. The type must be a lowercase, hyphenated name.

    Raises ``ValueError`` if the type is invalid or the render spec or module violates the schema.
    """
    if not isinstance(component_type, str) or not component_type:
        raise ValueError("component_type must be a non-empty string")
    if component_type in BUILTIN_TYPES:
        raise ValueError(f"{component_type!r} is a built-in component type")
    if (render is None) == (module is None):
        raise ValueError("pass exactly one of render= and module=")

    if module is not None:
        registration = _module_registration(component_type, module, events, two_way, fallback)
    else:
        if events or two_way or fallback:
            raise ValueError("events=, two_way= and fallback= go with module=")
        spec = RenderSpec.model_validate(render).validated()
        # Derive the round-trip map: indah event name -> the node prop it writes. A nested
        # element's ``on`` counts too, so a composite can carry its input anywhere in the tree.
        derived: dict[str, str] = {}
        _collect_events(spec, derived)
        registration = Registration(type=component_type, render=spec.wire(), events=derived)
    _REGISTRY[component_type] = registration
    return registration


def _module_registration(
    component_type: str,
    module: str | os.PathLike[str] | bytes,
    events: list[str] | tuple[str, ...],
    two_way: dict[str, str] | None,
    fallback: str | None,
) -> Registration:
    if not _TYPE_NAME.match(component_type):
        raise ValueError(
            f"a module component's type must be lowercase words joined by hyphens "
            f"(like 'tier-rail'), got {component_type!r}"
        )
    existing = _REGISTRY.get(component_type)
    if existing is None or existing.module is None:
        if sum(1 for r in _REGISTRY.values() if r.module is not None) >= MAX_MODULES:
            raise ValueError(f"too many module components (the limit is {MAX_MODULES})")
    data = _read_module(module)
    forward = list(events)
    two = dict(two_way or {})
    for name in [*forward, *two.values()]:
        if not isinstance(name, str) or not _EVENT_NAME.match(name):
            raise ValueError(f"event name {name!r} must be lowercase letters, digits, - or _")
    for prop in [*two, *([fallback] if fallback else [])]:
        if not isinstance(prop, str) or not _PROP_NAME.match(prop):
            raise ValueError(f"prop name {prop!r} is not a valid prop name")
    for name in two.values():
        if name not in forward:
            forward.append(name)
    return Registration(
        type=component_type,
        module=data,
        module_hash=hashlib.sha256(data).hexdigest()[:16],
        forward=tuple(forward),
        two_way=two,
        fallback=fallback,
    )


def _collect_events(spec: RenderSpec, into: dict[str, str]) -> None:
    for ev in spec.on.values():
        if ev.prop is not None:
            into.setdefault(ev.event, ev.prop)
    for child in spec.children:
        _collect_events(child, into)


def registered(component_type: str) -> Registration | None:
    return _REGISTRY.get(component_type)


def clear_registry() -> None:
    """Drop all registrations (used by tests to stay isolated)."""
    _REGISTRY.clear()


def custom(component_type: str, **props: Any) -> CustomComponent:
    """Instantiate a registered custom component, binding props to signals or values.

    For a module component (ADR-0039), ``on_<event>=fn`` attaches a handler for a declared
    CustomEvent; ``fn`` receives the event's ``detail`` and may be ``async``."""
    registration = _REGISTRY.get(component_type)
    if registration is None:
        raise ValueError(f"{component_type!r} is not registered; call register_component() first")
    handlers: dict[str, Callable[[Any], Any]] = {}
    if registration.module is not None:
        for name in [k for k in props if k.startswith("on_")]:
            event = name[3:].replace("_", "-") if name[3:] not in registration.forward else name[3:]
            if event not in registration.forward or not callable(props[name]):
                raise ValueError(
                    f"{name}= needs a callable and a declared event "
                    f"(declared: {', '.join(registration.forward) or 'none'})"
                )
            handlers[event] = props.pop(name)
    component = CustomComponent(registration, props)
    component._handlers = handlers
    return component


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
        self._handlers: dict[str, Callable[[Any], Any]] = {}

    def static_props(self) -> dict[str, Any]:
        if self._reg.module is not None:
            props: dict[str, Any] = {"_module": self._reg.module_wire()}
        else:
            props = {"_spec": self._reg.render}
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
        if self._reg.module is not None:
            return self._handle_module(event, payload)
        prop = self._reg.events.get(event)
        if prop is not None and "value" in payload:
            target = self._bindings.get(prop)
            if isinstance(target, Signal):
                target.set(payload["value"])
                return True
        return False

    def _handle_module(self, event: str, payload: dict[str, Any]) -> bool | Any:
        """A CustomEvent forwarded from the module: write a two-way prop, call the handler."""
        if event not in self._reg.forward:
            return False
        detail = payload.get("detail")
        handled = False
        for prop, name in self._reg.two_way.items():
            target = self._bindings.get(prop)
            if name == event and isinstance(detail, dict) and "value" in detail:
                if isinstance(target, Signal):
                    target.set(detail["value"])
                    handled = True
        handler = self._handlers.get(event)
        if handler is not None:
            result = handler(detail)
            if inspect.iscoroutine(result):
                return result  # async handler: the session awaits it in the background
            handled = True
        return handled

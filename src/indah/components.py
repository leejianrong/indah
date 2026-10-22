"""UI components: a tree of nodes, each serialisable to JSON (ADR-0005).

A component holds static props and, where a prop is bound to a signal, a getter
that reads it. The session (session.py) assigns each node a stable id, serialises
the tree for the ``init`` message, and wires an effect per reactive prop so a
signal change emits a minimal patch for exactly that node.

Domain logic stays out of here: a Button's ``on_click`` is a plain callable the
caller supplies, a Slider writes to a plain Signal, and a StreamText is fed by a
plain async generator the caller wraps (ADR-0009).
"""

from __future__ import annotations

import asyncio
import base64
import functools
import inspect
import io
import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from .csp import register_img_host
from .diff import compute_diff
from .keys import normalize_keys
from .markdown import to_blocks
from .protocol import RenderSpec
from .reactive import Computed, Signal, effect
from .routes import compile_route, match_routes, normalize_path
from .stream import Stream

if TYPE_CHECKING:
    from .context import Context
    from .session import Session

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
    # Hover/focus hint shown by the shell (ADR-0030). Every subclass constructor accepts
    # ``tooltip=`` (see ``__init_subclass__``); a plain attribute also works.
    tooltip: str | None = None
    # A component whose event payload must never reach an audit log (a password field). A
    # subclass overrides it, as a class attribute or a property.
    sensitive: bool = False
    # Props that carry a secret (ADR-0036). They are sent live to the open stream but never
    # kept: left out of the ``init`` snapshot and out of the hub's replay history, so a
    # reconnect cannot be handed them. Clearing one (``None``) carries no secret and is kept.
    ephemeral: frozenset[str] = frozenset()

    def __init__(
        self, children: list[Component] | None = None, *, tooltip: str | None = None
    ) -> None:
        self.id: str | None = None
        self.children: list[Component] = children or []
        if tooltip is not None:
            self.tooltip = tooltip

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        init = cls.__dict__.get("__init__")
        if init is None:
            return

        @functools.wraps(init)
        def __init__(self: Component, *args: Any, tooltip: str | None = None, **kw: Any) -> None:
            init(self, *args, **kw)
            if tooltip is not None:
                self.tooltip = tooltip

        cls.__init__ = __init__  # type: ignore[method-assign]

    def static_props(self) -> dict[str, Any]:
        return {}

    def forget(self) -> None:
        """Drop any secret held in an ephemeral prop. Called when the session ends and when a
        tab (re)connects with a fresh ``init``, which cannot carry it (ADR-0036)."""

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        """Prop name -> getter. Getters read signals, so effects can track them."""
        return {}

    def stream_props(self) -> dict[str, tuple[Stream, Callable[[list[Any]], list[Any]]]]:
        """Reactive props fed by a ``Stream``: prop name -> (stream, row -> wire).

        The session sends these as ``append`` patches instead of re-sending the whole
        prop on every change (IND-90). The prop must also appear in ``reactive_props``
        so the ``init`` snapshot carries its current value."""
        return {}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        """Apply a client event.

        Return ``False`` if unhandled, ``True`` if handled synchronously, or a
        coroutine if the handler is async (the session awaits it as a background
        task so long work never blocks the request or the event loop).
        """
        return False

    def to_json(self) -> dict[str, Any]:
        props = dict(self.static_props())
        for name, getter in self.reactive_props().items():
            if name not in self.ephemeral:
                props[name] = getter()
        if self.tooltip:
            props["tooltip"] = self.tooltip
        return {
            "id": self.id,
            "type": self.type,
            "props": props,
            "children": [child.to_json() for child in self.children],
        }


class Column(Component):
    """A vertical stack of children. ``gap`` (a CSS length) overrides the default spacing."""

    type = "column"

    def __init__(self, children: list[Component] | None = None, *, gap: str = "") -> None:
        super().__init__(children)
        self._gap = gap

    def static_props(self) -> dict[str, Any]:
        return {"gap": self._gap} if self._gap else {}


_CARD_VARIANTS = ("outlined", "flat", "tonal")
_JUSTIFY = ("start", "center", "end", "between", "around")


class Card(Component):
    """A surface panel: a titled card that floats on the page ground (ADR-0014).

    The building block of the "panels on warm porcelain" Studio layout -- wrap a
    region's children in a ``Card`` to give it a surface, radius, and soft shadow.
    ``title`` renders a small uppercase panel heading. ``variant`` is ``"outlined"`` (the
    default: border and shadow), ``"flat"`` (no border, no shadow, no surface: the children
    sit on the page) or ``"tonal"`` (a tinted fill, no border). ``padding`` is a CSS length
    that replaces the default inner padding.
    """

    type = "card"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        title: str = "",
        variant: str = "outlined",
        padding: str = "",
    ) -> None:
        super().__init__(children)
        if variant not in _CARD_VARIANTS:
            raise ValueError(f"Card variant must be one of {_CARD_VARIANTS}, got {variant!r}")
        self._title = title
        self._variant = variant
        self._padding = padding

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"title": self._title}
        if self._variant != "outlined":
            props["variant"] = self._variant
        if self._padding:
            props["padding"] = self._padding
        return props


class Text(Component):
    """A text display bound to a source.

    With ``markdown=True`` the source is rendered as a safe subset of Markdown: it
    is parsed (server-side) into a block tree the shell renders through its safe DOM
    builder, so raw HTML stays literal and nothing can inject script (see
    ``markdown.py``). The node then carries ``blocks`` instead of ``text``.

    Plain text is a *readout*: large and semi-bold, made for a counter or a figure.
    ``size="body"`` renders it as ordinary body text instead (normal size and weight,
    newlines kept), for a status line or a short note. Plain text never interprets
    markup; use ``markdown=True`` for backticks, emphasis or links.
    """

    type = "text"

    def __init__(self, source: Source, *, markdown: bool = False, size: str = "readout") -> None:
        super().__init__()
        if size not in ("readout", "body"):
            raise ValueError(f"size must be 'readout' or 'body', not {size!r}")
        self._source = source
        self._markdown = markdown
        self._size = size

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"markdown": True} if self._markdown else {}
        if self._size == "body":
            props["size"] = "body"
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._markdown:
            return {"blocks": lambda: to_blocks(str(_read(self._source)))}
        return {"text": lambda: str(_read(self._source))}


class Button(Component):
    """A clickable button.

    ``variant`` picks the Studio treatment: ``"filled"`` (default, the magenta
    primary), ``"tonal"`` (the teal secondary container -- a softer secondary
    action), or ``"ghost"`` (outline only). It is a static styling prop; the
    click behaviour is identical.
    """

    type = "button"

    def __init__(
        self,
        label: Source,
        on_click: Callable[[], Any] | None = None,
        *,
        variant: str = "filled",
        confirm: str | None = None,
    ) -> None:
        super().__init__()
        self._label = label
        self._on_click = on_click
        self._variant = variant
        # ``confirm`` makes the shell ask first; the click is only posted once the
        # user accepts. It is a UX guard, not authorization: the server still runs
        # any click it receives (ADR-0030).
        self._confirm = confirm

    def static_props(self) -> dict[str, Any]:
        # Only emit non-default props, so a plain Button stays minimal on the wire.
        props: dict[str, Any] = {}
        if self._variant != "filled":
            props["variant"] = self._variant
        if self._confirm:
            props["confirm"] = self._confirm
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"label": lambda: str(_read(self._label))}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "click" and self._on_click is not None:
            result = self._on_click()
            if inspect.iscoroutine(result):
                return result  # async handler: the session awaits it in the background
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

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(payload["value"])
            return True
        return False


class TextInput(Component):
    """A single-line text box two-way bound to a ``Signal[str]``.

    Needed for the Slice 3 demo's prompt box; part of the R5 starter set (V4).
    """

    type = "textinput"

    def __init__(
        self,
        value: Signal[str],
        *,
        placeholder: str = "",
        label: str = "",
        password: bool = False,
        on_submit: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self._value = value
        self._placeholder = placeholder
        self._label = label
        # ``password`` masks the field (``<input type=password>``) for secrets like an
        # API key. It is only display masking - the value still round-trips to the
        # server like any input, so keep it in session state and never log it.
        self._password = password
        self._on_submit = on_submit

    @property
    def sensitive(self) -> bool:  # type: ignore[override]
        return self._password

    def static_props(self) -> dict[str, Any]:
        return {
            "placeholder": self._placeholder,
            "label": self._label,
            "password": self._password,
        }

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        if event == "submit":
            # Enter in the box. Always handled (a no-op without on_submit, so it
            # never 400s); runs on_submit sync or async, like a Button click.
            if self._on_submit is not None:
                result = self._on_submit()
                if inspect.iscoroutine(result):
                    return result
            return True
        return False


class TextArea(Component):
    """A multiline text box two-way bound to a ``Signal[str]`` (IND-98).

    Like :class:`TextInput` the focused element is client-owned (ADR-0013), and the
    shell also debounces keystrokes and flushes on blur, so a long note is not one
    POST per character. There is no submit event: Enter inserts a newline.
    """

    type = "textarea"

    def __init__(
        self,
        value: Signal[str],
        *,
        placeholder: str = "",
        label: str = "",
        rows: int = 4,
    ) -> None:
        super().__init__()
        self._value = value
        self._placeholder = placeholder
        self._label = label
        self._rows = rows

    def static_props(self) -> dict[str, Any]:
        return {"placeholder": self._placeholder, "label": self._label, "rows": self._rows}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


CODE_LANGUAGES = ("json", "yaml", "text")


class CodeEditor(Component):
    """A syntax-aware editor for data and config text, two-way bound to a ``Signal[str]``
    (ADR-0032): highlighting, auto-indent, auto-closing brackets and quotes, bracket
    matching, folding, search, line numbers, and (for JSON) lint with the error position.

    ``language`` is ``"json"`` (default), ``"yaml"`` or ``"text"``. ``read_only`` shows a
    value without letting the viewer change it. ``lint=False`` turns the JSON check off.
    ``height`` is a CSS length (default ``24rem``); the editor scrolls inside it.
    ``format_button=True`` (JSON only, not read-only) adds a Format button that re-indents
    the JSON with two spaces and keeps the key order; text that is not valid JSON is left
    as it is. ``on_save`` makes Ctrl/Cmd-S call it, after the signal holds the latest text.

    The editor is a separate same-origin file the shell fetches the first time one renders,
    so apps without an editor never download it; if it cannot load, a plain text area with
    the same binding is shown. Like the other inputs the focused editor is client-owned
    (ADR-0013), keystrokes are debounced and flushed on blur, and a large value is bounded
    by ``create_app(max_event_bytes=)``. Tab indents; press Ctrl-M (Cmd-M) to turn that off
    so the keyboard can leave the editor.
    """

    type = "codeeditor"

    def __init__(
        self,
        value: Signal[str],
        *,
        language: str = "json",
        read_only: bool = False,
        lint: bool = True,
        height: str = "24rem",
        label: str = "",
        placeholder: str = "",
        format_button: bool = False,
        on_save: Callable[[], Any] | None = None,
    ) -> None:
        if language not in CODE_LANGUAGES:
            raise ValueError(
                f"CodeEditor language must be one of {CODE_LANGUAGES}, got {language!r}"
            )
        if not _CSS_LENGTH.match(height):
            raise ValueError(f"CodeEditor height {height!r} must be a length like '24rem'")
        super().__init__()
        self._value = value
        self._language = language
        self._read_only = bool(read_only)
        self._lint = bool(lint)
        self._height = height
        self._label = label
        self._placeholder = placeholder
        self._format = bool(format_button) and language == "json" and not read_only
        self._on_save = on_save

    def static_props(self) -> dict[str, Any]:
        return {
            "format": self._format,
            "save": self._on_save is not None,
            "language": self._language,
            "readOnly": self._read_only,
            "lint": self._lint,
            "height": self._height,
            "label": self._label,
            "placeholder": self._placeholder,
        }

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: str(self._value.value or "")}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if self._read_only or "value" not in payload:
            return False
        text = str(payload["value"])
        if event == "input":
            self._value.set(text)
            return True
        if event == "format" and self._format:
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                return False  # not valid JSON: leave the text alone
            self._value.set(text)
            return True
        if event == "save" and self._on_save is not None:
            self._value.set(text)
            result = self._on_save()
            return result if inspect.iscoroutine(result) else True
        return False


class Checkbox(Component):
    """A checkbox two-way bound to a ``Signal[bool]`` (R5)."""

    type = "checkbox"

    def __init__(self, value: Signal[bool], *, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"checked": lambda: bool(self._value.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "change" and "value" in payload:
            self._value.set(bool(payload["value"]))
            return True
        return False


class Switch(Component):
    """A toggle switch two-way bound to a ``Signal[bool]``: a :class:`Checkbox` drawn as
    a ``role="switch"`` control, for an immediate on/off setting (a pin, a flag)."""

    type = "switch"

    def __init__(self, value: Signal[bool], *, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"checked": lambda: bool(self._value.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "change" and "value" in payload:
            self._value.set(bool(payload["value"]))
            return True
        return False


BADGE_TONES = ("neutral", "ok", "warn", "err", "info")


class Badge(Component):
    """A small status chip. ``text`` may be a string, signal or callable; ``tone`` is one
    of ``neutral``/``ok``/``warn``/``err``/``info`` (the same tones as a Table badge)."""

    type = "badge"

    def __init__(self, text: Source, *, tone: str = "neutral") -> None:
        if tone not in BADGE_TONES:
            raise ValueError(f"Badge tone must be one of {BADGE_TONES}, got {tone!r}")
        super().__init__()
        self._text = text
        self._tone = tone

    def static_props(self) -> dict[str, Any]:
        return {"tone": self._tone}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"text": lambda: str(_read(self._text))}


class SecretReveal(Component):
    """Show a secret once (a new API token), with Copy and "I have saved it" buttons.

    ``value`` is a ``Signal[str | None]``: set it to the secret to reveal it, ``None`` (the
    default) shows nothing. The value is an *ephemeral prop* (ADR-0036): it goes to the open
    tab only, never into the ``init`` snapshot or the replay history, so a reload or a
    reconnect cannot show it again. It is cleared when the user dismisses it and when the
    session closes. If the connection drops before the user has copied it, issue a new one.

    Never put a secret in an exception message: a failing handler's message is echoed to the
    tab as a toast. The component is ``sensitive``, so an audit hook never records its events'
    payloads. ``on_dismiss`` runs after the value has been cleared.
    """

    type = "secretreveal"
    sensitive = True
    ephemeral = frozenset({"value"})

    def __init__(
        self,
        value: Signal[str | None],
        *,
        label: str = "",
        on_dismiss: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self._value = value
        self._label = label
        self._on_dismiss = on_dismiss

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "dismiss":
            self._value.set(None)
            if self._on_dismiss is not None:
                result = self._on_dismiss()
                if inspect.iscoroutine(result):
                    return result
            return True
        return False

    def forget(self) -> None:
        self._value.set(None)


class Number(Component):
    """A numeric input two-way bound to a ``Signal[float]`` (R5).

    Like a Slider without the track: a plain number box with optional bounds.
    """

    type = "number"

    def __init__(
        self,
        value: Signal[float],
        *,
        min: float | None = None,
        max: float | None = None,
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

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "input" and "value" in payload:
            self._value.set(payload["value"])
            return True
        return False


class Date(Component):
    """A date picker two-way bound to a ``Signal[str]`` (ISO ``YYYY-MM-DD``) (R5)."""

    type = "date"

    def __init__(self, value: Signal[str], *, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("input", "change") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


def _normalise_option(option: Any) -> dict[str, str]:
    """Accept ``"a"`` or ``("value", "Label")`` -> ``{"value","label"}`` (both str).

    HTML ``<select>`` values are strings on the wire, so a Select rounds-trips
    string values; pass ``(value, label)`` tuples when the shown text differs from
    the value.
    """
    if isinstance(option, (tuple, list)) and len(option) == 2:
        value, label = option
        return {"value": str(value), "label": str(label)}
    return {"value": str(option), "label": str(option)}


def _options_are_live(options: Any) -> bool:
    """True when ``options`` is a Signal, a Computed or a callable (not a plain list)."""
    return isinstance(options, (Signal, Computed)) or (
        callable(options) and not isinstance(options, (list, tuple))
    )


def _wire_options(
    comp: Component, options: Any, normalise: Callable[[Any], dict[str, Any]]
) -> None:
    """Remember where a control's options come from; read them now so a bad option fails at
    construction, as before. A live source is re-read whenever the signals it uses change."""
    comp._options_src = options  # type: ignore[attr-defined]
    comp._options_live = _options_are_live(options)  # type: ignore[attr-defined]
    comp._options_norm = normalise  # type: ignore[attr-defined]
    comp._options = [normalise(o) for o in _read(options)]  # type: ignore[attr-defined]


def _options_static(comp: Component) -> dict[str, Any]:
    return {} if comp._options_live else {"options": comp._options}  # type: ignore[attr-defined]


def _options_reactive(comp: Component) -> dict[str, Callable[[], Any]]:
    if not comp._options_live:  # type: ignore[attr-defined]
        return {}
    return {
        "options": lambda: [
            comp._options_norm(o)  # type: ignore[attr-defined]
            for o in _read(comp._options_src)  # type: ignore[attr-defined]
        ]
    }


def _prune_to_options(comp: Component, value: Signal[Any]) -> None:
    """For a multi-value control with live options: when the options change, drop selected
    values that are no longer offered. A single-value control is left alone."""
    if not comp._options_live:  # type: ignore[attr-defined]
        return
    armed = False

    def run() -> None:
        nonlocal armed
        present = {
            comp._options_norm(o)["value"]  # type: ignore[attr-defined]
            for o in _read(comp._options_src)  # type: ignore[attr-defined]
        }
        if armed:
            current = list(value.peek())
            kept = [v for v in current if v in present]
            if kept != current:
                value.set(kept)
        armed = True

    comp._options_effect = effect(run)  # type: ignore[attr-defined]


class Select(Component):
    """A drop-down two-way bound to a ``Signal[str]`` (R5, value-bearing).

    Set the signal from Python and the selection updates; choose in the UI and the
    signal is readable in Python (via the ``change`` event). ``options`` may be a list, or a
    Signal, Computed or callable returning one: the control follows it with no reload, and the
    signal is left alone (a value no longer offered is for the app to handle).
    """

    type = "select"

    def __init__(
        self,
        value: Signal[str],
        *,
        options: list[Any],
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        _wire_options(self, options, _normalise_option)
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {**_options_static(self), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value, **_options_reactive(self)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


class Radio(Component):
    """A radio group two-way bound to a ``Signal[str]`` (R5).

    Like a Select, but shows every option at once. Options are ``"a"`` or
    ``(value, label)`` tuples, same as Select.
    """

    type = "radio"

    def __init__(self, value: Signal[str], *, options: list[Any], label: str = "") -> None:
        super().__init__()
        self._value = value
        _wire_options(self, options, _normalise_option)
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {**_options_static(self), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value, **_options_reactive(self)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            self._value.set(str(payload["value"]))
            return True
        return False


class MultiSelect(Component):
    """A multi-select two-way bound to a ``Signal[list[str]]`` (R5).

    The signal holds the list of selected string values; choosing in the UI
    replaces it. Options are ``"a"`` or ``(value, label)`` tuples, same as Select, and may be
    a Signal, Computed or callable; when they change, selected values no longer offered are
    dropped from the signal.
    """

    type = "multiselect"

    def __init__(self, value: Signal[list], *, options: list[Any], label: str = "") -> None:
        super().__init__()
        self._value = value
        _wire_options(self, options, _normalise_option)
        _prune_to_options(self, value)
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {**_options_static(self), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: list(self._value.value), **_options_reactive(self)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            values = payload["value"]
            if not isinstance(values, (list, tuple)):
                return False
            self._value.set([str(v) for v in values])
            return True
        return False


def _normalise_choice(option: Any, tones: dict[str, str] | None = None) -> dict[str, Any]:
    """An option for Chips or Segmented: ``"a"``, ``("value", "Label")`` or a dict with
    ``value``, ``label`` and optionally ``count`` (an int shown beside the label) and ``tone``
    (one of ``BADGE_TONES``). ``tones`` maps a value to a tone for the whole control."""
    if isinstance(option, dict):
        value = str(option["value"])
        out: dict[str, Any] = {"value": value, "label": str(option.get("label", value))}
        count, tone = option.get("count"), option.get("tone")
    else:
        out = _normalise_option(option)
        value, count, tone = out["value"], None, None
    if tones and value in tones:
        tone = tones[value]
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError(f"an option's count must be an int, got {count!r}")
        out["count"] = count
    if tone is not None:
        if tone not in BADGE_TONES:
            raise ValueError(f"an option's tone must be one of {BADGE_TONES}, got {tone!r}")
        out["tone"] = tone
    return out


class Chips(Component):
    """Filter chips: a row of pill buttons two-way bound to a signal.

    With ``multi=False`` (the default) the signal is a ``Signal[str]`` and the chips behave
    like a radio group; with ``multi=True`` it is a ``Signal[list[str]]`` and each chip toggles.
    An option is ``"a"``, ``(value, label)`` or ``{"value", "label", "count", "tone"}``: a
    ``count`` shows beside the label and a ``tone`` (``ok``/``warn``/``err``/``info``) tints it.
    Arrow keys move between chips; Space or Enter selects.
    """

    type = "chips"

    def __init__(
        self,
        value: Signal[Any],
        *,
        options: list[Any],
        multi: bool = False,
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        self._multi = multi
        _wire_options(self, options, _normalise_choice)
        if multi:
            _prune_to_options(self, value)
        self._label = label

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {**_options_static(self), "label": self._label}
        if self._multi:
            props["multi"] = True
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._multi:
            return {"value": lambda: list(self._value.value), **_options_reactive(self)}
        return {"value": lambda: self._value.value, **_options_reactive(self)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event not in ("change", "input") or "value" not in payload:
            return False
        raw = payload["value"]
        if self._multi:
            if not isinstance(raw, (list, tuple)):
                return False
            self._value.set([str(v) for v in raw])
            return True
        if isinstance(raw, (list, tuple, dict)):
            return False
        self._value.set(str(raw))
        return True


class Segmented(Component):
    """A segmented control: a joined row of options, one selected, bound to a ``Signal[str]``.

    Options are as for :class:`Chips`. ``tones`` maps an option's value to a tone (so the
    "record" segment can be red) without spelling out dicts. Arrow keys move and select.
    """

    type = "segmented"

    def __init__(
        self,
        value: Signal[str],
        *,
        options: list[Any],
        tones: dict[str, str] | None = None,
        label: str = "",
    ) -> None:
        super().__init__()
        self._value = value
        _wire_options(self, options, lambda o: _normalise_choice(o, tones))
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {**_options_static(self), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: self._value.value, **_options_reactive(self)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event in ("change", "input") and "value" in payload:
            raw = payload["value"]
            if isinstance(raw, (list, tuple, dict)):
                return False
            self._value.set(str(raw))
            return True
        return False


class Image(Component):
    """An image bound to a source that yields a URL or a ``data:`` URI (R5).

    The source is a signal/string/callable; set it from Python and the shown image
    updates. Displays only (no UI-change direction); its current value stays
    readable via the bound signal.
    """

    type = "image"

    def __init__(self, source: Source, *, alt: str = "") -> None:
        super().__init__()
        self._source = source
        self._alt = alt

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"src": lambda: _image_src(_read(self._source))}


def _image_src(value: Any) -> str:
    """Coerce a source value to something an ``<img src>`` accepts.

    A string (URL or ``data:`` URI) passes through; raw ``bytes`` are encoded as a
    PNG ``data:`` URI so a caller can hand over image bytes directly.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        encoded = base64.b64encode(bytes(value)).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return str(value)


class Audio(Component):
    """An audio player bound to a source that yields a URL or a ``data:`` URI (G8).

    The source is a signal/string/callable; set it from Python (after loading or
    generating a clip) and the player updates. Raw ``bytes`` are encoded as a
    ``data:`` URI using ``media_type`` (default ``audio/wav``) -- pass the type that
    matches your bytes (e.g. ``"audio/mpeg"`` for MP3). Playback is native browser
    controls; there is no waveform/spectrogram here (pair with ``Plot``/``Heatmap``
    for that).
    """

    type = "audio"

    def __init__(self, source: Source, *, media_type: str = "audio/wav") -> None:
        super().__init__()
        self._source = source
        self._media_type = media_type

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"src": lambda: _audio_src(_read(self._source), self._media_type)}


def _audio_src(value: Any, media_type: str) -> str:
    """Coerce a source value to something an ``<audio src>`` accepts.

    A string (URL or ``data:`` URI) passes through; raw ``bytes`` are encoded as a
    ``data:`` URI tagged with ``media_type`` so a caller can hand over audio bytes
    directly, whatever the encoding.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        encoded = base64.b64encode(bytes(value)).decode("ascii")
        return f"data:{media_type};base64,{encoded}"
    return str(value)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_boxes(value: Any) -> list[dict[str, Any]]:
    """Normalise detection boxes to ``[{x,y,w,h,label,color,score}, ...]`` (coords in
    ``[0, 1]``, fractions of the image)."""
    out: list[dict[str, Any]] = []
    for b in value or []:
        if isinstance(b, dict):
            box = {
                "x": _num(b.get("x")),
                "y": _num(b.get("y")),
                "w": _num(b.get("w")),
                "h": _num(b.get("h")),
            }
        elif isinstance(b, (list, tuple)) and len(b) >= 4:
            box = {"x": _num(b[0]), "y": _num(b[1]), "w": _num(b[2]), "h": _num(b[3])}
        else:
            continue
        if isinstance(b, dict):
            if b.get("label") is not None:
                box["label"] = str(b["label"])
            if b.get("color"):
                box["color"] = str(b["color"])
            if b.get("score") is not None:
                box["score"] = _num(b["score"])
        out.append(box)
    return out


def _to_points(value: Any) -> list[dict[str, Any]]:
    """Normalise keypoints to ``[{x,y,label,color}, ...]`` (coords in ``[0, 1]``)."""
    out: list[dict[str, Any]] = []
    for p in value or []:
        if isinstance(p, dict):
            pt = {"x": _num(p.get("x")), "y": _num(p.get("y"))}
            if p.get("label") is not None:
                pt["label"] = str(p["label"])
            if p.get("color"):
                pt["color"] = str(p["color"])
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            pt = {"x": _num(p[0]), "y": _num(p[1])}
        else:
            continue
        out.append(pt)
    return out


def _to_masks(value: Any) -> list[dict[str, Any]]:
    """Normalise masks to ``[{src, opacity}, ...]`` - each an overlay image (a
    URL/``data:`` URI or PNG ``bytes``) drawn over the base image with an alpha."""
    out: list[dict[str, Any]] = []
    for m in value or []:
        if isinstance(m, dict):
            src = _image_src(m.get("src"))
            opacity = _num(m.get("opacity", 0.5), 0.5)
        else:
            src = _image_src(m)
            opacity = 0.5
        if src:
            out.append({"src": src, "opacity": opacity})
    return out


class ImageOverlay(Component):
    """An image with vector overlays drawn on top (ADR-0020): the read-only display
    path for detection boxes, segmentation masks, and keypoints.

    The base image is a ``source`` (URL / ``data:`` URI / PNG ``bytes``, like
    ``Image``). ``boxes``, ``points``, and ``masks`` are reactive sources whose
    coordinates are **fractions of the image** (``[0, 1]``), so they line up at any
    rendered size. Because they are ordinary reactive props, streaming a model's
    output per frame is a prop update over the existing ``patch`` op - no
    ``protocol_version`` bump. Display only (the model produces the shapes; the shell
    draws them); interactive annotation - the user *drawing* boxes - is the ADR-0020
    step-two follow-up.

    - ``boxes``: ``{x, y, w, h, label?, color?, score?}`` (or an ``(x, y, w, h)`` tuple).
    - ``points``: ``{x, y, label?, color?}`` (or an ``(x, y)`` tuple).
    - ``masks``: an overlay image (URL / ``data:`` / bytes) or ``{src, opacity?}``.

    ``label_mode`` controls how a box's ``label``/``score`` are shown: ``"always"``
    (the default) draws a permanent tag above the box; ``"hover"`` shows nothing
    until the box is hovered, as a tooltip - useful once a frame has enough boxes
    that always-on labels overlap each other and the image underneath.
    """

    type = "imageoverlay"

    def __init__(
        self,
        source: Source,
        *,
        boxes: Source = None,
        points: Source = None,
        masks: Source = None,
        alt: str = "",
        label_mode: Literal["always", "hover"] = "always",
    ) -> None:
        super().__init__()
        self._source = source
        self._boxes = boxes
        self._points = points
        self._masks = masks
        self._alt = alt
        self._label_mode = label_mode

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt, "labelMode": self._label_mode}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {
            "src": lambda: _image_src(_read(self._source)),
            "boxes": lambda: _to_boxes(_read(self._boxes)),
            "points": lambda: _to_points(_read(self._points)),
            "masks": lambda: _to_masks(_read(self._masks)),
        }
        return props


class Plot(Component):
    """A rendered figure, shown as an image (R5).

    Accepts a Matplotlib ``Figure`` (duck-typed on ``savefig`` -- no hard
    dependency), raw PNG ``bytes``, or a URL / ``data:`` URI string, in a signal or
    plain. The figure is rasterised to a PNG ``data:`` URI on the Python side, so
    nothing extra is needed in the browser and it rounds-trips like an image.
    """

    type = "image"  # reuses the shell's <img> renderer

    def __init__(self, source: Source, *, alt: str = "plot") -> None:
        super().__init__()
        self._source = source
        self._alt = alt

    def static_props(self) -> dict[str, Any]:
        return {"alt": self._alt}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"src": lambda: _figure_src(_read(self._source))}


def _figure_src(value: Any) -> str:
    """A Matplotlib ``Figure`` -> PNG ``data:`` URI; otherwise defer to _image_src."""
    if value is not None and hasattr(value, "savefig"):
        buffer = io.BytesIO()
        value.savefig(buffer, format="png", bbox_inches="tight")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    return _image_src(value)


def _normalise_series(spec: Any) -> dict[str, Any]:
    """A series descriptor: ``"loss"`` or ``{"label","stroke"}`` -> a wire dict."""
    if isinstance(spec, dict):
        out: dict[str, Any] = {"label": str(spec.get("label", ""))}
        if spec.get("stroke"):
            out["stroke"] = str(spec["stroke"])
        return out
    return {"label": str(spec)}


def _to_rows(value: Any) -> list[list[Any]]:
    """Coerce chart data to a JSON-safe list of rows ``[[x, y0, y1, ...], ...]``."""
    if value is None:
        return []
    rows: list[list[Any]] = []
    for row in value:
        if isinstance(row, (list, tuple)):
            rows.append([_json_safe(v) for v in row])
        else:
            rows.append([_json_safe(row)])
    return rows


class Chart(Component):
    """An interactive, client-side chart (ADR-0018, hybrid charting).

    Where ``Plot`` rasterises a figure to a PNG on the Python side (the zero-JS
    static path), ``Chart`` sends its data as ordinary reactive props and the shell's
    bundled uPlot draws it in the browser -- so zoom (drag on the x-axis), hover, and
    live updates all run client-side, with no PNG per frame. It is a line /
    time-series chart: ``series`` names the y-columns, and the data is a list of rows
    ``[[x, y0, y1, ...], ...]`` (x first, then one value per series).

    Two ways to drive it:

    - **Reactive** -- pass ``data`` as a ``Signal`` / callable / list; setting it
      replaces the whole dataset (good for a static chart, or one recomputed from
      inputs).
    - **Streaming** -- leave ``data`` unset and call :meth:`push` (or :meth:`extend`)
      to append points. Each call emits an *append* patch carrying only the new
      row(s), so a live curve grows at O(point) on the wire, the same way
      ``StreamText`` streams text. :meth:`clear` resets it. ``snapshot`` always
      carries the full accumulated data, so a fresh connect or a resume re-renders
      the whole curve (ADR-0011).

    Example (a streaming loss curve fed from a training loop, ADR-0009)::

        chart = Chart(series=["loss"], title="Training loss", x_label="step")

        async def train():
            chart.clear()
            for step, loss in enumerate(run_epoch()):
                chart.push(step, loss)
                await asyncio.sleep(0)
    """

    type = "chart"

    def __init__(
        self,
        data: Source = None,
        *,
        series: list[Any] | None = None,
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        height: int = 240,
        points: bool = False,
    ) -> None:
        super().__init__()
        self._reactive = data is not None
        self._data = data
        self._buffer: list[list[Any]] = []
        self._series = [_normalise_series(s) for s in (series or [])]
        self._title = title
        self._x_label = x_label
        self._y_label = y_label
        self._height = int(height)
        self._points = bool(points)
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so push/extend/clear can emit patches."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "series": self._series,
            "title": self._title,
            "xLabel": self._x_label,
            "yLabel": self._y_label,
            "height": self._height,
            "points": self._points,
        }
        if not self._reactive:
            # Streaming mode: carry the accumulated data in the snapshot so a fresh
            # connect / resume re-renders the full curve.
            props["data"] = [list(row) for row in self._buffer]
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._reactive:
            return {"data": lambda: _to_rows(_read(self._data))}
        return {}

    # -- streaming API (only when data= is unset) ----------------------------

    def _guard_streaming(self) -> None:
        if self._reactive:
            raise TypeError(
                "push/extend/clear are for a streaming Chart; this one has reactive data="
            )

    def push(self, *row: Any) -> None:
        """Append one point ``(x, y0, y1, ...)`` and emit an append delta."""
        self._guard_streaming()
        point = [_json_safe(v) for v in row]
        self._buffer.append(point)
        if self._session is not None:
            self._session.emit_append(self.id, "data", [point])

    def extend(self, rows: Any) -> None:
        """Append several points at once, as a single append patch."""
        self._guard_streaming()
        batch = [[_json_safe(v) for v in row] for row in rows]
        if not batch:
            return
        self._buffer.extend(batch)
        if self._session is not None:
            self._session.emit_append(self.id, "data", batch)

    def clear(self) -> None:
        """Reset the accumulated points (emits a props replace)."""
        self._guard_streaming()
        self._buffer = []
        if self._session is not None:
            self._session.emit_props(self.id, {"data": []})


def _to_columns(value: Any) -> list[list[Any]]:
    """Coerce a 2-D field to a JSON-safe list of columns ``[[y0, y1, ...], ...]``."""
    if value is None:
        return []
    cols: list[list[Any]] = []
    for col in value:
        cols.append([_json_safe(v) for v in col])
    return cols


class Heatmap(Component):
    """A client-side heatmap / 2-D field (ADR-0019): spectrograms, heatmaps, maps.

    The interactive/real-time counterpart to a server-PNG ``Plot`` of a raster: the
    2-D field rides ordinary reactive props and the shell's canvas renderer draws it
    (no PNG per frame, no ``protocol_version`` bump). The field ``z`` is **column-major**
    -- a list of columns, ``z[x][y]`` -- so a streaming spectrogram appends one new
    column (a time slice) per frame via the append op at O(column), the same path
    ``Chart``/``StreamText`` use. The shell draws column ``x`` at horizontal position
    ``x`` and colours cell ``(x, y)`` by ``z[x][y]`` through ``colormap``.

    Two ways to drive it, like ``Chart``:

    - **Reactive** -- pass ``z`` as a ``Signal`` / callable / list of columns; setting
      it replaces the whole field (a confusion matrix, an attention map).
    - **Streaming** -- leave ``z`` unset and call :meth:`push_column` (or
      :meth:`extend`) to append time slices (a live spectrogram); :meth:`clear`
      resets. ``snapshot`` carries the full field for a resume.

    ``zmin`` / ``zmax`` fix the colour scale (else it auto-scales in the browser);
    ``colormap`` is one of the shell's built-ins (``"magma"``, ``"viridis"``,
    ``"gray"``).
    """

    type = "heatmap"

    def __init__(
        self,
        z: Source = None,
        *,
        colormap: str = "magma",
        zmin: float | None = None,
        zmax: float | None = None,
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        height: int = 240,
    ) -> None:
        super().__init__()
        self._reactive = z is not None
        self._z = z
        self._buffer: list[list[Any]] = []
        self._colormap = colormap
        self._zmin = zmin
        self._zmax = zmax
        self._title = title
        self._x_label = x_label
        self._y_label = y_label
        self._height = int(height)
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so push/extend/clear can emit patches."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "colormap": self._colormap,
            "zmin": self._zmin,
            "zmax": self._zmax,
            "title": self._title,
            "xLabel": self._x_label,
            "yLabel": self._y_label,
            "height": self._height,
        }
        if not self._reactive:
            props["z"] = [list(col) for col in self._buffer]
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._reactive:
            return {"z": lambda: _to_columns(_read(self._z))}
        return {}

    # -- streaming API (only when z= is unset) -------------------------------

    def _guard_streaming(self) -> None:
        if self._reactive:
            raise TypeError(
                "push_column/extend/clear are for a streaming Heatmap; this one has reactive z="
            )

    def push_column(self, column: Any) -> None:
        """Append one column (a time slice) and emit an append delta."""
        self._guard_streaming()
        col = [_json_safe(v) for v in column]
        self._buffer.append(col)
        if self._session is not None:
            self._session.emit_append(self.id, "z", [col])

    def extend(self, columns: Any) -> None:
        """Append several columns at once, as a single append patch."""
        self._guard_streaming()
        batch = [[_json_safe(v) for v in col] for col in columns]
        if not batch:
            return
        self._buffer.extend(batch)
        if self._session is not None:
            self._session.emit_append(self.id, "z", batch)

    def clear(self) -> None:
        """Reset the accumulated field (emits a props replace)."""
        self._guard_streaming()
        self._buffer = []
        if self._session is not None:
            self._session.emit_props(self.id, {"z": []})


DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_ATTRIBUTION = "© OpenStreetMap contributors"


def _to_latlon(value: Any) -> list[float]:
    if value is None:
        return [0.0, 0.0]
    lat, lon = value
    return [_num(lat), _num(lon)]


def _to_markers(value: Any) -> list[dict[str, Any]]:
    """Coerce a source value to ``[{lat, lon, label?, color?, radius?}, ...]``."""
    if value is None:
        return []
    out: list[dict[str, Any]] = []
    for m in value:
        if isinstance(m, dict):
            if "lat" not in m or "lon" not in m:
                continue
            entry = {"lat": _num(m["lat"]), "lon": _num(m["lon"])}
            for key in ("label", "color", "radius"):
                if m.get(key) is not None:
                    entry[key] = m[key]
        else:
            lat, lon = m
            entry = {"lat": _num(lat), "lon": _num(lon)}
        out.append(entry)
    return out


def _to_polygons(value: Any) -> list[dict[str, Any]]:
    """Coerce a source value to ``[{points, label?, color?, fillOpacity?}, ...]``."""
    if value is None:
        return []
    out: list[dict[str, Any]] = []
    for p in value:
        points = p["points"] if isinstance(p, dict) else p
        rings = [[_num(lat), _num(lon)] for lat, lon in points]
        entry: dict[str, Any] = {"points": rings}
        if isinstance(p, dict):
            for key in ("label", "color", "fillOpacity"):
                if p.get(key) is not None:
                    entry[key] = p[key]
        out.append(entry)
    return out


def _to_polylines(value: Any) -> list[dict[str, Any]]:
    """Coerce a source value to ``[{points, label?, color?, weight?}, ...]``."""
    if value is None:
        return []
    out: list[dict[str, Any]] = []
    for p in value:
        points = p["points"] if isinstance(p, dict) else p
        path = [[_num(lat), _num(lon)] for lat, lon in points]
        entry: dict[str, Any] = {"points": path}
        if isinstance(p, dict):
            for key in ("label", "color", "weight"):
                if p.get(key) is not None:
                    entry[key] = p[key]
        out.append(entry)
    return out


class Map(Component):
    """An interactive client-side map (Leaflet, ADR-0019-style hybrid: G5).

    ``center`` is a ``(lat, lon)`` pair and ``zoom`` a Leaflet zoom level (typically
    0-19); both are reactive sources -- set them from Python (e.g. "fly to" a new
    place) and the existing map instance re-views there, without resetting whatever
    pan/zoom the viewer is currently at from an unrelated prop update. ``markers``
    (``{lat, lon, label?, color?, radius?}``), ``polygons``
    (``{points:[(lat,lon),...], label?, color?, fillOpacity?}``), and ``polylines``
    (``{points:[(lat,lon),...], label?, color?, weight?}``) are reactive lists
    redrawn wholesale on change -- the same "no structural children op, ship a plain
    list prop" shape as ``ImageOverlay``'s boxes/points. ``polylines`` is an *open*
    path (Leaflet ``L.polyline``) -- unlike ``polygons``, it is not auto-closed back
    to its first point and has no fill, which is what a real route/track (a GPX
    trail, a path between two points) needs; use ``polygons`` for a closed, filled
    area instead.

    Markers/polygons/polylines render as Leaflet vector layers (circle markers,
    polygons, polylines), not the classic pin icon, which needs image assets
    incompatible with the shell's no-external-requests singlefile build (ADR-0004).
    This is display plus native pan/zoom; the viewer's own pan/zoom is not reported
    back to Python (matching ``ImageOverlay``'s zoom/pan, which is client-side only).

    Tiles load live from ``tile_url`` in the **viewer's own browser** (never
    indah's server) -- the same as any Leaflet map on any website, and not the kind
    of server-side scraping the map-poster/prettymap demos avoid for a public
    deployment. The default is OpenStreetMap's public tile server, whose usage
    policy asks non-trivial-traffic sites to run their own tiles or use a
    commercial provider; swap ``tile_url``/``attribution`` for that when it matters
    -- it's a per-deployment concern, not indah's.
    """

    type = "map"

    def __init__(
        self,
        center: Source,
        *,
        zoom: Source = 12,
        markers: Source = None,
        polygons: Source = None,
        polylines: Source = None,
        height: int = 320,
        tile_url: str = DEFAULT_TILE_URL,
        attribution: str = DEFAULT_ATTRIBUTION,
        label: str = "",
    ) -> None:
        super().__init__()
        self._center = center
        self._zoom = zoom
        self._markers = markers
        self._polygons = polygons
        self._polylines = polylines
        self._height = int(height)
        self._tile_url = tile_url
        register_img_host(tile_url)  # so a strict CSP lets this host's tiles load (ADR-0038)
        self._attribution = attribution
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {
            "height": self._height,
            "tileUrl": self._tile_url,
            "attribution": self._attribution,
            "label": self._label,
        }

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {
            "center": lambda: _to_latlon(_read(self._center)),
            "zoom": lambda: _read(self._zoom),
            "markers": lambda: _to_markers(_read(self._markers)),
            "polygons": lambda: _to_polygons(_read(self._polygons)),
            "polylines": lambda: _to_polylines(_read(self._polylines)),
        }


class DataFrame(Component):
    """A tabular display bound to a source (R5).

    Accepts a pandas ``DataFrame`` (duck-typed -- no hard dependency), a
    ``{"columns": [...], "rows": [[...], ...]}`` dict, or a list of row dicts, in a
    signal or plain. Set it from Python and the rendered table updates.
    """

    type = "dataframe"

    def __init__(self, source: Source, *, label: str = "") -> None:
        super().__init__()
        self._source = source
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"data": lambda: _to_table(_read(self._source))}


_COL_KINDS = frozenset({"text", "mono", "badge", "time", "number"})
_TONES = frozenset({"ok", "warn", "err", "info", "neutral"})
_CSS_LENGTH = re.compile(r"^\d+(\.\d+)?(ch|px|rem|em|%|vw|vh)$")


@dataclass(frozen=True)
class Col:
    """A typed column for a rich ``Table`` (ADR-0027).

    ``kind`` picks the cell renderer (all shell-side, none interpret HTML): ``text``,
    ``mono`` (truncated, full value on hover), ``badge`` (a pill; ``tones`` maps a cell
    value to ``ok|warn|err|info|neutral``), ``time`` (an ISO string or epoch ms/s shown
    relative, "3s ago", refreshed live) and ``number`` (right-aligned, grouped).
    ``time_format`` (for ``kind="time"`` only) picks how a time reads: ``"relative"`` (the
    default), ``"clock"`` (``09:14:22.318``) or ``"datetime"`` (``2026-10-21 09:14:22``), both in
    the viewer's local time. The tooltip always carries the full ISO (UTC) value.
    """

    field: str
    title: str | None = None
    kind: str = "text"
    width: str | None = None
    sortable: bool = True
    tones: dict[str, str] | None = None
    time_format: str = "relative"

    def __post_init__(self) -> None:
        if self.kind not in _COL_KINDS:
            raise ValueError(f"Col kind {self.kind!r} not in {sorted(_COL_KINDS)}")
        if self.time_format not in _TIME_FORMATS:
            raise ValueError(f"Col time_format {self.time_format!r} not in {_TIME_FORMATS}")
        if self.time_format != "relative" and self.kind != "time":
            raise ValueError("Col time_format only applies to kind='time'")
        for value, tone in (self.tones or {}).items():
            if tone not in _TONES:
                raise ValueError(f"Col tone {tone!r} for {value!r} not in {sorted(_TONES)}")
        if self.width is not None and not _CSS_LENGTH.match(self.width):
            raise ValueError(f"Col width {self.width!r} must be a length like '12ch' or '8rem'")

    def wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "field": self.field,
            "title": self.title if self.title is not None else self.field,
            "kind": self.kind,
            "sortable": self.sortable,
        }
        if self.width is not None:
            out["width"] = self.width
        if self.tones:
            out["tones"] = dict(self.tones)
        if self.time_format != "relative":
            out["timeFormat"] = self.time_format
        return out


DENSITIES = ("comfortable", "compact")
_TIME_FORMATS = ("relative", "clock", "datetime")
MAX_TABLE_LIMIT = 500
MAX_CHECK_ALL = 10_000  # most keys a remote table's "select all" will gather
_MAX_SEARCH = 200
_MAX_FILTERS = 20
logger = logging.getLogger("indah")


@dataclass(frozen=True)
class TableQuery:
    """What a remote ``Table`` asks its loader for (IND-101): a window of the rows that
    match ``search``/``filters``, ordered by ``sort`` (``(field, "asc"|"desc")``).
    ``seq`` numbers the viewer's queries so an old answer is never shown over a new one."""

    search: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    sort: tuple[str, str] | None = None
    offset: int = 0
    limit: int = 50
    seq: int = 0

    @classmethod
    def parse(cls, payload: dict[str, Any], sortable: set[str] | frozenset[str]) -> TableQuery:
        """Build a query from a client payload, clamping what is clampable (``offset`` >= 0,
        ``1 <= limit <= 500``, ``search`` to 200 characters) and ignoring a sort on a column
        that is not sortable. Raises ``ValueError`` for a wrongly typed field."""

        def integer(name: str, default: int) -> int:
            value = payload.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"query {name} must be an integer")
            return value

        search = payload.get("search", "")
        if not isinstance(search, str):
            raise ValueError("query search must be a string")
        raw_filters = payload.get("filters", {})
        if not isinstance(raw_filters, dict):
            raise ValueError("query filters must be an object")
        filters = {
            str(k): v
            for k, v in list(raw_filters.items())[:_MAX_FILTERS]
            if isinstance(v, (str, int, float, bool)) or v is None
        }
        sort = payload.get("sort")
        if sort is not None and not (isinstance(sort, (list, tuple)) and len(sort) == 2):
            raise ValueError("query sort must be [field, direction]")
        if sort is not None and not (sort[0] in sortable and sort[1] in ("asc", "desc")):
            sort = None
        return cls(
            search=search[:_MAX_SEARCH],
            filters=filters,
            sort=(sort[0], sort[1]) if sort is not None else None,
            offset=max(0, integer("offset", 0)),
            limit=min(MAX_TABLE_LIMIT, max(1, integer("limit", 50))),
            seq=integer("seq", 0),
        )


@dataclass(frozen=True)
class RowAction:
    """A per-row button on a rich ``Table`` (IND-99). ``on_click(key)`` runs (sync or
    async) with the row's key; ``confirm`` makes the shell ask first, like
    ``Button(confirm=)`` -- a UX guard, not authorization. Rows can be stale by the time
    a click lands, so a handler must tolerate a key that no longer exists."""

    label: str
    on_click: Callable[[Any], Any]
    confirm: str | None = None
    variant: str = "ghost"

    def wire(self, index: int) -> dict[str, Any]:
        out: dict[str, Any] = {"id": f"a{index}", "label": self.label, "variant": self.variant}
        if self.confirm:
            out["confirm"] = self.confirm
        return out


class Table(Component):
    """An interactive table (ADR-0021, ADR-0027): sort, page, and select.

    **Classic form**, ``Table(source, ...)``: a superset of ``DataFrame``'s display (a
    pandas frame, a ``{"columns","rows"}`` dict, or a list of row dicts) with client-side
    sort/paging and row select. Bind ``selected`` to a ``Signal[int]`` (the selected row
    index, or ``None``) and a click sets it, so the selection drives the rest of the app.

    **Rich form**, ``Table(rows=..., columns=[Col(...)], key="id")``: rows are dicts, each
    with a stable ``key`` (a ULID, say), columns are typed (:class:`Col`), and ``selected``
    holds the row's *key*, not its position, so it survives sorting and new rows. ``rows``
    may be a ``Stream``: appended rows arrive as small ``append`` patches and the browser
    keeps the newest ``stream.limit``. ``columns`` may be omitted when the rows are a
    non-empty static list. ``height`` (a CSS length) makes the body scroll under a sticky
    header. ``search=True`` adds a filter box (case-insensitive, over every column, in the
    browser, so rows streaming in are filtered too); ``column_toggle=True`` lets the viewer
    hide columns (remembered in the browser); ``follow=True`` keeps the newest row in view
    while rows arrive and pauses when the viewer scrolls up (needs ``height``).
    ``actions=[RowAction(...)]`` adds a button per row that calls back with the row key;
    ``checked=`` (a ``Signal[list]`` of keys) adds a checkbox column plus select-all for
    bulk operations. Both need the rich form with a ``key``.

    **Remote form**, ``Table(columns=[...], key="id", remote=loader)``: for more rows than
    one prop should carry. The shell debounces search, sort and paging into a ``query``
    event; ``loader(TableQuery)`` returns ``(rows, total)`` for that window (sync loaders run
    in a worker thread, so a blocking database call is fine; ``async`` ones run on the loop).
    A newer query supersedes an older one, whose late answer is dropped; an offset past the
    end is pulled back to the last window. ``reload_on=[signal, ...]`` re-runs the last query
    when one changes (a project picker, say), ``query=`` mirrors the latest ``TableQuery``
    into a signal and ``page_size`` is the window size (default 50). Sorting and ``search=``
    are server-side here; the loader is the one place that honours them. ``follow=`` is not
    available with ``remote=`` (it raises ``ValueError``). The header checkbox ticks only the
    rows shown; with ``checked=`` a "Select all M" button gathers every match, up to
    ``MAX_CHECK_ALL`` keys.

    ``virtual=True`` (rich or remote form, needs ``height``) renders only the rows in view
    plus a small overscan, with spacers standing in for the rest, so the DOM stays small at
    tens of thousands of rows. Rows have one fixed height, so cells do not wrap. In remote
    mode the shell fetches windows as the viewer scrolls and keeps a few recent ones.
    ``density="compact"`` shrinks this table's rows (the app-wide default is
    ``create_app(density=)``); pass a ``Signal[str]`` to let the viewer toggle it.

    Sorting and paging are client-side; the data rides ordinary reactive props, so no
    ``protocol_version`` bump. Use ``DataFrame`` when you only need to show a table.
    """

    type = "table"

    def __init__(
        self,
        source: Source = None,
        *,
        rows: Source | Stream | None = None,
        columns: list[Col] | None = None,
        key: str | None = None,
        selected: Signal[Any] | None = None,
        page_size: int = 0,
        label: str = "",
        height: str | None = None,
        search: bool = False,
        column_toggle: bool = False,
        follow: bool = False,
        actions: list[RowAction] | None = None,
        checked: Signal[list[Any]] | None = None,
        remote: Callable[[TableQuery], Any] | None = None,
        reload_on: list[Signal[Any]] | None = None,
        query: Signal[TableQuery | None] | None = None,
        virtual: bool = False,
        density: str | Signal[str] | None = None,
    ) -> None:
        super().__init__()
        if isinstance(density, str) and density not in DENSITIES:
            raise ValueError(f"Table density must be one of {DENSITIES}, got {density!r}")
        if virtual and (height is None or (rows is None and remote is None)):
            raise ValueError("Table virtual=True needs the rich form and height=")
        if remote is not None:
            if rows is not None or source is not None:
                raise ValueError("Table remote= replaces rows=/source: pass one or the other")
            if key is None or columns is None:
                raise ValueError("Table remote= needs key= and columns=")
            if follow:
                raise ValueError("Table follow= is for streamed rows, not remote= windows")
            rows = []  # the rich form, with the window held in self._window
        elif reload_on or query is not None:
            raise ValueError("Table reload_on=/query= go with remote=")
        if rows is None and (
            columns is not None
            or key is not None
            or search
            or column_toggle
            or follow
            or actions
            or checked is not None
        ):
            raise ValueError(
                "Table columns=/key=/search=/column_toggle=/follow=/actions=/checked= go "
                "with rows=; the classic form takes none of them"
            )
        if (actions or checked is not None) and key is None:
            raise ValueError("Table actions=/checked= need key= (they refer to rows by key)")
        if follow and height is None:
            raise ValueError("Table follow=True needs height= (the body scrolls inside it)")
        if rows is None and source is None:
            raise ValueError("Table needs a source (classic form) or rows= (rich form)")
        if rows is not None and source is not None:
            raise ValueError("pass a positional source or rows=, not both")
        if height is not None and not _CSS_LENGTH.match(height):
            raise ValueError(f"Table height {height!r} must be a length like '20rem'")
        self._source = source
        self._rows = rows
        self._key = key
        self._page_size = int(page_size)
        self._selected = selected
        self._label = label
        self._height = height
        self._search = bool(search)
        self._column_toggle = bool(column_toggle)
        self._follow = bool(follow)
        self._actions = list(actions or [])
        self._checked = checked
        self._virtual = bool(virtual)
        self._density = density
        self._loader = remote
        if remote is not None and not page_size:
            self._page_size = 50
        self._query_signal = query
        self._window: Signal[dict[str, Any]] = Signal(
            {"rows": [], "total": 0, "offset": 0, "seq": 0}
        )
        self._seq_seen = 0
        self._last_query: TableQuery | None = None
        self._reload_tasks: set[asyncio.Task[None]] = set()
        self._reload_effect: Any = None
        if remote is not None and reload_on:
            deps = list(reload_on)
            armed = False

            def on_change() -> None:
                nonlocal armed
                for dep in deps:  # read them all, so each one is tracked
                    dep.value  # noqa: B018
                if armed:
                    self._spawn_reload()
                armed = True

            self._reload_effect = effect(on_change)
        self._columns: list[Col] | None = None
        if rows is not None:
            self._columns = list(columns) if columns is not None else self._infer_columns(rows)

    @staticmethod
    def _infer_columns(rows: Any) -> list[Col]:
        if isinstance(rows, (Signal, Stream)) or callable(rows):
            raise ValueError("pass columns= when rows are a Stream, Signal or callable")
        records = _to_records(rows, None)
        if not records:
            raise ValueError("pass columns= when the rows are empty")
        return [Col(name) for name in records[0]]

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "pageSize": self._page_size,
            "selectable": self._selected is not None,
            "label": self._label,
        }
        if self._columns is not None:
            props["columns"] = [c.wire() for c in self._columns]
            if self._key is not None:
                props["rowKey"] = self._key
            if self._height is not None:
                props["height"] = self._height
            props["search"] = self._search
            props["columnToggle"] = self._column_toggle
            props["follow"] = self._follow
            if self._virtual:
                props["virtual"] = True
            if isinstance(self._density, str):
                props["density"] = self._density
            props["checkable"] = self._checked is not None
            if self._loader is not None:
                props["remote"] = True
                if self._checked is not None:
                    props["checkAllMax"] = MAX_CHECK_ALL
            if self._actions:
                props["actions"] = [a.wire(i) for i, a in enumerate(self._actions)]
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        if self._columns is None:
            props: dict[str, Callable[[], Any]] = {"data": lambda: _to_table(_read(self._source))}
        elif self._loader is not None:
            props = {"window": lambda: self._window.value}
        else:
            props = {"rows": lambda: _to_records(_read(self._rows), self._key)}
        if self._selected is not None:
            if self._columns is None:
                props["value"] = lambda: (
                    None if self._selected.value is None else int(self._selected.value)
                )
            else:
                props["value"] = lambda: _json_safe(self._selected.value)
        if (
            self._columns is not None
            and self._density is not None
            and not isinstance(self._density, str)
        ):
            density = self._density
            props["density"] = lambda: d if (d := _read(density)) in DENSITIES else "comfortable"
        if self._checked is not None:
            props["checked"] = lambda: [_json_safe(k) for k in (self._checked.value or [])]
        return props

    def stream_props(self) -> dict[str, tuple[Stream, Callable[[list[Any]], list[Any]]]]:
        if self._columns is not None and isinstance(self._rows, Stream):
            return {"rows": (self._rows, lambda rows: _to_records(rows, self._key))}
        return {}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "select" and self._selected is not None:
            if "key" in payload and self._columns is not None:
                self._selected.set(payload["key"])
                return True
            if "index" in payload:
                self._selected.set(int(payload["index"]))
                return True
        if event == "query" and self._loader is not None:
            sortable = {c.field for c in self._columns or [] if c.sortable}
            try:
                query = TableQuery.parse(payload, sortable)
            except ValueError:
                return False
            return self._run_query(query)
        if event == "check" and self._checked is not None:
            keys = payload.get("keys")
            if isinstance(keys, list):
                self._checked.set(keys)
                return True
        if event == "check_all" and self._checked is not None and self._loader is not None:
            if self._last_query is not None:
                return self._check_all(self._last_query)
        if event == "action" and "key" in payload:
            actions = {f"a{i}": a for i, a in enumerate(self._actions)}
            action = actions.get(str(payload.get("action")))
            if action is not None:
                result = action.on_click(payload["key"])
                if inspect.iscoroutine(result):
                    return result
                return True
        return False

    # -- remote mode (IND-101) ----------------------------------------------

    async def _run_query(self, query: TableQuery) -> None:
        if query.seq < self._seq_seen:
            return  # a newer query already arrived: never load for a superseded one
        self._seq_seen = query.seq
        self._last_query = query
        if self._query_signal is not None:
            self._query_signal.set(query)
        await self._load(query)

    async def _check_all(self, query: TableQuery) -> None:
        """Tick every row that matches the viewer's current search/filters, not just the
        loaded window: walk the loader in windows, up to ``MAX_CHECK_ALL`` keys. Rows
        already ticked stay, in front. The shown window is left alone."""
        assert self._key is not None
        gathered: list[Any] = []
        offset = 0
        while offset < MAX_CHECK_ALL:
            limit = min(MAX_TABLE_LIMIT, MAX_CHECK_ALL - offset)
            rows, total = await self._call_loader(replace(query, offset=offset, limit=limit))
            gathered += [_json_safe(r[self._key]) for r in _to_records(rows, self._key)]
            offset += len(rows)
            if not rows or offset >= total:
                break
        assert self._checked is not None
        kept = list(self._checked.value or [])
        seen = set(kept)
        self._checked.set(kept + [k for k in gathered if k not in seen])

    async def _call_loader(self, query: TableQuery) -> tuple[list[Any], int]:
        loader = self._loader
        assert loader is not None
        if inspect.iscoroutinefunction(loader):
            result = await loader(query)
        else:
            result = await asyncio.to_thread(loader, query)
            if inspect.isawaitable(result):
                result = await result
        rows, total = result
        return list(rows), int(total)

    async def _load(self, query: TableQuery) -> None:
        rows, total = await self._call_loader(query)
        if query.seq < self._seq_seen:
            return  # superseded while the loader ran: drop the late answer
        if not rows and total > 0 and query.offset >= total:
            # The data shrank under the viewer: pull the window back to the last page.
            query = replace(query, offset=(total - 1) // query.limit * query.limit)
            rows, total = await self._call_loader(query)
            if query.seq < self._seq_seen:
                return
        self._window.set(
            {
                "rows": _to_records(rows, self._key),
                "total": total,
                "offset": query.offset,
                "seq": query.seq,
            }
        )

    def _spawn_reload(self) -> None:
        """Re-run the last query (a ``reload_on`` signal changed). Needs the event loop,
        like any signal write that reaches the UI; outside one it is skipped."""
        if self._last_query is None:
            return  # nothing has been shown yet; the shell's first query will load
        try:
            task = asyncio.get_running_loop().create_task(self._load(self._last_query))
        except RuntimeError:
            return
        self._reload_tasks.add(task)
        task.add_done_callback(self._reload_done)

    def _reload_done(self, task: asyncio.Task[None]) -> None:
        self._reload_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Table reload failed", exc_info=task.exception())


def _to_records(source: Any, key: str | None) -> list[dict[str, Any]]:
    """Normalise rows to ``[{field: json-safe value}, ...]``; every row must carry ``key``."""
    if source is None:
        return []
    if hasattr(source, "columns") and hasattr(source, "to_dict"):  # pandas, duck-typed
        source = source.to_dict(orient="records")
    if not isinstance(source, (list, tuple)):
        raise TypeError(f"Table rows must be a list of dicts, not {type(source).__name__}")
    out: list[dict[str, Any]] = []
    for row in source:
        if not isinstance(row, dict):
            raise TypeError(f"Table rows must be dicts, got {type(row).__name__}")
        if key is not None and key not in row:
            raise ValueError(f"Table row is missing its key {key!r}: {row!r}")
        out.append({str(k): _json_safe(v) for k, v in row.items()})
    return out


class Stat(Component):
    """A metric / KPI card (ADR-0021): a big value with a label and optional delta.

    The tile dashboards pair with a ``Table``. ``value`` and ``delta`` are sources
    (signal / callable / plain); the shell colours the delta green when it does not
    start with ``-`` and red when it does (so pass e.g. ``"+2.4%"`` / ``"-1.1%"``).
    Display only; no new protocol capability.
    """

    type = "stat"

    def __init__(
        self, value: Source, *, label: str = "", delta: Source = None, help: str = ""
    ) -> None:
        super().__init__()
        self._value = value
        self._label = label
        self._delta = delta
        self._help = help

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label, "help": self._help}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {"value": lambda: str(_read(self._value))}
        if self._delta is not None:
            props["delta"] = lambda: None if _read(self._delta) is None else str(_read(self._delta))
        return props


def _json_safe(value: Any) -> Any:
    """Coerce a cell value to something JSON can carry (e.g. a numpy scalar)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):  # numpy / pandas scalar
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return str(value)


def _to_table(source: Any) -> dict[str, Any]:
    """Normalise a table-ish value to ``{"columns": [...], "rows": [[...], ...]}``."""
    if source is None:
        return {"columns": [], "rows": []}
    # pandas DataFrame (duck-typed): to_dict(orient="split") -> {columns, data}.
    if hasattr(source, "columns") and hasattr(source, "to_dict"):
        split = source.to_dict(orient="split")
        columns = [str(c) for c in split.get("columns", [])]
        rows = [[_json_safe(v) for v in row] for row in split.get("data", [])]
        return {"columns": columns, "rows": rows}
    if isinstance(source, dict) and "columns" in source and "rows" in source:
        columns = [str(c) for c in source["columns"]]
        rows = [[_json_safe(v) for v in row] for row in source["rows"]]
        return {"columns": columns, "rows": rows}
    if isinstance(source, (list, tuple)) and source and isinstance(source[0], dict):
        columns = list(source[0].keys())
        rows = [[_json_safe(row.get(c)) for c in columns] for row in source]
        return {"columns": [str(c) for c in columns], "rows": rows}
    raise TypeError(f"DataFrame cannot render a {type(source).__name__}")


class StreamText(Component):
    """A text container that grows token-by-token over the SSE channel (R5).

    Unlike a signal-bound ``Text``, a StreamText holds a plain accumulating
    string (not a signal), so:

    - ``snapshot()`` always carries the full text so far -- a fresh connect or a
      resume that falls back to ``init`` re-renders correctly (ADR-0011);
    - ``feed(token)`` emits an *append* patch carrying only the delta, so the wire
      cost is O(token), not O(text) per token.

    Feed it from a plain async generator the caller wraps (ADR-0009)::

        stream = StreamText()

        async def on_generate():
            stream.reset()
            async for token in my_llm(prompt.value):
                stream.feed(token)
    """

    type = "streamtext"

    def __init__(self, *, label: str = "") -> None:
        super().__init__()
        self._text = ""
        self._label = label
        self._session: Session | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so feed/reset can emit patches."""
        self._session = session

    @property
    def text(self) -> str:
        return self._text

    def static_props(self) -> dict[str, Any]:
        # Current text (not truly static) so init/resume snapshots are complete.
        return {"text": self._text, "label": self._label}

    def feed(self, token: str) -> None:
        """Append a token: grows the text and emits an append patch to clients."""
        token = str(token)
        if not token:
            return
        self._text += token
        if self._session is not None:
            self._session.emit_append(self.id, "text", token)

    def reset(self) -> None:
        """Clear the accumulated text (e.g. before a new generation)."""
        self._text = ""
        if self._session is not None:
            self._session.emit_props(self.id, {"text": ""})


class Progress(Component):
    """A progress bar bound to a source (R5, Slice A).

    Pass a value in ``[0, max]`` (a signal, number, or callable) to show
    determinate progress; pass ``None`` (the default) for an indeterminate bar that
    just signals "working". Set the value from Python and the bar updates reactively.
    """

    type = "progress"

    def __init__(self, value: Source = None, *, max: float = 1.0, label: str = "") -> None:
        super().__init__()
        self._value = value
        self._max = max
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"max": self._max, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"value": lambda: _progress_value(_read(self._value))}


def _progress_value(value: Any) -> float | None:
    """Coerce a progress value to a float, or ``None`` for an indeterminate bar."""
    if value is None:
        return None
    return float(value)


class Spinner(Component):
    """An indeterminate busy indicator (Slice A).

    ``active`` (a signal or bool) toggles it: while true the shell shows a spinner
    (and the optional ``label``); while false it renders nothing, so it can gate on
    a "loading" signal.
    """

    type = "spinner"

    def __init__(self, *, active: Source = True, label: str = "") -> None:
        super().__init__()
        self._active = active
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"active": lambda: bool(_read(self._active))}


# -- File upload (ADR-0017) --------------------------------------------------
#
# Upload is the one input whose payload is binary, not JSON, so it does not ride
# ``POST /api/event``: the shell posts the file(s) to a separate multipart route
# (``POST /api/upload``), and the app hands the bytes to this component's handler
# as ``UploadedFile`` objects. Everything after that is ordinary indah -- the
# handler mutates signals / feeds a StreamText and results flow back over SSE.


@dataclass
class UploadedFile:
    """One uploaded file's bytes and metadata, handed to an ``Upload`` handler.

    ``data`` is the raw bytes; ``text()`` decodes them and ``size`` is their length.
    The handler owns what it does with the bytes (ADR-0009/Q-sec).
    """

    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        """The file decoded as text. ``errors`` is passed to ``bytes.decode``: the default
        ``"strict"`` raises on bad bytes; use ``"replace"`` or ``"ignore"`` for a file that
        is not clean text."""
        return self.data.decode(encoding, errors)


class Upload(Component):
    """A file input (image / audio / any file), ADR-0017.

    ``on_upload`` is a plain callable the caller supplies (ADR-0009). It receives an
    :class:`UploadedFile` (or a ``list`` of them when ``multiple=True``); it may be
    sync or ``async def`` (an async handler runs in the background like a Button's,
    so a slow model never blocks the request). ``accept`` is an HTML accept hint
    (e.g. ``"image/*"``) and ``multiple`` allows selecting several files; both are UI
    hints -- the hard size cap is enforced server-side by the upload route.
    """

    type = "upload"

    def __init__(
        self,
        on_upload: Callable[[Any], Any] | None = None,
        *,
        label: str = "",
        accept: str = "",
        multiple: bool = False,
    ) -> None:
        super().__init__()
        self._on_upload = on_upload
        self._label = label
        self._accept = accept
        self._multiple = multiple

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label, "accept": self._accept, "multiple": bool(self._multiple)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        # The upload route dispatches a synthetic "upload" event whose payload
        # carries the parsed UploadedFile objects (not JSON) -- so it reuses the
        # whole session dispatch/sink/error path like any other event.
        if event == "upload":
            files: list[UploadedFile] = list(payload.get("files", []))
            if self._on_upload is not None:
                arg: Any = files if self._multiple else (files[0] if files else None)
                result = self._on_upload(arg)
                if inspect.iscoroutine(result):
                    return result  # async handler: awaited as a background task
            return True  # always handled (a no-op without a handler), never 400s
        return False


@dataclass
class DownloadFile:
    """Bytes to hand back to the user, with the filename the browser saves as."""

    data: bytes
    filename: str = "download"
    media_type: str = "application/octet-stream"


class Download(Component):
    """A download link that hands the user a file back (ADR-0017).

    Bind ``source`` to a signal/callable/plain value that yields one of:

    - a URL string (served elsewhere) -- passed through as the link target;
    - raw ``bytes`` -- served by indah at a per-session blob URL (``filename`` and
      ``media_type`` name the download);
    - a :class:`DownloadFile` -- bytes plus their own filename/media type.

    Set the source from Python (e.g. after a run produces a CSV or an image) and the
    link updates; ``None`` yields an inert link. Serving is per-session (ADR-0010),
    so one viewer's file is not reachable from another's session.
    """

    type = "download"

    def __init__(
        self,
        source: Source = None,
        *,
        label: str = "Download",
        filename: str = "download",
        media_type: str = "application/octet-stream",
    ) -> None:
        super().__init__()
        self._source = source
        self._label = label
        self._filename = filename
        self._media_type = media_type
        self._session: Session | None = None
        self._cache: tuple[Any, tuple[str, str]] | None = None

    def bind(self, session: Session) -> None:
        """Called by the session during wiring so bytes can be served per-session."""
        self._session = session

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {
            "href": lambda: self._resolve()[0],
            "filename": lambda: self._resolve()[1],
        }

    def _resolve(self) -> tuple[str, str]:
        """Coerce the source to ``(href, filename)``, serving bytes if needed.

        Cached by the source value so repeated getter calls (the two props, plus
        every snapshot) do not re-serve identical bytes under a fresh token.
        """
        value = _read(self._source)
        if self._cache is not None and _same_download(self._cache[0], value):
            return self._cache[1]

        if value is None:
            result = ("", self._filename)
        elif isinstance(value, DownloadFile):
            result = self._serve(value.data, value.filename, value.media_type)
        elif isinstance(value, (bytes, bytearray)):
            result = self._serve(bytes(value), self._filename, self._media_type)
        else:
            result = (str(value), self._filename)  # already a URL

        self._cache = (value, result)
        return result

    def _serve(self, data: bytes, filename: str, media_type: str) -> tuple[str, str]:
        if self._session is None:
            return ("", filename)  # not wired yet (e.g. serialised standalone)
        return (self._session.serve_file(data, filename=filename, media_type=media_type), filename)


def _same_download(a: Any, b: Any) -> bool:
    """Value-equality for the download cache, treating bytes/bytearray by content."""
    if isinstance(a, (bytes, bytearray)) and isinstance(b, (bytes, bytearray)):
        return bytes(a) == bytes(b)
    return a is b or a == b


# -- Layout containers (ADR-0015) --------------------------------------------
#
# These arrange existing child nodes, so they need no new protocol capability:
# the tree still serialises as nodes with ``children`` and their show/active state
# rides ordinary reactive props merged by the existing ``patch`` op. Layout itself
# is CSS in the shell driven by these static props (columns, gap, orientation).


def _as_signal(value: Any, default: Any, cast: Callable[[Any], Any]) -> Signal:
    """Return ``value`` if it is a Signal, else wrap a plain value in one.

    Lets ``Tabs``/``Expander`` accept either a caller's Signal (so the app drives
    the active/open state) or a plain literal (so the container is self-contained
    and the shell's clicks still round-trip through the reactive graph).
    """
    if isinstance(value, Signal):
        return value
    return Signal(cast(default if value is None else value))


class Row(Component):
    """A horizontal flex row of children, wrapping onto the next line as needed.

    ``justify`` spaces the children along the row: ``"start"``, ``"center"``, ``"end"``,
    ``"between"`` or ``"around"``. Setting it (like ``align``) sizes the children to their
    content instead of sharing the width, so ``Row(justify="between")`` with a title and a
    button puts one at each end. A ``Spacer`` between children does the same job.
    """

    type = "row"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        gap: str = "1rem",
        wrap: bool = True,
        align: str = "stretch",
        justify: str = "",
    ) -> None:
        super().__init__(children)
        if justify and justify not in _JUSTIFY:
            raise ValueError(f"Row justify must be one of {_JUSTIFY}, got {justify!r}")
        self._gap = gap
        self._wrap = wrap
        self._align = align
        self._justify = justify

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"gap": self._gap, "wrap": bool(self._wrap), "align": self._align}
        if self._justify:
            props["justify"] = self._justify
        return props


class Spacer(Component):
    """Flexible empty space: it grows to fill a ``Row`` (or ``Column``), pushing what follows
    to the far end. ``size`` (a CSS length) makes a fixed gap instead."""

    type = "spacer"

    def __init__(self, *, size: str = "") -> None:
        super().__init__()
        self._size = size

    def static_props(self) -> dict[str, Any]:
        return {"size": self._size} if self._size else {}


class Divider(Component):
    """A thin rule between groups. ``vertical=True`` draws it between the children of a ``Row``."""

    type = "divider"

    def __init__(self, *, vertical: bool = False) -> None:
        super().__init__()
        self._vertical = vertical

    def static_props(self) -> dict[str, Any]:
        return {"vertical": True} if self._vertical else {}


class Grid(Component):
    """An N-column grid of children that collapses to one column at phone width."""

    type = "grid"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        columns: int = 2,
        gap: str = "1rem",
    ) -> None:
        super().__init__(children)
        self._columns = columns
        self._gap = gap

    def static_props(self) -> dict[str, Any]:
        return {"columns": int(self._columns), "gap": self._gap}


class Shortcuts(Component):
    """Invisible keyboard shortcuts, active while this component is in the rendered tree.

    ``Shortcuts({"a": approve, "g l": (go_log, "Go to the log"), "mod+k": palette})``
    maps key specs (see :mod:`indah.keys`) to handlers, each optionally paired with a
    description for the ``?`` help overlay. Bare keys and sequences are ignored while
    the user types in a field or while a dialog is open; ``mod+``/``alt+`` combos fire
    anywhere outside a dialog. To scope a map to one page, place it inside that page's
    tab or container. Not user-rebindable.
    """

    type = "shortcuts"

    def __init__(self, keys: dict[str, Callable[[], Any] | tuple[Callable[[], Any], str]]) -> None:
        super().__init__()
        self._handlers: dict[str, Callable[[], Any]] = {}
        self._labels: dict[str, str] = {}
        for spec, target in keys.items():
            canonical = normalize_keys(spec)
            if canonical in self._handlers:
                raise ValueError(f"duplicate shortcut {canonical!r}")
            fn, label = target if isinstance(target, tuple) else (target, "")
            self._handlers[canonical] = fn
            self._labels[canonical] = label

    def static_props(self) -> dict[str, Any]:
        return {"keys": [{"keys": k, "label": self._labels[k]} for k in self._handlers]}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        fn = self._handlers.get(str(payload.get("keys", ""))) if event == "press" else None
        if fn is None:
            return False
        result = fn()
        if inspect.iscoroutine(result):
            return result
        return True


class SplitPane(Component):
    """Two panes with a draggable divider (IND-103). Everything is client-side: dragging,
    the arrow keys on the focused divider (Shift for bigger steps, Home/End for the limits,
    double-click to reset) and the remembered ratio (``localStorage``, by ``key``) never
    touch the server. ``initial`` is the first pane's share, ``min`` the least either pane
    may shrink to. A ``vertical`` split stacks the panes and needs a ``height`` (default
    ``28rem``); a horizontal one stacks on a phone."""

    type = "splitpane"

    def __init__(
        self,
        first: Component,
        second: Component,
        *,
        direction: str = "horizontal",
        initial: float = 0.4,
        min: float = 0.2,
        key: str | None = None,
        height: str | None = None,
    ) -> None:
        _check_split(direction, initial, min)
        if height is not None and not _CSS_LENGTH.match(height):
            raise ValueError(f"SplitPane height {height!r} must be a length like '20rem'")
        super().__init__([first, second])
        self._direction = direction
        self._initial = initial
        self._min = min
        self._key = key
        self._height = height

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {
            "direction": self._direction,
            "initial": self._initial,
            "min": self._min,
        }
        if self._key:
            props["key"] = self._key
        if self._height:
            props["height"] = self._height
        return props


def _check_split(direction: str, initial: float, minimum: float) -> None:
    if direction not in ("horizontal", "vertical"):
        raise ValueError(f"split direction must be horizontal or vertical, got {direction!r}")
    if not 0 < minimum <= 0.5:
        raise ValueError("split min must be in (0, 0.5]")
    if not minimum <= initial <= 1 - minimum:
        raise ValueError("split initial must lie within [min, 1 - min]")


class MasterDetail(Component):
    """A list beside its detail: a :class:`SplitPane` on wide screens, and on a narrow one
    the master alone with the detail in a drawer. ``open`` (a ``Signal[bool]``) says whether
    the drawer is showing; set it when the user picks a row, the drawer's close clears it.
    On a wide screen the detail is always visible and ``open`` is ignored."""

    type = "masterdetail"

    def __init__(
        self,
        master: Component,
        detail: Component,
        *,
        open: Signal[bool] | None = None,
        initial: float = 0.4,
        min: float = 0.2,
        key: str | None = None,
        title: str = "",
    ) -> None:
        _check_split("horizontal", initial, min)
        super().__init__([master, detail])
        self._open = open if open is not None else Signal(False)
        self._initial = initial
        self._min = min
        self._key = key
        self._title = title

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"initial": self._initial, "min": self._min, "title": self._title}
        if self._key:
            props["key"] = self._key
        return props

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"open": lambda: bool(self._open.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "close":
            self._open.set(False)
            return True
        return False


class Router(Component):
    """Pages chosen by the URL (ADR-0029). ``routes`` maps a pattern (``/``,
    ``/projects/{project}``) to the page's component; ``not_found`` is shown when none
    matches. Every page is built up front and the shell renders only the active one, so a
    page is a function of data (the route's params), not of structure. Hidden pages are
    still in the snapshot: never put anything role-restricted in one. Because every page
    exists from the start, its reactive code runs on every navigation, including when its
    route is not showing and its params are absent: read them with ``ctx.params.value.get``.

    The app must be created with ``spa=True`` so a deep link such as
    ``/ui/projects/auth`` serves the shell. Pair it with :class:`Link` for navigation and
    ``ctx.navigate`` for navigating from code.
    """

    type = "router"

    def __init__(
        self,
        ctx: Context,
        routes: dict[str, Component],
        *,
        not_found: Component | None = None,
    ) -> None:
        if not routes:
            raise ValueError("Router needs at least one route")
        compiled = [compile_route(pattern) for pattern in routes]
        super().__init__([*routes.values(), *([not_found] if not_found is not None else [])])
        ctx._set_routes(compiled)  # ctx.params reads the same table
        self._ctx = ctx
        self._routes = compiled
        self._has_not_found = not_found is not None

    def _active(self) -> int:
        found = match_routes(self._routes, self._ctx.path.value)
        if found is not None:
            return found[0]
        return len(self._routes) if self._has_not_found else -1

    def static_props(self) -> dict[str, Any]:
        return {"routes": [r.pattern for r in self._routes], "notFound": self._has_not_found}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"active": self._active}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "navigate":
            try:
                self._ctx._client_navigated(payload.get("path"))  # type: ignore[arg-type]
            except ValueError:
                return False
            return True
        return False


class Link(Component):
    """A real ``<a href>`` to an in-app path (ADR-0029): a plain click navigates without a
    page load, while a middle-click, Ctrl/Cmd-click or "open in new tab" use the URL as any
    link would. ``to`` is an in-app path like ``/projects/auth``, never an external URL; pass
    a callable for a link that depends on the route's params. ``active`` is true while the
    page is showing (``match="prefix"``: or one beneath it), so a sidebar can highlight where
    you are."""

    type = "link"

    def __init__(
        self, ctx: Context, label: str, *, to: str | Callable[[], str], match: str = "exact"
    ) -> None:
        if match not in ("exact", "prefix"):
            raise ValueError(f"Link match must be 'exact' or 'prefix', got {match!r}")
        super().__init__()
        self._ctx = ctx
        self._label = label
        # ``to`` may be a callable (a link that depends on the route's params); it is then
        # a reactive prop and is validated each time it is read.
        self._to_source = to
        self._static_to = normalize_path(to) if isinstance(to, str) else None
        self._match = match

    def _to(self) -> str:
        if self._static_to is not None:
            return self._static_to
        return normalize_path(self._to_source())  # type: ignore[operator]

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"label": self._label}
        if self._static_to is not None:
            props["to"] = self._static_to
        return props

    def _active(self) -> bool:
        path, to = self._ctx.path.value, self._to()
        if path == to:
            return True
        # ``prefix`` also lights up for the pages under it (whole segments; "/" is exact).
        return self._match == "prefix" and to != "/" and path.startswith(to + "/")

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props: dict[str, Callable[[], Any]] = {"active": self._active}
        if self._static_to is None:
            props["to"] = self._to
        return props

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "navigate" and payload.get("path") == self._to():
            self._ctx._client_navigated(self._to())
            return True
        return False


class NavItem(Link):
    """A ``Link`` for a sidebar or rail, with an optional ``icon`` and a live count ``badge``.

    ``badge`` may be a value, a signal or a callable. It shows as a small count at the end of
    the item and disappears when it is ``None``, empty or zero, so "Pending 3" becomes
    "Pending" the moment the queue is empty. ``icon`` is a short glyph (an emoji or a symbol),
    not an image. Active state, ``match`` and navigation are the Link's."""

    type = "navitem"

    def __init__(
        self,
        ctx: Context,
        label: str,
        *,
        to: str | Callable[[], str],
        badge: Source | None = None,
        icon: str | None = None,
        match: str = "exact",
    ) -> None:
        super().__init__(ctx, label, to=to, match=match)
        self._badge = badge
        self._icon = icon

    def static_props(self) -> dict[str, Any]:
        props = super().static_props()
        if self._icon:
            props["icon"] = self._icon
        return props

    def _badge_text(self) -> str:
        value = _read(self._badge)
        if value is None or value is False:
            return ""
        text = str(value).strip()
        return "" if text in ("", "0") else text

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        props = super().reactive_props()
        if self._badge is not None:
            props["badge"] = self._badge_text
        return props


MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_JSON_DEPTH = 64


def _json_clean(value: Any, depth: int = 0) -> Any:
    """Coerce ``value`` into data every JSON parser accepts: string keys, no NaN/Infinity,
    unknown objects as strings, and nesting cut at 64 levels."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if depth >= _MAX_JSON_DEPTH:
        return "..."
    if isinstance(value, dict):
        return {str(k): _json_clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(v, depth + 1) for v in value]
    return str(value)


def _json_doc(value: Any) -> dict[str, Any]:
    """``{"data", "error"}`` for a ``JsonTree``: the document as JSON-safe data, or an
    error message (invalid text, too large) with ``data`` of ``None``."""
    try:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        data = _json_clean(value)
        size = len(json.dumps(data, allow_nan=False))
    except (ValueError, RecursionError) as exc:  # JSONDecodeError and UnicodeDecodeError too
        return {"data": None, "error": f"Invalid JSON: {exc}"}
    if size > MAX_JSON_BYTES:
        limit = MAX_JSON_BYTES // (1024 * 1024)
        return {"data": None, "error": f"Document too large ({size // 1024} KB; limit {limit} MB)"}
    return {"data": data, "error": None}


class JsonTree(Component):
    """A read-only, collapsible view of a JSON document (IND-108): an object, a list, or
    JSON text (``str``/``bytes``). The browser renders a node's children only when it is
    opened, in chunks, so a megabyte document stays responsive. ``expanded`` is how many
    levels start open, ``search`` adds a filter box that opens the path to every match,
    and each node has a "copy path" button (``$.a.b[0]``). A value that is not valid JSON,
    or is over 8 MB, shows an error line instead of raising.
    """

    type = "jsontree"

    def __init__(
        self, value: Source, *, expanded: int = 1, search: bool = True, label: str = ""
    ) -> None:
        if expanded < 0:
            raise ValueError("JsonTree expanded must be >= 0")
        super().__init__()
        self._doc: Computed[dict[str, Any]] = Computed(lambda: _json_doc(_read(value)))
        self._expanded = expanded
        self._search = bool(search)
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"expanded": self._expanded, "search": self._search, "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"doc": lambda: self._doc.value}


class Diff(Component):
    """A read-only comparison of two documents (IND-109): ``a`` ("incoming") against ``b``
    ("candidate"), each an object, a list, JSON text or plain text. In ``normalise="json"``
    mode both sides are pretty-printed with sorted keys first, so key order and formatting
    never show up as changes; ``"text"`` compares them as written. The diff is computed here
    (see :mod:`indah.diff`) and the browser draws it, ``split`` (side by side) or ``unified``
    (the viewer can switch), with the changed characters of a changed line marked.
    ``context`` is how many unchanged lines stay around a change (``None`` keeps them all).
    At most 5,000 lines per side are compared, and a very large, very repetitive input is
    diffed approximately; both are flagged in the UI.
    """

    type = "diff"

    def __init__(
        self,
        a: Source,
        b: Source,
        *,
        mode: str = "split",
        normalise: str = "json",
        context: int | None = 3,
        labels: tuple[str, str] = ("incoming", "candidate"),
    ) -> None:
        if mode not in ("split", "unified"):
            raise ValueError(f"Diff mode must be 'split' or 'unified', got {mode!r}")
        if normalise not in ("json", "text"):
            raise ValueError(f"Diff normalise must be 'json' or 'text', got {normalise!r}")
        if context is not None and context < 0:
            raise ValueError("Diff context must be >= 0 or None")
        if len(labels) != 2:
            raise ValueError("Diff labels must be a pair")
        super().__init__()
        self._mode = mode
        self._labels = [str(labels[0]), str(labels[1])]
        self._diff: Computed[dict[str, Any]] = Computed(
            lambda: compute_diff(_read(a), _read(b), normalise=normalise, context=context)
        )

    def static_props(self) -> dict[str, Any]:
        return {"mode": self._mode, "labels": self._labels}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"diff": lambda: self._diff.value}


class Tabs(Component):
    """A tabbed container: one child panel shown at a time (ADR-0015).

    ``labels`` names the tabs (one per child); ``active`` is the index of the shown
    panel. Pass a ``Signal[int]`` to drive it from Python, or leave it and the
    container keeps its own; either way a tab click round-trips through the graph
    and the shell re-renders only the active panel.
    """

    type = "tabs"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        labels: list[Any],
        active: Signal[int] | int | None = None,
    ) -> None:
        super().__init__(children)
        self._labels = [str(label) for label in labels]
        self._active = _as_signal(active, 0, int)

    def static_props(self) -> dict[str, Any]:
        return {"labels": self._labels}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"active": lambda: int(self._active.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "select" and "index" in payload:
            self._active.set(int(payload["index"]))
            return True
        return False


class Sidebar(Component):
    """A persistent side region plus a main region (ADR-0015).

    The first child renders in the sidebar; the rest render in the main region.
    On a narrow screen the sidebar stacks above the main region.
    """

    type = "sidebar"


class AppShell(Component):
    """The frame of an app: a pinned rail beside a scrolling main region, with an optional top bar.

    ``rail`` (a component, usually a ``Column`` with the logo, a switcher and ``NavItem``s or
    ``Link``s) stays in place while the page scrolls. ``main`` is the content (a component, or a
    list that is wrapped in a ``Column``) and keeps the app's ``max_width``. ``top`` is an
    optional bar above ``main``. ``rail_width`` is a CSS length (default ``"256px"``). On a
    narrow screen the rail becomes a drawer behind a menu button; choosing a link or button in
    it closes the drawer. Works inside a ``Router`` page and with ``create_app(spa=True)``.
    """

    type = "appshell"

    def __init__(
        self,
        *,
        rail: Component,
        main: Component | list[Component],
        top: Component | None = None,
        rail_width: str = "256px",
    ) -> None:
        if not _CSS_LENGTH.match(rail_width):
            raise ValueError(f"rail_width must be a CSS length like '256px', got {rail_width!r}")
        if isinstance(main, list):
            main = Column(children=main)
        super().__init__([rail, main] + ([top] if top is not None else []))
        self._has_top = top is not None
        self._rail_width = rail_width

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        if self._has_top:
            props["hasTop"] = True
        if self._rail_width != "256px":
            props["railWidth"] = self._rail_width
        return props


class Expander(Component):
    """A collapsible section: a labelled header that shows/hides its children.

    ``open`` is a reactive prop -- pass a ``Signal[bool]`` to drive it from Python,
    or a plain bool for the initial state. Toggling in the UI round-trips through
    the graph and the shell renders the children only while open.
    """

    type = "expander"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        label: str = "",
        open: Signal[bool] | bool = False,
    ) -> None:
        super().__init__(children)
        self._label = label
        self._open = _as_signal(open, False, bool)

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"open": lambda: bool(self._open.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "toggle":
            if "value" in payload:
                self._open.set(bool(payload["value"]))
            else:
                self._open.set(not self._open.value)
            return True
        return False


# -- Overlays (ADR-0030) ------------------------------------------------------


class _Overlay(Component):
    """Shared behaviour of :class:`Modal` and :class:`Drawer`: an ``open`` signal the
    shell renders the children for only while true, and a ``close`` event (Esc, the
    backdrop or the close button) that clears it and runs ``on_close``.

    The children stay in the tree, so their props are in the snapshot even while the
    overlay is closed: do not put anything secret in one.
    """

    def __init__(
        self,
        children: list[Component] | None,
        *,
        open: Signal[bool] | bool,
        title: str,
        on_close: Callable[[], Any] | None,
    ) -> None:
        super().__init__(children)
        self._open = _as_signal(open, False, bool)
        self._title = title
        self._on_close = on_close

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"open": lambda: bool(self._open.value)}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if event == "close":
            self._open.set(False)
            if self._on_close is not None:
                result = self._on_close()
                if inspect.iscoroutine(result):
                    return result
            return True
        return False


class Modal(_Overlay):
    """A centred dialog over a backdrop, with a focus trap and Esc to close."""

    type = "modal"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        open: Signal[bool] | bool = False,
        title: str = "",
        size: str = "md",
        on_close: Callable[[], Any] | None = None,
    ) -> None:
        if size not in ("sm", "md", "lg"):
            raise ValueError(f"Modal size must be sm, md or lg, got {size!r}")
        super().__init__(children, open=open, title=title, on_close=on_close)
        self._size = size

    def static_props(self) -> dict[str, Any]:
        return {"title": self._title, "size": self._size}


class Drawer(_Overlay):
    """A panel sliding in from the ``left`` or ``right`` edge; same behaviour as Modal."""

    type = "drawer"

    def __init__(
        self,
        children: list[Component] | None = None,
        *,
        open: Signal[bool] | bool = False,
        side: str = "right",
        title: str = "",
        on_close: Callable[[], Any] | None = None,
    ) -> None:
        if side not in ("left", "right"):
            raise ValueError(f"Drawer side must be left or right, got {side!r}")
        super().__init__(children, open=open, title=title, on_close=on_close)
        self._side = side

    def static_props(self) -> dict[str, Any]:
        return {"title": self._title, "side": self._side}


# -- Data-driven list (ADR-0016) ---------------------------------------------
#
# Growing/variable content (logs, search results, chat, galleries) is modelled as
# *data*, not as a growing subtree: the items live in one reactive prop and the
# shell renders each through a template. Add/remove/reorder is an ordinary prop
# change carried by the existing ``patch`` op -- no structural children op, no
# ``protocol_version`` bump. ``Chat`` and ``Gallery`` are specialisations the shell
# renders with a built-in template; the generic ``List`` renders each item with an
# ADR-0012 render spec (or as text when none is given).


def _to_items(value: Any) -> list[Any]:
    """Coerce a source value to a JSON-safe list of items (dicts or scalars)."""
    if value is None:
        return []
    out: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            out.append({str(k): _json_safe(v) for k, v in item.items()})
        else:
            out.append(_json_safe(item))
    return out


class List(Component):
    """A data-driven list bound to a ``Signal[list]`` (ADR-0016).

    The items live in one reactive prop; set the signal to a new list to add,
    remove, or reorder (mutating in place will not notify -- assign a fresh list,
    e.g. ``items.set(items.value + [row])``). Pass an ``item`` render spec (the
    ADR-0012 vocabulary, binding each item's fields) to shape each row; without one
    each item renders as text. ``empty`` is shown when the list is empty.

    Editable rows (ADR-0016 amendment, IND-110): give ``key="id"`` and every item must be
    a dict with a unique ``id``. The shell then keys each row by it, so adding, removing or
    reordering keeps every other row (and the cursor in a focused input) in place. A
    template event (an ``on={...}`` in the spec) is delivered to
    ``on_item(key, event, value)`` -- sync or ``async`` -- for the row it came from; update
    the signal from there. A key that is not a current row is refused.
    """

    type = "list"

    def __init__(
        self,
        items: Source,
        *,
        item: dict[str, Any] | RenderSpec | None = None,
        empty: str = "",
        key: str | None = None,
        on_item: Callable[[Any, str, Any], Any] | None = None,
    ) -> None:
        super().__init__()
        if on_item is not None and key is None:
            raise ValueError("List on_item= needs key= (events refer to rows by key)")
        if key is not None and isinstance(items, Stream):
            raise ValueError("a keyed List takes a signal or callable, not a Stream")
        self._items = items
        self._empty = empty
        self._key = key
        self._on_item = on_item
        if item is None:
            self._template: dict[str, Any] | None = None
        else:
            spec = item if isinstance(item, RenderSpec) else RenderSpec.model_validate(item)
            self._template = spec.validated().wire()

    def static_props(self) -> dict[str, Any]:
        props: dict[str, Any] = {"empty": self._empty}
        if self._template is not None:
            props["template"] = self._template
        if self._key is not None:
            props["keyField"] = self._key
        return props

    def _current(self) -> list[Any]:
        items = _to_items(_read(self._items))
        if self._key is not None:
            seen: set[Any] = set()
            for row in items:
                if not isinstance(row, dict):
                    raise ValueError(f"List key={self._key!r} needs dict items, got {row!r}")
                if self._key not in row:
                    raise ValueError(f"List item is missing its key {self._key!r}: {row!r}")
                if row[self._key] in seen:
                    raise ValueError(f"List keys must be unique; {row[self._key]!r} repeats")
                seen.add(row[self._key])
        return items

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"items": self._current}

    def stream_props(self) -> dict[str, tuple[Stream, Callable[[list[Any]], list[Any]]]]:
        if isinstance(self._items, Stream) and self._key is None:
            return {"items": (self._items, _to_items)}
        return {}

    def handle(self, event: str, payload: dict[str, Any]) -> bool | Any:
        if self._on_item is None or "key" not in payload:
            return False
        key = payload["key"]
        try:
            known = any(row.get(self._key) == key for row in self._current())
        except ValueError:
            return False
        if not known:
            return False
        result = self._on_item(key, event, payload.get("value"))
        if inspect.iscoroutine(result):
            return result
        return True


def _to_messages(value: Any) -> list[dict[str, str]]:
    """Normalise chat messages to ``[{"role","content"}, ...]`` (both strings)."""
    if value is None:
        return []
    out: list[dict[str, str]] = []
    for message in value:
        if isinstance(message, dict):
            role = str(message.get("role", "assistant"))
            content = str(message.get("content", ""))
        elif isinstance(message, (tuple, list)) and len(message) == 2:
            role, content = str(message[0]), str(message[1])
        else:
            continue
        out.append({"role": role, "content": content})
    return out


class Chat(Component):
    """A chat transcript of role bubbles bound to a ``Signal[list]`` (ADR-0016).

    ``messages`` is a list of ``{"role","content"}`` (or ``(role, content)``) items;
    the shell renders one bubble per message and auto-scrolls to the newest. Bind
    ``pending`` to a ``Signal[str]`` to show a live, still-streaming assistant bubble
    while a reply is being generated (set it back to ``""`` once committed).
    """

    type = "chat"

    def __init__(self, messages: Source, *, pending: Source = None, label: str = "") -> None:
        super().__init__()
        self._messages = messages
        self._pending = pending
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {
            "messages": lambda: _to_messages(_read(self._messages)),
            "pending": lambda: str(_read(self._pending)) if self._pending is not None else "",
        }


def _to_images(value: Any) -> list[dict[str, str]]:
    """Normalise gallery images to ``[{"src","alt","caption"}, ...]``.

    Accepts a URL/``data:`` URI string, raw PNG ``bytes``, or a dict with ``src``
    (plus optional ``alt``/``caption``); reuses the ``Image`` source coercion.
    """
    if value is None:
        return []
    out: list[dict[str, str]] = []
    for image in value:
        if isinstance(image, dict):
            out.append(
                {
                    "src": _image_src(image.get("src")),
                    "alt": str(image.get("alt", "")),
                    "caption": str(image.get("caption", "")),
                }
            )
        else:
            out.append({"src": _image_src(image), "alt": "", "caption": ""})
    return out


class Gallery(Component):
    """An image grid bound to a ``Signal[list]`` (ADR-0016).

    ``images`` is a list of URL/``data:`` strings, PNG ``bytes``, or
    ``{"src","alt","caption"}`` dicts; the shell lays them out in ``columns``
    columns (collapsing on a phone). Set the signal to a new list to grow the grid.
    """

    type = "gallery"

    def __init__(self, images: Source, *, columns: int = 3, label: str = "") -> None:
        super().__init__()
        self._images = images
        self._columns = columns
        self._label = label

    def static_props(self) -> dict[str, Any]:
        return {"columns": int(self._columns), "label": self._label}

    def reactive_props(self) -> dict[str, Callable[[], Any]]:
        return {"images": lambda: _to_images(_read(self._images))}


def walk(root: Component):
    """Yield every component in the tree, pre-order."""
    yield root
    for child in root.children:
        yield from walk(child)

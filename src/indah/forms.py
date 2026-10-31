"""A form helper: disabled until valid, errors beside the field (ADR-0047).

``Form`` groups inputs, takes a validator per field, exposes ``valid`` and the error text, and
makes one submit button that is disabled while the form is invalid. It builds ordinary
components (a ``TextInput``, a ``Select``, a ``Button``), so layout stays the app's own::

    form = indah.Form(on_submit=invite)  # invite(values) -> None | {field: message}
    email = form.text("email", label="Email", validate=[validators.required(), validators.email()])
    page = indah.Column(children=[email, form.submit("Send invite")])

Every rule runs on the server, on each change. A form belongs to one session: build it in the
session factory, like any signal.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

from .components import Button, Select, TextInput, _normalise_option
from .reactive import Computed, Signal, batch, computed, effect

logger = logging.getLogger("indah")

Validator = Callable[[str], "str | None"]


class validators:  # noqa: N801 - a namespace: ``indah.validators.required()``
    """Ready-made validators: ``str -> str | None`` (the message, or ``None`` when fine).

    Anything else is a lambda. Emptiness is ``required``'s job, so the others accept ``""``."""

    @staticmethod
    def required(message: str = "Required") -> Validator:
        return lambda value: None if value.strip() else message

    @staticmethod
    def min_length(n: int, message: str | None = None) -> Validator:
        text = message or f"Use at least {n} characters"
        return lambda value: text if value and len(value) < n else None

    @staticmethod
    def max_length(n: int, message: str | None = None) -> Validator:
        text = message or f"Use at most {n} characters"
        return lambda value: text if len(value) > n else None

    @staticmethod
    def pattern(regex: str, message: str = "Invalid") -> Validator:
        compiled = re.compile(regex)
        return lambda value: None if not value or compiled.fullmatch(value) else message

    @staticmethod
    def email(message: str = "Enter a valid email address") -> Validator:
        # Deliberately loose: one @, no spaces, a dot in the domain. The server that sends the
        # mail is the real check.
        shape = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")
        return lambda value: None if not value or shape.fullmatch(value) else message


class _Field:
    def __init__(
        self, name: str, signal: Signal[str], initial: str, rules: Iterable[Validator]
    ) -> None:
        self.name = name
        self.signal = signal
        self.initial = initial
        self.rules = list(rules)
        self.server: Signal[tuple[str, str] | None] = Signal(None)  # (message, value it was for)
        self.touched: Signal[bool] = Signal(False)  # the value has changed at least once
        armed = False
        self._restoring = False  # the next change is ``reset`` putting the value back

        def watch() -> None:
            nonlocal armed
            signal.value  # noqa: B018 - track every change
            if self._restoring:
                self._restoring = False
            elif armed:
                self.touched.set(True)
            armed = True

        self._watch = effect(watch)  # kept: an effect nobody holds is collected

    def restore(self) -> None:
        """Back to ``initial``, untouched and with no server error."""
        self._restoring = self.signal.value != self.initial  # no change, no effect run to clear it
        self.signal.set(self.initial)
        self.server.set(None)
        self.touched.set(False)

    def check(self) -> str | None:
        """The first failing validator's message. A validator that raises is a failure."""
        value = self.signal.value
        for rule in self.rules:
            try:
                message = rule(value)
            except Exception:
                logger.exception("a form validator raised for field %r", self.name)
                return "Invalid"
            if message:
                return str(message)
        return None

    def server_error(self) -> str | None:
        """A server-side message, for as long as the value is the one it was set for."""
        current = self.server.value
        if current is not None and current[1] == self.signal.value:
            return current[0]
        return None


class Form:
    """Fields, validators, ``valid``, the error text and one submit button (ADR-0047).

    ``on_submit(values)`` (sync or async) gets ``{name: str}``; it may return ``{name: message}``
    to put a server-side error beside a field. ``valid``, ``values`` and ``errors`` are computed
    values and ``submitting`` a signal, so the rest of the page can follow them."""

    def __init__(self, on_submit: Callable[[dict[str, str]], Any] | None = None) -> None:
        self._on_submit = on_submit
        self._fields: dict[str, _Field] = {}
        self._count = Signal(0)  # read by the computed values, so a late field is tracked
        self.submitting: Signal[bool] = Signal(False)
        self.values: Computed[dict[str, str]] = computed(self._values)
        self.errors: Computed[dict[str, str]] = computed(self._errors)
        self.valid: Computed[bool] = computed(lambda: not self.errors.value)

    # -- fields ------------------------------------------------------------

    def text(
        self,
        name: str,
        *,
        label: str = "",
        placeholder: str = "",
        initial: str = "",
        validate: Iterable[Validator] = (),
        password: bool = False,
    ) -> TextInput:
        field = self._add(name, initial, validate)
        return TextInput(
            field.signal,
            label=label,
            placeholder=placeholder,
            password=password,
            error=lambda: self._shown(field),
        )

    def select(
        self,
        name: str,
        *,
        options: list[Any],
        label: str = "",
        initial: str | None = None,
        validate: Iterable[Validator] = (),
    ) -> Select:
        if initial is None:
            first = options[0] if isinstance(options, (list, tuple)) and options else ""
            initial = _normalise_option(first)["value"] if first != "" else ""
        field = self._add(name, initial, validate)
        return Select(field.signal, options=options, label=label, error=lambda: self._shown(field))

    def submit(self, label: str = "Submit", *, variant: str = "filled") -> Button:
        """The submit button: disabled while the form is invalid or a submission runs. The
        click handler checks again on the server and does nothing when it should not run."""
        return Button(
            label,
            self._click,
            variant=variant,
            disabled=lambda: self.submitting.value or not self.valid.value,
        )

    def _add(self, name: str, initial: str, validate: Iterable[Validator]) -> _Field:
        if name in self._fields:
            raise ValueError(f"the form already has a field named {name!r}")
        field = _Field(name, Signal(str(initial)), str(initial), validate)
        self._fields[name] = field
        self._count.set(self._count.value + 1)
        return field

    # -- state -------------------------------------------------------------

    def _values(self) -> dict[str, str]:
        self._count.value  # noqa: B018 - track fields added later
        return {name: field.signal.value for name, field in self._fields.items()}

    def _errors(self) -> dict[str, str]:
        self._count.value  # noqa: B018
        out: dict[str, str] = {}
        for name, field in self._fields.items():
            message = field.server_error() or field.check()
            if message:
                out[name] = message
        return out

    def _shown(self, field: _Field) -> str | None:
        """What to show beside a field: a server error, else a validator error once the person
        has changed the field (even back to its initial value)."""
        server = field.server_error()
        if server:
            return server
        return field.check() if field.touched.value else None

    def set_error(self, name: str, message: str) -> None:
        """Put a server-side ``message`` beside a field. It stays until the field's value
        changes. Raises ``KeyError`` for a name the form does not have."""
        field = self._fields[name]
        field.server.set((str(message), field.signal.value))

    def reset(self) -> None:
        """Every field back to its ``initial``, no errors, as on load."""

        def apply() -> None:
            for field in self._fields.values():
                field.restore()

        batch(apply)

    # -- submit ------------------------------------------------------------

    async def _click(self) -> None:
        if self.submitting.value or not self.valid.value:
            return
        self.submitting.set(True)
        try:
            result = None
            if self._on_submit is not None:
                result = self._on_submit(dict(self.values.value))
                if inspect.isawaitable(result):
                    result = await result
            if isinstance(result, dict):
                for name, message in result.items():
                    if name in self._fields and message:
                        self.set_error(name, str(message))
        finally:
            self.submitting.set(False)

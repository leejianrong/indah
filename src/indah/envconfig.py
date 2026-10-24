"""Configuration from the environment for ``create_app`` (IND-202).

ConfigMaps, Secrets and ``fly secrets`` set environment variables, not Python arguments. For each
setting below, ``create_app`` reads the variable only when the matching argument was **not given**:
an explicit argument always wins, including an explicit empty list or ``None``. A variable that is
unset or blank counts as not set. A bad value fails when the app is created, with a message that
names the variable. Secret values are never logged: the log names the variables that were used.

- ``INDAH_SECRETS`` -> ``secret=`` as a list (comma separated; the first signs, any verifies)
- ``INDAH_SECRET`` -> ``secret=`` (one secret; ignored when ``INDAH_SECRETS`` is set)
- ``INDAH_TRUSTED_PROXIES`` -> ``trusted_proxies=`` (comma separated IPs, CIDRs or preset names
  ``fly``, ``cloudflare``, ``k8s``, ``private``; ``*`` and ``auto`` refused)
- ``INDAH_FLY_IPS`` -> the public IPs the ``fly`` preset trusts (the preset reads it, not
  ``create_app``)
- ``INDAH_ALLOWED_ORIGINS`` -> ``allowed_origins=`` (comma separated ``https://host[:port]``)
- ``INDAH_CSP`` -> ``csp=`` (``strict`` or ``off``)
- ``INDAH_LIMITS`` -> ``limits=`` (a preset: ``public`` or ``none``)
- ``INDAH_DRAIN_SECONDS`` -> ``drain_seconds=`` (seconds, 0 or more)
- ``INDAH_FACTORY_TIMEOUT`` -> ``factory_timeout=`` (seconds, more than 0)
- ``INDAH_COMPRESS`` -> ``compress=`` (1/0, true/false, yes/no, on/off)
- ``INDAH_WARN_UNTRUSTED_FORWARDING`` -> ``warn_untrusted_forwarding=`` (same booleans)
- ``INDAH_NODE_HEADER`` -> ``node_header=`` (same booleans; ``INDAH_NODE`` names the node)
- ``INDAH_DOCTOR_TOKEN`` -> ``doctor=`` (a token of 16+ characters; turns the deploy doctor on)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from .guard import normalize_origins
from .hardening import Limits
from .proxy_presets import check_entries

logger = logging.getLogger("indah")


class _Unset:
    """The default of an argument that the environment may fill: 'not given'."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Any = _Unset()

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


class EnvConfig:
    """Resolve settings from ``environ`` and remember which variables were used."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        self.used: list[str] = []
        self.secret_variable: str | None = None

    def _take(self, name: str) -> str | None:
        value = self._environ.get(name)
        if value is None or not value.strip():
            return None
        self.used.append(name)
        return value.strip()

    def secret(self, arg: Any) -> Any:
        """``secret=`` if given (``None`` is not given), else INDAH_SECRETS, else INDAH_SECRET."""
        if arg is not None:
            return arg
        many = self._take("INDAH_SECRETS")
        if many is not None:
            self.secret_variable = "INDAH_SECRETS"
            return _split(many)
        one = self._take("INDAH_SECRET")
        if one is not None:
            self.secret_variable = "INDAH_SECRET"
        return one

    def trusted_proxies(self, arg: Any) -> Sequence[str]:
        if arg is not UNSET:
            return arg
        text = self._take("INDAH_TRUSTED_PROXIES")
        if text is None:
            return ()
        entries = _split(text)
        if "*" in entries:
            raise ValueError(
                "INDAH_TRUSTED_PROXIES: '*' is refused, it would make every forwarded header "
                "believable. List your gateway's IPs or CIDRs, or name a preset."
            )
        try:
            check_entries(entries)
        except ValueError as exc:
            raise ValueError(f"INDAH_TRUSTED_PROXIES: {exc}") from None
        return entries

    def allowed_origins(self, arg: Any) -> Sequence[str]:
        if arg is not UNSET:
            return arg
        text = self._take("INDAH_ALLOWED_ORIGINS")
        if text is None:
            return ()
        entries = _split(text)
        try:
            normalize_origins(entries)
        except ValueError as exc:
            raise ValueError(f"INDAH_ALLOWED_ORIGINS: {exc}") from None
        return entries

    def csp(self, arg: Any) -> str | None:
        if arg is not UNSET:
            return arg
        text = self._take("INDAH_CSP")
        if text is None:
            return None
        value = text.lower()
        if value == "strict":
            return "strict"
        if value in ("off", "none"):
            return None
        raise ValueError("INDAH_CSP must be 'strict' or 'off' (a custom policy is csp= in code)")

    def limits(self, arg: Any) -> Limits | None:
        if arg is not UNSET:
            return arg
        text = self._take("INDAH_LIMITS")
        if text is None:
            return None
        value = text.lower()
        if value == "public":
            return Limits.public()
        if value in ("none", "off"):
            return None
        raise ValueError("INDAH_LIMITS must be 'public' or 'none'")

    def number(self, name: str, arg: Any, default: float, *, positive: bool = False) -> float:
        """A number of seconds: ``positive`` means more than 0, otherwise 0 or more."""
        if arg is not UNSET:
            return arg
        text = self._take(name)
        if text is None:
            return default
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{name} must be a number of seconds, got {text!r}") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{name} must be a finite number of seconds, got {text!r}")
        if positive and not value > 0:
            raise ValueError(f"{name} must be more than 0, got {text!r}")
        if not positive and value < 0:
            raise ValueError(f"{name} must be 0 or more, got {text!r}")
        return value

    def boolean(self, name: str, arg: Any, default: bool) -> bool:
        if arg is not UNSET:
            return arg
        text = self._take(name)
        if text is None:
            return default
        value = text.lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        raise ValueError(f"{name} must be one of 1/0, true/false, yes/no, on/off, got {text!r}")

    def doctor(self, arg: Any) -> Any:
        """``doctor=`` if given (even ``None`` or ``False``), else INDAH_DOCTOR_TOKEN, else off."""
        if arg is not UNSET:
            return arg
        return self._take("INDAH_DOCTOR_TOKEN")

    def report(self) -> tuple[str, ...]:
        """Log once, at INFO, which variables configured this app (names only)."""
        names = tuple(dict.fromkeys(self.used))
        if names:
            logger.info("indah: configured from the environment: %s", ", ".join(names))
        return names

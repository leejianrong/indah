"""App-level theme tokens: override the shell's design tokens for one app (IND-88).

The shell styles everything through CSS custom properties (ADR-0014), so a theme is a
token-set swap::

    create_app(theme=Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"},
                           radius="8px", font="system-ui, sans-serif"))

The result is injected as one ``<style>`` block after the shell's own, so it wins at
equal specificity. Because the values land inside that block, names are checked against
the documented token set and values against a conservative character allowlist: nothing
that could close the block, open a rule or fetch a resource gets through.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# The colour/elevation roles an app may override per scheme (``--radius`` and the font
# stacks have their own arguments, since they do not differ between light and dark).
COLOUR_TOKENS = frozenset(
    {
        "bg",
        "surface",
        "surface-2",
        "surface-3",
        "text",
        "muted",
        "outline",
        "outline-soft",
        "primary",
        "on-primary",
        "primary-container",
        "on-primary-container",
        "secondary",
        "on-secondary",
        "secondary-container",
        "on-secondary-container",
        "ok",
        "warn",
        "err",
        "shadow",
    }
)

# Letters, digits, space and the punctuation of colours (#hex, rgb(), oklch(), alpha),
# lengths (rem, %), shadows and font stacks (quotes, commas). No ``; { } < > \ @ :``.
_VALUE_OK = re.compile(r"[A-Za-z0-9 #%.,()'\"\-+/*_]{1,120}")
_FORBIDDEN = ("url(", "expression", "import", "javascript")


def _value(name: str, value: str) -> str:
    text = str(value).strip()
    if not _VALUE_OK.fullmatch(text) or any(word in text.lower() for word in _FORBIDDEN):
        raise ValueError(f"theme value for {name!r} is not an allowed CSS value: {value!r}")
    return text


# An app's own roles (ADR-0031 amendment, IND-134): ``x-`` then lowercase words, so they can
# never shadow a core role and the core set stays closed.
_EXTRA_NAME = re.compile(r"x-[a-z0-9]+(-[a-z0-9]+)*")


def _extras(scheme: str, tokens: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw, value in (tokens or {}).items():
        name = str(raw).removeprefix("--")
        if not _EXTRA_NAME.fullmatch(name):
            raise ValueError(
                f"extra {scheme} theme token {raw!r} must be named x-<name>, "
                "lowercase letters, digits and hyphens (e.g. 'x-brand')"
            )
        out[name] = _value(name, value)
    return out


def _tokens(scheme: str, tokens: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw, value in (tokens or {}).items():
        name = str(raw).removeprefix("--")
        if name not in COLOUR_TOKENS:
            allowed = ", ".join(sorted(COLOUR_TOKENS))
            raise ValueError(f"unknown {scheme} theme token {raw!r} (allowed: {allowed})")
        out[name] = _value(name, value)
    return out


class Theme:
    """Token overrides for one app. ``light``/``dark`` map a token name (with or without
    the leading ``--``) to a CSS value; ``radius`` and ``font`` apply to both schemes.

    ``extra_light`` / ``extra_dark`` add the app's own tokens, which must be named ``x-<name>``
    and are emitted as ``--x-<name>`` for the app's own CSS to read. The core roles above stay a
    closed set. Define an extra in both schemes if it should differ, since a token set only in
    ``extra_dark`` has no value in the light scheme."""

    def __init__(
        self,
        *,
        light: Mapping[str, str] | None = None,
        dark: Mapping[str, str] | None = None,
        radius: str | None = None,
        font: str | None = None,
        extra_light: Mapping[str, str] | None = None,
        extra_dark: Mapping[str, str] | None = None,
    ) -> None:
        self.light = _tokens("light", light) | _extras("light", extra_light)
        self.dark = _tokens("dark", dark) | _extras("dark", extra_dark)
        self.radius = _value("radius", radius) if radius is not None else None
        self.font = _value("font", font) if font is not None else None

    def css(self) -> str:
        """The override stylesheet, or ``""`` when there is nothing to override."""
        base = dict(self.light)
        if self.radius:
            base["radius"] = self.radius
        rules = []
        if base or self.font:
            body = [f"--{k}: {v};" for k, v in base.items()]
            if self.font:
                body += [f"--font-body: {self.font};", f"--font-display: {self.font};"]
            rules.append(":root {\n  " + "\n  ".join(body) + "\n}")
        if self.dark:
            body = [f"--{k}: {v};" for k, v in self.dark.items()]
            rules.append(':root[data-theme="dark"] {\n  ' + "\n  ".join(body) + "\n}")
        return "\n".join(rules)

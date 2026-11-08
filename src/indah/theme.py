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

import hashlib
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

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


_MAX_FONT_BYTES = 2 * 1024 * 1024
_MAX_FONTS = 8
_FAMILY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,59}")
_WEIGHT = re.compile(r"[1-9]00(?: [1-9]00)?")


@dataclass(frozen=True)
class Font:
    """One self-hosted font file for ``Theme(fonts=[...])``.

    ``src`` is woff2 bytes or a path to a ``.woff2`` file, read once when the theme is built;
    a URL is never accepted. ``family`` is the name to use in a font stack (``font_body="'Hanken
    Grotesk', sans-serif"``). ``weight`` is ``"400"`` or a variable font's range, ``"100 900"``."""

    family: str
    src: bytes | str | os.PathLike[str]
    weight: str = "400"
    style: str = "normal"


def _load_font(font: Font) -> bytes:
    if not isinstance(font, Font):
        raise TypeError(f"fonts take Font(...) items, got {font!r}")
    if not _FAMILY.fullmatch(font.family):
        raise ValueError(f"font family {font.family!r} must be 1-60 letters, digits, space, _ or -")
    if not _WEIGHT.fullmatch(font.weight):
        raise ValueError(f"font weight {font.weight!r} must be like '400' or '100 900'")
    if font.style not in ("normal", "italic"):
        raise ValueError(f"font style {font.style!r} must be 'normal' or 'italic'")
    data = bytes(font.src) if isinstance(font.src, bytes) else Path(font.src).read_bytes()
    if len(data) > _MAX_FONT_BYTES:
        raise ValueError(
            f"font {font.family!r} is {len(data)} bytes; the limit is {_MAX_FONT_BYTES}"
        )
    if not data.startswith(b"wOF2"):
        raise ValueError(f"font {font.family!r} must be woff2 bytes or the path of a .woff2 file")
    return data


_MAX_CSS_BYTES = 256 * 1024
_STYLE_END = re.compile(r"</style", re.IGNORECASE)


def _load_css(css: str | Path | None) -> str:
    """The app stylesheet: a ``Path`` is read once, a ``str`` is the CSS itself."""
    if css is None:
        return ""
    if isinstance(css, str):
        text = css
        if "{" not in text and text.strip().endswith(".css"):
            raise ValueError(
                f"css={css!r} looks like a file name; pass pathlib.Path(...) to read it"
            )
    else:
        text = Path(css).read_text(encoding="utf-8")
    if len(text.encode()) > _MAX_CSS_BYTES:
        raise ValueError(f"css is over the {_MAX_CSS_BYTES} byte limit")
    if _STYLE_END.search(text):
        raise ValueError("css must not contain a </style tag")
    return text.strip()


def _font_name(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16] + ".woff2"


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
    the leading ``--``) to a CSS value; ``radius`` and the fonts apply to both schemes.

    ``font_display`` (headings, the brand), ``font_body`` (running text) and ``font_mono``
    (code, numbers, table headers) each set one font stack. ``font`` stays as the shorthand for
    display and body together; a slot given with it wins for its own token.

    ``fonts`` ships typefaces with the app: each :class:`Font` is a woff2 file the app serves from
    its own origin (cached for a year) with a generated ``@font-face``, so the page never asks
    another host for a font and the CSP is unchanged.

    ``css`` is the app's own stylesheet (a ``Path`` is read once, a ``str`` is the CSS), emitted
    after everything above in the same nonced ``<style>``, so a ``@media`` rule works under
    ``csp="strict"`` with no custom component. It is trusted app code, not user input.

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
        font_display: str | None = None,
        font_body: str | None = None,
        font_mono: str | None = None,
        fonts: Iterable[Font] = (),
        css: str | Path | None = None,
        extra_light: Mapping[str, str] | None = None,
        extra_dark: Mapping[str, str] | None = None,
    ) -> None:
        self._css = _load_css(css)
        self.light = _tokens("light", light) | _extras("light", extra_light)
        self.dark = _tokens("dark", dark) | _extras("dark", extra_dark)
        self.radius = _value("radius", radius) if radius is not None else None
        self.font = _value("font", font) if font is not None else None
        # ``font`` is the shorthand for display and body; a slot overrides it for its own token.
        self.font_display = _value("font_display", font_display) if font_display else self.font
        self.font_body = _value("font_body", font_body) if font_body else self.font
        self.font_mono = _value("font_mono", font_mono) if font_mono is not None else None
        # name -> bytes, served by ``create_app`` at ``api/fonts/<name>`` (name = content hash)
        self.font_files: dict[str, bytes] = {}
        self._faces: list[str] = []
        listed = list(fonts)
        if len(listed) > _MAX_FONTS:
            raise ValueError(f"at most {_MAX_FONTS} fonts, got {len(listed)}")
        seen: set[tuple[str, str, str]] = set()
        for font in listed:
            data = _load_font(font)
            key = (font.family, font.weight, font.style)
            if key in seen:
                raise ValueError(f"font {font.family!r} {font.weight} {font.style} is listed twice")
            seen.add(key)
            name = _font_name(data)
            self.font_files[name] = data
            self._faces.append(
                "@font-face {\n"
                f"  font-family: '{font.family}';\n"
                f"  font-style: {font.style};\n"
                f"  font-weight: {font.weight};\n"
                "  font-display: swap;\n"
                f"  src: url(api/fonts/{name}) format('woff2');\n"
                "}"
            )

    def css(self) -> str:
        """The override stylesheet, or ``""`` when there is nothing to override."""
        base = dict(self.light)
        if self.radius:
            base["radius"] = self.radius
            base["radius-control"] = self.radius  # buttons and badges follow it too
        rules = list(self._faces)
        slots = {
            "font-display": self.font_display,
            "font-body": self.font_body,
            "font-mono": self.font_mono,
        }
        if base or any(slots.values()):
            body = [f"--{k}: {v};" for k, v in base.items()]
            body += [f"--{k}: {v};" for k, v in slots.items() if v]
            rules.append(":root {\n  " + "\n  ".join(body) + "\n}")
        if self.dark:
            body = [f"--{k}: {v};" for k, v in self.dark.items()]
            rules.append(':root[data-theme="dark"] {\n  ' + "\n  ".join(body) + "\n}")
        if self._css:
            rules.append(self._css)  # last, so it wins over the tokens and faces above
        return "\n".join(rules)

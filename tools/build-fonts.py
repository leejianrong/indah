#!/usr/bin/env python
"""Regenerate frontend/src/fonts.css: the self-hosted Studio typeface bundle.

indah's shell fetches nothing at runtime (ADR-0004), so the Studio identity fonts
(ADR-0014) are subset to Latin + common punctuation and embedded as base64 woff2.
This pulls Google's already-Latin-subset woff2, trims them with fonttools, and
writes the ``@font-face`` block.

Run:  uv run --with fonttools --with brotli python tools/build-fonts.py

Faces kept small on purpose: Bricolage Grotesque as one variable file (display,
400-700), IBM Plex Sans + Mono at 400 and 600 only (body/mono; weight 500 maps to
600 in the shell CSS). Regenerate and commit frontend/src/fonts.css, then rebuild
the shell with `make frontend`.
"""

from __future__ import annotations

import base64
import io
import re
import urllib.request
from pathlib import Path

from fontTools import subset

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "fonts.css"

# Latin basic + Latin-1 (accents) + the punctuation the UI and user text use.
_UNICODES = (
    "U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+2013,U+2014,U+2018-201A,"
    "U+201C-201E,U+2020-2022,U+2026,U+2039,U+203A,U+2044,U+20AC,U+2122,U+2190-2193,U+2212"
)

# (Google css2 query, CSS family name, css font-weight to emit)
_FACES = [
    ("Bricolage+Grotesque:wght@400..700", "Bricolage Grotesque", "400 700"),
    ("IBM+Plex+Sans:wght@400", "IBM Plex Sans", "400"),
    ("IBM+Plex+Sans:wght@600", "IBM Plex Sans", "600"),
    ("IBM+Plex+Mono:wght@400", "IBM Plex Mono", "400"),
    ("IBM+Plex+Mono:wght@600", "IBM Plex Mono", "600"),
]


def _fetch(url: str) -> bytes:
    return urllib.request.urlopen(  # noqa: S310 - fixed Google Fonts hosts
        urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=30
    ).read()


def _latin_woff2(query: str) -> bytes:
    css = _fetch(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode()
    for block in re.split(r"(?=/\*)", css):
        label = re.match(r"/\*\s*([\w-]+)\s*\*/", block.strip())
        if label and label.group(1) == "latin":
            url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
            return _fetch(url)
    raise RuntimeError(f"no latin subset for {query}")


def _subset(woff2: bytes) -> bytes:
    options = subset.Options(flavor="woff2", desubroutinize=True)
    options.layout_features = ["kern", "liga", "calt"]
    font = subset.load_font(io.BytesIO(woff2), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=subset.parse_unicodes(_UNICODES))
    subsetter.subset(font)
    out = io.BytesIO()
    subset.save_font(font, out, options)
    return out.getvalue()


def main() -> None:
    faces = []
    for query, family, weight in _FACES:
        trimmed = _subset(_latin_woff2(query))
        b64 = base64.b64encode(trimmed).decode()
        faces.append(
            f"@font-face {{\n"
            f"  font-family: '{family}';\n"
            f"  font-style: normal;\n"
            f"  font-weight: {weight};\n"
            f"  font-display: swap;\n"
            f"  src: url(data:font/woff2;base64,{b64}) format('woff2');\n"
            f"}}"
        )
        print(f"{family} {weight}: {len(trimmed) / 1024:.1f} KB")
    header = (
        "/* indah Studio typeface bundle - self-hosted, base64 woff2 (ADR-0004: the\n"
        "   shell fetches nothing at runtime). Subset to Latin + common punctuation.\n"
        "   Bricolage Grotesque (variable, display), IBM Plex Sans (body), IBM Plex\n"
        "   Mono (mono). Regenerate with tools/build-fonts.py. */\n"
    )
    _OUT.write_text(header + "\n".join(faces) + "\n")
    print(f"wrote {_OUT}")


if __name__ == "__main__":
    main()

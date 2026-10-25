"""The gallery catalog: load and validate ``gallery.toml`` (IND-191).

Pure standard library (plus ``tomli`` on Python 3.10), so the validation runs in the fast test
layer without Starlette or the demo libraries. ``gallery_app`` turns the entries into cards.

An entry is a plain dict. ``hosted`` entries are examples in this repo that the gallery runs;
``listed`` entries are apps someone else hosts, shown as a card that links out.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

HERE = Path(__file__).parent
CATALOG = HERE / "gallery.toml"
THUMB_DIR = HERE / "thumbnails"

KINDS = ("hosted", "listed")
BLURB_MAX = 120
TITLE_MAX = 40
THUMB_MAX_BYTES = 600_000
_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_MODULE = re.compile(r"[a-z_][a-z0-9_]*")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_TAG = re.compile(r"[a-z0-9-]{1,24}")
_TEXT_FIELDS = ("title", "blurb", "author", "emoji", "slug", "module", "tags")
_REQUIRED = {
    "hosted": ("slug", "title", "blurb", "author", "module", "added"),
    "listed": (
        "slug",
        "title",
        "blurb",
        "author",
        "url",
        "source_url",
        "thumbnail",
        "indah_version",
        "added",
    ),
}


def load_catalog(path: Path = CATALOG) -> list[dict[str, Any]]:
    """Read the catalog file into a list of entries (not validated)."""
    with open(path, "rb") as f:
        return list(tomllib.load(f).get("app", []))


def _https(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def validate_catalog(entries: list[dict[str, Any]], thumb_dir: Path = THUMB_DIR) -> list[str]:
    """Return a list of problems, empty when the catalog is sound."""
    problems: list[str] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        name = e.get("slug") or f"entry {i}"
        err = lambda msg, name=name: problems.append(f"{name}: {msg}")  # noqa: E731
        kind = e.get("kind")
        if kind not in KINDS:
            err(f"kind must be one of {KINDS}, got {kind!r}")
            continue
        for field in _REQUIRED[kind]:
            if not e.get(field):
                err(f"missing {field}")
        slug = e.get("slug", "")
        if slug:
            if not _SLUG.fullmatch(slug):
                err("slug must be lowercase letters, digits and hyphens")
            if slug in seen:
                err("duplicate slug")
            seen.add(slug)
        for field in _TEXT_FIELDS:
            value = e.get(field)
            texts = value if isinstance(value, list) else [value]
            if any(isinstance(t, str) and re.search(r"[<>&]", t) for t in texts):
                err(f"{field} must be plain text (no <, > or &)")
        if len(e.get("title", "")) > TITLE_MAX:
            err(f"title is longer than {TITLE_MAX} characters")
        if len(e.get("blurb", "")) > BLURB_MAX:
            err(f"blurb is longer than {BLURB_MAX} characters")
        if not all(isinstance(t, str) and _TAG.fullmatch(t) for t in e.get("tags", [])):
            err("tags must be short lowercase words")
        if e.get("added"):
            try:
                date.fromisoformat(str(e["added"]))
            except ValueError:
                err("added must be a date, YYYY-MM-DD")
        if e.get("indah_version") and not _VERSION.fullmatch(e["indah_version"]):
            err("indah_version must look like 0.9.0")
        for field in ("url", "source_url"):
            if e.get(field) and not _https(e[field]):
                err(f"{field} must be an https URL")
        if kind == "hosted":
            if e.get("module") and not _MODULE.fullmatch(e["module"]):
                err("module must be a Python module name")
            if e.get("url"):
                err("a hosted entry has no url (the gallery serves it under /<slug>)")
        thumb = e.get("thumbnail")
        if thumb:
            path = thumb_dir / thumb
            if Path(thumb).name != thumb or not path.is_file():
                err(f"thumbnail {thumb!r} is not a file in {thumb_dir.name}/")
            elif path.stat().st_size > THUMB_MAX_BYTES:
                err(f"thumbnail is larger than {THUMB_MAX_BYTES} bytes")
    return problems


def hosted(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("kind") == "hosted"]


def listed(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("kind") == "listed"]

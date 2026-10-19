"""In-app paths and route patterns for ``Router`` (IND-105/106, ADR-0029).

An in-app path is the part of the URL after the app's mount point: ``/projects/auth``.
A pattern is that with ``{name}`` or ``{name:int}`` segments::

    /                                   the home page
    /projects/{project}                 params {"project": "auth"}
    /projects/{project}/entries/{id}    params {"project": "auth", "id": "01J..."}

Matching is by whole segments, first route wins (so a literal can shadow a param), and a
trailing slash is ignored. Param values are percent-decoded after the split, so an encoded
slash stays inside one segment.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

MAX_PATH = 2048
_SEGMENT_PARAM = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)(?::(int))?\}$")
_BAD_CHARS = re.compile(r"[\s\\?#\x00-\x1f\x7f]")


def normalize_path(path: Any) -> str:
    """A canonical in-app path (leading ``/``, no trailing ``/``, no empty segments).

    Raises ``ValueError`` for anything that is not a plain path: no leading slash, a
    protocol-relative ``//host``, a query or fragment, whitespace, a backslash, a control
    character or more than 2048 characters. The path is later handed back to the browser to
    push into its history, so it must never be able to name another origin."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError(f"not an in-app path: {path!r}")
    if len(path) > MAX_PATH or _BAD_CHARS.search(path):
        raise ValueError("not an in-app path")
    segments = [seg for seg in path.split("/") if seg]
    return "/" + "/".join(segments)


@dataclass(frozen=True)
class Route:
    pattern: str
    # One entry per segment: a literal string, or (name, cast) for a param.
    parts: tuple[str | tuple[str, Callable[[str], Any]], ...]

    def match(self, path: str) -> dict[str, Any] | None:
        segments = [seg for seg in path.split("/") if seg]
        if len(segments) != len(self.parts):
            return None
        params: dict[str, Any] = {}
        for part, seg in zip(self.parts, segments, strict=True):
            if isinstance(part, str):
                if part != seg:
                    return None
                continue
            name, cast = part
            try:
                params[name] = cast(unquote(seg))
            except ValueError:
                return None
        return params


def compile_route(pattern: str) -> Route:
    """Validate and compile ``pattern``; raises ``ValueError`` at definition time."""
    if not pattern.startswith("/") or pattern.startswith("//"):
        raise ValueError(f"route pattern must start with a single '/': {pattern!r}")
    parts: list[str | tuple[str, Callable[[str], Any]]] = []
    seen: set[str] = set()
    for seg in [s for s in pattern.split("/") if s]:
        if "{" in seg or "}" in seg:
            m = _SEGMENT_PARAM.match(seg)
            if m is None:
                raise ValueError(f"bad route segment {seg!r} in {pattern!r}")
            name, kind = m.group(1), m.group(2)
            if name in seen:
                raise ValueError(f"duplicate param {name!r} in {pattern!r}")
            seen.add(name)
            parts.append((name, int if kind == "int" else str))
        elif "*" in seg or _BAD_CHARS.search(seg):
            raise ValueError(f"bad route segment {seg!r} in {pattern!r}")
        else:
            parts.append(seg)
    return Route(normalize_path(pattern), tuple(parts))


def match_routes(routes: list[Route], path: str) -> tuple[int, dict[str, Any]] | None:
    """The first route that matches ``path`` as ``(index, params)``, else ``None``."""
    for index, route in enumerate(routes):
        params = route.match(path)
        if params is not None:
            return index, params
    return None

"""Server-side diff for the ``Diff`` component (IND-109, ADR-0028).

Computed in Python with stdlib ``difflib`` over pretty-printed, key-sorted JSON (or raw
text), so the browser only has to draw rows and the result is testable in pytest. Rows::

    {"t": "eq",   "a": n, "b": m, "text": s}              an unchanged line
    {"t": "del",  "a": n, "text": s}                       only in a
    {"t": "add",  "b": m, "text": s}                       only in b
    {"t": "chg",  "a": n, "b": m, "at": s, "bt": s,        a changed line, with the
                  "ai": [[s, e], ...], "bi": [[s, e], ...]}   character spans that differ
    {"t": "skip", "n": k}                                  k unchanged lines left out

Bounds: at most ``MAX_LINES`` lines per side are compared (the rest is dropped and
``truncated`` is set), a line is clipped to ``MAX_LINE_CHARS``, and ``difflib`` is quadratic
in the worst case, so after the common prefix and suffix are trimmed an input whose
remaining work exceeds ``EXACT_COST_LIMIT`` is diffed with ``autojunk`` on, which is fast
but coarser (``approximate`` is set).
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any

MAX_LINES = 5000
MAX_LINE_CHARS = 2000
MAX_INLINE_CHARS = 400
EXACT_COST_LIMIT = 1_500_000  # len(a_mid) * len(b_mid) beyond which the diff is approximate
_MIN_INLINE_RATIO = 0.35
_PAIR_CUTOFF = 0.6  # how alike two lines must be to be shown as one changed line
_PAIR_BLOCK_LIMIT = 4096  # a replaced block of more than this many line pairs is not paired


def _stringify_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _stringify_keys(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_keys(v) for v in value]
    return value


def _pretty(value: Any) -> str:
    return json.dumps(
        _stringify_keys(value), sort_keys=True, indent=2, ensure_ascii=False, default=str
    )


def normalise_value(value: Any, mode: str) -> str:
    """The text that is compared: key-sorted pretty JSON in ``json`` mode (text that does not
    parse as JSON is used as it is), or the value as text in ``text`` mode."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    if mode == "json":
        if isinstance(value, str):
            try:
                return _pretty(json.loads(value))
            except (ValueError, RecursionError):
                return value
        return _pretty(value)
    return value if isinstance(value, str) else str(value)


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + "…"


def _lines(text: str) -> tuple[list[str], bool]:
    lines = text.splitlines()
    truncated = len(lines) > MAX_LINES
    return [_clip(line) for line in lines[:MAX_LINES]], truncated


def _spans(a: str, b: str) -> tuple[list[list[int]], list[list[int]]]:
    """The character ranges that differ between two lines, or none if they are too long
    or too dissimilar for marking every character to be useful."""
    if len(a) > MAX_INLINE_CHARS or len(b) > MAX_INLINE_CHARS:
        return [], []
    sm = SequenceMatcher(None, a, b, autojunk=False)
    if sm.ratio() < _MIN_INLINE_RATIO:
        return [], []
    ai: list[list[int]] = []
    bi: list[list[int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            ai.append([i1, i2])
        if j2 > j1:
            bi.append([j1, j2])
    return ai, bi


def _opcodes(a: list[str], b: list[str]) -> tuple[list[tuple[str, int, int, int, int]], bool]:
    """``difflib`` opcodes over ``a`` and ``b``, exact unless the work would be too large."""
    start = 0
    limit = min(len(a), len(b))
    while start < limit and a[start] == b[start]:
        start += 1
    end = 0
    while end < limit - start and a[len(a) - 1 - end] == b[len(b) - 1 - end]:
        end += 1
    mid_a, mid_b = a[start : len(a) - end], b[start : len(b) - end]
    approximate = len(mid_a) * len(mid_b) > EXACT_COST_LIMIT
    ops: list[tuple[str, int, int, int, int]] = []
    if start:
        ops.append(("equal", 0, start, 0, start))
    if mid_a or mid_b:
        sm = SequenceMatcher(None, mid_a, mid_b, autojunk=approximate)
        ops += [
            (tag, i1 + start, i2 + start, j1 + start, j2 + start)
            for tag, i1, i2, j1, j2 in sm.get_opcodes()
        ]
    if end:
        ops.append(("equal", len(a) - end, len(a), len(b) - end, len(b)))
    return ops, approximate


def _pair_block(
    a: list[str], b: list[str], i1: int, i2: int, j1: int, j2: int
) -> list[tuple[str, int, int]]:
    """Order a replaced block as ``("del", i, -1)``, ``("add", -1, j)`` and ``("chg", i, j)``.

    Lines are paired by similarity, not by position: the most alike pair (at least
    ``_PAIR_CUTOFF``) becomes a changed line, and the lines above and below it are paired
    the same way, so a removed line next to an edited one is not mistaken for an edit of it.
    This is the idea behind ``difflib.ndiff``. A block with nothing alike, or one too big to
    compare line by line, is plain removals followed by additions; a block of exactly one
    line for one line is always a changed line, however different."""
    out: list[tuple[str, int, int]] = []

    def plain(lo_a: int, hi_a: int, lo_b: int, hi_b: int) -> None:
        out.extend(("del", i, -1) for i in range(lo_a, hi_a))
        out.extend(("add", -1, j) for j in range(lo_b, hi_b))

    def walk(lo_a: int, hi_a: int, lo_b: int, hi_b: int) -> None:
        if lo_a >= hi_a or lo_b >= hi_b:
            plain(lo_a, hi_a, lo_b, hi_b)
            return
        if (hi_a - lo_a) * (hi_b - lo_b) > _PAIR_BLOCK_LIMIT:
            plain(lo_a, hi_a, lo_b, hi_b)
            return
        best, pair = _PAIR_CUTOFF, None
        for j in range(lo_b, hi_b):
            sm = SequenceMatcher(None, "", b[j][:MAX_INLINE_CHARS], autojunk=False)
            for i in range(lo_a, hi_a):
                sm.set_seq1(a[i][:MAX_INLINE_CHARS])
                if sm.real_quick_ratio() > best and sm.quick_ratio() > best:
                    ratio = sm.ratio()
                    if ratio > best:
                        best, pair = ratio, (i, j)
        if pair is None:
            plain(lo_a, hi_a, lo_b, hi_b)
            return
        i, j = pair
        walk(lo_a, i, lo_b, j)
        out.append(("chg", i, j))
        walk(i + 1, hi_a, j + 1, hi_b)

    if i2 - i1 == 1 and j2 - j1 == 1:
        return [("chg", i1, j1)]  # one line replaced by one line is simply a changed line
    walk(i1, i2, j1, j2)
    return out


def compute_diff(
    a: Any, b: Any, *, normalise: str = "json", context: int | None = 3
) -> dict[str, Any]:
    """Diff ``a`` against ``b``; see the module docstring for the row format."""
    a_lines, a_cut = _lines(normalise_value(a, normalise))
    b_lines, b_cut = _lines(normalise_value(b, normalise))
    ops, approximate = _opcodes(a_lines, b_lines)

    rows: list[dict[str, Any]] = []
    stats = {"add": 0, "del": 0, "chg": 0}
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            rows += [
                {"t": "eq", "a": i + 1, "b": j + 1, "text": a_lines[i]}
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            ]
            continue
        for kind, i, j in _pair_block(a_lines, b_lines, i1, i2, j1, j2):
            if kind == "del":
                rows.append({"t": "del", "a": i + 1, "text": a_lines[i]})
                stats["del"] += 1
            elif kind == "add":
                rows.append({"t": "add", "b": j + 1, "text": b_lines[j]})
                stats["add"] += 1
            else:
                at, bt = a_lines[i], b_lines[j]
                ai, bi = _spans(at, bt)
                rows.append(
                    {"t": "chg", "a": i + 1, "b": j + 1, "at": at, "bt": bt, "ai": ai, "bi": bi}
                )
                stats["chg"] += 1

    same = not any(stats.values())
    if same:
        rows = []
    elif context is not None:
        rows = _collapse(rows, context)
    return {
        "rows": rows,
        "stats": stats,
        "same": same,
        "truncated": a_cut or b_cut,
        "approximate": approximate,
    }


def _collapse(rows: list[dict[str, Any]], context: int) -> list[dict[str, Any]]:
    """Replace each long run of unchanged lines by a ``skip`` row, keeping ``context`` lines
    next to a change."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(rows):
        if rows[i]["t"] != "eq":
            out.append(rows[i])
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j]["t"] == "eq":
            j += 1
        run = rows[i:j]
        keep_head = 0 if i == 0 else context  # context after the previous change
        keep_tail = 0 if j == len(rows) else context  # context before the next change
        if len(run) <= keep_head + keep_tail:
            out += run
        else:
            out += run[:keep_head]
            out.append({"t": "skip", "n": len(run) - keep_head - keep_tail})
            out += run[len(run) - keep_tail :]
        i = j
    return out

"""A tiny, safe-by-construction Markdown renderer (for ``Text(markdown=True)``).

indah keeps its runtime dependencies to three (starlette, uvicorn, pydantic), so
rather than pull in a Markdown library we parse a documented subset here into a
*block tree* the shell renders with its safe DOM builder. Safety is structural,
not a scrub-after-the-fact: raw HTML in the source is never interpreted, it stays
literal text; links keep only http/https/mailto/relative hrefs; and every node is
an allowlisted tag or a plain string leaf the shell escapes. There is no path from
source text to a ``<script>`` (or any raw element), so nothing can inject script.

The tree is JSON on the wire (no protocol change -- a ``text`` node just carries a
``blocks`` prop instead of ``text``). A node is either:

- a ``str`` -- a text leaf the shell renders escaped; or
- ``{"tag": <name>, "children": [node, ...]}`` -- an element, with ``"href"`` added
  for an ``a``. ``hr``/``br`` carry no children.

Supported: headings (``#``..``######``), paragraphs, fenced code (```` ``` ````),
blockquotes (``>``), unordered (``-``/``*``/``+``) and ordered (``1.``) lists,
horizontal rules, and the inline spans ``**bold**``/``__bold__``, ``*italic*``/
``_italic_``, ``` `code` ```, and ``[text](url)`` links. Images and raw HTML are
intentionally left literal (use the ``Image`` component for pictures).
"""

from __future__ import annotations

import re
from typing import Any

# An href we are willing to render on an <a>: an absolute http(s)/mailto link, or a
# relative/in-page one. Anything else (notably ``javascript:``) is rejected and the
# link falls back to literal text.
_HREF_OK = re.compile(r"^(https?:|mailto:)|^(/|#|\./|\.\./)", re.IGNORECASE)
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE = re.compile(r"^>\s?")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_FENCE = re.compile(r"^```")
_ESCAPABLE = set("\\`*_[]()#>+-.!")

Node = Any  # str | dict[str, Any]


def to_blocks(text: str) -> list[Node]:
    """Parse ``text`` as Markdown into a safe block tree (see the module docstring)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Node] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if _FENCE.match(line):  # fenced code block
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # consume the closing fence (or end of input)
            code_leaf = {"tag": "code", "children": ["\n".join(code)]}
            blocks.append({"tag": "pre", "children": [code_leaf]})
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            blocks.append({"tag": f"h{level}", "children": _parse_inline(heading.group(2).strip())})
            i += 1
            continue

        if _HR.match(line):
            blocks.append({"tag": "hr"})
            i += 1
            continue

        if _QUOTE.match(line):  # blockquote: strip markers, recurse
            quoted: list[str] = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.sub("", lines[i]))
                i += 1
            blocks.append({"tag": "blockquote", "children": to_blocks("\n".join(quoted))})
            continue

        item = _LIST_ITEM.match(line)
        if item:
            ordered = bool(re.match(r"\d+\.", item.group(2)))
            items: list[Node] = []
            while i < len(lines):
                m = _LIST_ITEM.match(lines[i])
                if not m:
                    break
                items.append({"tag": "li", "children": _parse_inline(m.group(3).strip())})
                i += 1
            blocks.append({"tag": "ol" if ordered else "ul", "children": items})
            continue

        # Paragraph: soft-wrapped lines up to a blank line or the next block start.
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para.append(lines[i])
            i += 1
        joined = " ".join(part.strip() for part in para)
        blocks.append({"tag": "p", "children": _parse_inline(joined)})

    return blocks


def _is_block_start(line: str) -> bool:
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _HR.match(line)
        or _QUOTE.match(line)
        or _LIST_ITEM.match(line)
    )


def _safe_href(url: str) -> str | None:
    url = url.strip()
    return url if _HREF_OK.match(url) else None


def _parse_inline(text: str) -> list[Node]:
    """Parse inline spans within one run of text into a list of nodes."""
    nodes: list[Node] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            nodes.append("".join(buf))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf.append(text[i + 1])  # backslash escape -> literal next char
            i += 2
            continue

        if ch == "`":  # inline code (no inner parsing)
            close = text.find("`", i + 1)
            if close != -1:
                flush()
                nodes.append({"tag": "code", "children": [text[i + 1 : close]]})
                i = close + 1
                continue

        if text.startswith("**", i) or text.startswith("__", i):  # strong
            marker = text[i : i + 2]
            close = text.find(marker, i + 2)
            if close != -1:
                flush()
                nodes.append({"tag": "strong", "children": _parse_inline(text[i + 2 : close])})
                i = close + 2
                continue

        if ch in "*_":  # emphasis
            close = text.find(ch, i + 1)
            if close > i + 1:
                flush()
                nodes.append({"tag": "em", "children": _parse_inline(text[i + 1 : close])})
                i = close + 1
                continue

        if ch == "[":  # link
            link = _LINK.match(text, i)
            if link:
                href = _safe_href(link.group(2))
                if href is not None:
                    flush()
                    nodes.append(
                        {"tag": "a", "href": href, "children": _parse_inline(link.group(1))}
                    )
                    i = link.end()
                    continue
                # unsafe scheme: fall through so the raw "[text](url)" stays literal

        buf.append(ch)
        i += 1

    flush()
    return nodes

"""Inline SVG, sanitised (IND-275).

``parse_svg`` turns SVG text into a tree of allowlisted elements and attributes that the shell
builds with ``createElementNS``: no markup is parsed in the browser, no script, event handler,
style attribute, class, link or external reference gets through, and a colour may be a CSS colour
or ``var(--token)`` so a drawing follows the light and dark themes. A node is
``[tag, {attr: value}, *children]`` where a child is a node or a string.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

SVG_NS = "{http://www.w3.org/2000/svg}"
MAX_BYTES = 200_000
MAX_ELEMENTS = 5_000
MAX_DEPTH = 32

TAGS = frozenset(
    "svg g defs path rect circle ellipse line polyline polygon text tspan title desc "
    "linearGradient radialGradient stop clipPath".split()
)
ATTRS = frozenset(
    "viewBox preserveAspectRatio width height x y x1 y1 x2 y2 cx cy r rx ry fx fy d points "
    "transform fill stroke stroke-width stroke-dasharray stroke-dashoffset stroke-linecap "
    "stroke-linejoin stroke-miterlimit opacity fill-opacity stroke-opacity fill-rule clip-rule "
    "font-size font-family font-weight font-style text-anchor dominant-baseline letter-spacing "
    "id offset stop-color stop-opacity gradientUnits gradientTransform spreadMethod "
    "clipPathUnits clip-path dx dy rotate textLength lengthAdjust vector-effect".split()
)
_URL_ATTRS = frozenset({"fill", "stroke", "clip-path"})
_LOCAL_URL = re.compile(r"^url\(#[A-Za-z][\w.-]*\)$")
_PLAIN = re.compile(r"^[\w\s.,;:#%()+\-/*'\"]*$")  # numbers, lists, colours, font names, var(--x)


def _check_value(tag: str, name: str, value: str) -> str:
    if name in _URL_ATTRS and value.startswith("url("):
        if not _LOCAL_URL.match(value):
            raise ValueError(f"SVG {name} may only refer to an id in the same drawing: {value!r}")
        return value
    low = value.lower()
    if "url(" in low or "javascript" in low or "expression" in low or "&" in value or "<" in value:
        raise ValueError(f"SVG attribute {name}={value!r} is not allowed")
    if not _PLAIN.match(value):
        raise ValueError(f"SVG attribute {name} has characters that are not allowed: {value!r}")
    return value


def parse_svg(text: Any) -> list[Any]:
    """SVG text to a sanitised tree, or ``ValueError`` saying what was refused."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("an SVG is a non-empty string of SVG markup")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"an SVG is at most {MAX_BYTES // 1000} KB, got {len(text) // 1000} KB")
    if "<!" in text.replace("<!--", ""):  # a DOCTYPE or entity declaration; comments are fine
        raise ValueError("an SVG may not carry a DOCTYPE or entity declarations")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"not well-formed SVG: {e}") from None
    count = 0

    def walk(el: ET.Element, depth: int) -> list[Any]:
        nonlocal count
        count += 1
        if count > MAX_ELEMENTS:
            raise ValueError(f"an SVG has at most {MAX_ELEMENTS} elements")
        if depth > MAX_DEPTH:
            raise ValueError(f"an SVG is nested at most {MAX_DEPTH} deep")
        if not isinstance(el.tag, str):
            raise ValueError("an SVG may not carry comments or processing instructions as nodes")
        tag = el.tag[len(SVG_NS) :] if el.tag.startswith(SVG_NS) else el.tag
        if tag not in TAGS:
            raise ValueError(f"SVG element <{tag}> is not allowed; use {sorted(TAGS)}")
        attrs: dict[str, str] = {}
        for key, value in el.attrib.items():
            if key == "xmlns":
                continue
            if key not in ATTRS:
                raise ValueError(f"SVG attribute {key!r} on <{tag}> is not allowed")
            attrs[key] = _check_value(tag, key, value)
        node: list[Any] = [tag, attrs]
        if el.text and el.text.strip():
            node.append(el.text.strip())
        for child in el:
            node.append(walk(child, depth + 1))
            if child.tail and child.tail.strip():
                node.append(child.tail.strip())
        return node

    tree = walk(root, 1)
    if tree[0] != "svg":
        raise ValueError("the root of an SVG must be <svg>")
    return tree

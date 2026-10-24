"""Gzip for what indah serves (ADR-0042, IND-189).

The shell is about 570 KB and ``editor.js`` 630 KB; without this a client behind a proxy that does
not compress downloads them whole. Only responses that are static, or nearly so, are compressed:
the shell, ``editor.js`` and module components. The event stream and the JSON routes are never
touched, so a streamed frame is never held back waiting for a compression window.

Compressing the shell once per page load would cost about 35 ms of CPU (gzip level 6, measured),
so it is not done per response. The shell is a static template with a few small per-response
insertions (the CSP nonce after each ``<script`` and ``<style``), so it is compressed in pieces:
each static piece once, cached, as raw deflate ending on a byte boundary, and the insertions as
stored blocks between them. The result is one ordinary gzip member that every client decodes, and
a response costs a join, a CRC and some copying (about 1 ms).

BREACH needs a secret in the compressed body that an attacker can probe with guesses reflected in
the same body. The shell holds neither: a random nonce, a ``<base href>`` of ``../`` steps, and
the app's own title and theme. Session tokens travel in a POST body and ephemeral secrets on the
event stream, neither of which is compressed here.
"""

from __future__ import annotations

import gzip
import struct
import zlib
from collections import OrderedDict

_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"  # gzip, no name, mtime 0, OS unix
_FINAL_EMPTY_BLOCK = b"\x03\x00"  # a final, empty, fixed-Huffman deflate block
_STORED_MAX = 65535

_MAX_STATIC = 64
_MAX_PIECES = 16
_static: OrderedDict[str, bytes] = OrderedDict()
_pieces: OrderedDict[str, bytes] = OrderedDict()


def accepts_gzip(header: str | None) -> bool:
    """Whether an ``Accept-Encoding`` header allows gzip. An explicit ``gzip;q=0`` refuses it, and
    ``*`` allows it when gzip is not named."""
    if not header:
        return False
    explicit: bool | None = None
    star: bool | None = None
    for part in header.split(","):
        name, _, params = part.partition(";")
        name = name.strip().lower()
        q = 1.0
        for p in params.split(";"):
            key, _, value = p.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 1.0
        if name in ("gzip", "x-gzip"):
            explicit = q > 0
        elif name == "*":
            star = q > 0
    if explicit is not None:
        return explicit
    return bool(star)


def variant_etag(etag: str, gzipped: bool) -> str:
    """The validator of one representation: the gzip form gets its own, so a cache never mixes
    the two."""
    return etag[:-1] + '-gz"' if gzipped else etag


def matches_etag(if_none_match: str | None, etag: str) -> bool:
    """Whether ``If-None-Match`` names ``etag`` (weak validators count, and ``*`` matches)."""
    if not if_none_match:
        return False
    for token in if_none_match.split(","):
        token = token.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:]
        if token == etag:
            return True
    return False


def _remember(cache: OrderedDict[str, bytes], key: str, value: bytes, limit: int) -> bytes:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)
    return value


def gzip_static(key: str, data: bytes) -> bytes:
    """``data`` gzipped at the best level, once per ``key`` (the key carries the content hash)."""
    hit = _static.get(key)
    if hit is not None:
        return hit
    return _remember(_static, key, gzip.compress(data, compresslevel=9, mtime=0), _MAX_STATIC)


def _deflate_piece(text: str) -> bytes:
    hit = _pieces.get(text)
    if hit is not None:
        _pieces.move_to_end(text)
        return hit
    co = zlib.compressobj(6, zlib.DEFLATED, -15, 9)
    packed = co.compress(text.encode()) + co.flush(zlib.Z_FULL_FLUSH)  # ends byte-aligned
    return _remember(_pieces, text, packed, _MAX_PIECES)


def _stored(data: bytes) -> bytes:
    out = []
    for i in range(0, len(data), _STORED_MAX):
        chunk = data[i : i + _STORED_MAX]
        out.append(b"\x00" + struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF) + chunk)
    return b"".join(out)


def gzip_joined(parts: list[str], joiner: str) -> bytes:
    """gzip of ``joiner.join(parts)``, from cached compressed ``parts`` and stored ``joiner``s.

    Equivalent to ``gzip.compress(joiner.join(parts).encode())`` but, when the parts repeat from
    one call to the next, without compressing them again.
    """
    plain = joiner.join(parts).encode()
    glue = _stored(joiner.encode()) if joiner else b""
    body = []
    for i, part in enumerate(parts):
        if i and glue:
            body.append(glue)
        if part:
            body.append(_deflate_piece(part))
    body.append(_FINAL_EMPTY_BLOCK)
    trailer = struct.pack("<II", zlib.crc32(plain) & 0xFFFFFFFF, len(plain) & 0xFFFFFFFF)
    return _HEADER + b"".join(body) + trailer

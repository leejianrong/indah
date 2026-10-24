"""The compression helpers (IND-189, ADR-0042): Accept-Encoding parsing, the gzip a shell is
composed from cached pieces, and the nonce split that feeds it."""

import gzip
import os
import re

import pytest

from indah.compress import accepts_gzip, gzip_joined, gzip_static, matches_etag, variant_etag
from indah.csp import add_nonce, add_nonce_parts


@pytest.mark.unit
@pytest.mark.parametrize(
    "header, expected",
    [
        (None, False),
        ("", False),
        ("identity", False),
        ("gzip", True),
        ("GZIP", True),
        ("gzip, deflate, br", True),
        ("br, gzip;q=0.5", True),
        ("gzip;q=0", False),
        ("gzip ; q=0.0, br", False),
        ("*", True),
        ("*;q=0", False),
        ("br, *;q=0.1", True),
        ("x-gzip", True),
        ("gzip;q=nonsense", True),
        ("deflate, br", False),
    ],
)
def test_accepts_gzip(header, expected):
    assert accepts_gzip(header) is expected


@pytest.mark.unit
def test_gzip_static_round_trips_and_is_smaller():
    data = (b"function f(){return 1}\n" * 2000) + os.urandom(64)
    packed = gzip_static("k1", data)
    assert gzip.decompress(packed) == data
    assert len(packed) < len(data) // 4
    assert gzip_static("k1", data) is packed  # cached by key, compressed once


@pytest.mark.unit
@pytest.mark.parametrize("insert_len", [0, 1, 40, 65535, 65536, 140_000])
def test_gzip_joined_equals_the_plain_join(insert_len):
    parts = ["<html><head><script", "> var a = 'é ✓'; </script><style", ">body{}</style></html>"]
    joiner = ' nonce="' + ("x" * insert_len) + '"'
    packed = gzip_joined(parts, joiner)
    assert gzip.decompress(packed) == joiner.join(parts).encode()


@pytest.mark.unit
def test_gzip_joined_handles_an_empty_part_and_a_single_part():
    assert gzip.decompress(gzip_joined(["only"], "J")) == b"only"
    assert gzip.decompress(gzip_joined(["", "b", ""], "J")) == b"JbJ"
    assert gzip.decompress(gzip_joined([""], "J")) == b""


@pytest.mark.unit
def test_gzip_joined_is_a_single_standard_member():
    # one gzip member, so every client decodes it (not several concatenated members)
    packed = gzip_joined(["<script", ">1</script>" * 500], ' nonce="n"')
    import zlib

    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(packed)
    assert d.eof and d.unused_data == b""
    assert out.startswith(b'<script nonce="n">')


@pytest.mark.unit
def test_nonce_parts_join_back_to_add_nonce():
    html = (
        '<html><head><STYLE id="a">x</STYLE><script type="module">1</script>'
        "<scripture>no</scripture><script>2</script></head><body></body></html>"
    )
    parts = add_nonce_parts(html)
    assert len(parts) == 4  # three real tags, so three insertions
    assert ' nonce="N"'.join(parts) == add_nonce(html, "N")
    assert add_nonce_parts("<p>none</p>") == ["<p>none</p>"]
    real = open("src/indah/static/index.html", encoding="utf-8").read()
    assert ' nonce="Z9"'.join(add_nonce_parts(real)) == add_nonce(real, "Z9")
    assert re.search(r"<script(?=[\s>])", real)


@pytest.mark.unit
def test_etag_variants_and_matching():
    assert variant_etag('"abc"', False) == '"abc"'
    assert variant_etag('"abc"', True) == '"abc-gz"'
    assert matches_etag('"abc-gz"', '"abc-gz"')
    assert matches_etag('W/"abc-gz"', '"abc-gz"')
    assert matches_etag('"x", "abc-gz"', '"abc-gz"')
    assert matches_etag("*", '"abc-gz"')
    assert not matches_etag('"abc"', '"abc-gz"')
    assert not matches_etag(None, '"abc"')
    assert not matches_etag("", '"abc"')

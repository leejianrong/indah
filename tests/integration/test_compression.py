"""Compressed shell and static modules (IND-189, ADR-0042): Accept-Encoding, Vary, ETag and 304,
the CSP nonce, mounts, secure apps, and an event stream that stays uncompressed."""

import re
from importlib.resources import files

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from indah import Column, Text, create_app
from indah.custom import _REGISTRY, register_component
from indah.launch import launch
from indah.session import Session


def _build():
    return Session(Column(children=[Text("hi")]))


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


GZ = {"Accept-Encoding": "gzip"}
ID = {"Accept-Encoding": "identity"}


def _raw(r: httpx.Response) -> int:
    return int(r.headers["content-length"])


@pytest.mark.integration
async def test_editor_js_is_gzipped_when_asked_and_plain_otherwise():
    plain_bytes = files("indah.static").joinpath("editor.js").read_bytes()
    async with _client(create_app()) as c:
        gz = await c.get("/api/editor.js", headers=GZ)
        assert gz.headers["content-encoding"] == "gzip"
        assert gz.headers["vary"] == "Accept-Encoding"
        assert gz.content == plain_bytes  # httpx decoded it
        assert _raw(gz) < len(plain_bytes) // 2
        plain = await c.get("/api/editor.js", headers=ID)
        assert "content-encoding" not in plain.headers
        assert plain.headers["vary"] == "Accept-Encoding"
        assert plain.content == plain_bytes and _raw(plain) == len(plain_bytes)
        refused = await c.get("/api/editor.js", headers={"Accept-Encoding": "gzip;q=0"})
        assert "content-encoding" not in refused.headers


@pytest.mark.integration
async def test_each_representation_has_its_own_etag_and_a_304():
    async with _client(create_app()) as c:
        gz = await c.get("/api/editor.js", headers=GZ)
        plain = await c.get("/api/editor.js", headers=ID)
        assert gz.headers["etag"] != plain.headers["etag"]
        assert gz.headers["etag"].endswith('-gz"')
        again = await c.get("/api/editor.js", headers={**GZ, "If-None-Match": gz.headers["etag"]})
        assert again.status_code == 304 and again.content == b""
        assert again.headers["etag"] == gz.headers["etag"]
        assert again.headers["vary"] == "Accept-Encoding"
        weak = await c.get(
            "/api/editor.js", headers={**GZ, "If-None-Match": "W/" + gz.headers["etag"]}
        )
        assert weak.status_code == 304
        # a validator for the gzip form does not validate the identity form
        mixed = await c.get("/api/editor.js", headers={**ID, "If-None-Match": gz.headers["etag"]})
        assert mixed.status_code == 200 and "content-encoding" not in mixed.headers
        same = await c.get("/api/editor.js", headers={**ID, "If-None-Match": plain.headers["etag"]})
        assert same.status_code == 304


@pytest.mark.integration
async def test_shell_is_gzipped_and_decodes_to_the_same_page():
    async with _client(create_app(session_factory=_build)) as c:
        plain = await c.get("/", headers=ID)
        gz = await c.get("/", headers=GZ)
        assert "content-encoding" not in plain.headers
        assert gz.headers["content-encoding"] == "gzip"
        assert gz.headers["vary"] == "Accept-Encoding"
        assert gz.headers["content-type"].startswith("text/html")
        assert gz.text == plain.text
        assert _raw(gz) < _raw(plain) // 2


@pytest.mark.integration
async def test_strict_csp_shell_keeps_a_fresh_nonce_in_the_gzipped_body():
    app = create_app(session_factory=_build, csp="strict")
    async with _client(app) as c:
        first = await c.get("/", headers=GZ)
        second = await c.get("/", headers=GZ)
        plain = await c.get("/", headers=ID)
    assert first.headers["content-encoding"] == "gzip"
    assert first.headers["cache-control"] == "no-store"
    nonces = []
    for r in (first, second, plain):
        policy_nonce = re.search(
            r"script-src 'nonce-([^']+)'", r.headers["content-security-policy"]
        )
        tags = re.findall(r"<(?:script|style)(?=[\s>])[^>]*>", r.text, re.IGNORECASE)
        assert tags and all(f'nonce="{policy_nonce.group(1)}"' in t for t in tags)
        nonces.append(policy_nonce.group(1))
    assert len(set(nonces)) == 3
    assert first.text.replace(nonces[0], "N") == plain.text.replace(nonces[2], "N")


@pytest.mark.integration
async def test_compress_false_turns_it_all_off():
    async with _client(create_app(session_factory=_build, compress=False)) as c:
        for path in ("/", "/api/editor.js"):
            r = await c.get(path, headers=GZ)
            assert "content-encoding" not in r.headers, path
            assert "vary" not in r.headers or "accept-encoding" not in r.headers["vary"].lower()


@pytest.mark.integration
async def test_works_under_a_mount_with_spa_deep_links_and_secure_apps():
    inner = create_app(session_factory=_build, spa=True, csp="strict")
    parent = Starlette(routes=[Mount("/ui", app=inner)])
    async with _client(parent) as c:
        deep = await c.get("/ui/projects/auth", headers=GZ)
        assert deep.headers["content-encoding"] == "gzip"
        assert '<base href="../">' in deep.text
        assert (await c.get("/ui/api/editor.js", headers=GZ)).headers["content-encoding"] == "gzip"
    secure = create_app(session_factory=_build, secure=True, secret="s" * 16, csp="strict")
    async with _client(secure) as c:
        r = await c.get("/", headers=GZ)
        assert r.headers["content-encoding"] == "gzip" and "<script" in r.text


@pytest.mark.integration
async def test_module_component_files_are_gzipped_and_keep_their_caching():
    saved = dict(_REGISTRY)  # leave the built-in registrations as they were
    try:
        reg = register_component(
            "zip-me", module=b"export default class extends HTMLElement{}\n" * 400
        )
        async with _client(create_app()) as c:
            url = f"/api/components/zip-me.js?v={reg.module_hash}"
            gz = await c.get(url, headers=GZ)
            assert gz.headers["content-encoding"] == "gzip"
            assert gz.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert gz.content == reg.module
            plain = await c.get(url, headers=ID)
            assert plain.content == reg.module and "content-encoding" not in plain.headers
            assert (await c.get("/api/components/nope.js", headers=GZ)).status_code == 404
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


@pytest.mark.integration
def test_the_event_stream_is_never_compressed_and_flushes_at_once():
    import time

    app = create_app(session_factory=_build)
    handle = launch(app, block=False, open_inline=False)
    try:
        t0 = time.monotonic()
        with httpx.stream(
            "GET",
            handle.url.rstrip("/") + "/api/stream?sid=gz1",
            headers={"Accept-Encoding": "gzip, deflate, br"},
            timeout=10,
        ) as r:
            assert r.status_code == 200
            assert "content-encoding" not in r.headers
            assert r.headers["content-type"].startswith("text/event-stream")
            first = next(r.iter_raw())  # the first bytes arrive before any heartbeat interval
            assert b"data:" in first or first.startswith(b":")
            assert time.monotonic() - t0 < 5
    finally:
        handle.stop()


@pytest.mark.integration
async def test_json_routes_are_left_alone():
    async with _client(create_app(session_factory=_build)) as c:
        r = await c.get("/health", headers=GZ)
        assert "content-encoding" not in r.headers

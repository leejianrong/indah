"""GET /api/map.js (ADR-0042): the lazily loaded Leaflet module, revalidated by ETag, cached for
good when the request carries its content hash, and reachable under a mount prefix."""

import hashlib
from importlib.resources import files

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from indah.app import create_app

DIGEST = hashlib.sha1(files("indah.static").joinpath("map.js").read_bytes()).hexdigest()[:16]


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.integration
async def test_map_module_is_served_as_javascript_with_an_etag_and_304():
    async with _client(create_app()) as c:
        first = await c.get("/api/map.js")
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("text/javascript")
        assert first.headers["cache-control"] == "no-cache"
        assert b"createMap" in first.content
        etag = first.headers["etag"]
        assert etag.startswith(f'"{DIGEST}')  # a gzipped body has its own validator (ADR-0042)
        again = await c.get("/api/map.js", headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        stale = await c.get("/api/map.js", headers={"If-None-Match": '"nope"'})
        assert stale.status_code == 200


@pytest.mark.integration
async def test_map_module_is_gzipped_when_accepted_and_plain_when_not():
    async with _client(create_app()) as c:
        raw = (await c.get("/api/map.js", headers={"Accept-Encoding": "identity"})).content
        zipped = await c.get("/api/map.js", headers={"Accept-Encoding": "gzip"})
        assert zipped.headers["content-encoding"] == "gzip"
        assert zipped.headers["vary"] == "Accept-Encoding"
        assert zipped.content == raw  # httpx decodes it: same bytes, smaller on the wire
        assert (await c.get("/api/map.js", headers={"Accept-Encoding": "identity"})).headers[
            "etag"
        ] == f'"{DIGEST}"'


@pytest.mark.integration
async def test_a_request_with_the_content_hash_is_cached_for_good_and_a_wrong_one_is_not():
    async with _client(create_app()) as c:
        pinned = await c.get(f"/api/map.js?v={DIGEST}")
        assert pinned.headers["cache-control"] == "public, max-age=31536000, immutable"
        wrong = await c.get("/api/map.js?v=0123456789abcdef")
        assert wrong.status_code == 200  # still served, but revalidated
        assert wrong.headers["cache-control"] == "no-cache"


@pytest.mark.integration
async def test_the_editor_route_still_behaves_as_before():
    async with _client(create_app()) as c:
        first = await c.get("/api/editor.js")
        assert first.status_code == 200 and first.headers["cache-control"] == "no-cache"
        assert b"createEditor" in first.content
        assert first.headers["etag"] != (await c.get("/api/map.js")).headers["etag"]


@pytest.mark.integration
async def test_only_the_named_modules_are_served():
    async with _client(create_app()) as c:
        for path in ("/api/other.js", "/api/map.js/x", "/api/%2e%2e/map.js", "/api/map.js.map"):
            assert (await c.get(path)).status_code == 404, path


@pytest.mark.integration
async def test_map_module_is_reachable_under_a_mount_prefix():
    parent = Starlette(routes=[Mount("/ui", app=create_app(spa=True))])
    async with _client(parent) as c:
        assert (await c.get("/ui/api/map.js")).status_code == 200

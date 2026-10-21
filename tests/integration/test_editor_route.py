"""GET /api/editor.js (ADR-0032): the lazily loaded editor module, revalidated by ETag, also
reachable under a mount prefix."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from indah.app import create_app


@pytest.mark.integration
async def test_editor_module_is_served_as_javascript_with_an_etag_and_304():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://t"
    ) as c:
        first = await c.get("/api/editor.js")
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("text/javascript")
        assert first.headers["cache-control"] == "no-cache"
        assert b"createEditor" in first.content
        etag = first.headers["etag"]
        again = await c.get("/api/editor.js", headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        stale = await c.get("/api/editor.js", headers={"If-None-Match": '"nope"'})
        assert stale.status_code == 200


@pytest.mark.integration
async def test_editor_module_is_reachable_under_a_mount_prefix():
    parent = Starlette(routes=[Mount("/ui", app=create_app(spa=True))])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=parent), base_url="http://t"
    ) as c:
        assert (await c.get("/ui/api/editor.js")).status_code == 200

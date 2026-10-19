"""indah mounted as a sub-app under a parent ASGI app (IND-86, semula's `/ui` mount).

The shell uses document-relative URLs (`api/stream`, ...) so it survives a base path
(ADR-0001). That holds only at the app root. For an in-app deep path
(`/ui/projects/auth/entries/01J`) the server must (a) serve the shell there, and (b) hand
the shell a relative `<base href>` so `api/*` still resolves to the app root. The
fallback is opt-in (`spa=True`); the base is relative, so it works under a Mount and
behind a proxy that strips an unknown prefix.
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from indah.app import _base_href, create_app
from indah.components import Column, Text
from indah.session import Session


def _indah(**kwargs):
    return create_app(session_factory=lambda: Session(Column(children=[Text("hi")])), **kwargs)


def _parent(**kwargs) -> Starlette:
    async def health(request):
        return JSONResponse({"parent": True})

    return Starlette(
        routes=[Route("/v1/health", health), Mount("/ui", app=_indah(**kwargs))],
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_mounted_root_serves_the_shell_without_a_base_tag():
    async with _client(_parent()) as c:
        r = await c.get("/ui/")
    assert r.status_code == 200 and "<base" not in r.text


@pytest.mark.integration
async def test_mounted_app_routes_and_parent_routes_coexist():
    async with _client(_parent()) as c:
        assert (await c.get("/v1/health")).json() == {"parent": True}
        assert (await c.get("/ui/health")).json() == {"status": "ok"}
        bad = await c.post("/ui/api/event", json={"component": "nope", "event": "click"})
    assert bad.status_code == 400  # the event route is reachable under the mount


@pytest.mark.integration
async def test_deep_path_is_a_404_unless_spa_fallback_is_on():
    async with _client(_parent()) as c:
        r = await c.get("/ui/projects/auth/entries/01J")
    assert r.status_code == 404


@pytest.mark.integration
async def test_spa_fallback_serves_the_shell_with_a_relative_base_under_a_mount():
    async with _client(_parent(spa=True)) as c:
        deep = await c.get("/ui/projects/auth/entries/01J")
        slash = await c.get("/ui/projects/auth/")
    assert deep.status_code == 200 and '<base href="../../../">' in deep.text
    assert slash.status_code == 200 and '<base href="../../">' in slash.text


@pytest.mark.integration
async def test_spa_fallback_never_shadows_api_or_unknown_api_paths():
    async with _client(_parent(spa=True)) as c:
        unknown = await c.get("/ui/api/unknown")
        wrong_method = await c.get("/ui/api/event")
        health = await c.get("/ui/health")
    assert unknown.status_code == 404 and wrong_method.status_code == 404
    assert health.json() == {"status": "ok"}


@pytest.mark.integration
async def test_standalone_spa_app_gets_the_same_relative_base():
    async with _client(_indah(spa=True)) as c:
        assert '<base href="../">' in (await c.get("/a/b")).text
        assert "<base" not in (await c.get("/a")).text  # one segment: already at the root
        assert "<base" not in (await c.get("/")).text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("/", "", None),
        ("/a", "", None),
        ("/a/", "", "../"),
        ("/a/b", "", "../"),
        ("/ui/", "/ui", None),
        ("/ui/a/b/c", "/ui", "../../"),  # Starlette 1.x: path includes the mount prefix
        ("/a/b/c", "/ui", "../../"),  # older Starlette: path is already mount-relative
    ],
)
def test_base_href(path, root, expected):
    assert _base_href(path, root) == expected

"""The Fly gallery mounts every demo under a sub-path on one app (ADR-0023).

Proves the load-bearing assumption: an indah app served under a base path (e.g.
`/a`) works, and two mounted apps stay isolated. This is the same base-path property
that lets indah run behind Colab's/Runpod's proxies (ADR-0001), exercised locally.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

from indah.app import create_app
from indah.components import Button, Column, Text
from indah.reactive import Signal
from indah.session import Session

_GALLERY = Path(__file__).resolve().parents[2] / "deploy" / "fly" / "gallery_app.py"


def _build_gallery():
    spec = importlib.util.spec_from_file_location("gallery_app", _GALLERY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_gallery


def _counter_app():
    n = Signal(0)
    root = Column(
        children=[Button("inc", on_click=lambda: n.set(n.value + 1)), Text(lambda: str(n.value))]
    )
    return create_app(session=Session(root))


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_gallery_index_lists_the_mounted_demos():
    build_gallery = _build_gallery()
    gallery = build_gallery(
        [
            {"slug": "a", "title": "Demo A", "emoji": "🅰️", "app": _counter_app()},
            {"slug": "b", "title": "Demo B", "emoji": "🅱️", "app": _counter_app()},
        ]
    )
    async with _client(gallery) as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert "indah demos" in r.text
        assert 'href="a/"' in r.text and 'href="b/"' in r.text  # relative, base-path safe


@pytest.mark.integration
async def test_each_demo_is_served_and_isolated_under_its_subpath():
    build_gallery = _build_gallery()
    app_a = _counter_app()
    app_b = _counter_app()
    gallery = build_gallery(
        [
            {"slug": "a", "title": "A", "emoji": "🅰️", "app": app_a},
            {"slug": "b", "title": "B", "emoji": "🅱️", "app": app_b},
        ]
    )
    async with _client(gallery) as client:
        # The shell is served under the sub-path (uses relative api/ URLs -> base-path safe).
        shell = await client.get("/a/")
        assert shell.status_code == 200
        assert "EventSource" in shell.text and "api/stream" in shell.text

        # An event under /a routes to app_a and patches only its hub, not app_b's.
        r = await client.post("/a/api/event", json={"component": "n1", "event": "click"})
        assert r.status_code == 200 and r.json()["ok"] is True

    a_patches = [m for _, m in app_a.state.hub.history() if m.get("type") == "patch"]
    b_patches = [m for _, m in app_b.state.hub.history() if m.get("type") == "patch"]
    assert a_patches and not b_patches  # isolation: /a's event never touched /b


@pytest.mark.integration
async def test_mounted_demo_serves_its_own_chrome():
    # Each mounted sub-app carries its own app.state, so the shell's _index injects
    # that demo's chrome (tab title, clickable logo back to the gallery, source link).
    build_gallery = _build_gallery()
    app_a = _counter_app()
    app_a.state.page_title = "Demo A"
    app_a.state.home_url = "../"
    app_a.state.source_url = "https://github.com/leejianrong/indah/blob/main/examples/a.py"
    gallery = build_gallery([{"slug": "a", "title": "Demo A", "emoji": "🅰️", "app": app_a}])
    async with _client(gallery) as client:
        shell = await client.get("/a/")
    assert shell.status_code == 200
    assert "<title>Demo A - indah</title>" in shell.text  # distinct per-demo tab title
    assert "window.__INDAH_CHROME__={" in shell.text  # config assignment injected
    assert '"homeUrl": "../"' in shell.text  # logo links back to the gallery
    assert "examples/a.py" in shell.text  # view-source link


@pytest.mark.integration
async def test_subpath_without_trailing_slash_redirects():
    build_gallery = _build_gallery()
    gallery = build_gallery([{"slug": "a", "title": "A", "emoji": "🅰️", "app": _counter_app()}])
    async with _client(gallery) as client:
        r = await client.get("/a")  # no trailing slash
        # Starlette redirects a Mount root to its trailing-slash form.
        assert r.status_code in (307, 308)
        assert r.headers["location"].endswith("/a/")

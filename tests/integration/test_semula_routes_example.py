"""The semula routes example (examples/semula_routes.py): links, params, the project
switcher in the URL, row-click navigation and a 404 page, mounted at /ui."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from indah.app import _stream

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_routes.py"


def _load():
    spec = importlib.util.spec_from_file_location("semula_routes_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


def _request(app, sid, path):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": f"sid={sid}&path={path}".encode(),
        "headers": [],
        "app": app,
    }
    return Request(scope)


async def _open(app, sid, path):
    resp = await _stream(_request(app, sid, path))
    async for _frame in resp.body_iterator:  # the init frame is enough to create the session
        break
    await resp.body_iterator.aclose()
    return app.state.store.get(sid)


def _find(handle, type_, pred=lambda c: True):
    return next(c for c in handle.session._by_id.values() if c.type == type_ and pred(c))


def _texts(handle):
    return " | ".join(
        str(c.reactive_props().get("text", lambda: "")() or c.reactive_props()["blocks"]())
        for c in handle.session._by_id.values()
        if c.type == "text"
    )


def _navigations(handle):
    return [m["path"] for _, m in handle.hub.history() if m["type"] == "navigate"]


@pytest.fixture
def world():
    data = ex.make_entries(per_project=5, seed=7)
    return data, ex.build_routes_app(data)


@pytest.mark.integration
async def test_entry_ids_are_stable_so_pasted_links_survive_restarts():
    assert ex.make_entries(5, 7) == ex.make_entries(5, 7)
    assert set(ex.make_entries()) == set(ex.PROJECTS)


@pytest.mark.integration
async def test_a_deep_link_opens_that_entry_and_an_unknown_one_says_so(world):
    data, app = world
    entry = next(iter(data["docs-qa"].values()))
    h = await _open(app, "a", f"/projects/docs-qa/entries/{entry['id']}")
    assert entry["response"] in _texts(h) and "docs-qa" in _texts(h)
    router = _find(h, "router")
    assert router.reactive_props()["active"]() == 2

    h = await _open(app, "b", "/projects/docs-qa/entries/NOPE")
    assert "No entry" in _texts(h) and "NOPE" in _texts(h)
    h = await _open(app, "c", "/projects/ghost")
    assert "No project called" in _texts(h) and "ghost" in _texts(h)
    h = await _open(app, "d", "/totally/unknown")
    assert _find(h, "router").reactive_props()["active"]() == 3  # the 404 page


@pytest.mark.integration
async def test_the_switcher_navigates_and_the_url_sets_the_switcher_without_bouncing(world):
    data, app = world
    h = await _open(app, "a", "/")
    select = _find(h, "select")
    assert _navigations(h) == []  # starting on "/" does not redirect to a project
    h.session.dispatch(select.id, "change", {"value": "docs-qa"})
    assert h.session.ctx.path.value == "/projects/docs-qa"
    assert _navigations(h) == ["/projects/docs-qa"]
    # The URL moves (Back, a link): the switcher follows, and nothing navigates on its own.
    router = _find(h, "router")
    h.session.dispatch(router.id, "navigate", {"path": "/projects/support-bot"})
    assert select._value.value == "support-bot"
    h.session.dispatch(router.id, "navigate", {"path": "/"})
    assert h.session.ctx.path.value == "/"  # Back to the overview stays there
    assert _navigations(h) == ["/projects/docs-qa"]


@pytest.mark.integration
async def test_clicking_a_row_navigates_to_that_entry(world):
    data, app = world
    h = await _open(app, "a", "/projects/support-bot")
    table = _find(h, "table")
    first = next(iter(data["support-bot"]))
    h.session.dispatch(table.id, "select", {"key": first})
    assert h.session.ctx.path.value == f"/projects/support-bot/entries/{first}"
    assert _navigations(h) == [f"/projects/support-bot/entries/{first}"]
    assert table._selected.value is None  # the pick is consumed, ready for the next click


@pytest.mark.integration
async def test_sidebar_links_highlight_the_current_project_and_back_link_follows_params(world):
    data, app = world
    entry = next(iter(data["code-review"]))
    h = await _open(app, "a", f"/projects/code-review/entries/{entry}")
    sidebar = {  # the fixed links; the entry page's "back" link has a computed target
        c.static_props()["to"]: c
        for c in h.session._by_id.values()
        if c.type == "link" and "to" in c.static_props()
    }
    assert sidebar["/projects/code-review"].reactive_props()["active"]() is True  # prefix
    assert sidebar["/projects/docs-qa"].reactive_props()["active"]() is False
    back = next(
        c for c in h.session._by_id.values() if c.type == "link" and "to" not in c.static_props()
    )
    assert back.reactive_props()["to"]() == "/projects/code-review"


@pytest.mark.integration
async def test_parent_app_mounts_the_dashboard_with_spa_deep_links():
    app = ex.build_app(per_project=3, seed=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/health")).json()["projects"] == ex.PROJECTS
        deep = await c.get("/ui/projects/support-bot/entries/ABC")
        assert deep.status_code == 200 and "semula" in deep.text
        assert (await c.get("/ui/api/nope")).status_code == 404

"""Router over the HTTP boundary (IND-105): a tab starts on the page named by ``&path=``,
the SPA fallback serves deep links, and a client navigation moves only its own session."""

import json

import httpx
import pytest
from starlette.requests import Request

from indah.app import _stream, create_app
from indah.components import Column, Link, Router, Text
from indah.session import Session


def _factory(ctx):
    return Session(
        Column(
            children=[
                Link(ctx, "Auth", to="/projects/auth"),
                Router(
                    ctx,
                    routes={
                        "/": Text("home"),
                        "/projects/{project}": Text("project page"),
                        "/projects/{project}/entries/{entry_id}": Text("entry page"),
                    },
                    not_found=Text("404"),
                ),
            ]
        )
    )


def _app(**kw):
    return create_app(session_factory=_factory, spa=True, **kw)


def _request(app, sid, path=None):
    query = f"sid={sid}" + (f"&path={path}" if path is not None else "")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": query.encode(),
        "headers": [],
        "app": app,
    }
    return Request(scope)


async def _init(resp):
    text = ""
    async for chunk in resp.body_iterator:
        text += chunk if isinstance(chunk, str) else chunk.decode()
        if text.count("data: ") >= 1:
            break
    await resp.body_iterator.aclose()
    line = next(ln for ln in text.splitlines() if ln.startswith("data: "))
    return json.loads(line[len("data: ") :])


def _router_active(init):
    def walk(node):
        if node["type"] == "router":
            return node["props"]["active"]
        for child in node["children"]:
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(init["root"])


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "active"),
    [
        (None, 0),
        ("/", 0),
        ("/projects/auth", 1),
        ("/projects/auth/entries/01J", 2),
        ("/missing", 3),  # not_found
        ("//evil.example", 0),  # not a plain in-app path: ignored, starts at home
        ("/projects/auth?x=1", 0),  # a query is not part of a path: ignored, starts at home
    ],
)
async def test_a_new_tab_starts_on_the_page_its_path_names(path, active):
    app = _app()
    init = await _init(await _stream(_request(app, f"tab-{path}", path)))
    assert _router_active(init) == active


@pytest.mark.integration
async def test_a_client_navigation_moves_only_its_own_session():
    app = _app()
    a, b = app.state.store.get_or_create("a"), app.state.store.get_or_create("b")
    link = next(c for c in a.session._by_id.values() if c.type == "link")
    router_a = next(c for c in a.session._by_id.values() if c.type == "router")
    router_b = next(c for c in b.session._by_id.values() if c.type == "router")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/event",
            json={
                "sid": "a",
                "component": link.id,
                "event": "navigate",
                "payload": {"path": "/projects/auth"},
            },
        )
    assert resp.status_code == 200
    assert router_a.reactive_props()["active"]() == 1
    assert router_b.reactive_props()["active"]() == 0
    # The change reaches the tab as an ordinary patch of the router's `active` prop.
    patches = [m for _, m in a.hub.history() if m["type"] == "patch"]
    assert any(c["props"].get("active") == 1 for m in patches for c in m["changes"])
    assert not [m for _, m in a.hub.history() if m["type"] == "navigate"]  # no echo


@pytest.mark.integration
async def test_spa_fallback_serves_deep_links_but_not_api_paths():
    app = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        deep = await c.get("/projects/auth/entries/01J")
        api = await c.get("/api/nope")
    assert deep.status_code == 200 and '<base href="../../../">' in deep.text
    assert api.status_code == 404


def _request_with(app, sid, path, last_event_id=None):
    headers = [(b"last-event-id", last_event_id.encode())] if last_event_id else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": f"sid={sid}&path={path}".encode(),
        "headers": headers,
        "app": app,
    }
    return Request(scope)


@pytest.mark.integration
async def test_a_fresh_page_load_in_the_same_tab_takes_its_path_from_the_url():
    """The tab keeps its session id across full page loads, so typing a new URL in the
    address bar must move the existing session's page, not resume the old one."""
    app = _app()
    first = await _init(await _stream(_request_with(app, "tab", "/projects/auth")))
    assert _router_active(first) == 1
    second = await _init(await _stream(_request_with(app, "tab", "/zzz")))  # same sid
    assert _router_active(second) == 3  # not found: the URL won


@pytest.mark.integration
async def test_an_automatic_reconnect_keeps_the_sessions_current_page():
    """EventSource reconnects to the URL it first used, whose path is stale by then."""
    app = _app()
    await _init(await _stream(_request_with(app, "tab", "/projects/auth")))
    handle = app.state.store.get("tab")
    handle.session.ctx.navigate("/projects/auth/entries/01J")  # the user moved on
    last = f"{handle.hub.epoch}-0"
    resp = await _stream(_request_with(app, "tab", "/projects/auth", last_event_id=last))
    text = ""
    async for chunk in resp.body_iterator:
        text += chunk if isinstance(chunk, str) else chunk.decode()
        if "data: " in text:
            break
    await resp.body_iterator.aclose()
    assert handle.session.ctx.path.value == "/projects/auth/entries/01J"  # not reset to the URL


ENTRIES = {("auth", "01J"): "login reply", ("auth", "02K"): "logout reply", ("docs", "01J"): "doc"}


def _entry_factory(ctx):
    """The semula shape: the page is a computed of the route's params, not of structure."""
    from indah.reactive import computed

    entry = computed(
        lambda: ENTRIES.get((ctx.params.value.get("project"), ctx.params.value.get("entry_id")))
    )
    return Session(
        Column(
            children=[
                Router(
                    ctx,
                    routes={
                        "/": Text("home"),
                        "/projects/{project}/entries/{entry_id}": Text(
                            lambda: (
                                f"entry: {entry.value or 'missing'} "
                                f"({ctx.params.value.get('project')})"
                            )
                        ),
                    },
                    not_found=Text("404"),
                ),
            ]
        )
    )


def _texts(handle):
    return [
        c.reactive_props()["text"]() for c in handle.session._by_id.values() if c.type == "text"
    ]


@pytest.mark.integration
async def test_route_params_drive_a_computed_entry_across_navigation():
    app = create_app(session_factory=_entry_factory, spa=True)
    init = await _init(await _stream(_request(app, "t", "/projects/auth/entries/01J")))
    assert _router_active(init) == 1
    handle = app.state.store.get("t")
    assert "entry: login reply (auth)" in _texts(handle)

    router = next(c for c in handle.session._by_id.values() if c.type == "router")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in (
            "/projects/auth/entries/02K",
            "/projects/docs/entries/01J",
            "/projects/x/entries/9",
        ):
            resp = await client.post(
                "/api/event",
                json={
                    "sid": "t",
                    "component": router.id,
                    "event": "navigate",
                    "payload": {"path": path},
                },
            )
            assert resp.status_code == 200
    assert "entry: missing (x)" in _texts(handle)  # unknown entry, still a valid route
    patches = [c for _, m in handle.hub.history() if m["type"] == "patch" for c in m["changes"]]
    texts = [c["props"]["text"] for c in patches if "text" in c["props"]]
    assert texts == ["entry: logout reply (auth)", "entry: doc (docs)", "entry: missing (x)"]

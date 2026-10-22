"""A module-backed custom component over HTTP (ADR-0039): the route that serves the
module, and the event round trip through the normal event path (guard, audit, secure)."""

import asyncio
import hashlib

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from indah import Policy, Principal, create_app, guard
from indah.components import Column
from indah.custom import _REGISTRY, clear_registry, custom, register_component
from indah.reactive import Signal
from indah.session import Session

JS = b"export default class extends HTMLElement { connectedCallback() {} }\n"
HASH = hashlib.sha256(JS).hexdigest()[:16]
SECRET = "a-long-random-secret-value-0123456789"


@pytest.fixture(autouse=True)
def _registry():
    saved = dict(_REGISTRY)
    clear_registry()
    register_component("tier-rail", module=JS, events=["pick"], two_way={"value": "change"})
    register_component("chip", render={"tag": "span", "text": "label"})
    yield
    clear_registry()
    _REGISTRY.update(saved)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.integration
async def test_the_module_is_served_as_javascript_with_an_etag_and_304():
    async with _client(create_app()) as c:
        first = await c.get("/api/components/tier-rail.js")
        assert first.status_code == 200 and first.content == JS
        assert first.headers["content-type"].startswith("text/javascript")
        assert first.headers["cache-control"] == "no-cache"
        again = await c.get(
            "/api/components/tier-rail.js", headers={"If-None-Match": first.headers["etag"]}
        )
        assert again.status_code == 304 and again.content == b""


@pytest.mark.integration
async def test_a_matching_version_is_cached_forever_and_a_stale_one_is_not():
    async with _client(create_app()) as c:
        hit = await c.get(f"/api/components/tier-rail.js?v={HASH}")
        assert hit.headers["cache-control"] == "public, max-age=31536000, immutable"
        miss = await c.get("/api/components/tier-rail.js?v=deadbeef")
        assert miss.status_code == 200 and miss.headers["cache-control"] == "no-cache"


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        "/api/components/nope.js",  # not registered
        "/api/components/chip.js",  # registered, but a render spec: no module
        "/api/components/Tier-Rail.js",  # the name pattern is lowercase
        "/api/components/..%2f..%2fetc%2fpasswd.js",
        "/api/components/%2e%2e.js",
        "/api/components/tier-rail.js/extra",
        "/api/components/tier_rail.js",
        "/api/components/.js",
    ],
)
async def test_anything_but_a_registered_module_name_is_a_404(path):
    async with _client(create_app()) as c:
        assert (await c.get(path)).status_code == 404


@pytest.mark.integration
async def test_a_post_to_the_module_route_is_refused():
    async with _client(create_app()) as c:
        assert (await c.post("/api/components/tier-rail.js")).status_code == 405


@pytest.mark.integration
async def test_the_module_is_reachable_under_a_mount_prefix():
    parent = Starlette(routes=[Mount("/ui", app=create_app(spa=True))])
    async with _client(parent) as c:
        assert (await c.get("/ui/api/components/tier-rail.js")).content == JS


@pytest.mark.integration
async def test_a_secure_app_serves_the_module_without_a_session():
    app = create_app(
        session_factory=lambda ctx: Session(Column(children=[])),
        auth=lambda r: Principal(id="u") if r.headers.get("x-user") else None,
        secure=True,
        secret=SECRET,
    )
    async with _client(app) as c:
        assert (await c.get("/api/components/tier-rail.js")).status_code == 200


@pytest.mark.integration
async def test_the_module_route_carries_the_security_headers_and_a_strict_csp_page_allows_it():
    async with _client(create_app(security_headers=True, csp="strict")) as c:
        resp = await c.get("/api/components/tier-rail.js")
        assert resp.headers["x-content-type-options"] == "nosniff"
        page = await c.get("/")
        assert "script-src 'nonce-" in page.headers["content-security-policy"]
        assert "'self'" in page.headers["content-security-policy"]


def _event_app(seen, **kw):
    value = Signal(1)

    def build(ctx) -> Session:
        rail = custom(
            "tier-rail",
            value=value,
            on_pick=guard("entries:write")(lambda d: seen.append(("pick", d, ctx.user.id))),
        )
        return Session(Column(children=[rail]))

    return create_app(
        session_factory=build,
        auth=lambda r: Principal(id=r.headers["x-user"], roles=frozenset([r.headers["x-role"]])),
        secure=True,
        secret=SECRET,
        policy=Policy({"viewer": ["entries:read"], "editor": ["entries:*"]}),
        **kw,
    ), value


async def _login(c, user, role):
    h = {"X-User": user, "X-Role": role}
    return (await c.post("/api/session", json={}, headers=h)).json()["token"], h


@pytest.mark.integration
async def test_events_reach_the_handler_and_guard_applies_per_request():
    seen: list = []
    app, value = _event_app(seen)
    async with _client(app) as c:
        token, h = await _login(c, "eve", "editor")
        ok = await c.post(
            "/api/event",
            json={
                "sid": token,
                "component": "n1",
                "event": "pick",
                "payload": {"detail": {"t": 2}},
            },
            headers=h,
        )
        assert ok.status_code == 200
        two = await c.post(
            "/api/event",
            json={
                "sid": token,
                "component": "n1",
                "event": "change",
                "payload": {"detail": {"value": 5}},
            },
            headers=h,
        )
        assert two.status_code == 200 and value.peek() == 5
        vtoken, vh = await _login(c, "vera", "viewer")
        denied = await c.post(
            "/api/event",
            json={"sid": vtoken, "component": "n1", "event": "pick", "payload": {"detail": 1}},
            headers=vh,
        )
        assert denied.status_code == 403
        undeclared = await c.post(
            "/api/event",
            json={"sid": token, "component": "n1", "event": "other", "payload": {"detail": 1}},
            headers=h,
        )
        assert undeclared.status_code == 400
    await asyncio.sleep(0)
    assert seen == [("pick", {"t": 2}, "eve")]


@pytest.mark.integration
async def test_the_audit_hook_sees_a_module_event_without_its_values():
    events: list = []
    app, _ = _event_app([], audit=events.append)
    async with _client(app) as c:
        token, h = await _login(c, "eve", "editor")
        await c.post(
            "/api/event",
            json={
                "sid": token,
                "component": "n1",
                "event": "pick",
                "payload": {"detail": "secret-ish"},
            },
            headers=h,
        )
    assert [(e.component, e.event, e.payload_keys, e.user) for e in events] == [
        ("n1", "pick", ("detail",), "eve")
    ]
    assert "secret-ish" not in repr(events)


@pytest.mark.integration
async def test_the_snapshot_carries_the_module_url_for_the_session():
    app, _ = _event_app([])
    async with _client(app) as c:
        token, h = await _login(c, "eve", "editor")
        await c.post("/api/event", json={"sid": token, "component": "n1", "event": "x"}, headers=h)
        snap = app.state.store.get(token.split(".")[0]).session.snapshot()
    props = snap["children"][0]["props"]
    assert props["_module"]["url"].startswith("api/components/tier-rail.js?v=")

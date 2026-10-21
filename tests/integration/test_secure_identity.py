"""Identity and ownership over HTTP (ADR-0033, IND-113): who a request is, who owns a session.

A tiny parent middleware plays the identity provider: it turns an ``X-User`` header into
Starlette's ``scope["user"]``, which indah's default authenticator reads. The failure cases
matter most here: secure mode must fail closed, so each refusal also checks that no session
was created for the refused request.
"""

import httpx
import pytest
from starlette.authentication import SimpleUser

from indah import Principal, create_app
from indah.components import Button, Column, Text
from indah.reactive import Signal
from indah.session import Session


class FakeIdp:
    """Sets ``scope["user"]`` from ``X-User``; no header means anonymous."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            who = headers.get(b"x-user")
            if who:
                scope["user"] = SimpleUser(who.decode())
        await self.app(scope, receive, send)


def _factory(seen: list):
    def build(ctx) -> Session:
        seen.append(ctx.user)
        n = Signal(0)
        return Session(
            Column(
                children=[
                    Button("inc", on_click=lambda: n.set(n.value + 1)),
                    Text(lambda: f"{ctx.user.id if ctx.user else 'nobody'}:{n.value}"),
                ]
            )
        )

    return build


def _app(**kw):
    seen: list = []
    app = create_app(session_factory=_factory(seen), **kw)
    return app, FakeIdp(app), seen


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


async def _click(client, sid, **kw):
    return await client.post(
        "/api/event", json={"sid": sid, "component": "n1", "event": "click"}, **kw
    )


@pytest.mark.integration
async def test_factory_sees_the_authenticated_user_and_the_session_is_owned():
    app, asgi, seen = _app(secure=True)
    async with _client(asgi) as client:
        resp = await _click(client, "tab-a", headers={"X-User": "alice"})
    assert resp.status_code == 200
    assert [p.id for p in seen] == ["alice"] and isinstance(seen[0], Principal)
    assert app.state.store.get("tab-a").owner == "alice"
    text = app.state.store.get("tab-a").session.snapshot()["children"][1]["props"]["text"]
    assert text == "alice:1"


@pytest.mark.integration
async def test_an_authenticator_alone_gives_ctx_user_without_enforcing_anything():
    seen: list = []
    app = create_app(
        session_factory=_factory(seen), auth=lambda r: Principal(id="svc", roles={"admin"})
    )
    async with _client(app) as client:
        assert (await _click(client, "t")).status_code == 200
        assert (await _click(client, "")).status_code == 200  # id-less still shares `default`
    assert seen[0].id == "svc" and seen[0].roles == frozenset({"admin"})


@pytest.mark.integration
async def test_secure_refuses_anonymous_requests_on_every_route_and_creates_no_session():
    app, asgi, seen = _app(secure=True)
    async with _client(asgi) as client:
        assert (await _click(client, "t")).status_code == 401
        assert (await client.get("/api/stream", params={"sid": "t"})).status_code == 401
        up = await client.post(
            "/api/upload", data={"component": "n1", "sid": "t"}, files={"file": ("a", b"x")}
        )
        assert up.status_code == 401
    assert len(app.state.store) == 0 and seen == []


@pytest.mark.integration
async def test_secure_refuses_an_id_less_request_instead_of_sharing_a_default_session():
    app, asgi, seen = _app(secure=True)
    async with _client(asgi) as client:
        for sid in (None, ""):
            body = {"component": "n1", "event": "click"}
            if sid is not None:
                body["sid"] = sid
            resp = await client.post("/api/event", json=body, headers={"X-User": "alice"})
            assert resp.status_code == 401
        assert (await client.get("/api/stream", headers={"X-User": "alice"})).status_code == 401
    assert len(app.state.store) == 0 and seen == []


@pytest.mark.integration
async def test_another_principal_cannot_attach_to_a_session_it_does_not_own():
    app, asgi, seen = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        assert (await _click(client, "tab-a", headers={"X-User": "alice"})).status_code == 200
        assert (await _click(client, "tab-a", headers={"X-User": "mallory"})).status_code == 403
        assert (
            await client.get("/api/stream", params={"sid": "tab-a"}, headers={"X-User": "mallory"})
        ).status_code == 403
        up = await client.post(
            "/api/upload",
            data={"component": "n1", "sid": "tab-a"},
            files={"file": ("a", b"x")},
            headers={"X-User": "mallory"},
        )
        assert up.status_code == 403
    # alice's session is untouched: one click, never driven by mallory
    text = store.get("tab-a").session.snapshot()["children"][1]["props"]["text"]
    assert text == "alice:1" and [p.id for p in seen] == ["alice"]


@pytest.mark.integration
async def test_a_failing_or_wrong_authenticator_is_treated_as_nobody():
    def boom(request):
        raise RuntimeError("idp down")

    for bad in (boom, lambda r: "alice", lambda r: Principal(id="x", expires_at=1.0)):
        app = create_app(session_factory=_factory([]), auth=bad, secure=True)
        async with _client(app) as client:
            assert (await _click(client, "t")).status_code == 401, bad
        assert len(app.state.store) == 0


@pytest.mark.integration
async def test_an_async_authenticator_works():
    async def who(request):
        return Principal(id=request.headers["x-user"]) if "x-user" in request.headers else None

    app = create_app(session_factory=_factory([]), auth=who, secure=True)
    async with _client(app) as client:
        assert (await _click(client, "t", headers={"X-User": "bo"})).status_code == 200
        assert (await _click(client, "t2")).status_code == 401


@pytest.mark.integration
async def test_download_is_only_served_to_the_owner():
    app, asgi, _ = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        await _click(client, "tab-a", headers={"X-User": "alice"})
        url = store.get("tab-a").session.serve_file(
            b"secret", filename="s.txt", media_type="text/plain"
        )
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={"X-User": "mallory"})).status_code == 404
        owner = await client.get(url, headers={"X-User": "alice"})
        assert owner.status_code == 200 and owner.content == b"secret"


@pytest.mark.integration
def test_secure_needs_a_per_viewer_factory_and_a_valid_principal_id():
    with pytest.raises(ValueError, match="per-viewer"):
        create_app(session=Session(Column(children=[Text("x")])), secure=True)
    with pytest.raises(ValueError, match="non-empty"):
        Principal(id="")


@pytest.mark.integration
async def test_non_secure_apps_are_unchanged():
    app = create_app(session_factory=_factory([]))
    async with _client(app) as client:
        assert (await _click(client, "t")).status_code == 200
        assert (
            await client.post("/api/event", json={"component": "n1", "event": "click"})
        ).status_code == 200
    assert app.state.store.get("default") is not None

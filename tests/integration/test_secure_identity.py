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


SECRET = "a-long-random-secret-value-0123456789"


def _app(**kw):
    seen: list = []
    if kw.get("secure"):
        kw.setdefault("secret", SECRET)
    app = create_app(session_factory=_factory(seen), **kw)
    return app, FakeIdp(app), seen


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


async def _login(client, user, resume=None) -> str:
    resp = await client.post("/api/session", json={"resume": resume}, headers={"X-User": user})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


async def _click(client, sid, **kw):
    return await client.post(
        "/api/event", json={"sid": sid, "component": "n1", "event": "click"}, **kw
    )


@pytest.mark.integration
async def test_factory_sees_the_authenticated_user_and_the_session_is_owned():
    app, asgi, seen = _app(secure=True)
    async with _client(asgi) as client:
        token = await _login(client, "alice")
        resp = await _click(client, token, headers={"X-User": "alice"})
    sid = token.split(".")[0]
    assert resp.status_code == 200
    assert [p.id for p in seen] == ["alice"] and isinstance(seen[0], Principal)
    assert app.state.store.get(sid).owner == "alice"
    text = app.state.store.get(sid).session.snapshot()["children"][1]["props"]["text"]
    assert text == "alice:1"


@pytest.mark.integration
async def test_an_authenticator_alone_gives_ctx_user_without_enforcing_anything():
    seen: list = []
    app = create_app(
        session_factory=_factory(seen), auth=lambda r: Principal(id="svc", roles={"admin"})
    )
    async with _client(app) as client:
        assert (await _click(client, "t")).status_code == 200
        assert (await _click(client, "")).status_code == 400  # id-less never shares (IND-139)
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
        token = await _login(client, "alice")
        assert (await _click(client, token, headers={"X-User": "alice"})).status_code == 200
        # mallory replays alice's token, and tries alice's raw sid
        sid = token.split(".")[0]
        for presented in (token, sid):
            m = {"X-User": "mallory"}
            assert (await _click(client, presented, headers=m)).status_code == 403
            assert (
                await client.get("/api/stream", params={"sid": presented}, headers=m)
            ).status_code == 403
            up = await client.post(
                "/api/upload",
                data={"component": "n1", "sid": presented},
                files={"file": ("a", b"x")},
                headers=m,
            )
            assert up.status_code == 403
    text = store.get(sid).session.snapshot()["children"][1]["props"]["text"]
    assert text == "alice:1" and [p.id for p in seen] == ["alice"]  # never driven by mallory


@pytest.mark.integration
async def test_a_failing_or_wrong_authenticator_is_treated_as_nobody():
    def boom(request):
        raise RuntimeError("idp down")

    for bad in (boom, lambda r: "alice", lambda r: Principal(id="x", expires_at=1.0)):
        app = create_app(session_factory=_factory([]), auth=bad, secure=True, secret=SECRET)
        async with _client(app) as client:
            assert (await _click(client, "t")).status_code == 401, bad
        assert len(app.state.store) == 0


@pytest.mark.integration
async def test_an_async_authenticator_works():
    async def who(request):
        return Principal(id=request.headers["x-user"]) if "x-user" in request.headers else None

    app = create_app(session_factory=_factory([]), auth=who, secure=True, secret=SECRET)
    async with _client(app) as client:
        token = await _login(client, "bo")
        assert (await _click(client, token, headers={"X-User": "bo"})).status_code == 200
        assert (await _click(client, token)).status_code == 401


@pytest.mark.integration
async def test_download_is_only_served_to_the_owner():
    app, asgi, _ = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        token = await _login(client, "alice")
        await _click(client, token, headers={"X-User": "alice"})
        url = store.get(token.split(".")[0]).session.serve_file(
            b"secret", filename="s.txt", media_type="text/plain"
        )
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={"X-User": "mallory"})).status_code == 404
        owner = await client.get(url, headers={"X-User": "alice"})
        assert owner.status_code == 200 and owner.content == b"secret"


@pytest.mark.integration
def test_secure_needs_a_per_viewer_factory_and_a_valid_principal_id():
    with pytest.raises(ValueError, match="per-viewer"):
        create_app(session=Session(Column(children=[Text("x")])), secure=True, secret=SECRET)
    with pytest.raises(ValueError, match="secret"):
        create_app(session_factory=_factory([]), secure=True)
    with pytest.raises(ValueError, match="non-empty"):
        Principal(id="")


@pytest.mark.integration
async def test_non_secure_apps_are_unchanged():
    app = create_app(session_factory=_factory([]))
    async with _client(app) as client:
        assert (await _click(client, "t")).status_code == 200
        # an id-less event no longer falls through to a shared session (IND-139)
        assert (
            await client.post("/api/event", json={"component": "n1", "event": "click"})
        ).status_code == 400
    assert app.state.store.get("default") is None


@pytest.mark.integration
async def test_forged_unsigned_and_cross_principal_ids_are_refused_and_create_nothing():
    app, asgi, seen = _app(secure=True)
    async with _client(asgi) as client:
        alice = await _login(client, "alice")
        sid = alice.split(".")[0]
        bad = ["tab-a", "default", sid, sid + ".", sid + ".AAAA", "x" * 30 + ".yyy", alice + "x"]
        for token in bad:
            resp = await _click(client, token, headers={"X-User": "alice"})
            assert resp.status_code == 403, token
        # a token signed for bob is no good for alice
        bob = await _login(client, "bob")
        assert (await _click(client, bob, headers={"X-User": "alice"})).status_code == 403
    assert len(app.state.store) == 0 and seen == []


@pytest.mark.integration
async def test_reload_resumes_the_same_session_and_other_users_get_their_own():
    app, asgi, _ = _app(secure=True)
    async with _client(asgi) as client:
        first = await _login(client, "alice")
        await _click(client, first, headers={"X-User": "alice"})
        again = await _login(client, "alice", resume=first)
        assert again == first  # a reload keeps its session (and its state)
        stolen = await _login(client, "mallory", resume=first)  # replayed by someone else
        assert stolen != first and stolen.split(".")[0] != first.split(".")[0]
        junk = await _login(client, "alice", resume="not-a-token")
        assert junk != first
    text = app.state.store.get(first.split(".")[0]).session.snapshot()["children"][1]
    assert text["props"]["text"] == "alice:1"


@pytest.mark.integration
async def test_the_session_endpoint_needs_a_login_and_only_exists_on_secure_apps():
    app, asgi, _ = _app(secure=True)
    async with _client(asgi) as client:
        assert (await client.post("/api/session", json={})).status_code == 401
        assert (
            await client.post("/api/session", content=b"{", headers={"X-User": "a"})
        ).status_code == 400
        big = await client.post("/api/session", content=b"x" * 5000, headers={"X-User": "a"})
        assert big.status_code == 413
        ok = await client.post("/api/session", json={}, headers={"X-User": "a"})
        assert ok.headers["cache-control"] == "no-store" and ok.json()["user"]["id"] == "a"
    plain = create_app(session_factory=_factory([]))
    async with _client(plain) as client:
        assert (await client.post("/api/session", json={})).status_code in (404, 405)


@pytest.mark.integration
async def test_rotating_the_secret_keeps_old_tokens_working_until_dropped():
    old = "old-secret-value-0123456789abcdef"
    new = "new-secret-value-0123456789abcdef"
    app_old, asgi_old, _ = _app(secure=True, secret=old)
    async with _client(asgi_old) as client:
        token = await _login(client, "alice")
    app_rot, asgi_rot, _ = _app(secure=True, secret=[new, old])
    async with _client(asgi_rot) as client:
        assert (await _click(client, token, headers={"X-User": "alice"})).status_code == 200
    app_new, asgi_new, _ = _app(secure=True, secret=new)
    async with _client(asgi_new) as client:
        assert (await _click(client, token, headers={"X-User": "alice"})).status_code == 403


@pytest.mark.integration
async def test_discard_where_owner_drops_only_that_users_sessions():
    app, asgi, _ = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        a1 = await _login(client, "alice")
        a2 = await _login(client, "alice")
        b1 = await _login(client, "bob")
        for t, u in ((a1, "alice"), (a2, "alice"), (b1, "bob")):
            await _click(client, t, headers={"X-User": u})
    assert len(store) == 3
    assert store.discard_where(owner="alice") == 2
    assert len(store) == 1 and store.get(b1.split(".")[0]).owner == "bob"


@pytest.mark.integration
async def test_cross_origin_requests_are_refused_before_anything_is_parsed_or_created():
    app, asgi, seen = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        token = await _login(client, "alice")
        evil = {"X-User": "alice", "Origin": "https://evil.example"}
        cross = {"X-User": "alice", "Sec-Fetch-Site": "cross-site"}
        for hdrs in (evil, cross):
            assert (await client.post("/api/session", json={}, headers=hdrs)).status_code == 403
            assert (await _click(client, token, headers=hdrs)).status_code == 403
            up = await client.post(
                "/api/upload",
                data={"component": "n1", "sid": token},
                files={"file": ("a", b"x")},
                headers=hdrs,
            )
            assert up.status_code == 403
            stream = await client.get("/api/stream", params={"sid": token}, headers=hdrs)
            assert stream.status_code == 403
            assert (await client.get("/api/file/x/y", headers=hdrs)).status_code == 403
        # the same requests from the app's own origin go through
        mine = {"X-User": "alice", "Origin": "http://test", "Sec-Fetch-Site": "same-origin"}
        assert (await _click(client, token, headers=mine)).status_code == 200
        # the shell itself and the health check are not guarded
        assert (await client.get("/", headers=evil)).status_code == 200
    assert len(store) == 1 and [p.id for p in seen] == ["alice"]  # only the allowed click built one


@pytest.mark.integration
async def test_allowed_origins_admit_a_gateway_on_another_origin():
    app, asgi, _ = _app(secure=True, allowed_origins=["https://portal.example.com/"])
    async with _client(asgi) as client:
        hdrs = {
            "X-User": "a",
            "Origin": "https://portal.example.com",
            "Sec-Fetch-Site": "same-site",
        }
        assert (await client.post("/api/session", json={}, headers=hdrs)).status_code == 200
        hdrs["Origin"] = "https://other.example.com"
        assert (await client.post("/api/session", json={}, headers=hdrs)).status_code == 403
    with pytest.raises(ValueError, match="allowed_origins"):
        _app(secure=True, allowed_origins=["*"])


@pytest.mark.integration
async def test_sign_out_ends_every_session_of_that_user_and_tells_each_stream():
    holder: dict = {}

    def build(ctx) -> Session:
        holder.setdefault(ctx.user.id, []).append(ctx)
        return Session(
            Column(
                children=[
                    Button("noop", on_click=lambda: None),
                    Button("out", on_click=ctx.sign_out),
                ]
            )
        )

    app = create_app(session_factory=build, secure=True, secret=SECRET)
    store = app.state.store
    async with _client(FakeIdp(app)) as client:
        a1, a2 = await _login(client, "alice"), await _login(client, "alice")
        b1 = await _login(client, "bob")
        for t, u in ((a1, "alice"), (a2, "alice"), (b1, "bob")):
            await _click(client, t, headers={"X-User": u})
        hubs = [store.get(t.split(".")[0]).hub for t in (a1, a2, b1)]
        queues = [h.subscribe() for h in hubs]
        out = await client.post(
            "/api/event",
            json={"sid": a1, "component": "n2", "event": "click"},
            headers={"X-User": "alice"},
        )
        assert out.status_code == 200
    assert len(store) == 1 and store.get(b1.split(".")[0]) is not None  # only bob's remains
    types = [[m["type"] for _, m in list(q._queue)] for q in queues]  # noqa: SLF001
    assert "signed_out" in types[0] and "signed_out" in types[1]  # both of alice's tabs
    assert "signed_out" not in types[2]


@pytest.mark.integration
async def test_signed_out_user_gets_a_fresh_empty_session_not_the_old_one():
    app, asgi, _ = _app(secure=True)
    store = app.state.store
    async with _client(asgi) as client:
        token = await _login(client, "alice")
        await _click(client, token, headers={"X-User": "alice"})
        assert store.discard_where(owner="alice") == 1
        # the old token still verifies (same principal) but the state is gone: a new session
        await _click(client, token, headers={"X-User": "alice"})
    text = store.get(token.split(".")[0]).session.snapshot()["children"][1]["props"]["text"]
    assert text == "alice:1"  # one click on the rebuilt session, not two

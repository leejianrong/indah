"""Authorization over HTTP (ADR-0035, IND-118): omission at build time, guard at dispatch.

A role is only as good as the places it is checked, so these tests look at what actually
leaves the server: the ``init`` snapshot a viewer receives, and what a handler does when a
role is revoked between the page load and the click.
"""

import json

import httpx
import pytest

from indah import Policy, Principal, create_app, guard
from indah.components import Button, Column, Text
from indah.protocol import init_message
from indah.reactive import Signal
from indah.session import Session

SECRET = "a-long-random-secret-value-0123456789"
ROLES: dict[str, set[str]] = {"alice": {"admin"}, "vera": {"viewer"}, "eve": {"editor"}}
WORKSPACES: dict[str, str] = {}


def _who(request):
    user = request.headers.get("x-user")
    if not user:
        return None
    return Principal(id=user, roles=frozenset(ROLES.get(user, ())), workspace=WORKSPACES.get(user))


@pytest.fixture(autouse=True)
def _reset():
    ROLES.update({"alice": {"admin"}, "vera": {"viewer"}, "eve": {"editor"}})
    WORKSPACES.clear()


def _build(log, deleted):
    def build(ctx) -> Session:
        count = Signal(0)

        def delete():
            deleted.append(ctx.user.id)

        def wipe():  # require() inside the body, the other way to guard
            ctx.require("admin")
            deleted.append("wiped:" + ctx.user.id)

        async def archive():
            deleted.append("archived:" + ctx.user.id)

        children = [
            Text(lambda: f"count {count.value}"),
            Button("delete", on_click=guard("entries:write")(delete)),
            Button("wipe", on_click=wipe),
            Button("archive", on_click=guard("entries:write")(archive)),
            *ctx.only("tokens:manage", lambda: Text("ADMIN-ONLY-SECRET-PANEL")),
        ]
        log.append((ctx.user.id, ctx.can("tokens:manage"), ctx.workspace))
        return Session(Column(children=children))

    return build


POLICY = Policy({"viewer": ["entries:read"], "editor": ["entries:*"], "admin": ["*"]})


def _app(**kw):
    log, deleted = [], []
    app = create_app(
        session_factory=_build(log, deleted),
        auth=_who,
        secure=True,
        secret=SECRET,
        policy=POLICY,
        **kw,
    )
    return app, log, deleted


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _login(client, user):
    resp = await client.post("/api/session", json={}, headers={"X-User": user})
    return resp.json()["token"]


async def _init(app, client, token, user) -> str:
    """The text of the ``init`` message this user's stream would start with."""
    await _click(client, token, user, "n0")  # opens the session (a Text: no handler, a 400)
    snapshot = app.state.store.get(token.split(".")[0]).session.snapshot()
    return json.dumps(init_message(snapshot))


async def _click(client, token, user, node):
    return await client.post(
        "/api/event",
        json={"sid": token, "component": node, "event": "click"},
        headers={"X-User": user},
    )


@pytest.mark.integration
async def test_a_viewers_init_snapshot_has_no_admin_subtree_and_an_admins_does():
    app, log, _ = _app()
    async with _client(app) as client:
        viewer = await _init(app, client, await _login(client, "vera"), "vera")
        admin = await _init(app, client, await _login(client, "alice"), "alice")
    assert "ADMIN-ONLY-SECRET-PANEL" not in viewer
    assert "ADMIN-ONLY-SECRET-PANEL" in admin
    assert json.loads(viewer)["type"] == "init"
    assert (("vera", False, None) in log) and (("alice", True, None) in log)


@pytest.mark.integration
async def test_a_viewer_cannot_run_a_guarded_handler_and_gets_403():
    app, _, deleted = _app()
    async with _client(app) as client:
        token = await _login(client, "vera")
        assert (await _click(client, token, "vera", "n2")).status_code == 403  # guard(...)
        assert (await _click(client, token, "vera", "n3")).status_code == 403  # ctx.require
        assert (await _click(client, token, "vera", "n4")).status_code == 403  # async + guard
    assert deleted == []


@pytest.mark.integration
async def test_permitted_roles_run_the_handlers():
    app, _, deleted = _app()
    async with _client(app) as client:
        ed = await _login(client, "eve")
        assert (await _click(client, ed, "eve", "n2")).status_code == 200
        assert (await _click(client, ed, "eve", "n3")).status_code == 403  # editor is not admin
        assert (await _click(client, ed, "eve", "n4")).status_code == 200
        ad = await _login(client, "alice")
        assert (await _click(client, ad, "alice", "n3")).status_code == 200
    import asyncio

    await asyncio.sleep(0)  # let the spawned async handler run
    assert sorted(deleted) == ["archived:eve", "eve", "wiped:alice"]


@pytest.mark.integration
async def test_a_role_revoked_after_the_page_loaded_fails_the_next_action_closed():
    app, _, deleted = _app()
    async with _client(app) as client:
        token = await _login(client, "eve")
        assert (await _click(client, token, "eve", "n2")).status_code == 200
        ROLES["eve"] = {"viewer"}  # the IdP revoked it; the open tab still has the button
        resp = await _click(client, token, "eve", "n2")
    assert resp.status_code == 403
    assert deleted == ["eve"]  # only the first, pre-revocation click ran


@pytest.mark.integration
async def test_a_forbidden_event_is_not_audited_and_tells_the_tab():
    audited = []
    app, _, _ = _app(audit=audited.append)
    async with _client(app) as client:
        token = await _login(client, "vera")
        await _click(client, token, "vera", "n0")  # opens the session
        queue = app.state.store.get(token.split(".")[0]).hub.subscribe()
        await _click(client, token, "vera", "n2")
    assert audited == []
    kinds = [m for _, m in list(queue._queue)]  # noqa: SLF001
    assert any(m["type"] == "toast" and m.get("kind") == "warn" for m in kinds)


@pytest.mark.integration
async def test_ctx_workspace_and_a_session_is_bound_to_its_workspace():
    app, log, _ = _app()
    WORKSPACES["alice"] = "acme"
    async with _client(app) as client:
        token = await _login(client, "alice")
        assert (await _click(client, token, "alice", "n3")).status_code == 200
        assert log[-1] == ("alice", True, "acme")
        WORKSPACES["alice"] = "globex"  # same person, another workspace: not this session
        before = len(app.state.store)
        resp = await _click(client, token, "alice", "n3")
        other = await _login(client, "alice")
        assert (await _click(client, other, "alice", "n3")).status_code == 200
    assert resp.status_code == 403 and len(app.state.store) == before + 1
    assert other.split(".")[0] != token.split(".")[0]
    assert log[-1] == ("alice", True, "globex")


@pytest.mark.integration
async def test_an_app_with_no_policy_treats_a_permission_as_a_role():
    log, deleted = [], []
    app = create_app(session_factory=_build(log, deleted), auth=_who, secure=True, secret=SECRET)
    ROLES["alice"] = {"entries:write", "tokens:manage"}
    async with _client(app) as client:
        token = await _login(client, "alice")
        assert (await _click(client, token, "alice", "n2")).status_code == 200
        vera = await _login(client, "vera")
        assert (await _click(client, vera, "vera", "n2")).status_code == 403

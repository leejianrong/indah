"""An event for a session this process does not hold fails loudly (IND-199).

With more than one process and no affinity, a click can land on a process that never saw the
tab. It used to create a fresh, streamless session for that id and answer ``200``, so the click
vanished (IND-171 measured 3 of 20 and 5 of 20 events arriving). Now it is ``409`` with
``{"ok": false, "error": "unknown_session"}``, so the shell can re-open its stream and say so.
The secure rules do not move: an unauthenticated, forged or foreign id is still ``401``/``403``.
"""

import httpx
import pytest
from starlette.authentication import SimpleUser

from indah import Principal, create_app
from indah.components import Button, Column, Text
from indah.context import ConnectionInfo
from indah.reactive import Signal
from indah.session import Session

SECRET = "a-long-random-secret-value-0123456789"

pytestmark = pytest.mark.raw_events  # no tab connects for these: they test the bare route


def _factory():
    n = Signal(0)
    return Session(
        Column(
            children=[
                Button("inc", on_click=lambda: n.set(n.value + 1)),
                Text(lambda: str(n.value)),
            ]
        )
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class FakeIdp:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            who = dict(scope["headers"]).get(b"x-user")
            if who:
                scope["user"] = SimpleUser(who.decode())
        await self.app(scope, receive, send)


def _click(sid):
    return {"sid": sid, "component": "n1", "event": "click"}


@pytest.mark.integration
async def test_an_event_for_an_unknown_session_is_409_and_creates_nothing():
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        resp = await client.post("/api/event", json=_click("never-seen"))
    assert resp.status_code == 409
    assert resp.json() == {"ok": False, "error": "unknown_session"}
    assert app.state.store.get("never-seen") is None  # the refused event made no session


@pytest.mark.integration
async def test_an_event_for_a_known_session_still_works():
    app = create_app(session_factory=_factory)
    app.state.store.get_or_create("tab-a")  # what opening the stream does
    async with _client(app) as client:
        resp = await client.post("/api/event", json=_click("tab-a"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.integration
async def test_a_session_that_was_discarded_is_unknown_again():
    app = create_app(session_factory=_factory)
    store = app.state.store
    store.get_or_create("tab-a")
    store.discard("tab-a")  # evicted, idled out, or the process restarted
    async with _client(app) as client:
        resp = await client.post("/api/event", json=_click("tab-a"))
    assert resp.status_code == 409


@pytest.mark.integration
async def test_an_app_built_on_one_shared_session_is_unchanged():
    n = Signal(0)
    app = create_app(
        session=Session(Column(children=[Button("inc", on_click=lambda: n.set(n.value + 1))]))
    )
    async with _client(app) as client:
        resp = await client.post("/api/event", json=_click("any-id"))
    assert resp.status_code == 200 and n.value == 1


@pytest.mark.integration
async def test_an_upload_for_an_unknown_session_is_409_too():
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        resp = await client.post(
            "/api/upload",
            data={"sid": "never-seen", "component": "n1"},
            files={"file": ("a.txt", b"hi", "text/plain")},
        )
    assert resp.status_code == 409
    assert resp.json()["error"] == "unknown_session"
    assert app.state.store.get("never-seen") is None


@pytest.mark.integration
async def test_the_error_body_is_small_and_json():
    app = create_app(session_factory=_factory)
    async with _client(app) as client:
        resp = await client.post("/api/event", json=_click("never-seen"))
    assert resp.headers["content-type"].startswith("application/json")
    assert len(resp.content) < 100


# -- secure mode: the refusals before the unknown check do not move -------------------


def _secure():
    app = create_app(session_factory=lambda ctx: _factory(), secure=True, secret=SECRET)
    return app, FakeIdp(app)


async def _token(client, user):
    resp = await client.post("/api/session", json={}, headers={"X-User": user})
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.mark.integration
async def test_secure_unauthenticated_and_forged_and_foreign_ids_keep_their_status():
    app, wrapped = _secure()
    async with _client(wrapped) as client:
        alice = await _token(client, "alice")
        anon = await client.post("/api/event", json=_click(alice))
        forged = await client.post(
            "/api/event", json=_click("forged.value"), headers={"X-User": "alice"}
        )
        foreign = await client.post("/api/event", json=_click(alice), headers={"X-User": "bob"})
    assert anon.status_code == 401
    assert forged.status_code == 403
    assert foreign.status_code == 403  # not a 409: it must not say whether the id exists


@pytest.mark.integration
async def test_secure_owner_with_a_valid_but_unheld_token_gets_409():
    app, wrapped = _secure()
    async with _client(wrapped) as client:
        alice = await _token(client, "alice")  # signed for alice, but no stream was opened
        resp = await client.post("/api/event", json=_click(alice), headers={"X-User": "alice"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "unknown_session"


@pytest.mark.integration
async def test_secure_owner_with_a_held_session_works():
    app, wrapped = _secure()
    async with _client(wrapped) as client:
        alice = await _token(client, "alice")
        # what opening the stream does: the token's id, owned by alice
        app.state.store.get_or_create(alice.split(".")[0], ConnectionInfo(user=Principal("alice")))
        resp = await client.post("/api/event", json=_click(alice), headers={"X-User": "alice"})
    assert resp.status_code == 200

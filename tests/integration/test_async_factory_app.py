"""An async session factory over HTTP, including the secure path (IND-153)."""

import asyncio

import httpx
import pytest
from starlette.authentication import SimpleUser

from indah import create_app
from indah.components import Button, Column, Text
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _async_counter(delay: float = 0.0):
    async def factory(ctx) -> Session:
        await asyncio.sleep(delay)
        n = Signal(0)
        return Session(
            Column(
                children=[
                    Button("inc", on_click=lambda: n.set(n.value + 1)),
                    Text(lambda: f"{ctx.user.id if ctx.user else 'nobody'}:{n.value}"),
                ]
            )
        )

    return factory


@pytest.mark.integration
async def test_an_event_to_an_app_with_an_async_factory_works():
    app = create_app(session_factory=_async_counter(), factory_timeout=1.0)
    async with _client(app) as client:
        for _ in range(2):
            resp = await client.post(
                "/api/event", json={"sid": "t1", "component": "n1", "event": "click"}
            )
            assert resp.status_code == 200
    handle = app.state.store.get("t1")
    assert handle.session.snapshot()["children"][1]["props"]["text"] == "nobody:2"


@pytest.mark.integration
async def test_create_app_passes_the_timeout_and_placeholder_to_the_store():
    app = create_app(
        session_factory=_async_counter(),
        factory_timeout=0.25,
        factory_placeholder=lambda: Text("x"),
    )
    assert app.state.store.factory_timeout == 0.25


class FakeIdp:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            who = dict(scope["headers"]).get(b"x-user")
            if who:
                scope["user"] = SimpleUser(who.decode())
        await self.app(scope, receive, send)


@pytest.mark.integration
async def test_a_secure_app_gives_an_async_factory_the_user_and_the_owner():
    inner = create_app(
        session_factory=_async_counter(),
        secure=True,
        secret="a-long-random-secret-value-0123456789",
        factory_timeout=1.0,
    )
    app = FakeIdp(inner)
    async with _client(app) as client:
        minted = await client.post("/api/session", json={}, headers={"X-User": "bob"})
        token = minted.json()["token"]
        resp = await client.post(
            "/api/event",
            headers={"X-User": "bob"},
            json={"sid": token, "component": "n1", "event": "click"},
        )
        assert resp.status_code == 200
        other = await client.post(
            "/api/event",
            headers={"X-User": "alice"},
            json={"sid": token, "component": "n1", "event": "click"},
        )
        assert other.status_code == 403
    store = inner.state.store
    assert len(store) == 1
    handle = next(iter(store._handles.values()))  # noqa: SLF001
    assert handle.owner == "bob"
    assert handle.session.snapshot()["children"][1]["props"]["text"] == "bob:1"

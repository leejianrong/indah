"""A revealed secret over HTTP: the tab that asked sees it; a reconnect never does (IND-119)."""

import json

import httpx
import pytest

from indah import create_app
from indah.components import Button, Column, SecretReveal
from indah.protocol import init_message
from indah.reactive import Signal
from indah.session import Session

SECRET = "tok_live_SUPER-SECRET-123"


def _build():
    token: Signal[str | None] = Signal(None)
    return Session(
        Column(
            children=[
                Button("create", on_click=lambda: token.set(SECRET)),
                SecretReveal(token, label="Token"),
            ]
        )
    )


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_the_secret_is_delivered_live_once_and_absent_from_resume_and_snapshot():
    app = create_app(session_factory=_build)
    async with _client(app) as client:
        await client.post("/api/event", json={"sid": "t", "component": "n9", "event": "x"})
        handle = app.state.store.get("t")
        queue = handle.hub.subscribe()
        ok = await client.post("/api/event", json={"sid": "t", "component": "n1", "event": "click"})
        assert ok.status_code == 200
    live = json.dumps([m for _, m in list(queue._queue)])  # noqa: SLF001
    assert SECRET in live  # the open stream got it
    assert SECRET not in json.dumps(handle.hub.history())
    assert SECRET not in json.dumps(handle.hub.replay_since(0) or [])
    assert SECRET not in json.dumps(init_message(handle.session.snapshot()))

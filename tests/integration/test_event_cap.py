"""The /api/event body cap (IND-98): request bodies are bounded, oversize gets 413."""

import httpx
import pytest

from indah.app import create_app
from indah.components import Column, TextArea
from indah.reactive import Signal
from indah.session import Session


def _app(**kw):
    sig = Signal("")
    ta = TextArea(sig)
    return create_app(session=Session(Column(children=[ta])), **kw), sig, ta


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_a_3mb_event_is_rejected_413_by_default():
    app, sig, ta = _app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/event",
            json={"component": ta.id, "event": "input", "payload": {"value": "x" * 3_000_000}},
        )
    assert resp.status_code == 413
    assert sig.value == ""


@pytest.mark.integration
async def test_a_normal_event_still_passes_and_the_cap_is_configurable():
    app, sig, ta = _app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/event",
            json={"component": ta.id, "event": "input", "payload": {"value": "x" * 100_000}},
        )
    assert resp.status_code == 200 and len(sig.value) == 100_000

    app, sig, ta = _app(max_event_bytes=1000)
    async with _client(app) as client:
        resp = await client.post(
            "/api/event",
            json={"component": ta.id, "event": "input", "payload": {"value": "x" * 2000}},
        )
    assert resp.status_code == 413


@pytest.mark.integration
async def test_a_chunked_body_over_the_cap_is_rejected_without_content_length():
    app, sig, ta = _app(max_event_bytes=1000)

    async def body():
        yield b'{"component": "' + ta.id.encode() + b'", "event": "input", "payload": {"value": "'
        yield b"x" * 5000
        yield b'"}}'

    async with _client(app) as client:
        resp = await client.post(
            "/api/event", content=body(), headers={"Content-Type": "application/json"}
        )
    assert resp.status_code == 413

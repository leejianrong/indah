"""Integration tests across the HTTP boundary, in-process via ASGITransport.

No browser, no real TCP: these drive the ASGI app directly, so they belong to the
fast layer that runs in CI. The SSE stream itself is exercised two ways: the
framing generator in tests/unit/test_sse_events.py (deterministic, no HTTP), and
the full HTTP round trip in tests/e2e/test_live_server.py (real server, because
httpx's ASGITransport buffers streaming responses and cannot read an open stream).
"""

import httpx
import pytest

from indah.app import create_app


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_index_serves_the_shell():
    async with _client(create_app()) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "EventSource" in resp.text


@pytest.mark.integration
async def test_health_ok():
    async with _client(create_app()) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
async def test_event_with_bad_schema_is_rejected_422():
    async with _client(create_app()) as client:
        resp = await client.post("/api/event", json={"event": "increment"})  # missing component
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation"


@pytest.mark.integration
async def test_invalid_json_is_rejected_400():
    async with _client(create_app()) as client:
        resp = await client.post(
            "/api/event",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_unknown_event_is_rejected_400():
    async with _client(create_app()) as client:
        resp = await client.post("/api/event", json={"component": "nope", "event": "click"})
    assert resp.status_code == 400


@pytest.mark.integration
async def test_increment_event_updates_server_state():
    app = create_app()
    async with _client(app) as client:
        resp = await client.post("/api/event", json={"component": "counter", "event": "increment"})
    assert resp.status_code == 200
    assert app.state.counter == 1
    assert app.state.nodes["counter"] == "1"

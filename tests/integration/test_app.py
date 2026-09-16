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
from indah.components import Column, Slider, Text
from indah.reactive import Signal, computed
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _slider_app():
    """A small two-node app (slider a -> computed label) independent of the demo."""
    a = Signal(2)
    label = computed(lambda: f"a = {a.value}")
    root = Column(children=[Slider(a, min=0, max=10, step=1, label="a"), Text(label)])
    return create_app(session=Session(root))


@pytest.mark.integration
async def test_index_serves_the_generic_renderer():
    async with _client(create_app()) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "EventSource" in resp.text  # the shell opens the SSE stream
    assert "api/stream" in resp.text  # ...against the protocol endpoints


@pytest.mark.integration
async def test_index_has_no_chrome_by_default():
    async with _client(create_app()) as client:
        resp = await client.get("/")
    assert "<title>indah</title>" in resp.text  # plain tab title
    # The shell's own JS reads window.__INDAH_CHROME__; the injected config is an
    # assignment (`={`), which must be absent when no chrome is configured.
    assert "window.__INDAH_CHROME__={" not in resp.text


@pytest.mark.integration
async def test_index_injects_configured_chrome():
    app = create_app(
        session=Session(Column(children=[Text("hi")])),
        title="Poster generator",
        home_url="../",
        source_url="https://github.com/leejianrong/indah/blob/main/examples/poster.py",
    )
    async with _client(app) as client:
        resp = await client.get("/")
    assert "<title>Poster generator - indah</title>" in resp.text  # distinct tab title
    assert "window.__INDAH_CHROME__={" in resp.text  # config assignment injected
    assert "examples/poster.py" in resp.text  # view-source link reaches the shell
    assert '"homeUrl": "../"' in resp.text  # clickable-logo target


@pytest.mark.integration
async def test_chrome_json_escapes_angle_brackets():
    # A `<` in a URL must not break out of the injected <script>.
    app = create_app(
        session=Session(Column(children=[Text("hi")])),
        source_url="https://example.com/</script><b>x",
    )
    async with _client(app) as client:
        resp = await client.get("/")
    assert "</script><b>x" not in resp.text  # not injected raw
    assert "\\u003c/script>" in resp.text  # angle bracket escaped in the JSON blob


@pytest.mark.integration
async def test_health_ok():
    async with _client(create_app()) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
async def test_event_with_bad_schema_is_rejected_422():
    async with _client(create_app()) as client:
        resp = await client.post("/api/event", json={"event": "input"})  # missing component
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
async def test_unknown_component_is_rejected_400():
    async with _client(create_app()) as client:
        resp = await client.post("/api/event", json={"component": "nope", "event": "input"})
    assert resp.status_code == 400


@pytest.mark.integration
async def test_slider_event_updates_session_state():
    app = _slider_app()
    async with _client(app) as client:
        resp = await client.post(
            "/api/event", json={"component": "n1", "event": "input", "payload": {"value": 9}}
        )
    assert resp.status_code == 200
    # The computed label (n2) tracks slider a (n1).
    root = app.state.session.snapshot()
    label = root["children"][1]
    assert label["props"]["text"] == "a = 9"

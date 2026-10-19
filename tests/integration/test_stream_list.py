"""A ``List`` bound to a ``Stream`` over the app boundary (IND-90, ADR-0026)."""

import asyncio

import httpx
import pytest

from indah.app import _stream, create_app
from indah.components import Button, Column, List
from indah.session import Session
from indah.stream import Stream
from tests.integration.test_streaming import _first_frames, _stream_request


def _app(limit: int = 5):
    holder: dict[str, Stream] = {}

    def factory() -> Session:
        rows = Stream(limit=limit)
        holder["rows"] = rows
        root = Column(
            children=[
                List(rows, item={"tag": "span", "text": "t"}),
                Button("add", on_click=lambda: rows.append({"t": "from-click"})),
                Button("reset", on_click=lambda: rows.set([{"t": "fresh"}])),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory), holder


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _patches(hub):
    return [m for _, m in hub.history() if m["type"] == "patch"]


@pytest.mark.integration
async def test_appends_reach_the_hub_as_one_coalesced_patch_with_a_trim():
    app, holder = _app(limit=5)
    handle = app.state.store.get_or_create("t")
    handle.hub._coalesce = 0.02
    rows = holder["rows"]
    rows.append({"t": "a"})
    rows.append({"t": "b"}, {"t": "c"})
    assert _patches(handle.hub) == []  # held for the window
    await asyncio.sleep(0.08)
    (patch,) = _patches(handle.hub)
    (change,) = patch["changes"]
    assert change["append"] == {"items": [{"t": "a"}, {"t": "b"}, {"t": "c"}]}
    assert change["trim"] == {"items": 5}


@pytest.mark.integration
async def test_init_snapshot_includes_pending_rows_and_they_are_not_sent_twice():
    app, holder = _app()
    handle = app.state.store.get_or_create("t")
    handle.hub._coalesce = 0.02
    holder["rows"].append({"t": "early"})  # pending, not yet on the wire

    resp = await _stream(_stream_request(app, sid="t", last_event_id=None))
    text = await _first_frames(resp)  # the init frame
    assert '"early"' in text

    # Past the coalescing window, no duplicate append may follow the snapshot.
    await asyncio.sleep(0.08)
    assert text.count('"early"') == 1


@pytest.mark.integration
async def test_a_sync_handler_that_appends_returns_a_full_replace_in_its_response():
    app, holder = _app()
    handle = app.state.store.get_or_create("t")
    result = handle.session.dispatch("n2", "click", {})  # the "add" button
    (change,) = result.changes
    assert change["props"]["items"] == [{"t": "from-click"}]
    assert _patches(handle.hub) == []  # nothing queued behind it


@pytest.mark.integration
async def test_set_replaces_in_order_after_held_appends():
    app, holder = _app()
    handle = app.state.store.get_or_create("t")
    handle.hub._coalesce = 10
    rows = holder["rows"]
    rows.append({"t": "old"})
    rows.set([{"t": "fresh"}])
    first, second = _patches(handle.hub)
    assert "append" in first["changes"][0]
    assert second["changes"][0]["props"]["items"] == [{"t": "fresh"}]


@pytest.mark.integration
async def test_discarding_the_session_stops_listening_to_the_stream():
    app, holder = _app()
    store = app.state.store
    store.get_or_create("t")
    rows = holder["rows"]
    assert len(rows._listeners) == 1
    store.discard("t")
    assert rows._listeners == []

"""POST /api/event takes JSON only and never falls through to a shared session (IND-139)."""

import httpx
import pytest

from indah.app import create_app
from indah.components import Button, Column
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _per_tab():
    clicks = []

    def build() -> Session:
        btn = Button("go", on_click=lambda: clicks.append(1))
        return Session(Column(children=[btn]))

    return create_app(session_factory=build), clicks


_GO = "n1"  # ids are assigned in tree order: the Column is n0, its button n1
BODY = f'{{"sid": "tab-1", "component": "{_GO}", "event": "click"}}'


@pytest.mark.raw_events  # asserts what a refused request creates: no tab connects first
@pytest.mark.integration
@pytest.mark.parametrize(
    "ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None]
)
async def test_a_non_json_content_type_is_415_and_creates_no_session(ctype):
    app, clicks = _per_tab()
    headers = {"Content-Type": ctype} if ctype else {}
    async with _client(app) as client:
        resp = await client.post("/api/event", content=BODY, headers=headers)
    assert resp.status_code == 415
    assert clicks == [] and len(app.state.store) == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    "ctype", ["application/json", "application/json; charset=utf-8", "Application/JSON"]
)
async def test_json_content_types_are_accepted(ctype):
    app, clicks = _per_tab()
    async with _client(app) as client:
        resp = await client.post("/api/event", content=BODY, headers={"Content-Type": ctype})
    assert resp.status_code == 200 and clicks == [1]


@pytest.mark.integration
async def test_a_sid_less_event_on_a_per_tab_app_is_400_and_creates_nothing():
    app, clicks = _per_tab()
    async with _client(app) as client:
        resp = await client.post("/api/event", json={"component": _GO, "event": "click"})
    assert resp.status_code == 400
    assert clicks == [] and len(app.state.store) == 0


@pytest.mark.integration
async def test_a_sid_less_event_still_reaches_an_explicitly_shared_session():
    hits = Signal(0)
    btn = Button("go", on_click=lambda: hits.set(hits.value + 1))
    app = create_app(session=Session(Column(children=[btn])))
    async with _client(app) as client:
        resp = await client.post("/api/event", json={"component": "n1", "event": "click"})
    assert btn.id == "n1" and resp.status_code == 200 and hits.value == 1

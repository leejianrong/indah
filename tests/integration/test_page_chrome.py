"""``ctx.title`` and ``ctx.favicon`` (IND-152): the tab's title and icon follow the session."""

import logging

import httpx
import pytest

from indah.app import create_app
from indah.components import Column, Text
from indah.context import Context
from indah.protocol import chrome_message, init_message
from indah.session import Session

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
SVG = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'><circle r='4'/></svg>"


def _chromes(hub):
    return [m for _, m in hub.history() if m["type"] == "chrome"]


def _store(favicons=None):
    holder: dict = {}

    def build(ctx: Context) -> Session:
        holder["ctx"] = ctx
        return Session(Column(children=[Text("x")]))

    app = create_app(session_factory=build, favicons=favicons or {})
    store = app.state.store
    handle = store.get_or_create("tab")
    return app, handle, holder["ctx"]


@pytest.mark.unit
def test_chrome_message_shape_and_init_only_carries_it_when_set():
    assert chrome_message("(2) app", "api/brand/favicon/alert") == {
        "v": 1,
        "type": "chrome",
        "title": "(2) app",
        "favicon": "api/brand/favicon/alert",
    }
    assert "chrome" not in init_message({"id": "n0"})
    assert (
        init_message({"id": "n0"}, chrome={"title": "t", "favicon": None})["chrome"]["title"] == "t"
    )


@pytest.mark.unit
def test_setting_title_or_favicon_without_a_hub_does_not_raise():
    ctx = Context("s")
    ctx.title.set("anything")
    ctx.favicon.set("nope")
    assert ctx._chrome() == {"title": "anything", "favicon": None}


@pytest.mark.integration
def test_a_new_session_has_default_chrome_and_sends_nothing():
    _, handle, ctx = _store()
    assert ctx.title.value is None and ctx.favicon.value is None
    assert ctx._chrome() is None
    assert _chromes(handle.hub) == []


@pytest.mark.integration
def test_title_updates_reach_this_session_only_and_repeats_are_not_resent():
    app = create_app(session_factory=lambda ctx: Session(Column(children=[Text("x")])))
    store = app.state.store
    a, b = store.get_or_create("a"), store.get_or_create("b")
    a.session.ctx.title.set("(2) app")
    a.session.ctx.title.set("(2) app")
    assert [m["title"] for m in _chromes(a.hub)] == ["(2) app"]
    assert _chromes(b.hub) == []
    a.session.ctx.title.set(None)  # back to the app's own title
    assert _chromes(a.hub)[-1] == chrome_message(None, None)


@pytest.mark.integration
def test_a_registered_favicon_can_be_switched_and_cleared():
    _, handle, ctx = _store({"alert": PNG, "ok": SVG})
    ctx.favicon.set("alert")
    ctx.favicon.set("ok")
    ctx.favicon.set(None)
    assert [m["favicon"] for m in _chromes(handle.hub)] == [
        "api/brand/favicon/alert",
        "api/brand/favicon/ok",
        None,
    ]


@pytest.mark.integration
def test_an_unregistered_favicon_name_is_ignored_with_a_warning(caplog):
    _, handle, ctx = _store({"alert": PNG})
    with caplog.at_level(logging.WARNING, logger="indah"):
        ctx.favicon.set("missing")
    assert _chromes(handle.hub) == []
    assert "missing" in caplog.text
    assert ctx._chrome() is None  # nothing a fresh init could carry either


@pytest.mark.integration
def test_a_fresh_init_carries_the_current_chrome_and_a_closed_session_stops_publishing():
    _, handle, ctx = _store({"alert": PNG})
    ctx.title.set("(1) app")
    ctx.favicon.set("alert")
    assert ctx._chrome() == {"title": "(1) app", "favicon": "api/brand/favicon/alert"}
    sent = len(_chromes(handle.hub))
    ctx.close()
    ctx.title.set("late")
    assert len(_chromes(handle.hub)) == sent


@pytest.mark.integration
def test_the_title_is_capped_and_made_a_string():
    _, handle, ctx = _store()
    ctx.title.set("x" * 500)
    assert len(_chromes(handle.hub)[-1]["title"]) == 200


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_favicons_are_served_sandboxed_and_unknown_names_404():
    app, _, _ = _store({"alert": PNG, "ok": SVG})
    async with _client(app) as c:
        png = await c.get("/api/brand/favicon/alert")
        svg = await c.get("/api/brand/favicon/ok")
        missing = await c.get("/api/brand/favicon/nope")
        evil = await c.get("/api/brand/favicon/..%2Fsecret")
        upper = await c.get("/api/brand/favicon/Alert")
    assert (
        png.status_code == 200 and png.content == PNG and png.headers["content-type"] == "image/png"
    )
    assert svg.headers["content-type"] == "image/svg+xml"
    assert svg.headers["content-security-policy"] == "sandbox"
    assert svg.headers["x-content-type-options"] == "nosniff"
    assert missing.status_code == 404 and evil.status_code == 404 and upper.status_code == 404


@pytest.mark.integration
async def test_no_favicons_means_no_route_and_an_untouched_page():
    app = create_app(session_factory=lambda: Session(Column(children=[Text("x")])))
    async with _client(app) as c:
        assert (await c.get("/api/brand/favicon/alert")).status_code == 404
        assert "window.__INDAH_CHROME__=" not in (await c.get("/")).text  # no chrome blob either


@pytest.mark.unit
@pytest.mark.parametrize(
    "favicons",
    [
        {"Bad Name": PNG},  # names are lower-case words
        {"a/b": PNG},
        {"x": b"not an image"},
        {"big": PNG + b"\x00" * (70 * 1024)},
        {f"f{i}": PNG for i in range(17)},  # a small bounded set
    ],
)
def test_bad_favicons_fail_at_app_creation(favicons):
    with pytest.raises(ValueError):
        create_app(session_factory=lambda: Session(Column(children=[Text("x")])), favicons=favicons)


@pytest.mark.unit
def test_an_ico_favicon_is_accepted():
    ico = b"\x00\x00\x01\x00" + b"\x00" * 16
    app = create_app(
        session_factory=lambda: Session(Column(children=[Text("x")])), favicons={"ico": ico}
    )
    assert app.state.favicons["ico"][1] == "image/x-icon"

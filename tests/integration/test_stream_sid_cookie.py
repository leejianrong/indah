"""The stream's session id travels in a per-tab cookie, not the URL (IND-238, ADR-0002).

``?sid=`` put the (signed) session id in every access log, proxy log and browser history. The
shell now sets ``indah_sid_<k>=<sid>`` for its own tab key ``k`` and opens ``/api/stream?k=<k>``.
``?sid=`` still works for one release, except on an app that set ``limits`` or
``security_headers``, where it is refused unless ``allow_sid_in_url=True``.
"""

import json

import httpx
import pytest
from starlette.authentication import SimpleUser
from starlette.requests import Request

from indah import Limits, create_app
from indah.app import _stream
from indah.components import Column, Text
from indah.session import Session

TAB = "tabkey0123456789"
SECRET = "a-long-random-secret-value-0123456789"


def _factory(ctx):
    return Session(Column(children=[Text(f"user:{ctx.user.id if ctx.user else 'nobody'}")]))


def _request(app, *, query="", cookies=None, user=None):
    headers = []
    if cookies:
        value = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", value.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": query.encode(),
        "headers": headers,
        "app": app,
    }
    if user:
        scope["user"] = SimpleUser(user)
    return Request(scope)


async def _open(app, **kw):
    """Open the stream; return (status, store ids it made) after the first SSE chunk."""
    resp = await _stream(_request(app, **kw))
    if resp.status_code != 200:
        return resp.status_code, json.loads(resp.body)
    async for _ in resp.body_iterator:
        break
    await resp.body_iterator.aclose()
    return 200, None


@pytest.mark.integration
async def test_the_session_id_comes_from_the_tabs_cookie():
    app = create_app(session_factory=_factory)
    status, _ = await _open(app, query=f"k={TAB}&path=/", cookies={f"indah_sid_{TAB}": "tab-a"})
    assert status == 200
    assert app.state.store.get("tab-a") is not None
    assert app.state.store.get("default") is None


@pytest.mark.integration
async def test_two_tabs_with_two_keys_get_two_sessions_though_both_cookies_are_sent():
    app = create_app(session_factory=_factory)
    cookies = {"indah_sid_tabAAAAAAAA": "sid-a", "indah_sid_tabBBBBBBBB": "sid-b"}
    await _open(app, query="k=tabAAAAAAAA", cookies=cookies)
    await _open(app, query="k=tabBBBBBBBB", cookies=cookies)
    assert app.state.store.get("sid-a") is not None
    assert app.state.store.get("sid-b") is not None


@pytest.mark.integration
async def test_the_cookie_wins_over_a_sid_in_the_url():
    app = create_app(session_factory=_factory)
    await _open(app, query=f"k={TAB}&sid=from-url", cookies={f"indah_sid_{TAB}": "from-cookie"})
    assert app.state.store.get("from-cookie") is not None
    assert app.state.store.get("from-url") is None


@pytest.mark.integration
async def test_a_tab_whose_cookie_lapsed_never_falls_back_to_the_default_session():
    app = create_app(session_factory=_factory)
    status, body = await _open(app, query=f"k={TAB}&path=/")
    assert status == 400 and "cookie" in body["error"]
    assert app.state.store.get("default") is None


@pytest.mark.integration
async def test_a_sid_in_the_url_still_works_on_a_plain_app():
    app = create_app(session_factory=_factory)
    status, _ = await _open(app, query="sid=legacy-tab")
    assert status == 200 and app.state.store.get("legacy-tab") is not None


@pytest.mark.integration
@pytest.mark.parametrize("kw", [{"limits": Limits()}, {"security_headers": True}])
async def test_a_hardened_app_refuses_a_sid_in_the_url(kw):
    app = create_app(session_factory=_factory, **kw)
    status, body = await _open(app, query="sid=legacy-tab")
    assert status == 400 and "url" in body["error"]
    assert app.state.store.get("legacy-tab") is None
    # the cookie path is unaffected
    status, _ = await _open(app, query=f"k={TAB}", cookies={f"indah_sid_{TAB}": "tab-c"})
    assert status == 200 and app.state.store.get("tab-c") is not None


@pytest.mark.integration
async def test_allow_sid_in_url_can_be_set_either_way():
    on = create_app(session_factory=_factory, limits=Limits(), allow_sid_in_url=True)
    assert (await _open(on, query="sid=legacy-tab"))[0] == 200
    off = create_app(session_factory=_factory, allow_sid_in_url=False)
    assert (await _open(off, query="sid=legacy-tab"))[0] == 400


@pytest.mark.integration
@pytest.mark.parametrize("key", ["x", "has space", "a;b=c", "k" * 200, "../../etc"])
async def test_a_malformed_tab_key_is_ignored(key):
    app = create_app(session_factory=_factory)
    await _open(app, query=f"k={key}&sid=url-id", cookies={"indah_sid_x": "evil"})
    assert app.state.store.get("evil") is None
    assert app.state.store.get("url-id") is not None


async def _login(asgi, user):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=asgi), base_url="http://test"
    ) as client:
        resp = await client.post("/api/session", json={}, headers={"X-User": user})
        return resp.json()["token"]


class _Idp:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        who = dict(scope["headers"]).get(b"x-user") if scope["type"] == "http" else None
        if who:
            scope["user"] = SimpleUser(who.decode())
        await self.app(scope, receive, send)


@pytest.mark.integration
async def test_a_secure_app_takes_the_signed_token_from_the_cookie_and_refuses_another_person():
    app = create_app(session_factory=_factory, secure=True, secret=SECRET)
    alice = await _login(_Idp(app), "alice")
    cookie = {f"indah_sid_{TAB}": alice}
    assert (await _open(app, query=f"k={TAB}", cookies=cookie, user="alice"))[0] == 200
    assert app.state.store.get(alice.split(".")[0]).owner == "alice"
    # the same cookie replayed by someone else is refused and creates nothing
    other = create_app(session_factory=_factory, secure=True, secret=SECRET)
    status, _ = await _open(other, query=f"k={TAB}", cookies=cookie, user="mallory")
    assert status == 403 and other.state.store.get(alice.split(".")[0]) is None
    # and with no cookie and no sid, a secure app still answers 401
    assert (await _open(app, query=f"k={TAB}", user="alice"))[0] == 401

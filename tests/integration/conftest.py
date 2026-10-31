"""A test's "tab" connects before it clicks, as the shell does (IND-199).

An event or an upload for a session this process does not hold is ``409 unknown_session``: the
stream is what makes a session. Browsers always open the stream first, but an in-process test
that posts an event straight to ``/api/event`` would now be refused. So, unless a test is marked
``raw_events``, a ``post`` to ``/api/event`` or ``/api/upload`` first opens the stream for that
``sid`` (a short ``GET /api/stream`` with the same headers and the id in the tab cookie, which is
what builds the session, its owner and ``ctx.conn`` exactly as a real connection would), and only
when the process does not hold the session yet. The stream is cancelled right away; the session
stays, as it does after a real tab disconnects.

Mark a test ``raw_events`` to see the bare behaviour (see ``test_unknown_session.py``).
"""

import asyncio
import json
import re

import httpx
import pytest

_EVENT_SUFFIXES = ("/api/event", "/api/upload")  # also under a mount prefix, like /ui/api/event
_COOKIE_SAFE = re.compile(r"[A-Za-z0-9._~-]{1,200}")


def _app_of(client: httpx.AsyncClient):
    """The app that holds the sessions: the one behind an in-process client (through any
    wrapping middleware), or the first mounted app that has a store of its own."""
    app = getattr(client._transport, "app", None)  # noqa: SLF001
    while app is not None and not hasattr(app, "state"):
        app = getattr(app, "app", None)
    if app is None or hasattr(app.state, "store"):
        return app
    for value in list(getattr(app.state, "_state", {}).values()):
        if hasattr(getattr(value, "state", None), "store"):
            return value
    return app


def _sid_of(kwargs: dict) -> str | None:
    body = kwargs.get("json")
    if body is None and kwargs.get("content"):
        try:
            body = json.loads(kwargs["content"])
        except (ValueError, TypeError):
            body = None
    if body is None:
        body = kwargs.get("data")
    sid = body.get("sid") if isinstance(body, dict) else None
    return sid if isinstance(sid, str) and sid else None


@pytest.fixture(autouse=True)
def the_tab_connects_first(request, monkeypatch):
    if request.node.get_closest_marker("raw_events"):
        return
    real_post = httpx.AsyncClient.post

    async def post(self, url, *args, **kwargs):
        path = str(url)
        suffix = next((x for x in _EVENT_SUFFIXES if path.endswith(x)), None)
        if suffix:
            sid = _sid_of(kwargs)
            app = _app_of(self)
            store = getattr(getattr(app, "state", None), "store", None)
            if sid:
                # With no store to ask (a mounted app we cannot reach), just connect.
                real_sid = sid.split(".")[0] if getattr(app.state, "secure", False) else sid
                if store is None or store.get(real_sid) is None:
                    stream = path[: -len(suffix)] + "/api/stream"
                    headers = dict(kwargs.get("headers") or {})
                    params = {"sid": sid}
                    if _COOKIE_SAFE.fullmatch(sid):
                        # as the shell does (IND-238): the id rides in the tab's cookie, so a
                        # hardened app, which refuses ``?sid=``, still builds the session
                        params = {"k": "testtab0123456789"}
                        headers["Cookie"] = f"indah_sid_testtab0123456789={sid}"
                    try:
                        await asyncio.wait_for(
                            self.get(stream, params=params, headers=headers or None), 0.3
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        pass  # the stream is open: the session is held
        return await real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

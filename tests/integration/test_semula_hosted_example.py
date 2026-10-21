"""The two-user hosted demo (examples/semula_hosted.py): login, isolation and the audit rows.

Drives the parent app and the secure dashboard over HTTP. The real browser run (two profiles,
reload, sign-out) is the e2e test.
"""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_hosted.py"
spec = importlib.util.spec_from_file_location("semula_hosted_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _token(c, user, resume=None):
    r = await c.post("/ui/api/session", json={"resume": resume}, headers={"X-User": user})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.mark.integration
async def test_login_sets_a_cookie_and_anonymous_visitors_are_sent_to_it():
    async with _client(ex.build_app()) as c:
        anon = await c.get("/ui/")
        assert anon.status_code == 302 and anon.headers["location"] == "../login"
        page = await c.get("/login")
        assert page.status_code == 200 and "alice" in page.text and "bob" in page.text
        ok = await c.get("/login?user=alice")
        assert ok.status_code == 302 and "demo_user=alice" in ok.headers["set-cookie"]
        assert "httponly" in ok.headers["set-cookie"].lower()
        assert (await c.get("/ui/")).status_code == 200  # the cookie is now sent back
        unknown = await c.get("/login?user=mallory")
        assert "set-cookie" not in unknown.headers  # not a user: just the picker again


@pytest.mark.integration
async def test_each_user_gets_a_session_of_their_own_and_cannot_use_the_others():
    app = ex.build_app()
    async with _client(app) as c:
        a, b = await _token(c, "alice"), await _token(c, "bob")
        click = {"component": "n6", "event": "click"}
        ok = await c.post("/ui/api/event", json={"sid": a, **click}, headers={"X-User": "alice"})
        assert ok.status_code == 200
        stolen = await c.post("/ui/api/event", json={"sid": a, **click}, headers={"X-User": "bob"})
        assert stolen.status_code == 403
        anon = await c.post("/ui/api/event", json={"sid": a, **click})
        assert anon.status_code == 401
        assert b != a


@pytest.mark.integration
async def test_audit_rows_land_on_the_actors_own_topic_with_keys_only():
    app = ex.build_app()
    async with _client(app) as c:
        a = await _token(c, "alice")
        await c.post(
            "/ui/api/event",
            json={"sid": a, "component": "n6", "event": "click"},
            headers={"X-User": "alice"},
        )
        await c.post(
            "/ui/api/event",
            json={
                "sid": a,
                "component": "n8",
                "event": "input",
                "payload": {"value": "my secret note"},
            },
            headers={"X-User": "alice"},
        )
        await _token(c, "bob")
    rows = app.state.topics["alice"].recent()
    assert [(r["event"], r["keys"]) for r in rows] == [("click", "none"), ("input", "value")]
    assert "secret" not in repr(rows) and "bob" not in app.state.topics


@pytest.mark.integration
async def test_signing_out_revokes_the_fake_login_until_the_next_sign_in():
    app = ex.build_app()
    async with _client(app) as c:
        a = await _token(c, "alice")
        # the sign-out button is the second button on the first card
        out = await c.post(
            "/ui/api/event",
            json={"sid": a, "component": "n4", "event": "click"},
            headers={"X-User": "alice"},
        )
        assert out.status_code == 200 and "alice" in app.state.revoked
        assert (
            await c.post("/ui/api/session", json={}, headers={"X-User": "alice"})
        ).status_code == 401
        await c.get("/login?user=alice")
        assert "alice" not in app.state.revoked
        assert (
            await c.post("/ui/api/session", json={}, headers={"X-User": "alice"})
        ).status_code == 200

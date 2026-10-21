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


def _find(node, **want):
    """The first node in a snapshot whose type and props match ``want`` (props by name)."""
    props = node.get("props", {})
    if all(node.get(k, props.get(k)) == v for k, v in want.items()):
        return node
    for child in node.get("children", []):
        found = _find(child, **want)
        if found:
            return found
    return None


def _all(node, type_):
    found = [node] if node.get("type") == type_ else []
    for child in node.get("children", []):
        found += _all(child, type_)
    return found


async def _open(app, c, user):
    token = await _token(c, user)
    # touch the session so it exists (an unknown component is a 400 and creates it)
    await c.post(
        "/ui/api/event",
        json={"sid": token, "component": "none", "event": "x"},
        headers={"X-User": user},
    )
    session = app.state.ui.app.state.store.get(token.split(".")[0]).session
    return token, session


async def _click(c, user, token, node_id, event="click", payload=None):
    return await c.post(
        "/ui/api/event",
        json={"sid": token, "component": node_id, "event": event, "payload": payload or {}},
        headers={"X-User": user},
    )


@pytest.mark.integration
async def test_each_role_gets_only_the_ui_it_may_use():
    app = ex.build_app()
    async with _client(app) as c:
        trees = {}
        for user in ("bob", "alice", "carol"):
            _, session = await _open(app, c, user)
            trees[user] = session.snapshot()
    add = {u: _find(t, type="button", label="Add entry") for u, t in trees.items()}
    tokens = {u: _find(t, type="secretreveal") for u, t in trees.items()}
    assert add["bob"] is None and add["alice"] and add["carol"]  # viewer: no editing at all
    assert tokens["bob"] is None and tokens["alice"] is None and tokens["carol"]  # admin only
    assert "API tokens" not in str(trees["bob"]) and "API tokens" not in str(trees["alice"])


@pytest.mark.integration
async def test_admin_creates_a_token_it_is_shown_once_listed_and_revoked_with_a_hash_only_store():
    app = ex.build_app()
    async with _client(app) as c:
        token, session = await _open(app, c, "carol")
        hub = app.state.ui.app.state.store.get(token.split(".")[0]).hub
        queue = hub.subscribe()
        name = _find(session.snapshot(), type="textinput", label="Name")
        create = _find(session.snapshot(), type="button", label="Create token")
        await _click(c, "carol", token, name["id"], "input", {"value": "ci"})
        ok = await _click(c, "carol", token, create["id"])
        assert ok.status_code == 200
        (row,) = app.state.tokens.snapshot()
        assert row["name"] == "ci" and row["owner"] == "carol" and row["status"] == "active"
        reveal = session.find(_find(session.snapshot(), type="secretreveal")["id"])
        secret = reveal._value.value  # noqa: SLF001
        assert secret.startswith("ind_") and secret[4:12] == row["id"]
        # delivered live to the creating tab, kept out of the snapshot and the replay history
        live = str([m for _, m in list(queue._queue)])  # noqa: SLF001
        assert secret in live
        assert secret not in str(session.snapshot()) and secret not in str(hub.history())
        assert secret not in str(app.state.tokens.rows) and secret not in str(
            app.state.tokens.digests
        )
        # revoke it from the table's row action
        (table,) = [t for t in _all(session.snapshot(), "table") if t["props"].get("actions")]
        revoke_id = table["props"]["actions"][0]["id"]
        gone = await c.post(
            "/ui/api/event",
            json={
                "sid": token,
                "component": table["id"],
                "event": "action",
                "payload": {"action": revoke_id, "key": row["id"]},
            },
            headers={"X-User": "carol"},
        )
        assert gone.status_code == 200
        assert app.state.tokens.rows[row["id"]]["status"] == "revoked"


@pytest.mark.integration
async def test_a_role_revoked_mid_session_cannot_create_a_token_any_more():
    app = ex.build_app()
    async with _client(app) as c:
        token, session = await _open(app, c, "carol")
        create = _find(session.snapshot(), type="button", label="Create token")
        original = ex.USERS["carol"]
        ex.USERS["carol"] = (original[0], frozenset({"viewer"}))  # the admin was demoted
        try:
            resp = await _click(c, "carol", token, create["id"])
        finally:
            ex.USERS["carol"] = original
    assert resp.status_code == 403 and app.state.tokens.snapshot() == []


@pytest.mark.integration
async def test_an_editor_adds_an_entry_and_a_viewer_who_forges_the_click_is_refused():
    app = ex.build_app()
    async with _client(app) as c:
        a_token, a_session = await _open(app, c, "alice")
        add = _find(a_session.snapshot(), type="button", label="Add entry")
        assert (await _click(c, "alice", a_token, add["id"])).status_code == 200
        assert "1 entries" in str(a_session.snapshot())
        b_token, b_session = await _open(app, c, "bob")
        # bob's tree has no such button, but he can still POST its id: the guard stops it
        assert (await _click(c, "bob", b_token, add["id"])).status_code == 400  # not in his tree

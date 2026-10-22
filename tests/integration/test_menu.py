"""Menu over HTTP (IND-161): a restricted item is omitted for who may not see it (a forged
select of it is a no-op), and ``guard()`` refuses a visible but guarded item at click time."""

import pytest

from indah.components import Column, Menu, MenuItem
from indah.context import Context
from indah.session import Session


@pytest.mark.integration
async def test_restricted_items_are_omitted_and_guard_refuses_a_forged_select():
    import httpx

    from indah import Policy, Principal, create_app, guard

    ran: list[str] = []
    secret = "a-long-random-secret-value-0123456789"
    roles = {"alice": {"admin"}, "vera": {"viewer"}}

    def who(request):
        user = request.headers.get("x-user")
        return Principal(id=user, roles=frozenset(roles[user])) if user else None

    def build(ctx: Context) -> Session:
        remove = guard("entries:write")(lambda: ran.append(ctx.user.id))
        items = [
            MenuItem("Open", lambda: ran.append(f"open:{ctx.user.id}")),
            *ctx.only("entries:write", lambda: MenuItem("Remove", remove, danger=True)),
            MenuItem("Purge", remove, danger=True),  # shown to all, refused by guard() at click
        ]
        return Session(Column(children=[Menu("Actions", items)]))

    app = create_app(
        session_factory=build,
        auth=who,
        secure=True,
        secret=secret,
        policy=Policy({"viewer": ["entries:read"], "admin": ["*"]}),
    )

    async def select(client, token, user, item):
        return await client.post(
            "/api/event",
            json={"sid": token, "component": "n1", "event": "select", "payload": {"item": item}},
            headers={"X-User": user},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids = {}
        for user in ("alice", "vera"):
            token = (await client.post("/api/session", json={}, headers={"X-User": user})).json()[
                "token"
            ]
            assert (await select(client, token, user, "Open")).status_code == 200
            session = app.state.store.get(token.split(".")[0]).session
            menu = session.root.to_json()["children"][0]
            ids[user] = [i["id"] for i in menu["props"]["items"]]
            forged = await select(client, token, user, "Remove")
            assert forged.status_code == 200  # omitted for vera: nothing to run, nothing leaked
            purge = await select(client, token, user, "Purge")
            assert purge.status_code == (200 if user == "alice" else 403)
    assert ids == {"alice": ["Open", "Remove", "Purge"], "vera": ["Open", "Purge"]}
    # alice: Open, Remove, Purge. vera: Open only (her forged Remove found no item; Purge was 403).
    assert ran == ["open:alice", "alice", "alice", "open:vera"]

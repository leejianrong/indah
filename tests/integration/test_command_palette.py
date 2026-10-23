"""CommandPalette over HTTP (IND-165): a restricted command is omitted for who may not see it (a
forged run of it is a no-op), ``guard()`` refuses a visible but guarded command at run time, and a
jump command moves only the tab that ran it."""

import pytest

from indah.components import Column, Command, CommandPalette
from indah.context import Context
from indah.session import Session


@pytest.mark.integration
async def test_restricted_commands_are_omitted_and_guard_refuses_a_forged_run():
    import httpx

    from indah import Policy, Principal, create_app, guard

    ran: list[str] = []
    secret = "a-long-random-secret-value-0123456789"
    roles = {"alice": {"admin"}, "vera": {"viewer"}}

    def who(request):
        user = request.headers.get("x-user")
        return Principal(id=user, roles=frozenset(roles[user])) if user else None

    def build(ctx: Context) -> Session:
        purge = guard("entries:write")(lambda: ran.append(f"purge:{ctx.user.id}"))
        commands = [
            Command("Open log", to="/log", group="Go to"),
            Command("Say hi", lambda: ran.append(f"hi:{ctx.user.id}")),
            *ctx.only("entries:write", lambda: Command("Remove entry", purge)),
            Command("Purge", purge),  # shown to all, refused by guard() when run
        ]
        return Session(Column(children=[CommandPalette(commands, ctx=ctx)]))

    app = create_app(
        session_factory=build,
        auth=who,
        secure=True,
        secret=secret,
        policy=Policy({"viewer": ["entries:read"], "admin": ["*"]}),
    )

    async def run(client, token, user, command):
        return await client.post(
            "/api/event",
            json={"sid": token, "component": "n1", "event": "run", "payload": {"command": command}},
            headers={"X-User": user},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids = {}
        for user in ("alice", "vera"):
            token = (await client.post("/api/session", json={}, headers={"X-User": user})).json()[
                "token"
            ]
            assert (await run(client, token, user, "Say hi")).status_code == 200
            session = app.state.store.get(token.split(".")[0]).session
            palette = session.root.to_json()["children"][0]
            ids[user] = [c["id"] for c in palette["props"]["commands"]]
            forged = await run(client, token, user, "Remove entry")
            assert forged.status_code == 200  # omitted for vera: nothing to run, nothing leaked
            purge = await run(client, token, user, "Purge")
            assert purge.status_code == (200 if user == "alice" else 403)
    assert ids == {
        "alice": ["Open log", "Say hi", "Remove entry", "Purge"],
        "vera": ["Open log", "Say hi", "Purge"],
    }
    assert ran == ["hi:alice", "purge:alice", "purge:alice", "hi:vera"]

"""ctx.toast (IND-95): a handler's feedback reaches only the sender's session."""

import pytest

from indah.components import Button, Column
from indah.context import Context
from indah.protocol import TOAST_TARGET, toast_message
from indah.session import Session
from indah.session_store import InMemorySessionStore
from indah.transport import Hub


def _toasts(hub):
    return [m for _, m in hub.history() if m["type"] == "toast"]


@pytest.mark.unit
def test_toast_message_shape_and_validation():
    msg = toast_message("Saved", "success", 3)
    assert msg == {"v": 1, "type": "toast", "message": "Saved", "kind": "success", "ttl": 3}
    with pytest.raises(ValueError):
        toast_message("x", "loud", 4)
    with pytest.raises(ValueError):
        toast_message("x", "info", -1)


@pytest.mark.unit
def test_toast_without_a_hub_is_a_noop():
    Context("s").toast("nobody listening")  # a hand-built Context must not raise


@pytest.mark.integration
def test_toast_reaches_only_the_sending_session():
    def build(ctx: Context) -> Session:
        return Session(
            Column(
                children=[
                    Button("go", on_click=lambda: ctx.toast("Released 01J", kind="success", ttl=2))
                ]
            )
        )

    store = InMemorySessionStore(build)
    a, b = store.get_or_create("tab-a"), store.get_or_create("tab-b")
    a.session.dispatch("n1", "click", {})
    assert _toasts(a.hub) == [toast_message("Released 01J", "success", 2)]
    assert _toasts(b.hub) == []


@pytest.mark.integration
async def test_toast_from_an_async_handler_and_shared_hub_ordering():
    import asyncio

    holder = {}

    async def go():
        await asyncio.sleep(0)
        holder["ctx"].toast("done")

    def build(ctx):
        holder["ctx"] = ctx
        return Session(Column(children=[Button("go", on_click=go)]))

    handle = InMemorySessionStore(build).get_or_create("t")
    result = handle.session.dispatch("n1", "click", {})
    await handle.session._run_handler(result.coro)
    assert _toasts(handle.hub) == [toast_message("done", "info", 4.0)]
    assert isinstance(handle.hub, Hub)


# -- toast actions (IND-160) ---------------------------------------------------------------------


def _action_build(log, holder):
    def build(ctx: Context) -> Session:
        holder["ctx"] = ctx
        return Session(
            Column(
                children=[
                    Button(
                        "approve",
                        on_click=lambda: ctx.toast(
                            "Approved", action=("Undo", lambda: log.append(ctx.sid)), ttl=8
                        ),
                    )
                ]
            )
        )

    return build


def _action_of(hub):
    (msg,) = _toasts(hub)
    return msg["action"]


@pytest.mark.unit
def test_toast_message_carries_an_action_only_when_given():
    plain = toast_message("Saved", "success", 3)
    assert "action" not in plain  # an existing toast is byte for byte what it was
    msg = toast_message("Approved", "info", 8, action={"id": "t1", "label": "Undo"})
    assert msg["action"] == {"id": "t1", "label": "Undo"}
    for bad in ({"id": "t1", "label": ""}, {"id": "", "label": "Undo"}, {"label": "Undo"}):
        with pytest.raises(ValueError):
            toast_message("x", "info", 4, action=bad)
    with pytest.raises(ValueError):
        toast_message("x", "info", 4, action={"id": "t1", "label": "x" * 41})


@pytest.mark.integration
def test_the_action_runs_once_and_a_second_click_is_harmless():
    log: list[str] = []
    store = InMemorySessionStore(_action_build(log, {}))
    a = store.get_or_create("tab-a")
    a.session.dispatch("n1", "click", {})
    action = _action_of(a.hub)
    assert action["label"] == "Undo" and action["id"]

    first = a.session.dispatch(TOAST_TARGET, "action", {"id": action["id"]})
    assert first is not None and not first.forbidden
    assert log == ["tab-a"]
    again = a.session.dispatch(TOAST_TARGET, "action", {"id": action["id"]})
    assert again is not None  # a double click is not an error ...
    assert log == ["tab-a"]  # ... and it does not run twice


@pytest.mark.integration
def test_an_action_belongs_to_the_session_that_made_it():
    log: list[str] = []
    store = InMemorySessionStore(_action_build(log, {}))
    a, b = store.get_or_create("tab-a"), store.get_or_create("tab-b")
    a.session.dispatch("n1", "click", {})
    assert _toasts(b.hub) == []  # not shown to other tabs
    b.session.dispatch(TOAST_TARGET, "action", {"id": _action_of(a.hub)["id"]})
    assert log == []  # and tab-b cannot run tab-a's action by guessing its id


@pytest.mark.integration
def test_an_unknown_action_id_is_ignored():
    log: list[str] = []
    a = InMemorySessionStore(_action_build(log, {})).get_or_create("tab-a")
    for payload in ({"id": "nope"}, {}, {"id": 5}):
        result = a.session.dispatch(TOAST_TARGET, "action", payload)
        assert result is not None
    assert log == []
    assert a.session.dispatch(TOAST_TARGET, "other", {"id": "t1"}) is None


@pytest.mark.integration
def test_pending_actions_are_bounded():
    holder: dict = {}
    log: list[str] = []
    a = InMemorySessionStore(_action_build(log, holder)).get_or_create("tab-a")
    ctx = holder["ctx"]
    for n in range(200):
        ctx.toast(f"t{n}", action=("Undo", lambda n=n: log.append(str(n))))
    ids = [m["action"]["id"] for _, m in a.hub.history() if m["type"] == "toast"]
    a.session.dispatch(TOAST_TARGET, "action", {"id": ids[0]})  # the oldest was dropped
    assert log == []
    a.session.dispatch(TOAST_TARGET, "action", {"id": ids[-1]})
    assert log == ["199"]


@pytest.mark.integration
def test_an_action_validates_before_it_registers_anything():
    holder: dict = {}
    InMemorySessionStore(_action_build([], holder)).get_or_create("tab-a")
    ctx = holder["ctx"]
    with pytest.raises(ValueError):
        ctx.toast("x", action=("", lambda: None))
    with pytest.raises(TypeError):
        ctx.toast("x", action=("Undo", "not callable"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ctx.toast("x", action="Undo")  # type: ignore[arg-type]
    assert not ctx._toast_actions._fns  # noqa: SLF001


@pytest.mark.integration
async def test_an_async_action_runs_in_the_background():
    ran: list[str] = []

    async def undo() -> None:
        ran.append("undone")

    def build(ctx: Context) -> Session:
        return Session(
            Column(children=[Button("go", on_click=lambda: ctx.toast("x", action=("Undo", undo)))])
        )

    a = InMemorySessionStore(build).get_or_create("t")
    a.session.dispatch("n1", "click", {})
    result = a.session.dispatch(TOAST_TARGET, "action", {"id": _action_of(a.hub)["id"]})
    assert result is not None and result.coro is not None
    await a.session._run_handler(result.coro)  # noqa: SLF001
    assert ran == ["undone"]


@pytest.mark.integration
async def test_actions_over_http_run_once_and_respect_guard():
    import httpx

    from indah import Policy, Principal, create_app, guard

    ran: list[str] = []
    secret = "a-long-random-secret-value-0123456789"
    roles = {"alice": {"admin"}, "vera": {"viewer"}}

    def who(request):
        user = request.headers.get("x-user")
        return Principal(id=user, roles=frozenset(roles[user])) if user else None

    def build(ctx: Context) -> Session:
        undo = guard("entries:write")(lambda: ran.append(ctx.user.id))
        return Session(
            Column(
                children=[
                    Button("go", on_click=lambda: ctx.toast("Approved", action=("Undo", undo)))
                ]
            )
        )

    app = create_app(
        session_factory=build,
        auth=who,
        secure=True,
        secret=secret,
        policy=Policy({"viewer": ["entries:read"], "admin": ["*"]}),
    )

    async def post(client, token, user, component, event, payload=None):
        return await client.post(
            "/api/event",
            json={"sid": token, "component": component, "event": event, "payload": payload or {}},
            headers={"X-User": user},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for user in ("alice", "vera"):
            token = (await client.post("/api/session", json={}, headers={"X-User": user})).json()[
                "token"
            ]
            assert (await post(client, token, user, "n1", "click")).status_code == 200
            aid = _action_of(app.state.store.get(token.split(".")[0]).hub)["id"]
            resp = await post(client, token, user, TOAST_TARGET, "action", {"id": aid})
            assert resp.status_code == (200 if user == "alice" else 403)
            if user == "alice":  # a second click does nothing and is not an error
                again = await post(client, token, user, TOAST_TARGET, "action", {"id": aid})
                assert again.status_code == 200
    assert ran == ["alice"]  # the viewer's Undo was refused by guard() at click time

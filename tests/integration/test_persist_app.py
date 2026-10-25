"""``ctx.persist`` through ``create_app``: a rebuilt app restores a tab's small state (IND-208)."""

import httpx
import pytest
from starlette.authentication import SimpleUser

from indah import (
    Button,
    Column,
    MemoryStateStore,
    Principal,
    Session,
    Signal,
    SqliteStateStore,
    Text,
    create_app,
)
from indah.context import ConnectionInfo

SECRET = "a-long-random-secret-value-0123456789"


def _factory(ctx):
    tab = Signal("overview")
    clicks = Signal(0)
    ctx.persist("tab", tab)
    ctx.persist("clicks", clicks)
    return Session(
        Column(
            children=[
                Button("more", on_click=lambda: clicks.set(clicks.value + 1)),
                Button("billing", on_click=lambda: tab.set("billing")),
                Text(lambda: f"{tab.value}:{clicks.value}"),
            ]
        )
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _text(handle) -> str:
    def find(node):
        if node["type"] == "text":
            return node["props"]["text"] if "text" in node["props"] else node["props"].get("value")
        for child in node["children"]:
            found = find(child)
            if found is not None:
                return found
        return None

    return find(handle.session.snapshot())


def _ids(handle) -> list[str]:
    out: list[str] = []

    def walk(node):
        if node["type"] == "button":
            out.append(node["id"])
        for child in node["children"]:
            walk(child)

    walk(handle.session.snapshot())
    return out


@pytest.mark.integration
async def test_a_restart_restores_a_tabs_state_from_sqlite(tmp_path):
    path = tmp_path / "state.db"
    first = create_app(session_factory=_factory, state_store=SqliteStateStore(str(path)))
    first.state.persist_delay = 0
    handle = first.state.store.get_or_create("tab-1")
    more, billing = _ids(handle)
    async with _client(first) as client:
        await client.post("/api/event", json={"sid": "tab-1", "component": more, "event": "click"})
        await client.post("/api/event", json={"sid": "tab-1", "component": more, "event": "click"})
        await client.post(
            "/api/event", json={"sid": "tab-1", "component": billing, "event": "click"}
        )
    assert _text(handle) == "billing:2"

    # The process restarts: a new app, a new (empty) session store, the same file.
    second = create_app(session_factory=_factory, state_store=f"sqlite:///{path}")
    rebuilt = second.state.store.get_or_create("tab-1")
    assert _text(rebuilt) == "billing:2"  # already in the first snapshot
    assert _text(second.state.store.get_or_create("tab-2")) == "overview:0"  # a new tab


@pytest.mark.integration
async def test_the_default_store_restores_after_a_session_is_dropped():
    app = create_app(session_factory=_factory)
    assert isinstance(app.state.state_store, MemoryStateStore)
    app.state.persist_delay = 0
    handle = app.state.store.get_or_create("tab-1")
    _, billing = _ids(handle)
    async with _client(app) as client:
        await client.post(
            "/api/event", json={"sid": "tab-1", "component": billing, "event": "click"}
        )
    app.state.store.discard("tab-1")  # an idle session reaped
    assert _text(app.state.store.get_or_create("tab-1")) == "billing:0"


@pytest.mark.integration
def test_the_environment_picks_the_store(monkeypatch, tmp_path):
    monkeypatch.setenv("INDAH_STATE_STORE", f"sqlite:///{tmp_path / 'env.db'}")
    monkeypatch.setenv("INDAH_PERSIST_TTL", "90")
    monkeypatch.setenv("INDAH_PERSIST_MAX_BYTES", "2048")
    app = create_app(session_factory=_factory)
    assert isinstance(app.state.state_store, SqliteStateStore)
    assert app.state.persist_ttl == 90
    assert app.state.persist_max_bytes == 2048
    assert "INDAH_STATE_STORE" in app.state.env_used
    explicit = create_app(session_factory=_factory, state_store=MemoryStateStore())
    assert isinstance(explicit.state.state_store, MemoryStateStore)  # an argument wins


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("INDAH_STATE_STORE", "redis://localhost"),
        ("INDAH_STATE_STORE", "nonsense"),
        ("INDAH_PERSIST_TTL", "soon"),
        ("INDAH_PERSIST_TTL", "0"),
        ("INDAH_PERSIST_MAX_BYTES", "-5"),
        ("INDAH_PERSIST_MAX_BYTES", "1.5"),
    ],
)
def test_a_bad_value_stops_the_app_and_names_the_variable(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        create_app(session_factory=_factory)


class FakeIdp:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            who = dict(scope["headers"]).get(b"x-user")
            if who:
                scope["user"] = SimpleUser(who.decode())
        await self.app(scope, receive, send)


@pytest.mark.integration
async def test_a_secure_session_restores_for_its_owner_and_nobody_else():
    store = MemoryStateStore()
    app = create_app(session_factory=_factory, secure=True, secret=SECRET, state_store=store)
    app.state.persist_delay = 0
    alice, bob = Principal(id="alice"), Principal(id="bob")
    handle = app.state.store.get_or_create("sid-1", ConnectionInfo(user=alice))
    _, billing = _ids(handle)
    handle.session.dispatch(billing, "click", {})
    assert _text(handle) == "billing:0"
    app.state.store.discard("sid-1")

    again = app.state.store.get_or_create("sid-1", ConnectionInfo(user=alice))
    assert _text(again) == "billing:0"
    app.state.store.discard("sid-1")
    stranger = app.state.store.get_or_create("sid-1", ConnectionInfo(user=bob))
    assert _text(stranger) == "overview:0"  # same sid, other principal: nothing
    assert all(":alice:" in k or ":bob:" in k for k in store._data)


@pytest.mark.integration
async def test_over_http_another_users_token_never_reaches_the_state():
    store = MemoryStateStore()
    app = create_app(session_factory=_factory, secure=True, secret=SECRET, state_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=FakeIdp(app)), base_url="http://test"
    ) as client:
        # FakeIdp wraps the app, so the wrapped app's own state is the one to reach.
        token = (await client.post("/api/session", json={}, headers={"x-user": "alice"})).json()[
            "token"
        ]
        stolen = await client.get("/api/stream", params={"sid": token}, headers={"x-user": "bob"})
    assert stolen.status_code == 403
    assert len(store) == 0

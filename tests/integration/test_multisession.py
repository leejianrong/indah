"""Per-session isolation across the HTTP boundary (ADR-0010), in-process.

Drives the ASGI app directly (no browser, no TCP), sending events with different
`sid`s and asserting: two sessions do not see each other's signal writes, and a
handler's patches reach only that session's hub -- never another viewer's stream.
The open SSE stream itself is proven in the browser e2e (KAN-1418); ASGITransport
buffers streaming responses, so here we inspect each session's hub directly.
"""

import httpx
import pytest

from indah.app import build_demo_session, create_app
from indah.components import Button, Column, Text
from indah.reactive import Signal
from indah.session import Session


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _counter_app():
    """A per-viewer counter: n1 is the +1 button, n2 the count label over signal n."""

    def factory() -> Session:
        n = Signal(0)
        root = Column(
            children=[
                Button("inc", on_click=lambda: n.set(n.value + 1)),
                Text(lambda: str(n.value)),
            ]
        )
        return Session(root)

    return create_app(session_factory=factory)


def _count(handle) -> str:
    return handle.session.snapshot()["children"][1]["props"]["text"]


async def _click(client, sid) -> None:
    resp = await client.post("/api/event", json={"sid": sid, "component": "n1", "event": "click"})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_two_sessions_do_not_see_each_others_signal_writes():
    app = _counter_app()
    store = app.state.store
    async with _client(app) as client:
        await _click(client, "tab-a")
        await _click(client, "tab-a")
        await _click(client, "tab-b")

    # Independent signals: A clicked twice, B once.
    assert _count(store.get("tab-a")) == "2"
    assert _count(store.get("tab-b")) == "1"


@pytest.mark.integration
async def test_a_handlers_patches_reach_only_its_own_sessions_hub():
    app = _counter_app()
    store = app.state.store
    async with _client(app) as client:
        await _click(client, "tab-a")
        await _click(client, "tab-a")
        await _click(client, "tab-b")

    hub_a = store.get("tab-a").hub
    hub_b = store.get("tab-b").hub
    assert hub_a is not hub_b

    # Each click publishes exactly one patch to the sender's hub, and nothing to the
    # other's -- so the patch stream is isolated, not merely the state.
    assert hub_a.current_offset == 2
    assert hub_b.current_offset == 1

    # And the payloads on each hub only ever describe that session's own count.
    a_texts = [c["props"]["text"] for _, m in hub_a.history() for c in m["changes"]]
    b_texts = [c["props"]["text"] for _, m in hub_b.history() for c in m["changes"]]
    assert a_texts == ["1", "2"]
    assert b_texts == ["1"]


@pytest.mark.integration
async def test_a_factory_app_has_no_single_shared_session():
    # A per-session app exposes no app.state.session -- there is no one graph to
    # name; callers reach state only through the store, keyed by sid.
    app = _counter_app()
    assert not hasattr(app.state, "session")
    assert not hasattr(app.state, "hub")


@pytest.mark.integration
async def test_an_event_creates_the_senders_session_on_first_sight():
    app = _counter_app()
    async with _client(app) as client:
        await _click(client, "fresh")
    assert app.state.store.get("fresh") is not None
    assert app.state.store.get("never-seen") is None


@pytest.mark.integration
async def test_a_shared_session_app_still_exposes_one_graph():
    # Back-compat: create_app(session=...) keeps the pre-Slice-C single shared
    # session, and every sid drives it.
    n = Signal(0)
    root = Column(
        children=[Button("inc", on_click=lambda: n.set(n.value + 1)), Text(lambda: str(n.value))]
    )
    app = create_app(session=Session(root))
    assert app.state.session is not None
    async with _client(app) as client:
        await _click(client, "tab-a")
        await _click(client, "tab-b")  # a different tab drives the same graph
    assert app.state.session.snapshot()["children"][1]["props"]["text"] == "2"


@pytest.mark.integration
def test_session_and_factory_are_mutually_exclusive():
    with pytest.raises(ValueError, match="at most one"):
        create_app(session=Session(Column()), session_factory=build_demo_session)

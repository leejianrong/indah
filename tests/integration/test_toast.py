"""ctx.toast (IND-95): a handler's feedback reaches only the sender's session."""

import pytest

from indah.components import Button, Column
from indah.context import Context
from indah.protocol import toast_message
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

"""The semula pending-queue example (examples/semula_pending.py): a release in one tab
clears the row, ticks and drawer in every tab, and a stale click is harmless."""

import asyncio
import importlib.util
import random
import sys
from pathlib import Path

import httpx
import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_pending.py"


def _load():
    spec = importlib.util.spec_from_file_location("semula_pending_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


def _find(session, type_, pred=lambda c: True):
    return next(c for c in session._by_id.values() if c.type == type_ and pred(c))


def _toasts(handle):
    return [m["message"] for _, m in handle.hub.history() if m["type"] == "toast"]


def _rows(handle):
    return [r["id"] for r in _find(handle.session, "table").reactive_props()["rows"]()]


def _two_tabs(queue, n=3):
    app = ex.build_pending_app(queue)
    rng = random.Random(3)
    calls = [queue.park(ex.fake_call(rng)).call for _ in range(n)]
    store = app.state.store
    return store.get_or_create("a"), store.get_or_create("b"), [c["id"] for c in calls]


@pytest.mark.integration
async def test_release_in_one_tab_clears_the_row_in_every_tab_and_wakes_the_call():
    queue = ex.PendingQueue()
    a, b, ids = _two_tabs(queue)
    assert _rows(a) == ids and _rows(b) == ids
    parked = queue._items[ids[0]]
    waiter = asyncio.create_task(ex.hold(parked))

    table = _find(a.session, "table")
    a.session.dispatch(table.id, "select", {"key": ids[0]})
    a.session.dispatch(_find(a.session, "shortcuts").id, "press", {"keys": "a"})

    assert _rows(a) == ids[1:] and _rows(b) == ids[1:]  # gone in both tabs
    await asyncio.wait_for(waiter, 1)  # the parked call was released
    assert parked.outcome == "released" and parked.reply == "Approved"
    assert _toasts(a) == [f"Released {ids[0][:8]}"] and _toasts(b) == []


@pytest.mark.integration
async def test_submit_from_the_drawer_sends_the_reply_and_closes_it():
    queue = ex.PendingQueue()
    a, _, ids = _two_tabs(queue)
    s = a.session
    row_action = _find(s, "table")
    s.dispatch(row_action.id, "action", {"action": "a0", "key": ids[1]})  # Review
    drawer = _find(s, "drawer")
    assert drawer.reactive_props()["open"]() is True
    s.dispatch(_find(s, "textarea").id, "input", {"value": "Use the 30-day policy."})
    s.dispatch(_find(s, "button", lambda c: c._label == "Submit").id, "click", {})
    assert queue.resolved[0].reply == "Use the 30-day policy."
    assert drawer.reactive_props()["open"]() is False
    assert ids[1] not in _rows(a)


@pytest.mark.integration
async def test_a_stale_release_warns_instead_of_failing_and_other_tabs_state_settles():
    queue = ex.PendingQueue()
    a, b, ids = _two_tabs(queue)
    s_a, s_b = a.session, b.session
    # Tab B has the first row open in its drawer and ticked when tab A rejects it.
    s_b.dispatch(_find(s_b, "table").id, "action", {"action": "a0", "key": ids[0]})
    s_b.dispatch(_find(s_b, "table").id, "check", {"keys": [ids[0], ids[1]]})
    s_a.dispatch(_find(s_a, "table").id, "action", {"action": "a1", "key": ids[0]})  # Reject
    assert queue.resolved[0].outcome == "rejected"

    drawer_b = _find(s_b, "drawer")
    assert drawer_b.reactive_props()["open"]() is False  # closed under B's feet
    assert _find(s_b, "table").reactive_props()["checked"]() == [ids[1]]
    # B's late click on the gone row is a warning, not an error.
    s_b.dispatch(_find(s_b, "table").id, "action", {"action": "a1", "key": ids[0]})
    assert _toasts(b) == ["Already handled in another tab"]


@pytest.mark.integration
async def test_bulk_approve_releases_every_ticked_row_and_the_badge_counts_down():
    queue = ex.PendingQueue()
    a, b, ids = _two_tabs(queue, n=4)
    s = a.session
    s.dispatch(_find(s, "table").id, "check", {"keys": ids[:3]})
    s.dispatch(_find(s, "button", lambda c: c._label == "Approve checked").id, "click", {})
    assert [p.call["id"] for p in queue.resolved] == ids[:3]
    badge_b = _find(b.session, "badge")
    assert badge_b.reactive_props()["text"]() == "1 waiting"
    assert badge_b.static_props()["tone"] == "warn"


@pytest.mark.integration
async def test_producer_parks_up_to_max_pending_and_parent_app_serves_the_ui():
    queue = ex.PendingQueue()
    task = asyncio.create_task(ex.produce(queue, rate=500, max_pending=5, seed=1))
    await asyncio.sleep(0.2)
    task.cancel()
    assert len(queue) == 5
    app = ex.build_app(seed=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/health")).json()["status"] == "ok"
        assert (await c.get("/ui/")).status_code == 200

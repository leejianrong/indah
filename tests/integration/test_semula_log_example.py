"""The semula live-log example (examples/semula_log.py) stays runnable and within budget.

Checks the fake calls look like semula request-log rows, the parent app mounts the
dashboard at ``/ui`` next to a ``/v1`` route, every session follows one ``Topic`` while
its selection stays its own, and 40 events/s becomes about ten frames a second with the
newest row on the wire inside the coalescing window.
"""

import asyncio
import importlib.util
import random
import sys
import time
from pathlib import Path

import httpx
import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_log.py"


def _load():
    spec = importlib.util.spec_from_file_location("semula_log_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
def test_fake_calls_look_like_request_log_rows():
    rng = random.Random(7)
    calls = [ex.fake_call(rng, now_ms=1_700_000_000_000 + i) for i in range(200)]
    assert {c["tier"] for c in calls} <= set(ex.TIERS)
    for c in calls:
        assert len(c["id"]) == 26 and (c["result"] == "miss") == (c["tier"] == "miss")
        assert 0 <= c["score"] <= 1 and c["latency_ms"] > 0
    assert len({c["id"] for c in calls}) == 200
    assert [c["id"] for c in calls] == sorted(c["id"] for c in calls)  # ULIDs sort by time


@pytest.mark.integration
async def test_parent_app_mounts_the_dashboard_under_ui_and_a_v1_route():
    app = ex.build_app(seed=1)
    async with _client(app) as c:
        health = await c.get("/v1/health")
        ui = await c.get("/ui/")
        deep = await c.get("/ui/projects/auth")  # spa=True: the shell, not a 404
        root = await c.get("/", follow_redirects=False)
    assert health.json()["status"] == "ok"
    assert ui.status_code == 200 and "semula" in ui.text
    assert deep.status_code == 200 and '<base href="../">' in deep.text
    assert root.status_code in (302, 307) and root.headers["location"].endswith("ui/")


@pytest.mark.integration
async def test_every_tab_follows_the_topic_and_selection_stays_per_tab():
    app = ex.build_app(seed=1)
    store = app.state.ui.state.store
    a, b = store.get_or_create("a"), store.get_or_create("b")
    rng = random.Random(3)
    for _ in range(5):
        app.state.topic.publish(ex.fake_call(rng))

    def rows(h):
        return h.session.snapshot()["children"][1]["props"]["rows"]

    assert len(rows(a)) == len(rows(b)) == 5
    first = rows(a)[0]["id"]
    table_id = a.session.snapshot()["children"][1]["id"]
    a.session.dispatch(table_id, "select", {"key": first})

    def detail(h):
        return h.session.snapshot()["children"][2]["children"][0]["props"]["blocks"]

    assert first in str(detail(a)) and first not in str(detail(b))
    assert app.state.topic.subscriber_count == 2


@pytest.mark.integration
async def test_forty_events_a_second_make_about_ten_frames_and_show_up_within_the_window():
    app = ex.build_app(seed=1)
    handle = app.state.ui.state.store.get_or_create("t")
    topic = app.state.topic
    rng = random.Random(5)
    start = handle.hub.current_offset

    async def burst():
        for _ in range(60):  # 60 events at 40/s = 1.5 s
            topic.publish(ex.fake_call(rng))
            await asyncio.sleep(0.025)

    t0 = time.monotonic()
    await burst()
    await asyncio.sleep(0.15)  # let the last window close
    frames = handle.hub.current_offset - start
    seconds = time.monotonic() - t0
    assert frames <= seconds * 10 + 3, f"{frames} frames in {seconds:.2f}s"
    rows = [r for _, m in handle.hub.history() for c in m["changes"] for r in c["append"]["rows"]]
    assert len(rows) == 60

    # A single row is on the wire within the coalescing window plus slack.
    before = handle.hub.current_offset
    topic.publish(ex.fake_call(rng))
    await asyncio.sleep(0.25)
    assert handle.hub.current_offset == before + 1

"""The semula entries browser (examples/semula_entries.py) on 20k SQLite rows: windows are
correct and cheap, the sort is whitelisted, search is injection-safe, and a pin reloads
the table."""

import asyncio
import importlib.util
import sys
import time
from pathlib import Path

import httpx
import pytest

import indah

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "semula_entries.py"


def _load():
    spec = importlib.util.spec_from_file_location("semula_entries_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


@pytest.fixture(scope="module")
def store():
    return ex.EntryStore(20_000, seed=2)


def Q(**kw):
    return indah.TableQuery(**kw)


@pytest.mark.integration
def test_store_holds_20k_entries_and_windows_page_correctly(store):
    assert len(store) == 20_000
    rows, total = store.page("all", Q(limit=50))
    assert total == 20_000 and len(rows) == 50
    assert [r["ts"] for r in rows] == sorted((r["ts"] for r in rows), reverse=True)  # newest first
    nxt, _ = store.page("all", Q(limit=50, offset=50))
    assert {r["id"] for r in rows}.isdisjoint(r["id"] for r in nxt)
    tail, _ = store.page("all", Q(limit=50, offset=19_990))
    assert len(tail) == 10


@pytest.mark.integration
def test_project_search_and_sort_are_server_side(store):
    rows, total = store.page("docs-qa", Q(limit=500))
    assert total < 20_000 and {r["project"] for r in rows} == {"docs-qa"}
    rows, total = store.page("all", Q(search="case 1999", limit=50))
    assert total == 11 and all("case 1999" in r["prompt"] for r in rows)
    rows, _ = store.page("all", Q(sort=("hits", "desc"), limit=20))
    hits = [r["hits"] for r in rows]
    assert hits == sorted(hits, reverse=True) and hits[0] > hits[-1] - 1
    asc, _ = store.page("all", Q(sort=("hits", "asc"), limit=20))
    assert asc[0]["hits"] == 0
    assert {r["pinned"] for r in rows} <= {"", "pinned"} and {r["fuzzy"] for r in rows} <= {
        "",
        "fuzzy",
    }


@pytest.mark.integration
def test_search_text_and_sort_names_cannot_inject_sql(store):
    assert store.page("all", Q(search="x' OR 1=1 --"))[1] == 0
    assert store.page("all", Q(search="100%"))[1] == 0  # % is literal, not a wildcard
    assert store.page("all", Q(search="a_c"))[1] == 0  # _ is literal: "abc" must not match
    # A sort field outside the whitelist is ignored (TableQuery.parse also drops it).
    rows, total = store.page("all", Q(sort=("id; DROP TABLE entries", "asc"), limit=5))
    assert total == 20_000 and len(rows) == 5
    assert len(store) == 20_000


@pytest.mark.integration
def test_a_window_with_search_and_sort_is_within_the_latency_budget(store):
    store.page("all", Q(limit=10))  # warm
    started = time.perf_counter()
    for offset in range(0, 5000, 500):
        store.page("all", Q(search="case", sort=("prompt", "asc"), offset=offset, limit=500))
    per_window = (time.perf_counter() - started) / 10
    assert per_window < 0.25, per_window


def _find(session, type_, pred=lambda c: True):
    return next(c for c in session._by_id.values() if c.type == type_ and pred(c))


@pytest.mark.integration
async def test_selecting_a_row_opens_the_detail_and_pinning_reloads_the_table():
    store = ex.EntryStore(500, seed=3)
    app = ex.build_entries_app(store)
    handle = app.state.store.get_or_create("t")
    s = handle.session
    table = _find(s, "table")
    await table.handle("query", {"seq": 1, "limit": 20, "offset": 0})
    window = table.reactive_props()["window"]()
    assert window["total"] == 500 and len(window["rows"]) == 20
    first = window["rows"][0]
    assert first["pinned"] == ""

    s.dispatch(table.id, "select", {"key": first["id"]})
    md = _find(s, "masterdetail")
    assert md.reactive_props()["open"]() is True  # picking a row opens the detail
    shown = repr(_find(s, "card").children[0].reactive_props()["blocks"]())
    assert first["prompt"] in shown  # the preview shows the picked entry

    pin = _find(s, "button", lambda c: c._label == "Pin / unpin")
    s.dispatch(pin.id, "click", {})
    assert store.get(first["id"])["pinned"] == 1
    for _ in range(100):  # the version bump re-runs the last query on the event loop
        await asyncio.sleep(0.02)
        row = table.reactive_props()["window"]()["rows"][0]
        if row["pinned"] == "pinned":
            break
    assert row["id"] == first["id"] and row["pinned"] == "pinned"
    assert [m["message"] for _, m in handle.hub.history() if m["type"] == "toast"] == ["Pinned"]


@pytest.mark.integration
async def test_parent_app_serves_the_ui_and_health():
    app = ex.build_app(n=100, seed=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/health")).json() == {"status": "ok", "entries": 100}
        assert (await c.get("/ui/")).status_code == 200

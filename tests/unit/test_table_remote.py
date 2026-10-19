"""Table remote mode (IND-101): TableQuery parsing, loader results, stale-drop, clamping."""

import asyncio

import pytest

from indah.components import Col, Table, TableQuery
from indah.reactive import Signal

ROWS = [{"id": f"r{i:03d}", "n": i, "name": f"call {i}"} for i in range(95)]


def _loader(q: TableQuery):
    rows = [r for r in ROWS if q.search.lower() in r["name"]]
    if q.sort:
        field, direction = q.sort
        rows = sorted(rows, key=lambda r: r[field], reverse=direction == "desc")
    return rows[q.offset : q.offset + q.limit], len(rows)


def _table(loader=_loader, **kw):
    return Table(
        columns=[Col("id"), Col("n", sortable=True), Col("name")], key="id", remote=loader, **kw
    )


async def _ask(t, **payload):
    payload.setdefault("seq", 1)
    result = t.handle("query", payload)
    assert asyncio.iscoroutine(result)
    await result
    return t.reactive_props()["window"]()


@pytest.mark.unit
def test_parse_clamps_and_validates():
    q = TableQuery.parse(
        {"search": "x" * 500, "offset": -5, "limit": 100000, "seq": 3, "sort": ["n", "desc"]},
        {"n"},
    )
    assert (len(q.search), q.offset, q.limit, q.seq, q.sort) == (200, 0, 500, 3, ("n", "desc"))
    q = TableQuery.parse({}, set())
    assert q == TableQuery()  # all defaults
    assert TableQuery.parse({"limit": 0}, set()).limit == 1
    assert TableQuery.parse({"sort": ["secret", "asc"]}, {"n"}).sort is None  # unknown column
    assert TableQuery.parse({"sort": ["n", "sideways"]}, {"n"}).sort is None
    assert TableQuery.parse({"filters": {"p": "a", "bad": [1]}}, set()).filters == {"p": "a"}
    for bad in ({"offset": "x"}, {"seq": 1.5}, {"search": 5}, {"sort": "n"}, {"filters": []}):
        with pytest.raises(ValueError):
            TableQuery.parse(bad, {"n"})


@pytest.mark.unit
def test_remote_serialises_and_rejects_conflicting_arguments():
    t = _table(page_size=25)
    props = t.static_props()
    assert props["remote"] is True and props["pageSize"] == 25
    assert t.reactive_props()["window"]() == {"rows": [], "total": 0, "offset": 0, "seq": 0}
    assert "rows" not in t.reactive_props()
    assert _table().static_props()["pageSize"] == 50  # a window size by default
    with pytest.raises(ValueError):
        Table(rows=ROWS, columns=[Col("id")], key="id", remote=_loader)
    with pytest.raises(ValueError):
        Table(columns=[Col("id")], remote=_loader)  # needs key
    with pytest.raises(ValueError):
        _table(follow=True, height="10rem")
    with pytest.raises(ValueError):
        Table([{"a": 1}], remote=_loader)


@pytest.mark.unit
async def test_query_loads_a_window_and_total_sorted_and_searched():
    t = _table()
    w = await _ask(t, offset=0, limit=10)
    assert w["total"] == 95 and [r["id"] for r in w["rows"]] == [f"r{i:03d}" for i in range(10)]
    assert (w["offset"], w["seq"]) == (0, 1)
    w = await _ask(t, offset=10, limit=10, sort=["n", "desc"], seq=2)
    assert [r["n"] for r in w["rows"]] == list(range(84, 74, -1))
    w = await _ask(t, search="call 9", limit=50, seq=3)
    assert w["total"] == 6 and {r["n"] for r in w["rows"]} == {9, 90, 91, 92, 93, 94}


@pytest.mark.unit
async def test_a_superseded_query_is_dropped_even_if_it_finishes_last():
    gate = asyncio.Event()

    async def slow_then_fast(q):
        if q.seq == 1:
            await gate.wait()  # the old query is still in flight...
        return _loader(q)

    t = _table(slow_then_fast)
    old = asyncio.create_task(t.handle("query", {"seq": 1, "search": "call 1"}))
    await asyncio.sleep(0)
    w = await _ask(t, seq=2, search="call 2")
    gate.set()
    await old
    assert t.reactive_props()["window"]() == w and w["seq"] == 2  # ...and its late result lost
    # An older seq arriving after a newer one never even loads.
    seen = []
    t2 = _table(lambda q: (seen.append(q.seq), _loader(q))[1])
    await _ask(t2, seq=5)
    await _ask(t2, seq=4)
    assert seen == [5]


@pytest.mark.unit
async def test_offset_past_total_is_reclamped_to_the_last_window():
    t = _table()
    w = await _ask(t, offset=1000, limit=10)
    assert w["offset"] == 90 and len(w["rows"]) == 5 and w["total"] == 95


@pytest.mark.unit
async def test_sync_loader_runs_off_the_event_loop_thread_and_errors_propagate():
    import threading

    names = []

    def loader(q):
        names.append(threading.current_thread() is threading.main_thread())
        return _loader(q)

    await _ask(_table(loader))
    assert names == [False]

    def boom(q):
        raise RuntimeError("db down")

    t = _table(boom)
    with pytest.raises(RuntimeError, match="db down"):
        await t.handle("query", {"seq": 1})
    assert t.reactive_props()["window"]()["seq"] == 0  # nothing half-applied


@pytest.mark.unit
async def test_query_signal_mirrors_the_latest_query_and_bad_payloads_are_unhandled():
    seen = Signal(None)
    t = _table(query=seen)
    await _ask(t, seq=7, search="call 5")
    assert seen.value.search == "call 5" and seen.value.seq == 7
    assert t.handle("query", {"offset": "x"}) is False
    assert _table().handle("select", {}) is False


@pytest.mark.unit
async def test_reload_on_signals_re_run_the_last_query_keeping_its_seq():
    project = Signal("a")
    calls = []

    def loader(q):
        calls.append((project.value, q.search))
        return _loader(q)

    t = _table(loader, reload_on=[project])
    await _ask(t, seq=3, search="call 1")
    project.set("b")
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(calls) == 2:
            break
    assert calls == [("a", "call 1"), ("b", "call 1")]
    assert t.reactive_props()["window"]()["seq"] == 3  # same query, fresh answer

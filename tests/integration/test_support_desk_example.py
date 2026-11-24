"""The support desk example (examples/support_desk.py): four pages over one ticket list."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

from indah.app import _stream

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "support_desk.py"
if not _EXAMPLE.exists():
    pytest.skip("examples/ not present", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("support_desk_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ex = _load()


async def _open(path="/", sid="a"):
    app = ex.app
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/stream",
        "query_string": f"sid={sid}&path={path}".encode(),
        "headers": [],
        "app": app,
    }
    resp = await _stream(Request(scope))
    async for _frame in resp.body_iterator:
        break
    await resp.body_iterator.aclose()
    return app.state.store.get(sid)


def _find(h, type_, pred=lambda c: True):
    return next(c for c in h.session._by_id.values() if c.type == type_ and pred(c))


def _label(c):
    return c.to_json()["props"].get("label")


def _rows(table):
    return table.reactive_props()["rows"]()


@pytest.mark.integration
def test_tickets_are_stable_and_varied():
    assert ex.make_tickets() == ex.make_tickets()
    ts = ex.make_tickets()
    assert len({t["status"] for t in ts}) == 3 and len({t["assignee"] for t in ts}) > 2


@pytest.mark.integration
async def test_every_page_opens_and_an_unknown_address_is_a_404():
    for path, active in (("/", 0), ("/tickets/T-1003", 1), ("/reports", 2), ("/settings", 3)):
        h = await _open(path, sid=path)
        assert _find(h, "router").reactive_props()["active"]() == active, path
        json.dumps(h.session.snapshot())
    h = await _open("/nowhere", sid="x")
    assert _find(h, "router").reactive_props()["active"]() == 4  # the 404 page


@pytest.mark.integration
async def test_the_inbox_filters_by_status_and_a_row_click_opens_the_ticket():
    h = await _open("/", sid="inbox")
    table = _find(h, "table")
    assert {r["status"] for r in _rows(table)} == {"open"}
    radio = _find(h, "radio")
    h.session.dispatch(radio.id, "change", {"value": "all"})
    assert len(_rows(table)) == len(ex.make_tickets())
    first = _rows(table)[0]["id"]
    h.session.dispatch(table.id, "select", {"key": first})
    assert h.session.ctx.path.value == f"/tickets/{first}"
    assert table._selected.value is None


@pytest.mark.integration
async def test_changing_status_on_the_ticket_page_shows_in_the_inbox_and_the_charts():
    h = await _open("/tickets/T-1001", sid="edit")
    t = next(t for t in ex.make_tickets() if t["id"] == "T-1001")
    other = "resolved" if t["status"] != "resolved" else "open"
    status = _find(h, "select", lambda c: _label(c) == "Status")
    assert status._value.value == t["status"]  # the page starts from the ticket's own value
    h.session.dispatch(status.id, "change", {"value": other})
    bars = _find(h, "chart", lambda c: c.reactive_props()["xCategories"]() == ex.STATUSES)
    by_status = dict(zip(ex.STATUSES, (r[1] for r in bars.reactive_props()["data"]()), strict=True))
    expected = ex.counts(
        [{**x, "status": other} if x["id"] == "T-1001" else x for x in ex.make_tickets()],
        "status",
        ex.STATUSES,
    )
    assert list(by_status.values()) == [n for _, n in expected]
    # and the Inbox table, which is on another page of the same session, sees it too
    table = _find(h, "table")
    ids = {r["id"] for r in _rows(table)}
    assert ("T-1001" in ids) == (other == "open")


@pytest.mark.integration
async def test_a_ticket_page_does_not_write_back_when_you_only_look_at_it():
    h = await _open("/tickets/T-1002", sid="look")
    router = _find(h, "router")
    h.session.dispatch(router.id, "navigate", {"path": "/tickets/T-1003"})
    h.session.dispatch(router.id, "navigate", {"path": "/tickets/T-1002"})
    tickets = [
        (c.type, c.to_json()["props"].get("value"))
        for c in h.session._by_id.values()
        if c.type == "stat"
    ]
    fresh = await _open("/", sid="fresh")
    assert tickets == [
        (c.type, c.to_json()["props"].get("value"))
        for c in fresh.session._by_id.values()
        if c.type == "stat"
    ]


@pytest.mark.integration
async def test_notes_are_added_trimmed_capped_and_empty_ones_ignored():
    h = await _open("/tickets/T-1001", sid="notes")
    box = _find(h, "textinput")
    add = _find(h, "button", lambda c: _label(c) == "Add note")
    notes = _find(h, "list")
    h.session.dispatch(add.id, "click", {})  # nothing typed
    assert notes.reactive_props()["items"]() == []
    h.session.dispatch(box.id, "input", {"value": "  called the customer  "})
    h.session.dispatch(add.id, "click", {})
    assert [n["text"] for n in notes.reactive_props()["items"]()] == ["called the customer"]
    assert box._value.value == ""
    h.session.dispatch(box.id, "input", {"value": "x" * 1000})
    h.session.dispatch(add.id, "click", {})
    assert len(notes.reactive_props()["items"]()[-1]["text"]) == ex.MAX_NOTE


@pytest.mark.integration
async def test_two_visitors_do_not_share_edits():
    a = await _open("/tickets/T-1001", sid="va")
    b = await _open("/tickets/T-1001", sid="vb")
    status_a = _find(a, "select", lambda c: _label(c) == "Status")
    status_b = _find(b, "select", lambda c: _label(c) == "Status")
    original = status_b._value.value
    a.session.dispatch(
        status_a.id, "change", {"value": "pending" if original != "pending" else "open"}
    )
    assert status_b._value.value == original

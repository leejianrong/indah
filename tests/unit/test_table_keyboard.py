"""Table keyboard navigation (IND-164): ``Table(on_open=, keyboard=)``. Additive to ADR-0027."""

import asyncio

import pytest

from indah.components import Col, Column, Table
from indah.session import Session
from indah.transport import Hub

ROWS = [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
COLS = [Col("id"), Col("n")]


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]["props"]


def _table(**kw) -> Table:
    return Table(rows=ROWS, columns=COLS, key="id", **kw)


@pytest.mark.unit
def test_a_default_table_wires_no_keyboard_props():
    props = _wire(_table())
    assert "keyboard" not in props and "openable" not in props


@pytest.mark.unit
def test_on_open_turns_the_keyboard_on_and_marks_the_table_openable():
    props = _wire(_table(on_open=lambda key: None))
    assert props["keyboard"] is True and props["openable"] is True


@pytest.mark.unit
def test_keyboard_alone_does_not_claim_an_open_handler():
    props = _wire(_table(keyboard=True))
    assert props["keyboard"] is True and "openable" not in props


@pytest.mark.unit
def test_the_classic_form_refuses_keyboard_and_on_open():
    with pytest.raises(ValueError, match="rows="):
        Table([{"a": 1}], keyboard=True)
    with pytest.raises(ValueError, match="rows="):
        Table([{"a": 1}], on_open=lambda k: None)


@pytest.mark.unit
def test_an_open_event_calls_the_handler_with_the_row_key():
    got = []
    table = _table(on_open=got.append)
    assert table.handle("open", {"key": "b"}) is True
    assert got == ["b"]


@pytest.mark.unit
def test_an_async_handler_is_returned_to_be_awaited():
    got = []

    async def on_open(key):
        got.append(key)

    result = _table(on_open=on_open).handle("open", {"key": "a"})
    assert asyncio.iscoroutine(result)
    asyncio.run(result)
    assert got == ["a"]


@pytest.mark.unit
def test_open_without_a_key_or_a_handler_is_ignored():
    got = []
    assert _table(on_open=got.append).handle("open", {}) is False
    assert _table().handle("open", {"key": "a"}) is False
    assert got == []


@pytest.mark.unit
def test_a_remote_table_takes_on_open():
    table = Table(columns=COLS, key="id", remote=lambda q: ([], 0), on_open=lambda k: None)
    assert _wire(table)["openable"] is True

"""Rich table cells and text truncation (IND-148): ``Col(kind="cell", render=...)``,
``truncate=`` / ``max_width=`` / ``wrap=`` and ``sort_key=``. All additive to ADR-0027."""

import asyncio

import pytest

from indah.components import Col, Column, Table
from indah.session import Session
from indah.stream import Stream
from indah.transport import Hub

RAIL = {
    "tag": "div",
    "class": "tier-rail",
    "children": [
        {"tag": "span", "text": "tier"},
        {"tag": "span", "literal": "of 5"},
    ],
}


def _wire(component) -> dict:
    session = Session(Column(children=[component]))
    session.bind_hub(Hub(coalesce_seconds=0))
    return session.root.to_json()["children"][0]["props"]


@pytest.mark.unit
def test_the_default_column_wire_is_unchanged():
    assert Col("a").wire() == {"field": "a", "title": "a", "kind": "text", "sortable": True}


@pytest.mark.unit
def test_a_cell_column_carries_its_validated_spec_and_sort_key():
    wire = Col("tier", kind="cell", render=RAIL, sort_key="score").wire()
    assert wire["kind"] == "cell"
    assert wire["render"]["tag"] == "div"
    assert wire["render"]["children"][1]["literal"] == "of 5"
    assert wire["sortKey"] == "score"


@pytest.mark.unit
def test_truncate_wrap_and_max_width_wire_only_when_set():
    wire = Col("p", truncate=True, max_width="30ch").wire()
    assert wire["truncate"] is True and wire["maxWidth"] == "30ch" and "wrap" not in wire
    assert Col("p", wrap=True).wire()["wrap"] is True
    assert "truncate" not in Col("p", wrap=True).wire()


@pytest.mark.unit
def test_cell_and_render_go_together():
    with pytest.raises(ValueError, match="render"):
        Col("tier", kind="cell")
    with pytest.raises(ValueError, match="kind='cell'"):
        Col("tier", render=RAIL)


@pytest.mark.unit
def test_a_cell_spec_uses_the_existing_allowlist_and_is_display_only():
    with pytest.raises(ValueError, match="not allowed"):
        Col("x", kind="cell", render={"tag": "script"})
    with pytest.raises(ValueError, match="display"):
        Col(
            "x",
            kind="cell",
            render={"tag": "button", "on": {"click": {"event": "click"}}},
        )
    with pytest.raises(ValueError, match="display"):
        Col(
            "x",
            kind="cell",
            render={"tag": "div", "children": [{"tag": "input", "on": {"input": {"event": "i"}}}]},
        )


@pytest.mark.unit
def test_truncate_and_wrap_are_exclusive_and_max_width_needs_truncate():
    with pytest.raises(ValueError, match="truncate"):
        Col("p", truncate=True, wrap=True)
    with pytest.raises(ValueError, match="max_width"):
        Col("p", max_width="30ch")
    with pytest.raises(ValueError, match="length"):
        Col("p", truncate=True, max_width="wide")


@pytest.mark.unit
def test_wrap_is_refused_when_rows_have_one_fixed_height():
    with pytest.raises(ValueError, match="wrap"):
        Table(
            rows=[{"id": "a", "p": "x"}],
            columns=[Col("p", wrap=True)],
            key="id",
            virtual=True,
            height="20rem",
        )
    # truncate is fine in a virtual table
    Table(
        rows=[{"id": "a", "p": "x"}],
        columns=[Col("p", truncate=True)],
        key="id",
        virtual=True,
        height="20rem",
    )


@pytest.mark.unit
def test_a_stream_fed_table_carries_the_cell_spec_once_in_its_columns():
    stream = Stream(limit=50)
    table = Table(rows=stream, columns=[Col("tier", kind="cell", render=RAIL)], key="id")
    props = _wire(table)
    assert props["columns"][0]["render"]["class"] == "tier-rail"
    stream.append({"id": "1", "tier": 3})  # rows stay plain data; no spec per row


@pytest.mark.unit
def test_remote_sort_by_a_cell_column_uses_its_sort_key():
    seen = []

    def loader(q):
        seen.append(q.sort)
        return [], 0

    table = Table(
        columns=[Col("id"), Col("tier", kind="cell", render=RAIL, sort_key="score")],
        key="id",
        remote=loader,
    )
    asyncio.run(_ask(table, sort=["score", "desc"]))
    assert seen == [("score", "desc")]
    asyncio.run(_ask(table, sort=["tier", "asc"]))  # the column's own field is not the key
    assert seen[-1] is None


async def _ask(t, **payload):
    payload.setdefault("seq", 1)
    result = t.handle("query", payload)
    assert asyncio.iscoroutine(result)
    await result

"""Table v2 core: keyed rows, typed columns and Stream-fed rows (IND-91, ADR-0027).

Additive to ADR-0021: ``Table(source, ...)`` with no ``columns``/``rows``/``key`` is the
old table, untouched (``tests/unit/test_table.py``).
"""

import pytest

from indah.components import Col, Column, List, Table
from indah.reactive import Signal
from indah.session import Session
from indah.stream import Stream
from indah.transport import Hub

ROWS = [
    {"id": "01A", "result": "hit", "score": 0.91, "ts": 1_700_000_000_000},
    {"id": "01B", "result": "miss", "score": 0.12, "ts": 1_700_000_001_000},
]
COLS = [
    Col("id", kind="mono", width="12ch"),
    Col("result", kind="badge", tones={"hit": "ok", "miss": "warn"}),
    Col("score", kind="number"),
    Col("ts", title="When", kind="time"),
]


def _session(component):
    session = Session(Column(children=[component]))
    hub = Hub(coalesce_seconds=0)
    session.bind_hub(hub)
    return session, hub


@pytest.mark.unit
def test_col_defaults_and_wire_shape():
    assert Col("result").wire() == {
        "field": "result",
        "title": "result",
        "kind": "text",
        "sortable": True,
    }
    wire = Col("r", title="Result", kind="badge", width="8ch", sortable=False, tones={"a": "ok"})
    assert wire.wire() == {
        "field": "r",
        "title": "Result",
        "kind": "badge",
        "width": "8ch",
        "sortable": False,
        "tones": {"a": "ok"},
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [{"kind": "html"}, {"kind": "badge", "tones": {"a": "pink"}}, {"width": "10px; x"}],
)
def test_col_rejects_bad_kinds_tones_and_widths(kwargs):
    with pytest.raises(ValueError):
        Col("x", **kwargs)


@pytest.mark.unit
def test_rich_table_serialises_columns_keyed_rows_and_selection():
    picked: Signal = Signal("01B")
    t = Table(rows=ROWS, columns=COLS, key="id", selected=picked, label="Log", height="20rem")
    Session(Column(children=[t]))
    node = t.to_json()
    props = node["props"]
    assert node["type"] == "table"
    assert [c["field"] for c in props["columns"]] == ["id", "result", "score", "ts"]
    assert props["columns"][1]["tones"] == {"hit": "ok", "miss": "warn"}
    assert props["rows"] == ROWS
    assert props["rowKey"] == "id" and props["selectable"] is True
    assert props["value"] == "01B" and props["height"] == "20rem" and props["label"] == "Log"
    assert "data" not in props  # the legacy prop is not sent in rich mode


@pytest.mark.unit
def test_columns_are_inferred_from_static_rows():
    t = Table(rows=ROWS, key="id")
    Session(Column(children=[t]))
    assert [c["field"] for c in t.to_json()["props"]["columns"]] == ["id", "result", "score", "ts"]


@pytest.mark.unit
def test_columns_are_required_when_they_cannot_be_inferred():
    with pytest.raises(ValueError, match="columns"):
        Table(rows=Stream(limit=5), key="id")
    with pytest.raises(ValueError, match="columns"):
        Table(rows=[], key="id")


@pytest.mark.unit
def test_a_row_without_the_key_is_rejected():
    t = Table(rows=[{"id": "1"}, {"name": "no id"}], columns=[Col("id")], key="id")
    with pytest.raises(ValueError, match="key"):
        t.to_json()


@pytest.mark.unit
def test_select_by_key_sets_the_signal_and_patches_value_back():
    picked: Signal = Signal(None)
    t = Table(rows=ROWS, columns=COLS, key="id", selected=picked)
    session, _ = _session(t)
    result = session.dispatch(t.id, "select", {"key": "01A"})
    assert picked.value == "01A"
    assert result.changes == [{"target": t.id, "props": {"value": "01A"}}]


@pytest.mark.unit
def test_select_by_index_still_works_without_a_key():
    picked: Signal = Signal(None)
    t = Table(rows=ROWS, columns=COLS, selected=picked)
    session, _ = _session(t)
    session.dispatch(t.id, "select", {"index": 1})
    assert picked.value == 1


@pytest.mark.unit
def test_rows_are_json_safe_and_dataframes_become_records():
    class Frame:  # duck-typed pandas
        columns = ["id", "n"]

        def to_dict(self, orient):
            assert orient == "records"
            return [{"id": "a", "n": 1}]

    t = Table(rows=Frame(), key="id")
    Session(Column(children=[t]))
    assert t.to_json()["props"]["rows"] == [{"id": "a", "n": 1}]


@pytest.mark.unit
def test_a_stream_of_rows_is_sent_as_append_patches_with_a_trim():
    rows = Stream(limit=3)
    t = Table(rows=rows, columns=COLS, key="id")
    session, hub = _session(t)
    assert t.stream_props()["rows"][0] is rows
    rows.append(*ROWS)
    (item,) = [m for _, m in hub.history()]
    (change,) = item["changes"]
    assert change["target"] == t.id
    assert change["append"] == {"rows": ROWS} and change["trim"] == {"rows": 3}


@pytest.mark.unit
def test_the_legacy_table_is_untouched_by_the_new_arguments():
    t = Table({"columns": ["a"], "rows": [[1]]}, page_size=5)
    Session(Column(children=[t]))
    props = t.to_json()["props"]
    assert props["data"] == {"columns": ["a"], "rows": [[1]]}
    assert "columns" not in props and "rows" not in props and "rowKey" not in props
    assert t.stream_props() == {}


@pytest.mark.unit
def test_a_list_still_takes_a_stream_after_the_refactor():
    assert List(Stream(limit=2)).stream_props()


# -- search, column toggle, follow (IND-92) -------------------------------------


@pytest.mark.unit
def test_toolbar_flags_are_static_props_and_default_off():
    plain = Table(rows=ROWS, key="id")
    Session(Column(children=[plain]))
    p = plain.to_json()["props"]
    assert p["search"] is False and p["columnToggle"] is False and p["follow"] is False

    rich = Table(rows=ROWS, key="id", search=True, column_toggle=True, follow=True, height="10rem")
    Session(Column(children=[rich]))
    p = rich.to_json()["props"]
    assert p["search"] is True and p["columnToggle"] is True and p["follow"] is True


@pytest.mark.unit
def test_follow_needs_a_height_to_scroll_in():
    with pytest.raises(ValueError, match="height"):
        Table(rows=ROWS, key="id", follow=True)


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["search", "column_toggle", "follow"])
def test_the_classic_table_does_not_take_the_toolbar_flags(flag):
    with pytest.raises(ValueError, match="rows="):
        Table({"columns": ["a"], "rows": [[1]]}, **{flag: True})


@pytest.mark.unit
def test_time_columns_carry_an_absolute_format_only_when_asked():
    assert "timeFormat" not in Col("ts", kind="time").wire()  # relative stays the default
    assert Col("ts", kind="time", time_format="clock").wire()["timeFormat"] == "clock"
    assert Col("ts", kind="time", time_format="datetime").wire()["timeFormat"] == "datetime"
    with pytest.raises(ValueError):
        Col("ts", kind="time", time_format="iso")
    with pytest.raises(ValueError):  # a format on a non-time column is a mistake
        Col("ts", time_format="clock")

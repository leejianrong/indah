"""Unit tests for the interactive Table and the Stat metric card (ADR-0021).

Both ride reactive props (no protocol_version bump). Sorting/paging are client-side;
the server side is data in + a `select` event that binds a Signal (round-trip).
"""

import pytest

from indah.components import Column, Stat, Table
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub

_DATA = {"columns": ["ticker", "price"], "rows": [["AAPL", 220], ["MSFT", 410]]}


def _session(component):
    session = Session(Column(children=[component]))
    hub = Hub()
    session.bind_hub(hub)
    return session, hub


@pytest.mark.unit
def test_table_serialises_data_and_view_props():
    t = Table(_DATA, page_size=25, label="Peers")
    Session(Column(children=[t]))
    props = t.to_json()["props"]
    assert t.to_json()["type"] == "table"
    assert props["data"] == _DATA
    assert props["pageSize"] == 25
    assert props["selectable"] is False  # no `selected=` signal
    assert props["label"] == "Peers"


@pytest.mark.unit
def test_table_is_selectable_and_select_binds_the_signal():
    picked: Signal[int] = Signal(None)
    t = Table(_DATA, selected=picked)
    session, _ = _session(t)

    assert t.to_json()["props"]["selectable"] is True
    assert t.to_json()["props"]["value"] is None  # nothing selected yet

    # A row click round-trips: the signal is set, and it patches back as `value`.
    result = session.dispatch(t.id, "select", {"index": 1})
    assert picked.value == 1
    assert result.changes == [{"target": t.id, "props": {"value": 1}}]


@pytest.mark.unit
def test_table_reactive_data_replaces():
    data: Signal[list] = Signal([{"a": 1}, {"a": 2}])
    t = Table(data)
    session, hub = _session(t)
    assert session.snapshot()["children"][0]["props"]["data"] == {
        "columns": ["a"],
        "rows": [[1], [2]],
    }

    data.set([{"a": 1}, {"a": 2}, {"a": 3}])
    _, msg = hub.history()[-1]
    assert msg["changes"][0]["props"]["data"]["rows"] == [[1], [2], [3]]


@pytest.mark.unit
def test_select_without_a_bound_signal_is_unhandled():
    t = Table(_DATA)  # not selectable
    session, _ = _session(t)
    assert session.dispatch(t.id, "select", {"index": 0}) is None  # unknown event -> 400


@pytest.mark.unit
def test_stat_serialises_value_label_and_delta():
    price = Signal(220.0)
    change = Signal("+2.4%")
    s = Stat(
        lambda: f"${price.value:.2f}", label="Price", delta=lambda: change.value, help="vs open"
    )
    session, hub = _session(s)

    props = s.to_json()["props"]
    assert s.to_json()["type"] == "stat"
    assert props["value"] == "$220.00"
    assert props["label"] == "Price" and props["help"] == "vs open"
    assert props["delta"] == "+2.4%"

    change.set("-1.1%")
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {"target": s.id, "props": {"delta": "-1.1%"}}


@pytest.mark.unit
def test_stat_without_delta_omits_it():
    s = Stat("42", label="Count")
    Session(Column(children=[s]))
    assert "delta" not in s.to_json()["props"]

"""Unit tests for the client-side Chart component (ADR-0018, KAN-1423).

Chart data rides ordinary reactive props (so no protocol_version bump); streaming
points use the existing append op, the same O(delta) path StreamText uses for text.
"""

import pytest

from indah.components import Chart, Column
from indah.protocol import PROTOCOL_VERSION
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _chart_session(chart: Chart) -> tuple[Session, Hub]:
    session = Session(Column(children=[chart]))
    hub = Hub()
    session.bind_hub(hub)
    return session, hub


@pytest.mark.unit
def test_chart_serialises_series_and_encoding_as_props():
    chart = Chart(
        series=["loss", {"label": "acc", "stroke": "#2e6d62"}], title="Run", x_label="step"
    )
    Session(Column(children=[chart]))

    node = chart.to_json()
    assert node["type"] == "chart"
    props = node["props"]
    assert props["series"] == [{"label": "loss"}, {"label": "acc", "stroke": "#2e6d62"}]
    assert props["title"] == "Run"
    assert props["xLabel"] == "step"
    # A streaming chart (no data=) carries its (empty) accumulated data in the snapshot.
    assert props["data"] == []


@pytest.mark.unit
def test_reactive_data_replaces_and_rounds_trips_rows():
    data: Signal[list] = Signal([[0, 1.0], [1, 0.5]])
    chart = Chart(data, series=["loss"])
    session, hub = _chart_session(chart)

    # Snapshot carries the current rows (reactive mode: data is a reactive prop).
    node = session.snapshot()["children"][0]
    assert node["props"]["data"] == [[0, 1.0], [1, 0.5]]

    data.set([[0, 1.0], [1, 0.5], [2, 0.25]])
    _, msg = hub.history()[-1]
    assert msg["v"] == PROTOCOL_VERSION
    assert msg["changes"][0] == {
        "target": chart.id,
        "props": {"data": [[0, 1.0], [1, 0.5], [2, 0.25]]},
    }


@pytest.mark.unit
def test_push_appends_points_as_append_deltas_at_o_point():
    chart = Chart(series=["loss"], title="Training loss")
    session, hub = _chart_session(chart)

    chart.push(0, 1.0)
    chart.push(1, 0.7)

    # Each push emits an append carrying only the new row (not the whole series).
    changes = [msg["changes"][0] for _, msg in hub.history()]
    assert changes == [
        {"target": chart.id, "append": {"data": [[0, 1.0]]}},
        {"target": chart.id, "append": {"data": [[1, 0.7]]}},
    ]


@pytest.mark.unit
def test_extend_appends_a_batch_of_points_in_one_patch():
    chart = Chart(series=["a", "b"])
    session, hub = _chart_session(chart)

    chart.extend([[0, 1, 2], [1, 3, 4]])

    assert len(hub.history()) == 1  # one patch for the whole batch
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {"target": chart.id, "append": {"data": [[0, 1, 2], [1, 3, 4]]}}


@pytest.mark.unit
def test_snapshot_carries_full_accumulated_points_for_resume():
    chart = Chart(series=["loss"])
    session, _ = _chart_session(chart)
    chart.push(0, 1.0)
    chart.push(1, 0.5)

    # A resume that falls back to init must re-render the full curve so far.
    node = session.snapshot()["children"][0]
    assert node["type"] == "chart"
    assert node["props"]["data"] == [[0, 1.0], [1, 0.5]]


@pytest.mark.unit
def test_clear_resets_points_and_emits_a_replace():
    chart = Chart(series=["loss"])
    session, hub = _chart_session(chart)
    chart.push(0, 1.0)

    chart.clear()

    assert chart.to_json()["props"]["data"] == []
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {"target": chart.id, "props": {"data": []}}


@pytest.mark.unit
def test_streaming_api_rejected_on_a_reactive_chart():
    chart = Chart(Signal([]), series=["loss"])
    _chart_session(chart)
    with pytest.raises(TypeError):
        chart.push(0, 1.0)


# -- hover and click (IND-266) ----------------------------------------------------------------


@pytest.mark.unit
def test_hovered_and_clicked_signals_are_set_from_the_data_not_the_payload():
    from indah import Signal

    hovered, clicked = Signal(None), Signal(None)
    chart = Chart([[1, 10, 100], [2, 20, 200]], series=["a", "b"], hovered=hovered, clicked=clicked)
    props = chart.static_props()
    assert props["hoverable"] is True and props["clickable"] is True
    assert chart.handle("hover", {"index": 1, "series": 1}) is True
    assert hovered.value == {"series": "b", "index": 1, "x": 2, "y": 200}
    assert chart.handle("click", {"index": 0, "series": 0}) is True
    assert clicked.value == {"series": "a", "index": 0, "x": 1, "y": 10}
    assert chart.handle("hover", {"index": None}) is True and hovered.value is None
    assert clicked.value is not None  # leaving the plot does not clear a click


@pytest.mark.unit
def test_chart_events_refuse_what_the_data_cannot_back():
    from indah import Signal

    hovered = Signal(None)
    chart = Chart([[1, 10]], series=["a"], hovered=hovered)
    for bad in (
        {"index": 5, "series": 0},
        {"index": -1, "series": 0},
        {"index": 0, "series": 3},
        {"index": True, "series": 0},
        {"index": "0", "series": 0},
        {"series": 0},
    ):
        assert chart.handle("hover", bad) is False
    assert hovered.value is None
    assert chart.handle("click", {"index": 0, "series": 0}) is False  # no clicked signal bound
    assert "hoverable" in chart.static_props() and "clickable" not in chart.static_props()
    assert "hoverable" not in Chart([[1, 2]], series=["a"]).static_props()


@pytest.mark.unit
def test_chart_events_on_a_category_and_a_streaming_chart():
    from indah import Signal

    clicked = Signal(None)
    bars = Chart(
        [["x", 3], ["y", 4]],
        series=[{"label": "n", "kind": "bars"}],
        x_scale="category",
        clicked=clicked,
    )
    assert bars.handle("click", {"index": 1, "series": 0}) is True
    assert clicked.value == {"series": "n", "index": 1, "x": "y", "y": 4}
    live = Chart(series=["loss"], hovered=Signal(None))
    live.push(0, 1.5)
    assert live.handle("hover", {"index": 0, "series": 0}) is True

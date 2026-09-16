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

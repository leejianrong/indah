"""Unit tests for the client-side Heatmap / 2-D field component (ADR-0019).

The field rides reactive props (no protocol_version bump); a streaming spectrogram
appends columns via the existing append op, the same O(delta) path Chart uses.
"""

import pytest

from indah.components import Column, Heatmap
from indah.protocol import PROTOCOL_VERSION
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub


def _heatmap_session(hm: Heatmap) -> tuple[Session, Hub]:
    session = Session(Column(children=[hm]))
    hub = Hub()
    session.bind_hub(hub)
    return session, hub


@pytest.mark.unit
def test_heatmap_serialises_encoding_as_props():
    hm = Heatmap(colormap="viridis", zmin=0, zmax=1, title="Spec", y_label="freq")
    Session(Column(children=[hm]))

    props = hm.to_json()["props"]
    assert hm.to_json()["type"] == "heatmap"
    assert props["colormap"] == "viridis"
    assert props["zmin"] == 0 and props["zmax"] == 1
    assert props["title"] == "Spec" and props["yLabel"] == "freq"
    assert props["z"] == []  # streaming mode carries its (empty) field


@pytest.mark.unit
def test_reactive_field_replaces_columns():
    field: Signal[list] = Signal([[0.0, 1.0], [0.5, 0.5]])  # two columns of two rows
    hm = Heatmap(field, colormap="gray")
    session, hub = _heatmap_session(hm)

    assert session.snapshot()["children"][0]["props"]["z"] == [[0.0, 1.0], [0.5, 0.5]]

    field.set([[0.0, 1.0], [0.5, 0.5], [1.0, 0.0]])
    _, msg = hub.history()[-1]
    assert msg["v"] == PROTOCOL_VERSION
    assert msg["changes"][0] == {
        "target": hm.id,
        "props": {"z": [[0.0, 1.0], [0.5, 0.5], [1.0, 0.0]]},
    }


@pytest.mark.unit
def test_push_column_appends_a_time_slice_at_o_column():
    hm = Heatmap()  # streaming mode
    session, hub = _heatmap_session(hm)

    hm.push_column([0.1, 0.2, 0.3])
    hm.push_column([0.4, 0.5, 0.6])

    changes = [msg["changes"][0] for _, msg in hub.history()]
    assert changes == [
        {"target": hm.id, "append": {"z": [[0.1, 0.2, 0.3]]}},
        {"target": hm.id, "append": {"z": [[0.4, 0.5, 0.6]]}},
    ]


@pytest.mark.unit
def test_extend_appends_a_batch_of_columns_in_one_patch():
    hm = Heatmap()
    session, hub = _heatmap_session(hm)

    hm.extend([[1, 2], [3, 4]])

    assert len(hub.history()) == 1
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {"target": hm.id, "append": {"z": [[1, 2], [3, 4]]}}


@pytest.mark.unit
def test_snapshot_carries_full_field_for_resume():
    hm = Heatmap()
    session, _ = _heatmap_session(hm)
    hm.push_column([1, 2])
    hm.push_column([3, 4])

    node = session.snapshot()["children"][0]
    assert node["type"] == "heatmap"
    assert node["props"]["z"] == [[1, 2], [3, 4]]


@pytest.mark.unit
def test_clear_resets_field_and_emits_a_replace():
    hm = Heatmap()
    session, hub = _heatmap_session(hm)
    hm.push_column([1, 2])

    hm.clear()

    assert hm.to_json()["props"]["z"] == []
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {"target": hm.id, "props": {"z": []}}


@pytest.mark.unit
def test_streaming_api_rejected_on_a_reactive_heatmap():
    hm = Heatmap(Signal([]))
    _heatmap_session(hm)
    with pytest.raises(TypeError):
        hm.push_column([1, 2])

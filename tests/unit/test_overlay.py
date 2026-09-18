"""Unit tests for ImageOverlay (ADR-0020): read-only boxes/masks/keypoints.

Shapes ride reactive props (coords in [0,1]); streaming a model's output per frame
is a prop update over the existing patch op - no protocol_version bump.
"""

import base64

import pytest

from indah.components import Column, ImageOverlay
from indah.reactive import Signal
from indah.session import Session
from indah.transport import Hub

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def _session(component):
    session = Session(Column(children=[component]))
    hub = Hub()
    session.bind_hub(hub)
    return session, hub


@pytest.mark.unit
def test_overlay_serialises_src_and_normalised_boxes():
    boxes = [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "cat", "score": 0.9}]
    ov = ImageOverlay("http://img.png", boxes=boxes)
    Session(Column(children=[ov]))

    props = ov.to_json()["props"]
    assert ov.to_json()["type"] == "imageoverlay"
    assert props["src"] == "http://img.png"
    assert props["boxes"] == [
        {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "cat", "score": 0.9}
    ]
    assert props["points"] == [] and props["masks"] == []


@pytest.mark.unit
def test_box_tuple_and_points_are_normalised():
    ov = ImageOverlay("x", boxes=[(0.0, 0.0, 0.5, 0.5)], points=[{"x": 0.2, "y": 0.3}, (0.6, 0.7)])
    Session(Column(children=[ov]))
    props = ov.to_json()["props"]
    assert props["boxes"] == [{"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}]
    assert props["points"] == [{"x": 0.2, "y": 0.3}, {"x": 0.6, "y": 0.7}]


@pytest.mark.unit
def test_mask_bytes_become_a_data_uri_overlay():
    ov = ImageOverlay("x", masks=[{"src": _PNG, "opacity": 0.4}])
    Session(Column(children=[ov]))
    masks = ov.to_json()["props"]["masks"]
    assert len(masks) == 1
    assert masks[0]["src"].startswith("data:image/png;base64,")
    assert masks[0]["opacity"] == 0.4


@pytest.mark.unit
def test_label_mode_defaults_to_always_and_is_threaded_through():
    always = ImageOverlay("x")
    Session(Column(children=[always]))
    assert always.to_json()["props"]["labelMode"] == "always"

    hover = ImageOverlay("x", label_mode="hover")
    Session(Column(children=[hover]))
    assert hover.to_json()["props"]["labelMode"] == "hover"


@pytest.mark.unit
def test_streaming_detections_replace_boxes_over_the_patch_op():
    detections: Signal[list] = Signal([])
    ov = ImageOverlay("x", boxes=lambda: detections.value)
    session, hub = _session(ov)

    assert session.snapshot()["children"][0]["props"]["boxes"] == []

    detections.set([{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "dog"}])
    _, msg = hub.history()[-1]
    assert msg["changes"][0] == {
        "target": ov.id,
        "props": {"boxes": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "dog"}]},
    }

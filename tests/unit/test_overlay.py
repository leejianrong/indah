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


@pytest.mark.unit
def test_shapes_are_in_raster_pixels_and_validated():
    ov = ImageOverlay(
        "http://img.png",
        size=(650, 480),
        selected=Signal("a"),
        view=[0, 0, 100, 80],
        shapes=[
            {"id": "a", "box": [10, 20, 110, 220], "stroke": "#f00", "dash": [4, 3], "pick": True},
            {"id": 2, "points": [[0, 0], [5, 0], [5, 5]], "fill": "var(--x)", "label": "t"},
        ],
    )
    Session(Column(children=[ov]))
    j = ov.to_json()["props"]
    assert j["size"] == [650, 480] and j["selected"] == "a" and j["view"] == [0, 0, 100, 80]
    assert j["shapes"][0] == {
        "id": "a",
        "box": [10, 20, 110, 220],
        "stroke": "#f00",
        "dash": [4, 3],
        "pick": True,
    }
    assert j["shapes"][1]["id"] == "2" and j["shapes"][1]["label"] == "t"
    with pytest.raises(ValueError, match="size"):
        ImageOverlay("x", shapes=[])
    for bad in (
        {"id": "a"},
        {"id": "a", "box": [1, 2, 3]},
        {"id": "a", "points": [[0, 0]]},
        {"id": "a", "box": [0, 0, 1, 1], "stroke": "url(http://evil)"},
    ):
        with pytest.raises(ValueError):
            ImageOverlay("x", size=(1, 1), shapes=[bad]).reactive_props()["shapes"]()


@pytest.mark.unit
def test_pick_runs_only_for_a_current_pickable_shape():
    picked = []
    ov = ImageOverlay(
        "x",
        size=(10, 10),
        on_pick=picked.append,
        shapes=[{"id": "t0", "box": [0, 0, 5, 5], "pick": True}, {"id": "t1", "box": [5, 5, 9, 9]}],
    )
    assert ov.handle("pick", {"id": "t0"}) is True
    assert ov.handle("pick", {"id": "t1"}) is True  # not pickable: ignored
    assert ov.handle("pick", {"id": "zz"}) is True
    assert picked == ["t0"]
    assert ImageOverlay("x").handle("pick", {"id": "t0"}) is False


@pytest.mark.unit
def test_point_shape_is_validated_and_sent():
    ov = ImageOverlay(
        "x", size=(10, 10), shapes=[{"id": "p", "point": [3, 4], "stroke": "#f00", "label": "eye"}]
    )
    Session(Column(children=[ov]))
    assert ov.to_json()["props"]["shapes"] == [
        {"id": "p", "point": [3.0, 4.0], "stroke": "#f00", "label": "eye"}
    ]
    for bad in ({"id": "p", "point": [1]}, {"id": "p", "point": ["a", 2]}):
        with pytest.raises(ValueError):
            ImageOverlay("x", size=(10, 10), shapes=[bad]).reactive_props()["shapes"]()


@pytest.mark.unit
def test_draw_needs_a_size_and_a_known_mode():
    with pytest.raises(ValueError, match="size"):
        ImageOverlay("x", draw="box")
    with pytest.raises(ValueError, match="draw"):
        ImageOverlay("x", size=(10, 10), draw="circle").reactive_props()["draw"]()
    ov = ImageOverlay("x", size=(10, 10))
    Session(Column(children=[ov]))
    assert "draw" not in ov.to_json()["props"]


@pytest.mark.unit
def test_draw_mode_is_reactive_and_a_drawn_box_reaches_on_draw():
    mode: Signal[str | None] = Signal("box")
    drawn = []
    ov = ImageOverlay("x", size=(100, 50), draw=mode, on_draw=drawn.append)
    session, hub = _session(ov)
    assert session.snapshot()["children"][0]["props"]["draw"] == "box"

    # corners in any order are normalised and clamped into the picture
    assert ov.handle("draw", {"kind": "box", "box": [60, 40, -5, 10]}) is True
    assert drawn == [{"kind": "box", "box": [0.0, 10.0, 60.0, 40.0]}]

    # a slip of a drag (under 2 px either way) is not a box
    assert ov.handle("draw", {"kind": "box", "box": [10, 10, 11, 30]}) is True
    assert len(drawn) == 1

    # a point event while in box mode, junk and non-finite numbers are ignored
    for bad in (
        {"kind": "point", "point": [5, 5]},
        {"kind": "box", "box": [1, 2, 3]},
        {"kind": "box", "box": [0, 0, "a", 9]},
        {"kind": "box", "box": [0, 0, float("nan"), 9]},
        {"kind": "bogus"},
    ):
        assert ov.handle("draw", bad) is True
    assert len(drawn) == 1

    mode.set("point")
    assert ov.handle("draw", {"kind": "point", "point": [120, -3]}) is True
    assert drawn[-1] == {"kind": "point", "point": [100.0, 0.0]}

    mode.set(None)  # drawing switched off: a late event is ignored
    assert ov.handle("draw", {"kind": "point", "point": [1, 1]}) is True
    assert len(drawn) == 2
    plain = ImageOverlay("x", size=(10, 10))
    assert plain.handle("draw", {"kind": "point", "point": [1, 1]}) is False

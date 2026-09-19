"""The upload->detect->show example (examples/object_detection.py) stays runnable.

Drives the example's session through the same upload dispatch path a real upload
takes, so the demo is smoke-checked in CI. The "detector" is the example's own
deterministic mock; a real detector would ride the identical handler (ADR-0009).
"""

import importlib.util
from pathlib import Path

import pytest

from indah.components import UploadedFile
from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "object_detection.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("object_detection_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
def test_detect_is_deterministic_and_in_range():
    example = _load_example()
    a = example.detect(b"some image bytes")
    b = example.detect(b"some image bytes")
    assert a == b  # same bytes -> same boxes
    assert 3 <= len(a) <= 6
    for box in a:
        assert box["label"] in example.LABELS
        assert 0.0 <= box["x"] <= 1.0 and 0.0 <= box["y"] <= 1.0
        assert 0.0 < box["w"] <= 1.0 and 0.0 < box["h"] <= 1.0
        assert 0.55 <= box["score"] <= 0.99


@pytest.mark.integration
async def test_uploading_an_image_detects_boxes_and_labels_them_on_hover():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-a"
    hub = Hub()
    session.bind_hub(hub)

    upload = _node(session, "upload")
    overlay = _node(session, "imageoverlay")
    image_data = b"\x89PNG pretend-image"

    result = session.dispatch(
        upload.id,
        "upload",
        {"files": [UploadedFile("scene.png", "image/png", image_data)]},
    )
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The image was echoed back as a data: URI.
    assert overlay.reactive_props()["src"]().startswith("data:image/png;base64,")

    # Detections match the deterministic mock, and hover-only labels are on.
    boxes = example.detect(image_data)
    assert overlay.reactive_props()["boxes"]() == boxes
    assert overlay.static_props()["labelMode"] == "hover"

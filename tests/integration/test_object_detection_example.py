"""The pick-a-sample->detect->show example (examples/object_detection.py) stays
runnable.

Drives the example's session through the same dispatch path a real click/upload
takes, so the demo is smoke-checked in CI. ``detect`` runs a real onnxruntime
model (SSD-MobileNetV1), so these tests need onnxruntime/Pillow/huggingface_hub
installed -- skipped otherwise, same as the Playwright e2e tests skip without a
browser installed. The first test in this file to touch the model pays its
one-time load cost (a few seconds); every test after that is fast.
"""

import base64
import importlib.util
from pathlib import Path

import pytest

from indah.components import UploadedFile
from indah.transport import Hub

pytest.importorskip("onnxruntime")
pytest.importorskip("PIL")
pytest.importorskip("huggingface_hub")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "object_detection.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("object_detection_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


def _status_blocks_text(component) -> str:
    """The rendered text of a markdown ``Text`` node (its reactive prop is
    ``blocks``, a parsed tree, not ``text``)."""
    blocks = component.reactive_props().get("blocks")
    return str(blocks()) if blocks is not None else ""


@pytest.mark.integration
def test_detect_is_deterministic():
    """Real inference is deterministic: same bytes in, same boxes out."""
    example = _load_example()
    data = base64.b64decode(example._SAMPLES["cyclist"][1])
    a = example.detect(data)
    b = example.detect(data)
    assert a == b


@pytest.mark.integration
def test_detect_returns_plausible_coco_boxes():
    """Boxes are real model output, not a hash-derived stand-in: labels come from
    the COCO class list, scores/coordinates are in range, and boxes are sorted
    most-confident first (the model's own NMS ordering)."""
    example = _load_example()
    data = base64.b64decode(example._SAMPLES["cyclist"][1])
    boxes = example.detect(data)
    assert boxes  # the cyclist sample has real, confident detections
    for box in boxes:
        assert box["label"] in example.COCO_LABELS.values()
        assert 0.0 <= box["x"] < 1.0 and 0.0 <= box["y"] < 1.0
        assert 0.0 < box["w"] <= 1.0 and 0.0 < box["h"] <= 1.0
        assert example._SCORE_THRESHOLD <= box["score"] <= 1.0
    scores = [box["score"] for box in boxes]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.integration
def test_sample_photos_detect_multiple_real_objects():
    """The bundled samples exist so a first-time visitor sees the model get it
    right; each holds several COCO objects, unlike a single-subject classifier
    photo, so detection has something interesting to find."""
    example = _load_example()
    all_labels: set[str] = set()
    for slug, (label, b64) in example._SAMPLES.items():
        data = base64.b64decode(b64)
        boxes = example.detect(data)
        assert boxes, f"sample {slug!r} ({label}) found nothing"
        assert max(box["score"] for box in boxes) > 0.5, (
            f"sample {slug!r} ({label}) detected with low confidence"
        )
        all_labels.update(box["label"] for box in boxes)
    # Across the five samples, several distinct COCO classes show up -- proof this
    # is a real detector reading real pixels, not a hash of the file's bytes.
    assert len(all_labels) >= 5


@pytest.mark.integration
def test_session_shows_a_real_detection_on_creation_no_click_required():
    """A5 UX (docs/DEMOS-DOCS-ROUND2.md): the result card is populated with the
    first sample's real detections as soon as the session exists -- before any
    client event is dispatched."""
    example = _load_example()
    session = example.build_session()

    overlay = _node(session, "imageoverlay")
    assert overlay.reactive_props()["src"]().startswith("data:image/jpeg;base64,")
    boxes = overlay.reactive_props()["boxes"]()
    assert boxes  # already populated, not the empty starting state

    first_label, first_b64 = next(iter(example._SAMPLES.values()))
    assert overlay.reactive_props()["src"]() == f"data:image/jpeg;base64,{first_b64}"
    assert boxes == example.detect(base64.b64decode(first_b64))

    status = next(
        c
        for c in session._by_id.values()
        if c.type == "text" and "Detected" in _status_blocks_text(c)
    )
    assert first_label in _status_blocks_text(status)


@pytest.mark.integration
async def test_uploading_an_image_detects_boxes_and_labels_them_on_hover():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-a"
    hub = Hub()
    session.bind_hub(hub)

    upload = _node(session, "upload")
    overlay = _node(session, "imageoverlay")

    # A real, decodable JPEG -- detect() runs a real image decoder + model, so a
    # fake byte string wouldn't work as a fixture. Reuse a bundled sample's bytes
    # so the expected detections are known-good.
    image_data = base64.b64decode(example._SAMPLES["parking"][1])

    result = session.dispatch(
        upload.id,
        "upload",
        {"files": [UploadedFile("scene.jpg", "image/jpeg", image_data)]},
    )
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The image was echoed back as a data: URI.
    assert overlay.reactive_props()["src"]().startswith("data:image/jpeg;base64,")

    # Detections match a real inference run, and hover-only labels are on.
    boxes = example.detect(image_data)
    assert overlay.reactive_props()["boxes"]() == boxes
    assert overlay.static_props()["labelMode"] == "hover"


@pytest.mark.integration
async def test_non_image_upload_is_rejected_without_detecting():
    """ADR-0024: the public demo only ever needs a still image, so a disallowed
    content type is rejected before it reaches the detector."""
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-c"
    hub = Hub()
    session.bind_hub(hub)

    upload = _node(session, "upload")
    overlay = _node(session, "imageoverlay")
    preview_before = overlay.reactive_props()["src"]()

    # The status Text node -- distinct from the header/"Try a sample:" Text nodes --
    # already reads "Detected ..." thanks to the on-load eager run of the first sample.
    result_text = next(
        c
        for c in session._by_id.values()
        if c.type == "text" and "Detected" in _status_blocks_text(c)
    )

    result = session.dispatch(
        upload.id,
        "upload",
        {"files": [UploadedFile("payload.svg", "image/svg+xml", b"<svg></svg>")]},
    )
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    assert "Unsupported file type" in _status_blocks_text(result_text)
    # The pre-loaded sample result is left untouched, nothing was re-detected.
    assert overlay.reactive_props()["src"]() == preview_before


@pytest.mark.integration
def test_public_deploy_caps_uploads_at_4mb():
    """ADR-0024: lower than the framework's 25 MB default for this public demo."""
    example = _load_example()
    assert example.app.state.max_upload_bytes == 4 * 1024 * 1024


@pytest.mark.integration
async def test_clicking_a_sample_detects_it_too():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-b"
    hub = Hub()
    session.bind_hub(hub)

    overlay = _node(session, "imageoverlay")
    slug, (label, b64) = list(example._SAMPLES.items())[1]  # not the pre-loaded first
    button = next(
        c
        for c in session._by_id.values()
        if c.type == "button" and c.reactive_props()["label"]() == label
    )

    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    assert overlay.reactive_props()["src"]() == f"data:image/jpeg;base64,{b64}"
    assert overlay.reactive_props()["boxes"]() == example.detect(base64.b64decode(b64))

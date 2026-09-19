"""The upload->classify->show example (examples/upload_classify.py) stays runnable.

Drives the example's session through the same upload dispatch path a real upload
takes, so the demo is smoke-checked in CI. ``classify`` runs a real onnxruntime
model, so these tests need onnxruntime/Pillow/matplotlib installed -- skipped
otherwise, same as the Playwright e2e tests skip without a browser installed.
"""

import base64
import importlib.util
import io
from pathlib import Path

import pytest

from indah.components import UploadedFile
from indah.transport import Hub

pytest.importorskip("onnxruntime")
pytest.importorskip("PIL")
pytest.importorskip("matplotlib")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "upload_classify.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("upload_classify_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


def _image_node(session):
    """The classified-image ``Image`` -- distinct from the predictions ``Plot``,
    which also renders as an "image" node type (it rasterises to a PNG)."""
    return next(
        c
        for c in session._by_id.values()
        if c.type == "image" and c.static_props()["alt"] == "the classified image"
    )


def _tiny_png() -> bytes:
    """A real, tiny, decodable PNG -- classify() runs a real image decoder, so a
    fake byte string wouldn't work as a fixture."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 120, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.integration
def test_classify_returns_a_real_imagenet_label():
    example = _load_example()
    label, confidence = example.classify(_tiny_png())
    assert label in example.IMAGENET_LABELS
    assert 0.0 < confidence <= 1.0


@pytest.mark.integration
def test_classify_topk_is_sorted_most_confident_first():
    example = _load_example()
    top = example.classify_topk(_tiny_png(), k=5)
    assert len(top) == 5
    confidences = [c for _label, c in top]
    assert confidences == sorted(confidences, reverse=True)
    assert len({label for label, _c in top}) == 5  # five distinct classes


@pytest.mark.integration
def test_sample_photos_are_real_and_classify_confidently():
    """The bundled samples exist so a first-time visitor sees the model get it
    right; each one should classify with real confidence, not a coin flip."""
    example = _load_example()
    for slug, (label, b64) in example._SAMPLES.items():
        data = base64.b64decode(b64)
        _predicted_label, confidence = example.classify(data)
        assert confidence > 0.5, f"sample {slug!r} ({label}) classified with low confidence"


@pytest.mark.integration
async def test_uploading_an_image_classifies_it_and_offers_a_report():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-a"
    hub = Hub()
    session.bind_hub(hub)

    upload = _node(session, "upload")
    download = _node(session, "download")
    image = _image_node(session)

    png_bytes = _tiny_png()
    result = session.dispatch(
        upload.id,
        "upload",
        {"files": [UploadedFile("swatch.png", "image/png", png_bytes)]},
    )
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The image was echoed back as a data: URI.
    assert image.reactive_props()["src"]().startswith("data:image/png;base64,")

    # A prediction was produced, and a downloadable report is now offered.
    label, _ = example.classify(png_bytes)
    href = download.reactive_props()["href"]()
    assert href.startswith("api/file/tab-a/")
    token = href.rsplit("/", 1)[1]
    data, filename, _ = session.get_file(token)
    assert filename == "prediction.txt"
    assert label.encode() in data


@pytest.mark.integration
async def test_clicking_a_sample_classifies_it_too():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-b"
    hub = Hub()
    session.bind_hub(hub)

    download = _node(session, "download")
    slug, (label, b64) = next(iter(example._SAMPLES.items()))
    button = next(
        c
        for c in session._by_id.values()
        if c.type == "button" and c.reactive_props()["label"]() == label
    )

    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    image = _image_node(session)
    assert image.reactive_props()["src"]() == f"data:image/jpeg;base64,{b64}"

    predicted_label, _confidence = example.classify(base64.b64decode(b64))
    href = download.reactive_props()["href"]()
    token = href.rsplit("/", 1)[1]
    data, _filename, _ = session.get_file(token)
    assert predicted_label.encode() in data

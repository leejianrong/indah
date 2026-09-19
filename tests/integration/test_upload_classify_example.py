"""The upload->classify->show example (examples/upload_classify.py) stays runnable.

Drives the example's session through the same upload dispatch path a real upload
takes, so the demo is smoke-checked in CI. ``classify`` now runs a real onnxruntime
model (ADR-0009's swap already happened here), so these tests need onnxruntime/Pillow
installed -- skipped otherwise, same as the Playwright e2e tests skip without a
browser installed.
"""

import importlib.util
import io
from pathlib import Path

import pytest

from indah.components import UploadedFile
from indah.transport import Hub

pytest.importorskip("onnxruntime")
pytest.importorskip("PIL")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "upload_classify.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("upload_classify_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


def _tiny_png() -> bytes:
    """A real, tiny, decodable PNG -- classify() now runs a real image decoder, so a
    fake ``b"pretend-image"`` byte string (the old mock's fixture) would just error."""
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
async def test_uploading_an_image_classifies_it_and_offers_a_report():
    example = _load_example()
    session = example.build_session()
    session.session_id = "tab-a"
    hub = Hub()
    session.bind_hub(hub)

    upload = _node(session, "upload")
    download = _node(session, "download")
    image = _node(session, "image")

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

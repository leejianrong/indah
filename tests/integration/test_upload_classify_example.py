"""The upload->classify->show example (examples/upload_classify.py) stays runnable.

Drives the example's session through the same upload dispatch path a real upload
takes, so the demo is smoke-checked in CI. The "model" is the example's own
deterministic mock; a real model would ride the identical handler (ADR-0009).
"""

import importlib.util
from pathlib import Path

import pytest

from indah.components import UploadedFile
from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "upload_classify.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("upload_classify_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
def test_classify_is_deterministic():
    example = _load_example()
    a = example.classify(b"some image bytes")
    b = example.classify(b"some image bytes")
    assert a == b  # same bytes -> same (label, confidence)
    assert a[0] in example.LABELS
    assert 0.60 <= a[1] <= 0.99


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

    result = session.dispatch(
        upload.id,
        "upload",
        {"files": [UploadedFile("cat.png", "image/png", b"\x89PNG pretend-image")]},
    )
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    # The image was echoed back as a data: URI.
    assert image.reactive_props()["src"]().startswith("data:image/png;base64,")

    # A prediction was produced, and a downloadable report is now offered.
    label, _ = example.classify(b"\x89PNG pretend-image")
    href = download.reactive_props()["href"]()
    assert href.startswith("api/file/tab-a/")
    token = href.rsplit("/", 1)[1]
    data, filename, _ = session.get_file(token)
    assert filename == "prediction.txt"
    assert label.encode() in data

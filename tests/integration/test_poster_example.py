"""The poster-generator example (examples/poster.py) stays runnable.

Smoke-checks that render is deterministic, the preview re-renders reactively when a
control changes, and the finished poster is served for download (ADR-0017).
"""

import importlib.util
from pathlib import Path

import pytest

from indah.transport import Hub

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "poster.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("poster_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
def test_render_is_deterministic_and_varies_with_controls():
    example = _load_example()
    a = example.render_poster("Hi", "Peach", "Grid", 6, 3)
    b = example.render_poster("Hi", "Peach", "Grid", 6, 3)
    c = example.render_poster("Hi", "Peach", "Grid", 6, 4)  # different seed
    assert a == b and a != c
    assert a.startswith("<svg") and "made with indah" in a


@pytest.mark.integration
def test_changing_a_control_repatches_the_preview_and_download_serves_the_file():
    example = _load_example()
    session = example.build()
    session.session_id = "tab-a"
    hub = Hub()
    session.bind_hub(hub)

    image = _node(session, "image")
    select = _node(session, "select")  # palette

    # Change the palette -> the preview image src re-renders reactively. A sync event
    # returns its coalesced patches in result.changes (app.py publishes them).
    result = session.dispatch(select.id, "change", {"value": "Auburn"})
    src_patches = [
        change["props"]["src"]
        for change in result.changes
        if change.get("target") == image.id and "src" in change.get("props", {})
    ]
    assert src_patches and src_patches[-1].startswith("data:image/svg+xml,")

    # The Download serves the finished SVG per-session (ADR-0017).
    download = _node(session, "download")
    href = download.reactive_props()["href"]()
    assert href.startswith("api/file/tab-a/")
    token = href.rsplit("/", 1)[1]
    data, filename, media_type = session.get_file(token)
    assert filename == "poster.svg" and media_type == "image/svg+xml"
    assert data.startswith(b"<svg")

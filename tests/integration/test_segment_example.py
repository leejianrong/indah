"""The segmentation example (examples/segment.py): a drawn point or box becomes a mask."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "segment.py"
if not _EXAMPLE.exists():
    pytest.skip("examples/ not present", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("segment_example_session", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


def _texts(session):
    return [str(t.to_json()["props"].get("text", "")) for t in _by_type(session, "text")]


@pytest.mark.integration
def test_a_clicked_point_becomes_a_mask_and_a_readout():
    ex = _load()
    session = ex.build()
    (overlay,) = _by_type(session, "imageoverlay")
    props = overlay.to_json()["props"]
    assert props["size"] == [320, 240] and props["draw"] == "point" and props["masks"] == []

    result = session.dispatch(overlay.id, "draw", {"kind": "point", "point": [90, 90]})
    assert result is not None
    masks = overlay.reactive_props()["masks"]()
    assert len(masks) == 1 and masks[0]["src"].startswith("data:image/png;base64,")
    assert overlay.reactive_props()["shapes"]()[0]["point"] == [90.0, 90.0]
    assert any("Region:" in t and "% of the picture" in t for t in _texts(session))


@pytest.mark.integration
def test_a_box_fences_the_region_and_a_sample_pick_clears_it():
    ex = _load()
    session = ex.build()
    (overlay,) = _by_type(session, "imageoverlay")
    radio = _by_type(session, "radio")[0]
    session.dispatch(radio.id, "change", {"value": "box"})
    assert overlay.reactive_props()["draw"]() == "box"
    session.dispatch(
        overlay.id, "draw", {"kind": "point", "point": [1, 1]}
    )  # not the mode: ignored
    session.dispatch(overlay.id, "draw", {"kind": "box", "box": [60, 60, 120, 120]})
    shapes = overlay.reactive_props()["shapes"]()
    assert shapes[0]["box"] == [60.0, 60.0, 120.0, 120.0]

    button = next(
        b for b in _by_type(session, "button") if b.reactive_props()["label"]() == "Landscape"
    )
    session.dispatch(button.id, "click", {})
    assert overlay.reactive_props()["shapes"]() == [] and overlay.reactive_props()["masks"]() == []


@pytest.mark.integration
def test_a_bad_upload_says_why_and_keeps_the_picture():
    ex = _load()
    session = ex.build()
    (overlay,) = _by_type(session, "imageoverlay")
    before = overlay.reactive_props()["src"]()
    seg = ex.Segmenter()
    seg.on_upload(ex.indah.UploadedFile("a.txt", "text/plain", b"hi"))
    assert "JPEG" in seg.status.value
    assert overlay.reactive_props()["src"]() == before

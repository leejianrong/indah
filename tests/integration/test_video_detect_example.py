"""The stepped video detection demo (examples/video_detect.py) stays runnable (IND-62).

The detector is replaced by a stub, so this needs no model library: it checks that uploaded
frames are all analysed up front and that moving the slider swaps the picture and its boxes.
"""

import importlib.util
from pathlib import Path

import pytest

from indah.components import UploadedFile

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "video_detect.py"


def _load():
    spec = importlib.util.spec_from_file_location("video_detect_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


async def _upload(session, files):
    result = session.dispatch(_node(session, "upload").id, "upload", {"files": files})
    assert result is not None and result.coro is not None
    await result.coro


def _boxes(label):
    return [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": label, "score": 0.9}]


@pytest.mark.integration
async def test_every_frame_is_analysed_and_the_slider_steps_through_them(monkeypatch):
    example = _load()
    monkeypatch.setattr(example, "detect", lambda data: _boxes(data.decode()))
    session = example.build_session()
    files = [UploadedFile(f"{n}.jpg", "image/jpeg", n.encode()) for n in ("cat", "dog", "cup")]
    await _upload(session, files)

    overlay, slider = _node(session, "imageoverlay"), _node(session, "slider")
    assert overlay.to_json()["props"]["boxes"][0]["label"] == "cat"
    for value, label in ((50, "dog"), (100, "cup"), (0, "cat")):
        session.dispatch(slider.id, "input", {"value": value})
        assert overlay.to_json()["props"]["boxes"][0]["label"] == label


@pytest.mark.integration
async def test_a_video_without_a_decoder_says_so_and_a_bad_one_does_not_crash(monkeypatch):
    example = _load()
    monkeypatch.setattr(example, "detect", lambda data: [])

    def no_av(data):
        raise ImportError("av")

    monkeypatch.setattr(example, "video_frames", no_av)
    session = example.build_session()
    await _upload(session, [UploadedFile("a.mp4", "video/mp4", b"x")])
    assert _node(session, "imageoverlay").to_json()["props"]["src"] == ""

    def bad(data):
        raise ValueError("corrupt")

    monkeypatch.setattr(example, "video_frames", bad)
    await _upload(session, [UploadedFile("a.mp4", "video/mp4", b"x")])
    assert _node(session, "imageoverlay").to_json()["props"]["src"] == ""


@pytest.mark.integration
def test_frame_picking_is_even_and_capped():
    example = _load()
    assert example.pick_indices(5) == [0, 1, 2, 3, 4]
    picks = example.pick_indices(1000)
    assert len(picks) == example.MAX_FRAMES and picks[0] == 0 and picks[-1] == 999
    assert picks == sorted(set(picks))

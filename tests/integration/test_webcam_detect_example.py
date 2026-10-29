"""The live webcam demo (examples/webcam_detect.py) stays runnable (IND-64).

The detector is replaced by a stub, so this needs no model library: it checks the wiring, that a
frame reaching the Camera handler comes out as an image and boxes on the overlay together.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from indah.live import CameraFrame

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "webcam_detect.py"
BOX = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "cup", "score": 0.9}


def _load():
    spec = importlib.util.spec_from_file_location("webcam_detect_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node(session, node_type):
    return next(c for c in session._by_id.values() if c.type == node_type)


@pytest.mark.integration
async def test_a_frame_becomes_a_picture_with_boxes(monkeypatch):
    example = _load()
    monkeypatch.setattr(example, "detect", lambda data: [BOX] if data == b"jpeg" else [])
    session = example.build_session()
    camera = _node(session, "camera")

    result = session.dispatch(camera.id, "frame", {"frame": CameraFrame(b"jpeg", seq=1)})
    assert result is not None and result.coro is not None
    await result.coro

    overlay = _node(session, "imageoverlay").to_json()["props"]
    assert overlay["src"].startswith("data:image/jpeg;base64,")
    assert overlay["boxes"] == [BOX]


@pytest.mark.integration
async def test_an_empty_frame_clears_the_boxes(monkeypatch):
    example = _load()
    answers = iter([[BOX], []])
    monkeypatch.setattr(example, "detect", lambda data: next(answers))
    session = example.build_session()
    camera = _node(session, "camera")
    for seq in (1, 2):
        result = session.dispatch(camera.id, "frame", {"frame": CameraFrame(b"x", seq=seq)})
        await result.coro
    assert _node(session, "imageoverlay").to_json()["props"]["boxes"] == []
    await asyncio.sleep(0)


@pytest.mark.integration
def test_the_module_app_serves_live_only_with_a_websocket_library():
    example = _load()
    assert (example.app.state.live is not None) == example._has_websockets()

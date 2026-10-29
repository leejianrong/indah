"""The live microphone demo (examples/mic_transcribe.py) stays runnable (IND-65).

The model is replaced by a stub, so this needs no model library (nor numpy): it checks the
wiring, that streamed audio updates a partial transcript, closes sentences, and that a recorded
take is transcribed in one go.
"""

import importlib.util
import io
import struct
import wave
from pathlib import Path

import pytest

from indah.live import AudioChunk

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mic_transcribe.py"
SECOND = b"\x00\x00" * 16000


def _load():
    spec = importlib.util.spec_from_file_location("mic_transcribe_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nodes(session, node_type):
    return [c for c in session._by_id.values() if c.type == node_type]


def _texts(session) -> str:
    """Every string on the page, with emphasis shown as ``*...*``."""
    out: list[str] = []

    def strings(value, em: bool = False) -> None:
        if isinstance(value, str):
            out.append(f"*{value}*" if em else value)
        elif isinstance(value, list):
            for item in value:
                strings(item, em)
        elif isinstance(value, dict):
            for item in value.values():
                strings(item, em or value.get("tag") == "em")

    def walk(node: dict) -> None:
        strings(node["props"].get("blocks") or node["props"].get("text"))
        for child in node.get("children", []):
            walk(child)

    walk(session.snapshot())
    return " | ".join(out)


async def _feed(session, chunk):
    mic = _nodes(session, "microphone")[0]
    result = session.dispatch(mic.id, "audio", {"chunk": chunk})
    if result is not None and result.coro is not None:
        await result.coro


@pytest.mark.integration
async def test_audio_updates_a_partial_transcript_then_closes_the_sentence(monkeypatch):
    example = _load()
    monkeypatch.setattr(example, "_pcm_to_float", lambda data: data)
    heard = []
    monkeypatch.setattr(example, "transcribe", lambda data, rate: heard.append(len(data)) or "hi")
    session = example.build_session()

    await _feed(session, AudioChunk(SECOND, seq=1))
    assert heard == []  # under two seconds: no model run yet
    await _feed(session, AudioChunk(SECOND, seq=2))
    assert heard == [2 * len(SECOND)]
    assert "*hi*" in _texts(session)

    for seq in range(3, 13):  # past 12 s the sentence is closed and the buffer starts over
        await _feed(session, AudioChunk(SECOND, seq=seq))
    assert "hi" in _texts(session) and "*hi*" not in _texts(session)


@pytest.mark.integration
async def test_a_recorded_take_is_transcribed_in_one_go(monkeypatch):
    example = _load()
    monkeypatch.setattr(example, "_pcm_to_float", lambda data: list(data[:4]))
    monkeypatch.setattr(example, "transcribe", lambda samples, rate: f"rate {rate}")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<4h", 1, 2, 3, 4))
    session = example.build_session()
    await _feed(session, AudioChunk(buf.getvalue(), "audio/wav"))
    assert "rate 16000" in _texts(session)


@pytest.mark.integration
def test_the_module_app_serves_live_only_with_a_websocket_library():
    example = _load()
    assert (example.app.state.live is not None) == example._has_websockets()

"""Live speech recognition from your microphone, indah-style (IND-65, ADR-0045).

Press "Start microphone" and talk: the browser streams 16 kHz mono audio, and about every two
seconds the server runs Whisper over the sentence so far and updates the transcript. A sentence
is closed after 12 seconds and a new one starts, so the work per step stays bounded.

This is the Tier 1 demo: audio travels over an opt-in WebSocket (``create_app(live=True)``, which
needs ``pip install "indah[live]"``), so it is meant for a machine that passes WebSockets (your
laptop, Runpod, your own server). Where it cannot, for example in Colab, the page records a take
instead and sends it when you press Stop; the same handler transcribes it in one go.

The model is slower than speech at times. Audio waits in a bounded queue (2 s by default) and the
oldest is dropped past that, which the chunk reports as ``dropped_before``; the transcript then
skips ahead rather than falling further behind. The model runs off the event loop
(``asyncio.to_thread``).

The browser only hands out the microphone on ``https://`` pages or ``localhost``.

Run it with:  python examples/mic_transcribe.py
Needs:        pip install "indah[live]" transformers torch numpy
              (transformers, torch and numpy are this demo's own dependencies, not indah's)
"""

import asyncio
import importlib.util
import io
import threading
import wave

import indah
from indah import AudioChunk, Card, Column, Microphone, Session, Signal, Text, create_app

RATE = 16000
MODEL = "openai/whisper-tiny.en"
STEP_SECONDS = 2.0  # run the model after this much new audio
SEGMENT_SECONDS = 12.0  # close the sentence after this much audio

_pipe = None
_lock = threading.Lock()


def transcribe(samples, rate: int = RATE) -> str:
    """Text for float32 mono ``samples`` in [-1, 1] (the model loads on first use, so importing
    this module needs no model library)."""
    global _pipe
    with _lock:
        if _pipe is None:
            from transformers import pipeline

            _pipe = pipeline("automatic-speech-recognition", model=MODEL)
        return _pipe({"raw": samples, "sampling_rate": rate})["text"].strip()


def _pcm_to_float(data: bytes):
    import numpy as np

    return np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0


def _wav_to_float(data: bytes):
    """Float samples and rate from a 16-bit mono WAV take (the record-then-upload fallback)."""
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
        return _pcm_to_float(w.readframes(w.getnframes())), rate


def build_session() -> Session:
    """A fresh per-viewer graph: a microphone in, the transcript out."""
    done: Signal[str] = Signal("")  # closed sentences
    partial: Signal[str] = Signal("")  # the sentence being heard
    status: Signal[str] = Signal("_Press Start microphone and speak._")
    pending: list[bytes] = []  # PCM of the current sentence
    state = {"fresh": 0, "gaps": 0}  # bytes since the last model run; chunks dropped

    def seconds(nbytes: int) -> float:
        return nbytes / 2 / RATE

    async def on_audio(chunk: AudioChunk) -> None:
        if chunk.content_type == "audio/wav":  # a recorded take: one go
            samples, rate = _wav_to_float(chunk.data)
            status.set("_Transcribing your recording..._")
            text = await asyncio.to_thread(transcribe, samples, rate)
            indah.batch(
                lambda: (
                    done.set(f"{done.value} {text}".strip()),
                    status.set("_Done. Press Start microphone for another take._"),
                )
            )
            return
        state["gaps"] += chunk.dropped_before
        pending.append(chunk.data)
        state["fresh"] += chunk.size
        total = sum(len(p) for p in pending)
        if seconds(state["fresh"]) < STEP_SECONDS and seconds(total) < SEGMENT_SECONDS:
            return
        state["fresh"] = 0
        samples = _pcm_to_float(b"".join(pending))
        text = await asyncio.to_thread(transcribe, samples, RATE)
        closing = seconds(total) >= SEGMENT_SECONDS

        def update() -> None:
            if closing:
                done.set(f"{done.value} {text}".strip())
                partial.set("")
            else:
                partial.set(text)
            gaps = state["gaps"]
            status.set(
                f"Heard {seconds(total):.0f} s of this sentence"
                + (f"; skipped {gaps} chunks to keep up" if gaps else "")
            )

        indah.batch(update)
        if closing:
            pending.clear()

    mic = Microphone(on_audio, label="Your microphone", sample_rate=RATE)

    return Session(
        Column(
            children=[
                Text(
                    "# Live transcription\n\n"
                    "Whisper turns your speech into text as you talk, on the server. The model "
                    "re-reads the sentence every couple of seconds, so words can change as more "
                    "context arrives.",
                    markdown=True,
                ),
                Card(title="Microphone", children=[mic]),
                Card(
                    title="Transcript",
                    children=[
                        Text(
                            lambda: (
                                (
                                    (done.value + " " if done.value else "")
                                    + (f"*{partial.value}*" if partial.value else "")
                                ).strip()
                                or "_Nothing heard yet._"
                            ),
                            markdown=True,
                        ),
                        Text(lambda: status.value, markdown=True),
                        Text(lambda: f"Audio over {mic.transport.value}"),
                    ],
                ),
            ]
        )
    )


def _has_websockets() -> bool:
    return importlib.util.find_spec("websockets") is not None


# live=True only when a WebSocket library is installed; without one the demo records takes.
app = create_app(session_factory=build_session, live=_has_websockets(), max_upload_mb=8)


if __name__ == "__main__":
    indah.launch(app)

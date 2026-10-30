"""Audio analysis: pick a vowel, an instrument note or a spoken phrase and watch its
spectrogram stream in, next to its waveform and a live level meter.

The instruments and the speech are **real recordings**, bundled in
``examples/audio_samples/`` (about 500 KB), each credited in the app and in
``examples/audio_samples/ATTRIBUTION.txt``:

- **Violin, piano, alto saxophone**: one note each (about 2 s) from the University of
  Iowa Musical Instrument Samples by Lawrence Fritts
  (https://theremin.music.uiowa.edu/MIS.html), free to use without restrictions.
- **Speech**: about 7 s of "A Gift" by Amy Lowell, read by Algy Pug for LibriVox
  (https://librivox.org/a-gift-by-amy-lowell/), public domain.

The five **vowels** (/i/ /e/ /a/ /o/ /u/) stay synthesised, and are labelled as a
textbook model: a harmonic buzz shaped by resonant "formant" peaks at the classic
Peterson & Barney (1952) average adult formant frequencies. That is how real vowels
work (the vocal folds make a harmonic-rich buzz, the vocal tract's resonances shape
which harmonics come through loud), but it is a model, not a voice.

The recordings are found next to this file (``audio_samples/``). Where the file has no
folder beside it (a Colab notebook, a single-file Space) they are downloaded once from
GitHub into a temp folder; if that fails the demo still runs, with the vowels only.

``indah.Audio`` renders a native browser ``<audio controls>`` element, and there is
no way for Python to read back its playhead position today - so the spectrogram
doesn't chase play head, it streams in on its own timer when you click "Stream
spectrogram", independent of whether audio is playing. True playhead sync is a
small framework gap, not something this demo fakes.

Run it with:  python examples/audio_analysis.py
"""

from __future__ import annotations

import asyncio
import io
import math
import tempfile
import urllib.parse
import urllib.request
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

import indah

SR = 22_050  # sample rate of the synthesised vowels, Hz

# -- Peterson & Barney (1952)-style average adult formant frequencies (Hz) ---------
# F1/F2/F3 per vowel. These are the classic textbook numbers repeated in every
# intro phonetics course - a documented fact about how vowels sound, not audio.
_VOWEL_FORMANTS: dict[str, tuple[float, float, float]] = {
    "i": (270, 2290, 3010),  # "ee" as in "heed"
    "e": (530, 1840, 2480),  # "eh" as in "head"
    "a": (730, 1090, 2440),  # "ah" as in "hod"
    "o": (570, 840, 2410),  # "oh" as in "hawed"
    "u": (300, 870, 2240),  # "oo" as in "who'd"
}

_VOWEL_LABELS = {
    "i": "Vowel /i/ (heed) (textbook model)",
    "e": "Vowel /e/ (head) (textbook model)",
    "a": "Vowel /a/ (hod) (textbook model)",
    "o": "Vowel /o/ (hawed) (textbook model)",
    "u": "Vowel /u/ (who'd) (textbook model)",
}

_VOWEL_CREDIT = (
    "**Synthesised, not a recording.** A textbook source-filter model: a harmonic buzz "
    "shaped by the average adult formants of Peterson & Barney (1952)."
)

# -- the real recordings -------------------------------------------------------

AUDIO_DIR = Path(__file__).resolve().parent / "audio_samples" if "__file__" in globals() else None
_RAW_URL = "https://raw.githubusercontent.com/leejianrong/indah/main/examples/audio_samples/"

_MIS = (
    "University of Iowa Musical Instrument Samples, recorded by Lawrence Fritts - "
    "[theremin.music.uiowa.edu/{page}](https://theremin.music.uiowa.edu/{page}). "
    "Licence: free to use without restrictions."
)
_LIBRIVOX = (
    '"A Gift" by Amy Lowell, read by Algy Pug for LibriVox - '
    "[librivox.org/a-gift-by-amy-lowell](https://librivox.org/a-gift-by-amy-lowell/). "
    "Licence: public domain."
)


@dataclass(frozen=True)
class Recording:
    file: str
    label: str
    kind: Literal["instrument", "speech"]
    credit: str
    frame_size: int  # FFT window (samples): 512 at 16 kHz is a speech-style 32 ms window


RECORDINGS: dict[str, Recording] = {
    "instrument:violin": Recording(
        "violin.wav",
        "Violin (A4)",
        "instrument",
        "**Recording.** Violin, A4, arco, mf. " + _MIS.format(page="MISviolin.html"),
        1024,
    ),
    "instrument:piano": Recording(
        "piano.wav",
        "Piano (C4)",
        "instrument",
        "**Recording.** Piano, C4, mf. " + _MIS.format(page="MISpiano.html"),
        1024,
    ),
    "instrument:saxophone": Recording(
        "saxophone.wav",
        "Alto saxophone (C4)",
        "instrument",
        "**Recording.** Alto saxophone, about 264 Hz, no vibrato, mf. "
        + _MIS.format(page="MISaltosaxophone.html"),
        1024,
    ),
    "speech:librivox": Recording(
        "speech.wav",
        'Speech: "A Gift" (LibriVox)',
        "speech",
        "**Recording.** " + _LIBRIVOX,
        512,
    ),
}


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 - a fixed https URL
        return r.read()


def load_recordings(
    folder: Path | None, fetch: Callable[[str], bytes] = _fetch
) -> dict[str, tuple[np.ndarray, int]]:
    """Read each recording as ``(float samples, sample rate)``, keyed like ``RECORDINGS``.

    ``folder`` is the bundled ``audio_samples/`` directory; a file missing from it is
    downloaded from GitHub into it (or, when there is no such folder or it cannot be
    written, into a temp folder). A file that cannot be had is left out - the demo then
    runs with fewer samples rather than failing.
    """
    found: dict[str, tuple[np.ndarray, int]] = {}
    cache = folder
    for key, rec in RECORDINGS.items():
        path = (cache / rec.file) if cache else None
        if path is None or not path.exists():
            try:
                data = fetch(_RAW_URL + rec.file)
                if cache is None or not _writable(cache):
                    cache = Path(tempfile.gettempdir()) / "indah-audio-samples"
                cache.mkdir(parents=True, exist_ok=True)
                path = cache / rec.file
                path.write_bytes(data)
            except Exception:  # noqa: BLE001 - offline: skip this clip, keep the demo up
                continue
        try:
            with wave.open(str(path)) as w:
                sr = w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            found[key] = (pcm.astype(np.float64) / 32768.0, sr)
        except Exception:  # noqa: BLE001 - a corrupt download: skip it
            continue
    return found


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _envelope(n: int, sr: int, *, attack: float, release: float) -> np.ndarray:
    """A simple attack/sustain/release amplitude envelope, linear ramps."""
    env = np.ones(n, dtype=np.float64)
    a = min(int(attack * sr), n)
    r = min(int(release * sr), n - a)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a)
    if r > 0:
        env[n - r :] = np.linspace(1.0, 0.0, r)
    return env


def _normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) if x.size else 0.0
    if m < 1e-9:
        return x
    return (x / m) * peak


def synth_vowel(
    vowel: str, *, f0: float = 120.0, duration: float = 1.6, sr: int = SR
) -> np.ndarray:
    """A source-filter vowel: a harmonic buzz at ``f0`` shaped by the vowel's
    F1/F2/F3 formants, via additive synthesis (each harmonic weighted by how close
    it sits to a formant peak - the additive-synthesis alternative to an explicit
    bandpass filter bank, same idea as a parallel-formant vocoder)."""
    f1, f2, f3 = _VOWEL_FORMANTS[vowel]
    formants = [(f1, 1.0, 80.0), (f2, 0.6, 100.0), (f3, 0.3, 130.0)]  # (center, weight, bandwidth)
    n = int(duration * sr)
    t = np.arange(n) / sr
    signal = np.zeros(n, dtype=np.float64)
    n_harmonics = int((sr / 2) / f0)
    for k in range(1, n_harmonics + 1):
        freq = f0 * k
        if freq >= sr / 2:
            break
        source_amp = 1.0 / k  # a glottal buzz's natural spectral tilt (~ -1/f)
        gain = sum(w * math.exp(-0.5 * ((freq - fc) / bw) ** 2) for fc, w, bw in formants)
        gain = max(gain, 0.02)  # a small floor so between-formant harmonics aren't silent
        signal += source_amp * gain * np.sin(2 * np.pi * freq * t)
    signal *= _envelope(n, sr, attack=0.03, release=0.15)
    return _normalize(signal)


def to_wav_bytes(samples: np.ndarray, sr: int = SR) -> bytes:
    """16-bit PCM mono WAV, via the stdlib ``wave`` module - no extra dependency."""
    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


# -- spectrogram: a manual sliding-window FFT (numpy.fft only, no scipy) -----------

FRAME_SIZE = 1024
HOP = 256
MAX_FREQ_HZ = 6_000.0  # covers every vowel formant and instrument harmonic used here
FLOOR_DB = -80.0


def _hann(n: int) -> np.ndarray:
    if n <= 1:
        return np.ones(n, dtype=np.float64)
    i = np.arange(n)
    return 0.5 - 0.5 * np.cos(2 * np.pi * i / (n - 1))


def spectrogram_columns(
    samples: np.ndarray,
    *,
    sr: int = SR,
    frame_size: int = FRAME_SIZE,
    hop: int = HOP,
    max_freq: float = MAX_FREQ_HZ,
    floor_db: float = FLOOR_DB,
) -> tuple[list[list[float]], list[tuple[float, float]], list[float]]:
    """A time->frequency-magnitude(dB) column per hop, plus each frame's (rms, peak)
    in the time domain - a manual sliding-window FFT via ``numpy.fft.rfft``.

    Returns ``(columns, levels, freqs)``: ``columns`` is column-major
    (``columns[t][f]``, ready for :class:`indah.Heatmap`), ``levels`` is one
    ``(rms, peak)`` pair per column (for the live level-meter Stats), and ``freqs``
    is the retained bin centre frequencies (Hz), below ``max_freq``.
    """
    window = _hann(frame_size)
    # A full-scale sinusoid, windowed and FFT'd, peaks at about window.sum()/2 in raw
    # magnitude - normalise by that so "0 dB" means "as loud as a full-scale tone",
    # not an arbitrary raw-FFT unit. Without this, real harmonic energy routinely
    # exceeds a magnitude of 1 and everything above it clips flat at the ceiling.
    reference = window.sum() / 2.0
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sr)
    max_bin = int(np.searchsorted(freqs, max_freq))
    columns: list[list[float]] = []
    levels: list[tuple[float, float]] = []
    n = len(samples)
    starts = range(0, max(1, n - frame_size), hop) if n > frame_size else [0]
    for start in starts:
        frame = samples[start : start + frame_size]
        if len(frame) < frame_size:
            frame = np.pad(frame, (0, frame_size - len(frame)))
        spectrum = np.fft.rfft(frame * window)
        magnitude = np.abs(spectrum)[:max_bin] / reference
        db = np.clip(20.0 * np.log10(magnitude + 1e-6), floor_db, 0.0)
        columns.append([float(v) for v in db])
        levels.append((float(np.sqrt(np.mean(frame**2))), float(np.max(np.abs(frame)))))
    return columns, levels, [float(f) for f in freqs[:max_bin]]


def _waveform_svg(samples: np.ndarray, *, width: int = 640, height: int = 160) -> str:
    """A lightweight inline-SVG waveform (no matplotlib - this demo's only real
    dependency is numpy), encoded as a ``data:`` URI for :class:`indah.Plot`."""
    n = len(samples)
    points_n = min(500, n)
    idx = np.linspace(0, n - 1, points_n).astype(int)
    ys = samples[idx]
    xs_px = np.linspace(0, width, points_n)
    ys_px = (1.0 - (ys * 0.45 + 0.5)) * height
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs_px, ys_px, strict=True))
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
        f"<rect width='{width}' height='{height}' rx='12' fill='#8d8691' fill-opacity='0.14'/>"
        f"<line x1='0' y1='{height / 2:.1f}' x2='{width}' y2='{height / 2:.1f}' "
        f"stroke='#8d8691' stroke-opacity='0.5' stroke-width='1'/>"
        f"<polyline points='{points}' fill='none' stroke='#b5296b' stroke-width='1.5'/>"
        f"</svg>"
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


@dataclass
class Sample:
    key: str
    label: str
    kind: Literal["vowel", "instrument", "speech"]
    samples: np.ndarray
    sr: int
    credit: str  # Markdown shown under the player: who made this and under what licence
    wav_bytes: bytes = field(repr=False)
    waveform_svg: str = field(repr=False)
    spectrogram: list[list[float]] = field(repr=False)
    levels: list[tuple[float, float]] = field(repr=False)
    freqs: list[float] = field(repr=False)


def _build_sample(
    key: str,
    label: str,
    kind: Literal["vowel", "instrument", "speech"],
    samples: np.ndarray,
    *,
    sr: int = SR,
    credit: str = "",
    frame_size: int = FRAME_SIZE,
) -> Sample:
    cols, levels, freqs = spectrogram_columns(samples, sr=sr, frame_size=frame_size)
    return Sample(
        key=key,
        label=label,
        kind=kind,
        samples=samples,
        sr=sr,
        credit=credit,
        wav_bytes=to_wav_bytes(samples, sr),
        waveform_svg=_waveform_svg(samples),
        spectrogram=cols,
        levels=levels,
        freqs=freqs,
    )


def build_samples() -> dict[str, Sample]:
    """Load the recordings and synthesise the vowels once (audio + waveform SVG +
    spectrogram columns) - the "at import/build time" step. Streaming later just
    replays the precomputed spectrogram columns; nothing is recomputed per click."""
    samples: dict[str, Sample] = {}
    recorded = load_recordings(AUDIO_DIR)
    for key, rec in RECORDINGS.items():
        if key in recorded:
            audio, sr = recorded[key]
            samples[key] = _build_sample(
                key, rec.label, rec.kind, audio, sr=sr, credit=rec.credit, frame_size=rec.frame_size
            )
    for vowel, label in _VOWEL_LABELS.items():
        key = f"vowel:{vowel}"
        samples[key] = _build_sample(key, label, "vowel", synth_vowel(vowel), credit=_VOWEL_CREDIT)
    return samples


SAMPLES: dict[str, Sample] = build_samples()
DEFAULT_KEY = "speech:librivox" if "speech:librivox" in SAMPLES else "vowel:a"


def _fmt_db(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f} dB"


def _amp_to_db(amp: float) -> float:
    return 20.0 * math.log10(max(amp, 1e-6))


class AudioAnalysisDemo:
    """Per-session state: which sample is picked, and the streaming-spectrogram
    run (mirrors ``TrainingMonitor`` in training_dashboard.py - a plain object so
    the streaming loop reads like ordinary code)."""

    def __init__(self) -> None:
        self.picker = indah.Signal(DEFAULT_KEY)
        self.running = indah.Signal(False)
        self.status = indah.Signal('Pick a sample, then click "Stream spectrogram".')
        self.spectrogram = indah.Heatmap(
            colormap="magma",
            zmin=FLOOR_DB,
            zmax=0.0,
            title="Spectrogram (streaming)",
            x_label="time",
            y_label="frequency (Hz, 0-6000)",
            height=260,
        )
        self.rms_db: indah.Signal = indah.Signal(None)
        self.peak_db: indah.Signal = indah.Signal(None)

    def current(self) -> Sample:
        return SAMPLES[self.picker.value]

    async def analyze(self) -> None:
        if self.running.value:
            return
        self.running.set(True)
        self.spectrogram.clear()
        self.rms_db.set(None)
        self.peak_db.set(None)
        sample = self.current()
        self.status.set(f"Streaming {sample.label} spectrogram...")
        try:
            for column, (rms, peak) in zip(sample.spectrogram, sample.levels, strict=True):
                self.spectrogram.push_column(column)
                self.rms_db.set(_amp_to_db(rms))
                self.peak_db.set(_amp_to_db(peak))
                await asyncio.sleep(0.02)  # the "streaming" feel - audio is pre-generated
            self.status.set(f"Done - {sample.label} ({len(sample.spectrogram)} columns).")
        finally:
            self.running.set(False)


def build() -> indah.Session:
    m = AudioAnalysisDemo()

    options = [(s.key, s.label) for s in SAMPLES.values()]

    controls = indah.Card(
        title="Sample",
        children=[
            indah.Select(m.picker, options=options, label="Recording or vowel"),
            indah.Audio(lambda: m.current().wav_bytes, media_type="audio/wav"),
            indah.Text(lambda: m.current().credit, markdown=True),
            indah.Button("Stream spectrogram", on_click=m.analyze),
            indah.Spinner(active=m.running, label="streaming..."),
            indah.Text(lambda: m.status.value),
        ],
    )

    levels = indah.Row(
        children=[
            indah.Stat(value=lambda: _fmt_db(m.rms_db.value), label="RMS level"),
            indah.Stat(value=lambda: _fmt_db(m.peak_db.value), label="Peak level"),
        ],
    )

    workspace = indah.Column(
        children=[
            levels,
            indah.Card(
                title="Waveform",
                children=[indah.Plot(lambda: m.current().waveform_svg, alt="waveform")],
            ),
            indah.Card(children=[m.spectrogram]),
        ]
    )

    intro = indah.Text(
        "# Audio analysis: spectrograms of real recordings\n\n"
        "Violin, piano and saxophone notes and a spoken phrase are **real recordings**, "
        "credited under the player; the vowels are a **synthesised textbook model** of "
        "speech formants. Pick one, then stream its spectrogram in column by column "
        "via a manual sliding-window FFT (`numpy.fft`, no scipy/librosa).",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, workspace])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)

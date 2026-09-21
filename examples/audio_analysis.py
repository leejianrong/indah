"""Audio analysis: pick a vowel or an instrument note and watch its spectrogram
stream in, next to its waveform and a live level meter.

Every sample here is **synthesized, not recorded** - there is no audio file
anywhere in this repo. Bundling real recorded speech or instrument audio into a
public Apache-2.0 demo raises licensing questions (whose voice, whose performance,
under what terms) this project has deliberately stayed out of (see
docs/DEMOS-DOCS-REVAMP.md / docs/DEMOS-DOCS-ROUND2.md's licensing sections, and
map_poster.py's AGPL note for the same instinct applied to a different demo). So
instead of a recording, each sample is built from real published acoustic data:

- **Vowels** (/i/ /e/ /a/ /o/ /u/) use a source-filter model - a harmonic buzz
  excitation shaped by resonant "formant" peaks at the classic Peterson & Barney
  (1952) average adult formant frequencies (F1/F2/F3). Those numbers are
  well-documented phonetics facts, not copyrightable audio, and shaping a buzz with
  them is *how real vowels work*: the vocal folds produce a harmonic-rich buzz, the
  vocal tract's resonances (formants) shape which harmonics come through loud. The
  resulting spectrograms show the same formant-band structure a spectrogram of a
  real human vowel shows - that's the teaching point.
- **Instruments** (violin, piano, saxophone) use additive synthesis built around
  each instrument's real, well-documented spectral character: a violin's rich
  harmonic series with a slight bowed vibrato (frequency modulation); a piano's
  fast attack, per-harmonic exponential decay, and *inharmonicity* - a real
  physical property of a struck string, where partials land a little sharp of an
  exact integer multiple of the fundamental (``f_n ~= n*f0*sqrt(1 + B*n^2)``); a
  saxophone's emphasis on odd harmonics, a formant-like resonance peak, and a
  reed-buzz attack transient.

These are physically-motivated approximations, not samples of a real violin or a
real voice - please don't mistake them for recordings.

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
import urllib.parse
import wave
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

import indah

SR = 22_050  # mono sample rate, Hz - plenty for speech/instrument formant structure

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
    "i": "/i/ (heed)",
    "e": "/e/ (head)",
    "a": "/a/ (hod)",
    "o": "/o/ (hawed)",
    "u": "/u/ (who'd)",
}

# -- instrument notes ----------------------------------------------------------
_INSTRUMENT_F0 = {"violin": 440.0, "piano": 261.63, "saxophone": 233.08}  # A4, C4, Bb3
_INSTRUMENT_LABELS = {
    "violin": "Violin (A4)",
    "piano": "Piano (C4)",
    "saxophone": "Saxophone (Bb3)",
}


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


def synth_violin(*, f0: float = 440.0, duration: float = 1.8, sr: int = SR) -> np.ndarray:
    """A rich odd+even harmonic series with a bowed attack and a slight vibrato
    (frequency modulation ~5.5 Hz) - the FM is applied via a phase integral so the
    frequency actually wobbles, not just the amplitude."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    vibrato = 1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t)
    n_harmonics = int((sr / 2) / f0)
    signal = np.zeros(n, dtype=np.float64)
    for k in range(1, n_harmonics + 1):
        inst_freq = f0 * k * vibrato
        if float(np.max(inst_freq)) >= sr / 2:
            break
        phase = 2 * np.pi * np.cumsum(inst_freq) / sr
        amp = 1.0 / (k**1.2)
        signal += amp * np.sin(phase)
    signal *= _envelope(n, sr, attack=0.08, release=0.2)
    return _normalize(signal)


def synth_piano(
    *, f0: float = 261.63, duration: float = 2.2, sr: int = SR, inharmonicity: float = 0.0004
) -> np.ndarray:
    """A fast-attack, per-harmonic exponentially-decaying tone with inharmonicity -
    a struck string's partials land a little sharp of an exact integer multiple of
    the fundamental: ``f_n ~= n*f0*sqrt(1 + B*n^2)`` (a real, well-documented
    property of piano strings, B here a small stretch coefficient)."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    signal = np.zeros(n, dtype=np.float64)
    for k in range(1, 21):
        freq = k * f0 * math.sqrt(1 + inharmonicity * k**2)
        if freq >= sr / 2:
            break
        decay = 2.5 + 0.55 * k  # higher partials die out faster
        amp = (1.0 / k) * np.exp(-decay * t)
        signal += amp * np.sin(2 * np.pi * freq * t)
    signal *= _envelope(n, sr, attack=0.005, release=0.05)
    return _normalize(signal)


def synth_saxophone(*, f0: float = 233.08, duration: float = 1.8, sr: int = SR) -> np.ndarray:
    """Strong odd-harmonic emphasis (a reed instrument's clarinet-like character),
    a formant-like resonance bump around 1 kHz, and a short reed-buzz (noise)
    attack transient."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    formant_center, formant_bw = 1000.0, 500.0
    n_harmonics = int((sr / 2) / f0)
    signal = np.zeros(n, dtype=np.float64)
    for k in range(1, n_harmonics + 1):
        freq = f0 * k
        if freq >= sr / 2:
            break
        odd_emphasis = 1.0 if k % 2 else 0.35
        base_amp = odd_emphasis / k
        formant_gain = 1.0 + 1.5 * math.exp(-0.5 * ((freq - formant_center) / formant_bw) ** 2)
        signal += base_amp * formant_gain * np.sin(2 * np.pi * freq * t)
    rng = np.random.default_rng(42)  # deterministic - a fixed "reed" for reproducible builds
    attack_len = int(0.015 * sr)
    noise_env = np.zeros(n, dtype=np.float64)
    noise_env[:attack_len] = np.linspace(1.0, 0.0, attack_len)
    signal += 0.15 * rng.normal(0.0, 1.0, n) * noise_env
    signal *= _envelope(n, sr, attack=0.04, release=0.12)
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
        f"<rect width='{width}' height='{height}' rx='12' fill='#f3ebe0'/>"
        f"<line x1='0' y1='{height / 2:.1f}' x2='{width}' y2='{height / 2:.1f}' "
        f"stroke='#d8cabb' stroke-width='1'/>"
        f"<polyline points='{points}' fill='none' stroke='#b5296b' stroke-width='1.5'/>"
        f"</svg>"
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")


@dataclass
class Sample:
    key: str
    label: str
    kind: Literal["vowel", "instrument"]
    samples: np.ndarray
    wav_bytes: bytes = field(repr=False)
    waveform_svg: str = field(repr=False)
    spectrogram: list[list[float]] = field(repr=False)
    levels: list[tuple[float, float]] = field(repr=False)
    freqs: list[float] = field(repr=False)


def _build_sample(
    key: str, label: str, kind: Literal["vowel", "instrument"], samples: np.ndarray
) -> Sample:
    cols, levels, freqs = spectrogram_columns(samples)
    return Sample(
        key=key,
        label=label,
        kind=kind,
        samples=samples,
        wav_bytes=to_wav_bytes(samples),
        waveform_svg=_waveform_svg(samples),
        spectrogram=cols,
        levels=levels,
        freqs=freqs,
    )


def build_samples() -> dict[str, Sample]:
    """Synthesize every sample once (audio + waveform SVG + spectrogram columns) -
    the "at import/build time" generation step. Streaming later just replays the
    precomputed spectrogram columns; nothing is recomputed per click."""
    samples: dict[str, Sample] = {}
    for vowel, label in _VOWEL_LABELS.items():
        key = f"vowel:{vowel}"
        samples[key] = _build_sample(key, label, "vowel", synth_vowel(vowel))
    synths = {"violin": synth_violin, "piano": synth_piano, "saxophone": synth_saxophone}
    for name, label in _INSTRUMENT_LABELS.items():
        samples[f"instrument:{name}"] = _build_sample(
            f"instrument:{name}", label, "instrument", synths[name](f0=_INSTRUMENT_F0[name])
        )
    return samples


SAMPLES: dict[str, Sample] = build_samples()
DEFAULT_KEY = "vowel:a"


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
            indah.Select(m.picker, options=options, label="Vowel or instrument"),
            indah.Audio(lambda: m.current().wav_bytes, media_type="audio/wav"),
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
        "# Audio analysis: spectrograms of synthesized speech and instruments\n\n"
        "Every clip here is **synthesized from real acoustic data** (published vowel "
        "formant frequencies, and well-documented instrument harmonic structure) - "
        "there are no recordings in this demo, by design (see the module docstring "
        "for why). Pick a sample, then stream its spectrogram in column by column "
        "via a manual sliding-window FFT (`numpy.fft`, no scipy/librosa).",
        markdown=True,
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[controls, workspace])])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)

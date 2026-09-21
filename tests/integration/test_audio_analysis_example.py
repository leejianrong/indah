"""The audio-analysis example (examples/audio_analysis.py) stays runnable, and its
synthesized samples are physically/acoustically sane - real formant structure per
vowel, real inharmonicity in the synthesized piano, real odd-harmonic emphasis in
the synthesized saxophone. Nothing here is a recording (see the module docstring
for why); ``numpy`` is this demo's own dependency, not indah's, so every test is
skipped (not failed) when it isn't installed, same pattern as
``test_upload_classify_example.py`` (onnxruntime) and ``test_map_poster_example.py``
(matplotlib).

Assertions are shape/energy/ordering sanity checks, not exact-value snapshots -
synthesis parameters can shift without breaking these tests, as long as the
physics they're meant to demonstrate still holds.
"""

import importlib.util
import sys
import wave
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import numpy as np  # noqa: E402

from indah.transport import Hub  # noqa: E402

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "audio_analysis.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("audio_analysis_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    # dataclasses (module has `from __future__ import annotations`) resolves field
    # types via sys.modules[cls.__module__] - it must be registered before exec
    # (same requirement as test_map_poster_example.py).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


# -- synthesis sanity ---------------------------------------------------------


@pytest.mark.integration
def test_every_sample_is_generated_with_sane_waveform_and_spectrogram_data():
    example = _load_example()
    assert len(example.SAMPLES) == 8  # 5 vowels + 3 instruments
    for sample in example.SAMPLES.values():
        # A real, bounded, non-silent waveform.
        assert sample.samples.ndim == 1
        assert sample.samples.size > example.SR  # at least a second of audio
        assert np.all(np.abs(sample.samples) <= 1.0 + 1e-9)
        assert np.sqrt(np.mean(sample.samples**2)) > 0.01  # not near-silent

        # A spectrogram with matching column/row shape and a plausible dB range.
        cols = np.array(sample.spectrogram)
        assert cols.shape[0] == len(sample.levels) > 0
        assert cols.shape[1] == len(sample.freqs) > 0
        assert cols.max() <= 0.0 + 1e-9
        assert cols.min() >= example.FLOOR_DB - 1e-9
        assert cols.max() > example.FLOOR_DB  # some real signal, not just the floor

        # WAV bytes round-trip through the stdlib `wave` module as real 16-bit PCM.
        import io

        with wave.open(io.BytesIO(sample.wav_bytes)) as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == example.SR
            assert w.getnframes() == sample.samples.size


@pytest.mark.integration
def test_vowel_spectrograms_show_distinct_formant_structure():
    """The actual teaching point: /i/ (a documented low F1 ~270 Hz) and /a/ (a
    documented high F1 ~730 Hz) should show that contrast in their spectrograms -
    the low-frequency energy in /a/ sits meaningfully higher than in /i/."""
    example = _load_example()

    def low_band_centroid(key: str) -> float:
        sample = example.SAMPLES[key]
        freqs = np.array(sample.freqs)
        avg_db = np.array(sample.spectrogram).mean(axis=0)
        band = freqs <= 900  # covers every vowel's F1 used here
        linear = 10 ** (avg_db[band] / 20.0)
        return float(np.average(freqs[band], weights=linear))

    i_centroid = low_band_centroid("vowel:i")
    a_centroid = low_band_centroid("vowel:a")
    assert i_centroid < a_centroid, (
        f"/i/'s low-band energy ({i_centroid:.0f} Hz) should sit below /a/'s "
        f"({a_centroid:.0f} Hz), matching their real F1 values"
    )


@pytest.mark.integration
def test_piano_partials_are_stretched_sharp_by_inharmonicity():
    """A struck piano string's partials land a little sharp of an exact integer
    multiple of the fundamental (f_n ~= n*f0*sqrt(1+B*n^2)) - a real, documented
    physical property. Higher partials should drift further from their nominal
    (perfectly harmonic) frequency than lower ones."""
    example = _load_example()
    f0 = 261.63
    signal = example.synth_piano(f0=f0, duration=1.0)
    frame = signal[:8192]  # early in the note, before high partials decay away
    window = np.hanning(len(frame))
    freqs = np.fft.rfftfreq(len(frame), d=1.0 / example.SR)
    magnitude = np.abs(np.fft.rfft(frame * window))

    def peak_shift(harmonic: int) -> float:
        nominal = harmonic * f0
        band = (freqs >= nominal - 60) & (freqs <= nominal + 60)
        peak_freq = freqs[band][np.argmax(magnitude[band])]
        return peak_freq - nominal

    shift_2 = peak_shift(2)
    shift_5 = peak_shift(5)
    shift_10 = peak_shift(10)
    assert shift_2 >= -5.0  # the low partials are ~harmonic (negligible stretch)
    assert 0 < shift_5 < shift_10  # stretch grows with partial number
    assert shift_10 > 20.0  # the 10th partial is clearly, not just numerically, sharp


@pytest.mark.integration
def test_saxophone_emphasizes_odd_harmonics():
    """A real saxophone (like other single-reed instruments) favours odd harmonics
    over even ones - the fundamental should carry more energy than the 2nd
    harmonic, on average across the note."""
    example = _load_example()
    f0 = 233.08
    sample = example._build_sample("test", "test", "instrument", example.synth_saxophone(f0=f0))
    freqs = np.array(sample.freqs)
    avg_db = np.array(sample.spectrogram).mean(axis=0)

    def energy_near(target_hz: float) -> float:
        idx = int(np.argmin(np.abs(freqs - target_hz)))
        return float(avg_db[idx])

    assert energy_near(f0) > energy_near(2 * f0)


@pytest.mark.integration
def test_piano_attack_is_much_faster_than_violins_bowed_attack():
    """A struck piano note reaches full amplitude almost instantly; a bowed violin
    note swells in - the synthesized envelopes should reflect that contrast."""
    example = _load_example()
    piano = example.synth_piano(duration=1.0)
    violin = example.synth_violin(duration=1.0)

    def onset_ratio(signal: np.ndarray, sr: int) -> float:
        onset_rms = np.sqrt(np.mean(signal[: int(0.01 * sr)] ** 2))
        sustain_rms = np.sqrt(np.mean(signal[int(0.3 * sr) : int(0.4 * sr)] ** 2))
        return onset_rms / sustain_rms if sustain_rms > 0 else 0.0

    piano_ratio = onset_ratio(piano, example.SR)
    violin_ratio = onset_ratio(violin, example.SR)
    assert piano_ratio > violin_ratio  # piano is already loud at 10ms; violin isn't yet


# -- demo wiring ---------------------------------------------------------------


@pytest.mark.integration
def test_example_builds_a_session_with_the_expected_component_types():
    example = _load_example()
    session = example.build()
    types = {c.type for c in session._by_id.values()}
    assert {"select", "audio", "image", "heatmap", "stat", "button"} <= types


@pytest.mark.integration
async def test_streaming_pushes_one_heatmap_column_per_spectrogram_frame_and_updates_levels():
    example = _load_example()
    session = example.build()
    hub = Hub()
    session.bind_hub(hub)

    button = _by_type(session, "button")[0]
    stats = _by_type(session, "stat")
    result = session.dispatch(button.id, "click", {})
    assert result is not None and result.coro is not None  # async handler
    await result.coro

    appended_columns = [
        col
        for _, msg in hub.history()
        for change in msg.get("changes", [])
        if "append" in change and "z" in change["append"]
        for col in change["append"]["z"]
    ]
    default_sample = example.SAMPLES[example.DEFAULT_KEY]
    assert len(appended_columns) == len(default_sample.spectrogram)
    assert all(len(col) == len(default_sample.freqs) for col in appended_columns)

    # RMS/peak Stat tiles moved off their initial "-" placeholder.
    values = {s.static_props()["label"]: s.reactive_props()["value"]() for s in stats}
    assert all(v != "-" for v in values.values())


@pytest.mark.integration
async def test_changing_the_sample_selects_a_different_clip():
    example = _load_example()
    session = example.build()
    select = _by_type(session, "select")[0]
    audio = _by_type(session, "audio")[0]

    before = audio.reactive_props()["src"]()
    other_key = next(k for k in example.SAMPLES if k != example.DEFAULT_KEY)
    session.dispatch(select.id, "change", {"value": other_key})
    after = audio.reactive_props()["src"]()

    assert before.startswith("data:audio/wav;base64,")
    assert after.startswith("data:audio/wav;base64,")
    assert before != after

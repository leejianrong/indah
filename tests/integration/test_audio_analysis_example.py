"""The audio-analysis example (examples/audio_analysis.py) stays runnable. Its
instruments and its one speech clip are real recordings (examples/audio_samples/,
credited in ATTRIBUTION.txt and in the app); its vowels are a synthesised textbook
model with real formant structure. ``numpy`` is this demo's own dependency, not
indah's, so every test is skipped (not failed) when it isn't installed, same pattern as
``test_upload_classify_example.py`` (onnxruntime) and ``test_map_poster_example.py``
(matplotlib).

Assertions are shape/energy/ordering sanity checks, not exact-value snapshots -
synthesis parameters can shift without breaking these tests, as long as the
physics they're meant to demonstrate still holds.
"""

import importlib.util
import io
import json
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


# -- samples sanity -----------------------------------------------------------


@pytest.mark.integration
def test_every_sample_is_generated_with_sane_waveform_and_spectrogram_data():
    example = _load_example()
    assert len(example.SAMPLES) == 9  # 5 synthesised vowels + 3 instruments + 1 speech clip
    for sample in example.SAMPLES.values():
        # A real, bounded, non-silent waveform.
        assert sample.samples.ndim == 1
        assert sample.samples.size > sample.sr  # at least a second of audio
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
        with wave.open(io.BytesIO(sample.wav_bytes)) as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == sample.sr
            assert w.getnframes() == sample.samples.size


@pytest.mark.integration
def test_recordings_are_real_files_and_the_synthesised_vowels_say_so():
    example = _load_example()
    kinds = {k: s.kind for k, s in example.SAMPLES.items()}
    assert sorted(k for k, v in kinds.items() if v == "vowel") == [f"vowel:{v}" for v in "aeiou"]
    assert sorted(k for k, v in kinds.items() if v == "instrument") == [
        "instrument:piano",
        "instrument:saxophone",
        "instrument:violin",
    ]
    assert [k for k, v in kinds.items() if v == "speech"] == ["speech:librivox"]
    for key, sample in example.SAMPLES.items():
        if sample.kind == "vowel":
            assert "synthesi" in sample.credit.lower() and "textbook" in sample.credit.lower()
            assert "(textbook model)" in sample.label
        else:
            assert "synthesi" not in sample.credit.lower(), key


@pytest.mark.integration
def test_recordings_are_not_clipped_and_have_sensible_length():
    example = _load_example()
    for key, sample in example.SAMPLES.items():
        if sample.kind == "vowel":
            continue
        assert np.max(np.abs(sample.samples)) < 0.99, f"{key} is clipped"
        seconds = sample.samples.size / sample.sr
        if sample.kind == "speech":
            assert 5.0 <= seconds <= 10.0
        else:
            assert 1.5 <= seconds <= 2.5
        # a real recording has a noise floor between harmonics, unlike additive synthesis
        assert np.array(sample.spectrogram).mean() > example.FLOOR_DB + 3


@pytest.mark.integration
def test_bundled_audio_is_small_and_every_file_is_attributed():
    example = _load_example()
    folder = example.AUDIO_DIR
    wavs = sorted(folder.glob("*.wav"))
    assert [w.name for w in wavs] == ["piano.wav", "saxophone.wav", "speech.wav", "violin.wav"]
    assert sum(w.stat().st_size for w in wavs) < 600_000
    attribution = (folder / "ATTRIBUTION.txt").read_text()
    for w in wavs:
        assert w.name in attribution
    for url in (
        "https://theremin.music.uiowa.edu/MIS.html",
        "https://librivox.org/a-gift-by-amy-lowell/",
    ):
        assert url in attribution


@pytest.mark.integration
def test_every_recording_has_a_credit_with_name_source_link_and_licence():
    example = _load_example()
    for key, sample in example.SAMPLES.items():
        if sample.kind == "vowel":
            continue
        credit = sample.credit
        assert "](https://" in credit, key  # a source link
        assert "licence" in credit.lower(), key
    assert "Lawrence Fritts" in example.SAMPLES["instrument:violin"].credit
    assert "public domain" in example.SAMPLES["speech:librivox"].credit.lower()
    assert "Algy Pug" in example.SAMPLES["speech:librivox"].credit


@pytest.mark.integration
def test_a_missing_recordings_folder_is_fetched_and_a_failed_fetch_degrades_to_vowels(tmp_path):
    example = _load_example()
    seen: list[str] = []

    def failing_fetch(url: str) -> bytes:
        seen.append(url)
        raise OSError("offline")

    found = example.load_recordings(tmp_path / "nope", fetch=failing_fetch)
    assert found == {} and seen  # tried to download, did not raise

    real = {p.name: p.read_bytes() for p in example.AUDIO_DIR.glob("*.wav")}
    found = example.load_recordings(
        tmp_path / "cache", fetch=lambda url: real[url.rsplit("/", 1)[1]]
    )
    assert len(found) == 4  # downloaded into the cache folder, then read like local files
    assert (tmp_path / "cache" / "speech.wav").exists()


@pytest.mark.integration
def test_vowel_spectrograms_show_distinct_formant_structure():
    """The textbook model's teaching point: /i/ (a documented low F1 ~270 Hz) and /a/
    (a documented high F1 ~730 Hz) should show that contrast in their spectrograms -
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
def test_recorded_notes_have_the_expected_pitch_and_envelopes():
    """The recordings are the notes they claim to be, and a struck piano note decays
    while a bowed violin note holds."""
    example = _load_example()

    def peak_hz(key: str, lo: float, hi: float) -> float:
        s = example.SAMPLES[key]
        mag = np.abs(np.fft.rfft(s.samples[: s.sr] * np.hanning(s.sr)))
        freqs = np.fft.rfftfreq(s.sr, d=1.0 / s.sr)
        band = (freqs >= lo) & (freqs <= hi)
        return float(freqs[band][np.argmax(mag[band])])

    assert abs(peak_hz("instrument:violin", 400, 480) - 440.0) < 8  # A4
    assert abs(peak_hz("instrument:saxophone", 230, 300) - 264.0) < 8
    assert abs(peak_hz("instrument:piano", 240, 290) - 261.6) < 8  # C4 (first partial)

    def late_over_early(key: str) -> float:
        s = example.SAMPLES[key]
        sr = s.sr
        early = np.sqrt(np.mean(s.samples[int(0.1 * sr) : int(0.4 * sr)] ** 2))
        late = np.sqrt(np.mean(s.samples[int(1.2 * sr) : int(1.6 * sr)] ** 2))
        return float(late / early)

    assert late_over_early("instrument:piano") < 0.5 < late_over_early("instrument:violin")


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

    # An instrument clip: the hub keeps only a bounded history of recent messages,
    # and the 7 s speech clip has more columns than that.
    select = _by_type(session, "select")[0]
    session.dispatch(select.id, "change", {"value": "instrument:violin"})
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
    default_sample = example.SAMPLES["instrument:violin"]
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


@pytest.mark.integration
async def test_a_visible_credit_line_follows_the_picked_sample():
    example = _load_example()
    session = example.build()
    select = _by_type(session, "select")[0]

    def credit_text() -> str:
        out = []
        for c in _by_type(session, "text"):
            props = c.reactive_props()
            key = "blocks" if "blocks" in props else "text"
            out.append(json.dumps(props[key](), ensure_ascii=False))
        return "\n".join(out)

    session.dispatch(select.id, "change", {"value": "instrument:violin"})
    violin = credit_text()
    assert "University of Iowa" in violin and "theremin.music.uiowa.edu" in violin

    session.dispatch(select.id, "change", {"value": "speech:librivox"})
    speech = credit_text()
    assert "LibriVox" in speech and "librivox.org" in speech and "public domain" in speech.lower()

    session.dispatch(select.id, "change", {"value": "vowel:a"})
    assert "textbook" in credit_text().lower()

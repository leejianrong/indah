"""BarStrip (IND-162): a compact per-bar activity strip, built in to indah."""

import math

import pytest

from indah import BarStrip, Signal
from indah.protocol import BUILTIN_TYPES

pytestmark = pytest.mark.unit


def test_wire_has_type_and_series_and_leaves_defaults_off():
    assert "barstrip" in BUILTIN_TYPES
    node = BarStrip([1, 2, 3]).to_json()
    assert node["type"] == "barstrip"
    # Every bar is a list of segment values, so the shell has one shape to draw.
    assert node["props"] == {"series": [[1.0], [2.0], [3.0]]}


def test_stacked_series_options_and_names_travel_when_given():
    strip = BarStrip(
        [(3, 1), (2, 0)],
        height=48,
        tones=["ok", "err"],
        names=["hit", "miss"],
        labels=["12:01", "12:02"],
        max=10,
        label="Calls per minute",
    )
    assert strip.to_json()["props"] == {
        "series": [[3.0, 1.0], [2.0, 0.0]],
        "height": 48,
        "tones": ["ok", "err"],
        "names": ["hit", "miss"],
        "labels": ["12:01", "12:02"],
        "max": 10.0,
        "label": "Calls per minute",
    }


def test_series_follows_a_signal_computed_or_callable():
    data = Signal([1, 2])
    strip = BarStrip(data)
    read = strip.reactive_props()["series"]
    assert read() == [[1.0], [2.0]]
    data.set([1, 2, 5])
    assert read() == [[1.0], [2.0], [5.0]]
    assert BarStrip(lambda: [4]).reactive_props()["series"]() == [[4.0]]


def test_labels_may_be_live_too():
    labels = Signal(["a"])
    strip = BarStrip([1], labels=labels)
    assert strip.reactive_props()["labels"]() == ["a"]
    labels.set(["a", "b"])
    assert strip.reactive_props()["labels"]() == ["a", "b"]
    assert "labels" not in BarStrip([1]).reactive_props()


def test_bad_values_become_zero_rather_than_breaking_the_page():
    bars = BarStrip([-1, math.nan, math.inf, "x", None, True, 2]).to_json()["props"]["series"]
    assert bars == [[0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [2.0]]
    assert BarStrip(None).to_json()["props"]["series"] == []


def test_only_the_latest_bars_are_sent():
    series = BarStrip(list(range(2000))).to_json()["props"]["series"]
    assert len(series) == 1440 and series[-1] == [1999.0]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"tones": ["purple"]}, "tone"),
        ({"height": 4}, "height"),
        ({"height": 999}, "height"),
        ({"max": 0}, "max"),
        ({"max": -3}, "max"),
        ({"names": "hit"}, "names"),
    ],
)
def test_bad_options_fail_at_construction(kwargs, match):
    with pytest.raises(ValueError, match=match):
        BarStrip([1], **kwargs)


def test_default_tone_is_info_and_extra_segments_are_neutral():
    # Documented in the docstring; the shell applies it, the wire just omits `tones`.
    assert "tones" not in BarStrip([(1, 2)]).to_json()["props"]

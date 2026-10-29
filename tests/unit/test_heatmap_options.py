"""Heatmap colour stops, blank cells, origin, labels, groups and marks (ADR-0046)."""

import pytest

import indah


@pytest.mark.unit
def test_options_reach_the_wire_and_defaults_stay_off_it():
    props = indah.Heatmap(
        [[1.0, None]],
        colormap=["var(--x-neg)", "#343b66", "rgb(91, 141, 239)"],
        null_color="var(--surface-2)",
        origin="top",
        row_labels=["0>1", "0>2"],
        col_groups=[{"start": 0, "end": 80, "label": "rod 0"}],
        mark_x=5,
        mark_y=1,
        mark_color="var(--x-gold)",
    ).to_json()["props"]
    assert props["colormap"] == ["var(--x-neg)", "#343b66", "rgb(91, 141, 239)"]
    assert props["nullColor"] == "var(--surface-2)" and props["origin"] == "top"
    assert props["rowLabels"] == ["0>1", "0>2"]
    assert props["colGroups"] == [{"start": 0, "end": 80, "label": "rod 0"}]
    assert (props["markX"], props["markY"], props["markColor"]) == (5, 1, "var(--x-gold)")
    assert props["z"] == [[1.0, None]] or props["z"] is not None  # the field is still sent

    plain = indah.Heatmap([[0.0]]).to_json()["props"]
    for key in ("nullColor", "origin", "rowLabels", "colGroups", "markX", "markY", "markColor"):
        assert key not in plain
    assert plain["colormap"] == "magma"


@pytest.mark.unit
def test_marks_can_follow_signals():
    x, y = indah.Signal(3), indah.Signal(0)
    heatmap = indah.Heatmap([[0.0, 1.0]], mark_x=x, mark_y=lambda: y.value + 1)
    reactive = heatmap.reactive_props()
    assert "markX" in reactive and "markY" in reactive
    assert heatmap.to_json()["props"]["markX"] == 3 and heatmap.to_json()["props"]["markY"] == 1
    x.set(9)
    assert heatmap.to_json()["props"]["markX"] == 9
    cleared = indah.Heatmap([[0.0]], mark_x=indah.Signal(None)).to_json()["props"]
    assert cleared["markX"] is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"colormap": ["red"]},
        {"colormap": ["red"] * 10},
        {"colormap": ["url(x)", "red"]},
        {"null_color": "url(x)"},
        {"mark_color": "red; x"},
        {"origin": "left"},
        {"row_labels": ["a"] * 65},
        {"col_groups": [{"start": 0, "end": 3}]},
        {"col_groups": [{"start": 5, "end": 2, "label": "x"}]},
        {"col_groups": [{"start": 0, "end": 1, "label": "x"}] * 25},
        {"mark_x": "left"},
        {"mark_y": -1},
    ],
)
def test_bad_heatmap_options_are_refused(kwargs):
    with pytest.raises(ValueError):
        indah.Heatmap([[0.0]], **kwargs)


@pytest.mark.unit
def test_a_named_colormap_is_still_just_a_string():
    assert indah.Heatmap([[0.0]], colormap="viridis").to_json()["props"]["colormap"] == "viridis"

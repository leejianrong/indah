"""Chart series kinds, ranges, playhead, rules, highlight and legend (ADR-0046)."""

import pytest

import indah


@pytest.mark.unit
def test_series_kinds_and_styling_reach_the_wire():
    chart = indah.Chart(
        series=[
            {"label": "a", "kind": "bars", "stroke": "var(--x-explore)", "alpha": 0.5},
            {"label": "b", "kind": "scatter", "size": 4, "dash": [4, 3], "width": 1.5},
            {"label": "c", "kind": "line"},
            "d",
        ]
    )
    series = chart.to_json()["props"]["series"]
    assert series[0] == {"label": "a", "stroke": "var(--x-explore)", "kind": "bars", "alpha": 0.5}
    assert series[1] == {"label": "b", "kind": "scatter", "size": 4, "dash": [4, 3], "width": 1.5}
    assert series[2] == {"label": "c"}  # line is the default and is not sent
    assert series[3] == {"label": "d"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "pie"},
        {"stroke": "url(https://evil.example/x)"},
        {"stroke": "red; background: blue"},
        {"alpha": 2},
        {"alpha": True},
        {"size": 0},
        {"width": -1},
        {"dash": [1, 2, 3, 4, 5]},
        {"dash": "5 4"},
    ],
)
def test_bad_series_options_are_refused(bad):
    with pytest.raises(ValueError):
        indah.Chart(series=[bad])


@pytest.mark.unit
def test_ranges_rules_and_flags():
    props = indah.Chart(
        x_range=(1, 655),
        y_range=[0, 160],
        shade_after=True,
        rules=[{"y": 31, "label": "optimal 31", "color": "var(--x-gold)"}, {"y": 0, "dash": False}],
        highlight_color="var(--x-gold)",
        legend="labels",
    ).to_json()["props"]
    assert props["xRange"] == [1, 655] and props["yRange"] == [0, 160]
    assert props["shadeAfter"] is True and props["legend"] == "labels"
    assert props["rules"] == [
        {"y": 31, "label": "optimal 31", "color": "var(--x-gold)"},
        {"y": 0, "dash": False},
    ]
    assert props["highlightColor"] == "var(--x-gold)"
    plain = indah.Chart().to_json()["props"]
    for key in ("xRange", "yRange", "shadeAfter", "rules", "legend", "highlightColor"):
        assert key not in plain


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"x_range": (5, 5)},
        {"x_range": (9, 1)},
        {"x_range": (1,)},
        {"y_range": "0-1"},
        {"rules": [{"label": "no y"}]},
        {"rules": [{"y": 1}] * 13},
        {"rules": [{"y": 1, "color": "url(x)"}]},
        {"legend": "right"},
        {"highlight_color": "url(x)"},
    ],
)
def test_bad_chart_options_are_refused(kwargs):
    with pytest.raises(ValueError):
        indah.Chart(**kwargs)


@pytest.mark.unit
def test_playhead_and_highlight_are_static_numbers_or_reactive_sources():
    static = indah.Chart(playhead=412, highlight=411).to_json()["props"]
    assert static["playhead"] == 412 and static["highlight"] == 411

    at = indah.Signal(3)
    chart = indah.Chart(playhead=at, highlight=lambda: at.value + 1)
    props = chart.to_json()["props"]
    assert props["playhead"] == 3 and props["highlight"] == 4
    assert "playhead" in chart.reactive_props() and "highlight" in chart.reactive_props()
    at.set(7)
    assert chart.to_json()["props"]["playhead"] == 7
    assert chart.to_json()["props"]["highlight"] == 8

    cleared = indah.Chart(playhead=indah.Signal(None)).to_json()["props"]
    assert cleared["playhead"] is None


@pytest.mark.unit
def test_a_non_numeric_static_playhead_is_refused():
    with pytest.raises(ValueError):
        indah.Chart(playhead="soon")


# ---- steps, log scales, annotations and chart_rows (ADR-0049) ----------------------------------


@pytest.mark.unit
def test_step_series_and_align():
    series = indah.Chart(
        series=[{"label": "a", "kind": "step"}, {"label": "b", "kind": "step", "align": "before"}]
    ).to_json()["props"]["series"]
    assert series[0] == {"label": "a", "kind": "step"}  # after is the default and is not sent
    assert series[1] == {"label": "b", "kind": "step", "align": "before"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad", [{"kind": "line", "align": "after"}, {"kind": "step", "align": "middle"}]
)
def test_bad_align_is_refused(bad):
    with pytest.raises(ValueError):
        indah.Chart(series=[bad])


@pytest.mark.unit
def test_scales_reach_the_wire_only_when_log():
    assert "xScale" not in indah.Chart().to_json()["props"]
    props = indah.Chart(y_scale="log", y_range=(1, 1000)).to_json()["props"]
    assert props["yScale"] == "log" and "xScale" not in props


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"y_scale": "ln"},
        {"x_scale": "log", "x_range": (0, 10)},
        {"y_scale": "log", "rules": [{"y": 0}]},
        {"x_scale": "log", "rules": [{"x": -1}]},
        {"y_scale": "log", "bands": [{"y0": 0, "y1": 5}]},
        {"x_scale": "log", "markers": [{"x": 0, "y": 1}]},
    ],
)
def test_log_axes_refuse_non_positive_values(kwargs):
    with pytest.raises(ValueError):
        indah.Chart(**kwargs)


@pytest.mark.unit
def test_vertical_rules_bands_and_markers_reach_the_wire():
    props = indah.Chart(
        rules=[{"y": 31, "label": "best"}, {"x": 9, "label": "v3", "dash": False}],
        bands=[
            {"x0": 10, "x1": 40, "color": "var(--err)", "alpha": 0.12, "label": "fails"},
            {"y0": 0, "y1": 1.0},
        ],
        markers=[{"x": 12, "y": 4.2, "label": "Q=300", "color": "var(--ok)"}],
    ).to_json()["props"]
    assert props["rules"] == [{"y": 31, "label": "best"}, {"x": 9, "label": "v3", "dash": False}]
    assert props["bands"] == [
        {"x0": 10, "x1": 40, "label": "fails", "color": "var(--err)", "alpha": 0.12},
        {"y0": 0, "y1": 1.0},
    ]
    assert props["markers"] == [{"x": 12, "y": 4.2, "label": "Q=300", "color": "var(--ok)"}]


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"rules": [{"x": 1, "y": 2}]},  # one axis only
        {"rules": [{"label": "none"}]},
        {"rules": [{"x": 1, "color": "url(https://evil.example/x)"}]},
        {"bands": [{"x0": 5, "x1": 5}]},
        {"bands": [{"x0": 1, "x1": 2, "y0": 1, "y1": 2}]},
        {"bands": [{"x0": 1}]},
        {"bands": [{"x0": 1, "x1": 2, "alpha": 2}]},
        {"markers": [{"x": 1}]},
        {"markers": [{"x": 1, "y": 1, "color": "red; x"}]},
        {"rules": [{"x": i} for i in range(13)]},
        {"bands": [{"x0": i, "x1": i + 1} for i in range(13)]},
        {"markers": [{"x": i, "y": i} for i in range(13)]},
    ],
)
def test_bad_annotations_are_refused(kwargs):
    with pytest.raises(ValueError):
        indah.Chart(**kwargs)


@pytest.mark.unit
def test_chart_rows_unions_x_and_leaves_gaps():
    rows = indah.chart_rows({"score": [(0, 1.0), (5, 1.2)], "frontier": [(0, 1.5), (3, 1.4)]})
    assert rows == [[0, 1.0, 1.5], [3, None, 1.4], [5, 1.2, None]]


@pytest.mark.unit
def test_chart_rows_handles_nan_unsorted_repeats_and_empty():
    nan, inf = float("nan"), float("inf")
    rows = indah.chart_rows({"a": [(2, nan), (1, inf), (1, 3)], "b": []})
    assert rows == [[1, 3, None], [2, None, None]]  # last repeat wins; NaN becomes None
    assert indah.chart_rows({}) == []
    with pytest.raises(ValueError):
        indah.chart_rows({"a": [(float("nan"), 1)]})
    with pytest.raises(ValueError):
        indah.chart_rows({"a": [("1", 1)]})

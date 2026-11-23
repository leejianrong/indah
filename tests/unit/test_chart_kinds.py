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


# ---- time axis, integer ticks and a playhead label (IND-269, 270, 274) --------------------------


@pytest.mark.unit
def test_time_scale_turns_datetimes_into_unix_seconds():
    import datetime

    t0 = datetime.datetime(2026, 11, 1)
    chart = indah.Chart(
        [[t0, 1.0], [t0 + datetime.timedelta(hours=1), 2.0]], x_scale="time", series=["a"]
    )
    assert chart.static_props()["xScale"] == "time"
    assert chart.to_json()["props"]["data"] == [[1793491200.0, 1.0], [1793494800.0, 2.0]]
    aware = datetime.datetime(2026, 11, 1, 8, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    assert chart.reactive_props()["data"]()[0][0] == 1793491200.0
    streaming = indah.Chart(x_scale="time", series=["a"])
    streaming.push(aware, 1.0)
    streaming.extend([[t0, 2.0]])
    assert streaming.static_props()["data"] == [[1793491200.0, 1.0], [1793491200.0, 2.0]]


@pytest.mark.unit
def test_time_scale_is_x_only_and_a_number_passes_through():
    with pytest.raises(ValueError):
        indah.Chart(y_scale="time")
    chart = indah.Chart([[5, 1.0]], x_scale="time", series=["a"])
    assert chart.to_json()["props"]["data"] == [[5, 1.0]]


@pytest.mark.unit
def test_x_integer_is_linear_only_and_off_by_default():
    assert "xInteger" not in indah.Chart(series=["a"]).static_props()
    assert indah.Chart(series=["a"], x_integer=True).static_props()["xInteger"] is True
    with pytest.raises(ValueError):
        indah.Chart(series=["a"], x_integer=True, x_scale="log")


@pytest.mark.unit
def test_playhead_label_is_static_or_live():
    fixed = indah.Chart(series=["a"], playhead=3, playhead_label="step 3")
    assert fixed.static_props()["playheadLabel"] == "step 3"
    assert "playheadLabel" not in fixed.reactive_props()
    n = indah.Signal(1)
    live = indah.Chart(series=["a"], playhead=n, playhead_label=lambda: f"step {n.value}")
    assert "playheadLabel" not in live.static_props()
    assert live.reactive_props()["playheadLabel"]() == "step 1"
    n.set(2)
    assert live.reactive_props()["playheadLabel"]() == "step 2"
    assert "playheadLabel" not in indah.Chart(series=["a"]).to_json()["props"]


# ---- live annotations and a category axis (IND-272, IND-273) -------------------------------------


@pytest.mark.unit
def test_rules_bands_and_markers_can_be_live():
    cut = indah.Signal(5.0)
    chart = indah.Chart(
        [[0, 1.0]],
        series=["a"],
        rules=lambda: [{"y": cut.value, "label": "cut"}],
        bands=lambda: [{"y0": 0, "y1": cut.value}],
        markers=lambda: [{"x": 0, "y": cut.value}],
    )
    static = chart.static_props()
    assert not {"rules", "bands", "markers"} & static.keys()
    live = chart.reactive_props()
    assert live["rules"]() == [{"y": 5.0, "label": "cut"}]
    cut.set(7.5)
    assert live["rules"]() == [{"y": 7.5, "label": "cut"}]
    assert live["bands"]() == [{"y0": 0, "y1": 7.5}]
    assert live["markers"]()[0]["y"] == 7.5


@pytest.mark.unit
def test_a_live_annotation_is_checked_each_time_it_is_read():
    bad = indah.Signal([{"y": 1}])
    chart = indah.Chart([[1, 1]], series=["a"], y_scale="log", rules=bad)
    assert chart.reactive_props()["rules"]() == [{"y": 1}]
    bad.set([{"y": 0}])  # not above zero on a log axis: refused, as a fixed rule is
    with pytest.raises(ValueError):
        chart.reactive_props()["rules"]()
    # A plain list is still checked at once, and stays on the wire as before.
    with pytest.raises(ValueError):
        indah.Chart(series=["a"], rules=[{"y": 1, "x": 2}])
    assert indah.Chart(series=["a"], rules=[{"y": 1}]).static_props()["rules"] == [{"y": 1}]


@pytest.mark.unit
def test_category_scale_sends_positions_and_labels():
    rows = [["add", 3], ["mul", 5], ["add", 4], [None, 1]]
    chart = indah.Chart(rows, series=["n"], x_scale="category")
    assert chart.static_props()["xScale"] == "category"
    props = chart.to_json()["props"]
    assert props["xCategories"] == ["add", "mul", ""]
    assert props["data"] == [[0, 3], [1, 5], [0, 4], [2, 1]]
    live = indah.Signal([["a", 1]])
    chart = indah.Chart(live, series=["n"], x_scale="category")
    live.set([["b", 1], ["a", 2]])
    assert chart.reactive_props()["xCategories"]() == ["b", "a"]


@pytest.mark.unit
def test_category_scale_needs_data_and_a_linear_look():
    with pytest.raises(ValueError):
        indah.Chart(series=["n"], x_scale="category")  # streaming has no fixed labels
    with pytest.raises(ValueError):
        indah.Chart([["a", 1]], series=["n"], x_scale="category", x_integer=True)


# -- stacked and horizontal bars, box series (IND-265) -----------------------------------------------

BARS = [{"label": "a", "kind": "bars"}, {"label": "b", "kind": "bars"}]


@pytest.mark.unit
def test_stack_and_orientation_are_off_by_default_and_sent_when_set():
    plain = indah.Chart([["x", 1, 2]], series=BARS, x_scale="category").to_json()["props"]
    assert "stack" not in plain and "orientation" not in plain
    props = indah.Chart(
        [["x", 1, 2]], series=BARS, x_scale="category", stack=True, orientation="horizontal"
    ).to_json()["props"]
    assert props["stack"] is True and props["orientation"] == "horizontal"


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"stack": True, "series": ["line"]},  # nothing to stack
        {"orientation": "diagonal", "series": BARS},
        {"orientation": "horizontal", "series": BARS},  # needs a category x axis
        {"orientation": "horizontal", "series": ["line"], "x_scale": "category"},  # bars only
        {"orientation": "horizontal", "series": BARS, "x_scale": "category", "rules": [{"y": 1}]},
        {"orientation": "horizontal", "series": BARS, "x_scale": "category", "playhead": 1},
    ],
)
def test_bad_stack_and_orientation_are_refused(kwargs):
    kwargs.setdefault("data", [["x", 1, 2]])
    with pytest.raises(ValueError):
        indah.Chart(**kwargs)


@pytest.mark.unit
def test_a_box_series_takes_five_columns_and_hides_four_legend_rows():
    chart = indah.Chart(
        [["a", 1, 2, 3, 4, 5]],
        series=[{"label": "latency", "kind": "box", "stroke": "var(--primary)"}],
        x_scale="category",
    )
    series = chart.to_json()["props"]["series"]
    assert [s["box"] for s in series] == [0, 1, 2, 3, 4]
    assert all(s["kind"] == "box" and s["stroke"] == "var(--primary)" for s in series)
    assert series[0]["label"] == "latency" and series[2]["label"] == "latency median"


@pytest.mark.unit
def test_box_rows_summarise_samples_into_five_numbers():
    rows = indah.box_rows({"fast": [1, 2, 3, 4, 5], "slow": [10, 20, 30, 40, 100]})
    assert rows[0] == ["fast", 1, 2, 3, 4, 5]
    assert rows[1] == ["slow", 10, 20, 30, 40, 100]
    assert indah.box_rows({"one": [7]}) == [["one", 7, 7, 7, 7, 7]]
    with pytest.raises(ValueError, match="no samples"):
        indah.box_rows({"none": []})
    with pytest.raises(ValueError, match="finite"):
        indah.box_rows({"bad": [1, float("nan")]})

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

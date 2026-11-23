"""Spans: nested labelled intervals for flame charts, icicle charts and timelines (IND-268)."""

import pytest

from indah import Signal, Spans

pytestmark = pytest.mark.unit

FLAME = [
    {"label": "compile", "start": 0, "end": 100},
    {"label": "parse", "start": 0, "end": 20},
    {"label": "route", "start": 20, "end": 80},
    {"label": "swap", "start": 20, "end": 50},
    {"label": "emit", "start": 80, "end": 100},
]


def test_depth_comes_from_nesting_and_the_columns_are_sent():
    props = Spans(FLAME, unit="ms").to_json()["props"]
    cols = props["spans"]
    assert cols["label"] == ["compile", "parse", "route", "swap", "emit"]
    assert cols["row"] == [0, 1, 1, 2, 1]
    assert cols["id"] == ["s0", "s1", "s2", "s3", "s4"]
    assert cols["rows"] == 3 and props["unit"] == "ms" and props["layout"] == "flame"


def test_explicit_depth_ids_and_colours_are_kept():
    spans = [
        {"id": "a", "label": "A", "start": 5, "end": 9, "depth": 2, "color": "var(--ok)"},
        {"id": "b", "label": "B", "start": 6, "end": 7},
    ]
    cols = Spans(spans).to_json()["props"]["spans"]
    assert cols["id"] == ["a", "b"] and cols["row"][0] == 2
    assert cols["color"] == ["var(--ok)", None]


def test_timeline_packs_overlaps_into_rows_or_uses_lanes():
    spans = [
        {"label": "x", "start": 0, "end": 5},
        {"label": "y", "start": 3, "end": 8},
        {"label": "z", "start": 6, "end": 9},
    ]
    assert Spans(spans, layout="timeline").to_json()["props"]["spans"]["row"] == [0, 1, 0]
    lanes = [{**s, "lane": "gpu" if s["label"] == "y" else "cpu"} for s in spans]
    assert Spans(lanes, layout="timeline").to_json()["props"]["spans"]["row"] == [0, 1, 0]


@pytest.mark.parametrize(
    "bad",
    [
        [{"label": "a", "start": 5, "end": 1}],  # ends before it starts
        [{"label": "a", "start": "x", "end": 1}],
        [{"start": 0, "end": 1}],  # no label
        [{"label": "a", "start": 0, "end": 1, "color": "url(x)"}],
        [{"label": "a", "start": 0, "end": 1, "bogus": 1}],
        [{"id": "a", "label": "a", "start": 0, "end": 1}] * 2,  # duplicate id
        [{"label": "a", "start": 0, "end": float("nan")}],
    ],
)
def test_bad_spans_are_refused(bad):
    with pytest.raises(ValueError):
        Spans(bad)


def test_limits_and_options():
    with pytest.raises(ValueError, match="5,000"):
        Spans([{"label": "a", "start": i, "end": i + 1} for i in range(5001)])
    with pytest.raises(ValueError, match="layout"):
        Spans(FLAME, layout="radial")
    assert Spans([]).to_json()["props"]["spans"]["id"] == []


def test_selection_is_two_way_and_checked_against_the_ids():
    picked = Signal(None)
    s = Spans(FLAME, selected=picked)
    assert s.to_json()["props"]["selectable"] is True
    assert s.handle("select", {"id": "s2"}) is True and picked.value == "s2"
    assert s.handle("select", {"id": None}) is True and picked.value is None
    assert s.handle("select", {"id": "nope"}) is False and picked.value is None
    assert Spans(FLAME).handle("select", {"id": "s1"}) is False  # nothing bound
    with pytest.raises(ValueError, match="unknown span"):
        Spans(FLAME, selected=Signal("zz"))
    assert s.reactive_props()["selected"]() is None
    picked.set("s3")
    assert s.reactive_props()["selected"]() == "s3"


def test_view_zooms_and_a_source_replaces_the_spans():
    live = Signal(FLAME)
    view = Signal((20, 50))
    s = Spans(live, view=view)
    assert s.reactive_props()["view"]() == [20, 50]
    live.set(FLAME[:2])
    assert s.reactive_props()["spans"]()["label"] == ["compile", "parse"]
    with pytest.raises(ValueError, match="view"):
        Spans(FLAME, view=(5, 5))

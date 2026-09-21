"""The GPX-viewer example (examples/gpx_viewer.py) stays runnable.

Smoke-checks the dashboard builds, that the embedded real-trail cache decodes
correctly, that distance/elevation-gain/duration are sane numbers derived from the
real trackpoint sequence, and that scrubbing the progress slider moves the map's
current-position marker and the elevation chart's position marker together (the
same `Signal` drives both) - all without a network call (the cache is bundled,
gzip+base64, in the module itself, per OpenStreetMap/opentopodata).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "gpx_viewer.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("gpx_viewer_example", _EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    # dataclasses (module has `from __future__ import annotations`) resolves field
    # types via sys.modules[cls.__module__] - it must be registered before exec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _by_type(session, type_name):
    return [c for c in session._by_id.values() if c.type == type_name]


@pytest.mark.integration
def test_the_embedded_trail_decodes_with_real_looking_points():
    gv = _load_example()
    assert gv.SLUG in gv._CACHE
    points = gv._load(gv.SLUG)
    assert len(points) > 10
    for p in points:
        assert -90 <= p["lat"] <= 90
        assert -180 <= p["lon"] <= 180
        assert isinstance(p["ele"], (int, float))


@pytest.mark.integration
def test_distance_and_elevation_gain_are_sane_for_a_real_trail():
    gv = _load_example()
    points = gv._load(gv.SLUG)
    cum = gv._cumulative_distances_m(points)
    total_km = cum[-1] / 1000
    gain = gv._elevation_gain_m(points)
    # Southern Ridges Walk is a real, several-km Singapore trail with modest hills -
    # loose bounds so this stays robust to a future re-fetch, not brittle to it.
    assert 1 < total_km < 30
    assert 0 <= gain < 2000


@pytest.mark.integration
def test_duration_is_a_plausible_estimate_not_a_recorded_time():
    gv = _load_example()
    points = gv._load(gv.SLUG)
    cum = gv._cumulative_distances_m(points)
    gain = gv._elevation_gain_m(points)
    hours = gv._estimated_duration_hours(cum[-1], gain)
    assert 0 < hours < 12
    assert gv._format_duration(hours).startswith("~")  # "~" flags it as an estimate


@pytest.mark.integration
def test_scrubbing_progress_moves_the_map_marker_and_chart_position_together():
    gv = _load_example()
    session = gv.build()
    slider = _by_type(session, "slider")[0]
    trail_map = _by_type(session, "map")[0]
    chart = _by_type(session, "chart")[0]

    def current_marker():
        return trail_map.reactive_props()["markers"]()[2]  # start, end, current

    def marked_chart_point():
        rows = chart.reactive_props()["data"]()
        (row,) = [r for r in rows if r[2] is not None]
        return row

    before_marker = current_marker()
    before_x = marked_chart_point()[0]

    session.dispatch(slider.id, "input", {"value": 50})

    after_marker = current_marker()
    after_x = marked_chart_point()[0]
    assert after_marker != before_marker
    assert after_x != before_x
    # Halfway along the track (by distance, not by raw point index).
    total_km = gv._cumulative_distances_m(gv._load(gv.SLUG))[-1] / 1000
    assert abs(after_x - total_km / 2) < 0.5

    session.dispatch(slider.id, "input", {"value": 100})
    end_marker = current_marker()
    points = gv._load(gv.SLUG)
    assert round(end_marker["lat"], 4) == round(points[-1]["lat"], 4)
    assert round(end_marker["lon"], 4) == round(points[-1]["lon"], 4)


@pytest.mark.integration
def test_stats_reflect_the_distance_and_gain_computed_from_the_track():
    gv = _load_example()
    session = gv.build()
    stats = _by_type(session, "stat")
    labels = {s.static_props()["label"]: s.reactive_props()["value"]() for s in stats}
    points = gv._load(gv.SLUG)
    cum = gv._cumulative_distances_m(points)
    gain = gv._elevation_gain_m(points)
    assert labels["Distance"] == f"{cum[-1] / 1000:.2f} km"
    assert labels["Elevation gain"] == f"{gain:.0f} m"
    assert labels["Est. duration"].startswith("~")


@pytest.mark.unit
def test_load_caches_the_decoded_trackpoints():
    gv = _load_example()
    first = gv._load(gv.SLUG)
    second = gv._load(gv.SLUG)
    assert first is second  # decoded once, not on every call


@pytest.mark.unit
def test_interpolate_returns_the_endpoints_at_0_and_100_percent():
    gv = _load_example()
    points = gv._load(gv.SLUG)
    cum = gv._cumulative_distances_m(points)
    lat0, lon0, ele0 = gv._interpolate(points, cum, 0.0)
    assert (lat0, lon0, ele0) == (points[0]["lat"], points[0]["lon"], points[0]["ele"])
    lat1, lon1, ele1 = gv._interpolate(points, cum, cum[-1])
    assert (lat1, lon1, ele1) == (points[-1]["lat"], points[-1]["lon"], points[-1]["ele"])


@pytest.mark.unit
def test_elevation_gain_ignores_descents():
    gv = _load_example()
    points = [
        {"lat": 0, "lon": 0, "ele": 10},
        {"lat": 0, "lon": 0, "ele": 5},
        {"lat": 0, "lon": 0, "ele": 20},
    ]
    assert gv._elevation_gain_m(points) == 15  # 5->20 only; 10->5 is a descent

"""GPX viewer: an interactive Map + elevation profile over a real hiking trail.

The first demo to actually exercise the interactive client ``Map`` (map_poster/
grc_map both render a static server-side matplotlib ``Plot`` instead). A `Slider`
scrubs a "current position" marker along the track on the map, in sync with a
crosshair on a client `Chart` elevation profile - both driven by the same
`Signal`, the same "single source of truth" pattern the rest of indah's reactive
demos use.

Two layers, kept apart (ADR-0009):

- **The data layer** is offline: ``scripts/fetch_gpx_cache.py`` pulls a real,
  named OpenStreetMap hiking-route relation (``route=hiking``) via Overpass into
  ``examples/data/gpx_viewer/<slug>.json``, and ``scripts/compile_gpx_cache.py``
  gzips + base64-embeds it into the ``_CACHE`` block below. Re-run both by hand
  after adding a trail.
- **This module** only reads that embedded cache - no network call, no
  osmnx/shapely/requests import, at demo runtime.

Data provenance (see ``scripts/fetch_gpx_cache.py`` for the full explanation):

- **Track geometry** (the lat/lon sequence) is real: OpenStreetMap's "Southern
  Ridges Walk" hiking-route relation in Singapore, stitched into one continuous
  line.
- **Elevation** is real too: SRTM (~90m posting) via opentopodata.org's public
  API, not fabricated.
- **Duration** is NOT real - this is a static route, not a recorded track log, so
  there is no genuine "time at each point" data. The "Est. duration" stat is a
  *plausible estimate* (Naismith's rule, from distance + elevation gain), labelled
  as an estimate everywhere it appears, never presented as a recorded time.

Map data is (c) OpenStreetMap contributors, ODbL; elevation via opentopodata.org
(SRTM, public domain). The demo renders both attributions.

Run it with:  python examples/gpx_viewer.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import base64
import bisect
import gzip
import json
import math
from dataclasses import dataclass
from typing import Any

import indah


@dataclass(frozen=True)
class _Entry:
    label: str
    source: str
    attribution: str
    distance_m: float
    gz_b64: str


# BEGIN GENERATED CACHE (scripts/compile_gpx_cache.py) ----------------------
_CACHE: dict[str, _Entry] = {
    "southern-ridges-sg": _Entry(
        label="Southern Ridges Walk, Singapore",
        source="OpenStreetMap relation 5993965 (route=hiking)",
        attribution="Track: \u00a9 OSM contributors, ODbL. Elevation: SRTM via opentopodata.org.",
        distance_m=6927.9,
        gz_b64=(
            "H4sIALdrsWoC/4WYu4pdVwxAf8W4NsPWW8qvhBQp3JmkSRfy79FljI9GkrdhmOLAunq/9u//fv725z+ff/sEb2gOFF8+ff72"
            "91+vD4fe8gMi5qev377mJ9O389+XTx+Qc6wj77/yHaGJkElDkEWvUgKpIWAuD8IDiWMDIbAHiUXK6cgJ/0E4TMK0EQnA3WHm"
            "nVDwqyUAEzmPEMfFEu0Ey1UrxilD6AeimyGBQwgWSxa1zLgjVAK/OJg1BkFFry29DnREFB5k0Qt1IudJYt0Uo+FiLEm8STGx"
            "gdgTFo3NYcN8KCm5IcI9kh5PsuiZhHIPpKvyD0Q2ISMsLo+LRRbCpRNQXCxbcXmPSv5MQWgplR6UzDi8xTGwG6J6tyS4y1B5"
            "IiK+AKNQlEvai01EopuuFHILSRj0ViToTxR5UcyHFA57bOGhmB+knsOs/tjCMhHo1tN7n30naHaWiOhC6L0QviNLUEKGFH4s"
            "IZxqHZJBQNFrya6YpkBxMcFmykQO3xWTXsCoVQotUbGek0iHrsgZ9YikcUUAeq0gll5My+jKBjYQwauTLWgoVhaK6bEEIqb5"
            "T1LSWbaD0SkgSoEtiuVM7dUCGnw1H6Q7GU7pLrjU5OEhJTPiQWJrej3HslvwXUpPscOoN8J91GSm5RMWXJrYoT7tsxfEL6z/"
            "GPwsII3isKXy8URHuGxHG0LNYYlgmaq4tCSSjjjEk/uwLaCHO3LUb4hHm92vavDHFpBtUnTzFeMJJSw9iakjEmUUw9KTILot"
            "cuDWxNNU1IawVeRMRKybz/qLLs5IQ0opF1rmkcBQTPCOEE2kbEjki2LWPcZcW/KCYEykDHBYTBnlkqn/COHFYdRaUiJQ9lZe"
            "+j6P3Cc3us58hCHllFHB29CnjlDQU/q8NL7exl6I2x2J4TGou+6SlTDM53IT85L61BbXl/Wl8pkn4qMlZcfRy/bmwMMUArbL"
            "euwgp0vBKOeqTFvAR1Iil4VPpy1E0qsFmPCyvDopdI/llqSXqyWlQFfslEDO+ysJ63plAV1ltO3lNZ+qhxdD3LohmQ1yOQ8S"
            "gYnUoCxIjKAcKEFZENZ24Oewyb9bHNn6nPDwekjP80CUhxQsaTyfERJx7QhAuYplQWAodm4Hvuv7OlgJ55Jf88xzdRpILa95"
            "S+Z9jzIQu1ni2AvSc+TLLSedBIaQsoksNezINqz3a6dwGi52LS1snuvucgYiUM71GZasWOrmW7mOFsUCYnjMyvzapODisfIc"
            "NpGcK9rz2KS0sDlZ0hTr5iuWh71NikZPMfGyIk3zU7HeX17vPTcnB7j36PPtWSCB3vay4ThdZmTeOX3ZyzSNq/FI2AOJ7zfG"
            "z0oy0LG7GEhunTKHaE+w/K+XIs6N05perz3DLq81ubRLJ065WGcRJ9H3I3s9PF26cQj0hdLsfaD97CU0kfaSYJY1LJduHNLX"
            "adMP034KUe/ukg+PmjPyGkMtDoBbUAx5IEK36ZUIdOKUot8I6ueHZRLbLb2MkAdye9lLor2cJkFWcnizxDpxyliZrfgVk248"
            "GtllZ82gRDcehdvD3h//AxehNSQuGgAA"
        ),
    ),
}
# END GENERATED CACHE -------------------------------------------------------

SLUG = next(iter(_CACHE), "")  # one curated trail today; add more via CURATED + refetch

_decoded: dict[str, list[dict[str, Any]]] = {}


def _load(slug: str) -> list[dict[str, Any]]:
    """Decode one trail's trackpoints, lazily and once (gzip+base64 -> JSON)."""
    if slug not in _decoded:
        raw = gzip.decompress(base64.b64decode(_CACHE[slug].gz_b64))
        _decoded[slug] = json.loads(raw)
    return _decoded[slug]


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _cumulative_distances_m(points: list[dict[str, Any]]) -> list[float]:
    """Cumulative real-world distance (m) at each trackpoint (haversine), so
    scrubbing "progress" can be interpolated by distance rather than by raw point
    index (points are not evenly spaced along the track)."""
    cum = [0.0]
    for i in range(1, len(points)):
        a = (points[i - 1]["lat"], points[i - 1]["lon"])
        b = (points[i]["lat"], points[i]["lon"])
        cum.append(cum[-1] + _haversine_m(a, b))
    return cum


def _elevation_gain_m(points: list[dict[str, Any]]) -> float:
    """Total ascent: the sum of positive elevation deltas between consecutive
    trackpoints (the conventional "elevation gain" definition)."""
    return sum(max(0.0, points[i]["ele"] - points[i - 1]["ele"]) for i in range(1, len(points)))


def _estimated_duration_hours(distance_m: float, gain_m: float) -> float:
    """A *plausible estimate*, NOT a recorded time. This track is a static route
    geometry (see the module docstring) with no real GPX timestamps, so there is no
    genuine duration to report. Naismith's rule: ~5km/h on the flat, plus one extra
    hour per 600m of ascent."""
    return distance_m / 1000.0 / 5.0 + gain_m / 600.0


def _format_duration(hours: float) -> str:
    total_minutes = round(hours * 60)
    h, m = divmod(total_minutes, 60)
    return f"~{h}h {m:02d}m" if h else f"~{m}m"


def _track_center(points: list[dict[str, Any]]) -> tuple[float, float]:
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _interpolate(
    points: list[dict[str, Any]], cum: list[float], target_m: float
) -> tuple[float, float, float]:
    """``(lat, lon, ele)`` at ``target_m`` along the track, linearly interpolated
    within the bracketing segment."""
    if target_m <= 0:
        p = points[0]
        return p["lat"], p["lon"], p["ele"]
    if target_m >= cum[-1]:
        p = points[-1]
        return p["lat"], p["lon"], p["ele"]
    i = bisect.bisect_right(cum, target_m) - 1
    i = max(0, min(i, len(points) - 2))
    seg_len = cum[i + 1] - cum[i]
    t = 0.0 if seg_len <= 0 else (target_m - cum[i]) / seg_len
    a, b = points[i], points[i + 1]
    lat = a["lat"] + (b["lat"] - a["lat"]) * t
    lon = a["lon"] + (b["lon"] - a["lon"]) * t
    ele = a["ele"] + (b["ele"] - a["ele"]) * t
    return lat, lon, ele


def _nearest_index(cum: list[float], target_m: float) -> int:
    i = bisect.bisect_left(cum, target_m)
    if i == 0:
        return 0
    if i >= len(cum):
        return len(cum) - 1
    return i if (cum[i] - target_m) < (target_m - cum[i - 1]) else i - 1


def build() -> indah.Session:
    entry = _CACHE[SLUG]
    points = _load(SLUG)
    cum = _cumulative_distances_m(points)
    total_distance_m = cum[-1]
    gain_m = _elevation_gain_m(points)
    duration_h = _estimated_duration_hours(total_distance_m, gain_m)

    progress = indah.Signal(0.0)  # percent (0-100) along the track

    def current_point() -> tuple[float, float, float]:
        target_m = (progress.value / 100.0) * total_distance_m
        return _interpolate(points, cum, target_m)

    start, end = points[0], points[-1]

    def markers() -> list[dict[str, Any]]:
        lat, lon, _ele = current_point()
        return [
            {"lat": start["lat"], "lon": start["lon"], "label": "Start", "color": "#2e6d62"},
            {"lat": end["lat"], "lon": end["lon"], "label": "End", "color": "#8a3ffc"},
            {"lat": lat, "lon": lon, "label": "Current position", "color": "#b5296b", "radius": 9},
        ]

    polylines = [
        {"points": [(p["lat"], p["lon"]) for p in points], "color": "#b5296b", "weight": 4}
    ]

    trail_map = indah.Map(
        _track_center(points),
        zoom=14,
        markers=markers,
        polylines=polylines,
        height=420,
        label=entry.label,
    )

    def elevation_data() -> list[list[Any]]:
        # Two series: the elevation profile, and a "position" series that is null
        # everywhere except the point nearest the scrubber - a lone marker uPlot
        # draws as a dot (points=True), so the chart reflects the same `progress`
        # signal driving the map's current-position marker.
        target_m = (progress.value / 100.0) * total_distance_m
        marker_idx = _nearest_index(cum, target_m)
        rows = []
        for i, p in enumerate(points):
            marker_y = p["ele"] if i == marker_idx else None
            rows.append([round(cum[i] / 1000.0, 4), p["ele"], marker_y])
        return rows

    elevation = indah.Chart(
        elevation_data,
        series=["Elevation (m)", "Position"],
        title="Elevation profile",
        x_label="Distance (km)",
        y_label="Elevation (m)",
        height=200,
        points=True,
    )

    scrubber = indah.Slider(progress, min=0, max=100, step=0.5, label="Progress along the trail")

    stats = indah.Row(
        children=[
            indah.Stat(value=f"{total_distance_m / 1000:.2f} km", label="Distance"),
            indah.Stat(value=f"{gain_m:.0f} m", label="Elevation gain"),
            indah.Stat(
                value=_format_duration(duration_h),
                label="Est. duration",
                help="A Naismith's-rule estimate from distance + elevation gain - "
                "this trail has no recorded timestamps, so it's not a real time.",
            ),
        ]
    )

    intro = indah.Text(
        f"# GPX viewer: {entry.label}\n\n"
        "Drag the slider to scrub along a real hiking trail - the marker on the map "
        "and the position on the elevation profile move together, driven by the "
        "same signal.\n\n"
        f"Track source: {entry.source}. {entry.attribution}",
        markdown=True,
    )

    page = indah.Column(
        children=[
            intro,
            indah.Card(children=[trail_map]),
            indah.Card(children=[scrubber]),
            indah.Card(children=[elevation]),
            indah.Card(children=[stats]),
        ]
    )
    return indah.Session(page)


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)

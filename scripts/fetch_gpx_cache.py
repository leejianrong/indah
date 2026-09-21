"""One-time offline fetch: cache a real OSM hiking-trail track for the GPX-viewer demo.

This is a **build-time tool**, not part of the demo or of indah: it pulls a named
``route=hiking`` relation from OpenStreetMap (via Overpass) for a curated set of real
trails and writes a plain-JSON trackpoint list to
``examples/data/gpx_viewer/<slug>.json``. ``examples/gpx_viewer.py`` reads only the
*compiled* (gzip+base64-embedded) version of that JSON at runtime - see
``compile_gpx_cache.py`` - so the demo itself needs no osmnx/shapely/requests import
and the public Fly deployment never calls Overpass live (same rationale as
``fetch_map_poster_cache.py``: docs/DEMOS-DOCS-ROUND2.md §A8/§D).

Two real-data sources, one synthetic:

- **Track geometry** is a real named OSM hiking-route relation (``route=hiking``),
  fetched from Overpass and stitched into one continuous line with
  ``shapely.ops.linemerge`` (a relation's member ways are usually contiguous but not
  necessarily already end-to-end ordered). The longest merged component is kept as
  the track backbone (a route relation sometimes also carries short access/connector
  spurs, which would otherwise show up as disconnected detours).
- **Elevation** is real too: each simplified trackpoint is looked up against
  opentopodata.org's public ``srtm90m`` dataset (NASA SRTM, ~90m posting) - coarser
  than a real GPS/barometric GPX recording, but genuine measured terrain elevation,
  not fabricated.
- **Timestamps** are NOT fetched or fabricated here: this is a static route geometry,
  not a recorded track log, so there is no real "when were you at this point" data.
  ``examples/gpx_viewer.py`` derives a *plausible estimated* hiking duration from the
  distance/elevation (Naismith's rule) and labels it as an estimate, never as a
  recorded time - see the comment on ``_estimated_duration_hours`` there.

Data is (c) OpenStreetMap contributors, ODbL; elevation via opentopodata.org (SRTM,
public domain). The demo renders both attributions.

Re-run this after adding a trail to CURATED or changing SIMPLIFY_TOLERANCE_DEG:

    uv run --with osmnx --with shapely --with requests python scripts/fetch_gpx_cache.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import LineString
from shapely.ops import linemerge

OUT = Path(__file__).resolve().parents[1] / "examples" / "data" / "gpx_viewer"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ELEVATION_URL = "https://api.opentopodata.org/v1/srtm90m"
# opentopodata's public instance asks for <=100 locations/request and roughly
# 1 request/second - https://www.opentopodata.org/#public-api-notes.
ELEVATION_BATCH = 100
ELEVATION_PAUSE_S = 1.1
RETRIES = 4
# Keeps the cached track to a few hundred points (plenty for a smooth scrubber/
# elevation profile) instead of every raw OSM vertex.
SIMPLIFY_TOLERANCE_DEG = 0.00005  # ~5m at these latitudes

UA = {"User-Agent": "indah-demo-fetch/0.1 (github.com/leejianrong/indah; build-time only)"}

# slug, OSM relation id, display label, short source note shown in the demo.
CURATED: list[tuple[str, int, str, str]] = [
    (
        "southern-ridges-sg",
        5993965,
        "Southern Ridges Walk, Singapore",
        "OpenStreetMap relation 5993965 (route=hiking)",
    ),
]


def _retry(fn, *args, **kwargs):
    """Overpass's shared public mirror occasionally 502/503/504s or drops the
    connection under load - a short backoff clears it almost every time."""
    for attempt in range(RETRIES):
        try:
            resp = fn(*args, **kwargs)
            if isinstance(resp, requests.Response) and resp.status_code in (502, 503, 504):
                raise requests.exceptions.HTTPError(f"{resp.status_code} from {resp.url}")
            return resp
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
        ):
            if attempt == RETRIES - 1:
                raise
            time.sleep(10 * (attempt + 1))


def _fetch_relation_geometry(relation_id: int) -> list[list[tuple[float, float]]]:
    """The relation's member ways, each as a ``[(lon, lat), ...]`` coordinate list."""
    query = f"[out:json][timeout:80];relation({relation_id});(._;>;);out body geom;"
    resp = _retry(requests.post, OVERPASS_URL, data={"data": query}, headers=UA, timeout=85)
    resp.raise_for_status()
    data = resp.json()
    ways = [el for el in data["elements"] if el["type"] == "way" and "geometry" in el]
    return [
        [(pt["lon"], pt["lat"]) for pt in w["geometry"]] for w in ways if len(w["geometry"]) >= 2
    ]


def _stitch(way_coords: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Merge a route relation's (unordered) member ways into one continuous track -
    the longest connected component, since a route relation sometimes also carries
    short access spurs that would otherwise dangle off the main line."""
    lines = [LineString(coords) for coords in way_coords]
    merged = linemerge(lines)
    parts = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
    longest = max(parts, key=lambda line: line.length)
    simplified = longest.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
    return list(simplified.coords)  # (lon, lat)


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _fetch_elevations(points_lonlat: list[tuple[float, float]]) -> list[float]:
    """Real terrain elevation (SRTM 90m) for each point, batched and rate-limited."""
    out: list[float] = []
    for i in range(0, len(points_lonlat), ELEVATION_BATCH):
        batch = points_lonlat[i : i + ELEVATION_BATCH]
        locs = "|".join(f"{lat},{lon}" for lon, lat in batch)
        resp = _retry(
            requests.get, ELEVATION_URL, params={"locations": locs}, headers=UA, timeout=30
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "OK":
            raise RuntimeError(f"opentopodata error: {payload}")
        out.extend(r["elevation"] for r in payload["results"])
        if i + ELEVATION_BATCH < len(points_lonlat):
            time.sleep(ELEVATION_PAUSE_S)
    return out


def fetch_one(relation_id: int, label: str, source: str) -> dict[str, Any]:
    print(f"  fetching relation {relation_id}...")
    way_coords = _fetch_relation_geometry(relation_id)
    track = _stitch(way_coords)
    print(f"  stitched {len(track)} points (from {len(way_coords)} ways)")

    print("  fetching real elevation (opentopodata/SRTM)...")
    elevations = _fetch_elevations(track)

    points = [
        {"lat": round(lat, 6), "lon": round(lon, 6), "ele": round(ele, 1)}
        for (lon, lat), ele in zip(track, elevations, strict=True)
    ]
    distance_m = sum(_haversine_m(track[i], track[i + 1]) for i in range(len(track) - 1))

    return {
        "label": label,
        "source": source,
        "attribution": "Track: © OSM contributors, ODbL. Elevation: SRTM via opentopodata.org.",
        "distance_m": round(distance_m, 1),
        "points": points,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (slug, relation_id, label, source) in enumerate(CURATED):
        if i:
            time.sleep(5)  # be polite to the shared Overpass mirror between trails
        print(f"{slug}:")
        data = fetch_one(relation_id, label, source)
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        print(f"  wrote {path} ({len(data['points'])} points, {data['distance_m'] / 1000:.2f} km)")


if __name__ == "__main__":
    main()

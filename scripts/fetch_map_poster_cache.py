"""One-time offline fetch: cache real OSM geometry for the map-poster demo.

This is a **build-time tool**, not part of the demo or of indah: it pulls streets,
buildings, water, and green space from OpenStreetMap (via osmnx/Overpass) for a
curated set of neighborhoods and writes plain-JSON coordinate lists to
``examples/data/map_poster/<slug>.json``. ``examples/map_poster.py`` reads only those
JSON files at runtime, so the demo itself needs no osmnx/geopandas/shapely and the
public Fly deployment never calls Nominatim/Overpass live (docs/DEMOS-DOCS-ROUND2.md
§A8/§D - no arbitrary live OSM calls from a public box).

Data is (c) OpenStreetMap contributors, ODbL - the demo renders that attribution on
every poster. Re-run this after adding a location to CURATED or changing DIST_M:

    uv run --with osmnx --with shapely python scripts/fetch_map_poster_cache.py
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import osmnx as ox
import requests
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

RETRIES = 4

OUT = Path(__file__).resolve().parents[1] / "examples" / "data" / "map_poster"
DIST_M = 650  # a walkable-neighborhood crop around each point, prettymaps-style
SIMPLIFY_DEG = 0.00002  # ~2m at these latitudes - a poster doesn't need survey precision
MAX_BUILDINGS = 700  # bounds the cache size in a dense old-town core (seeded sample)

# slug, osmnx place query, display label.
CURATED: list[tuple[str, str, str]] = [
    ("marina-bay-sg", "Marina Bay, Singapore", "Marina Bay, Singapore"),
    ("le-marais-paris", "Le Marais, Paris, France", "Le Marais, Paris"),
    ("shibuya-tokyo", "Shibuya, Tokyo, Japan", "Shibuya, Tokyo"),
    ("soho-nyc", "SoHo, Manhattan, New York, USA", "SoHo, Manhattan"),
    ("kreuzberg-berlin", "Kreuzberg, Berlin, Germany", "Kreuzberg, Berlin"),
    ("camden-london", "Camden Town, London, UK", "Camden Town, London"),
]

GREEN_TAGS = {
    "leisure": ["park", "garden"],
    "landuse": ["grass", "forest", "meadow"],
    "natural": ["wood"],
}
WATER_TAGS = {"natural": "water", "waterway": True}
BUILDING_TAGS = {"building": True}


def _rings(geom: BaseGeometry) -> list[list[list[float]]]:
    """A geometry's polygon exterior rings as ``[[lon, lat], ...]`` lists (holes dropped
    - a stylized poster doesn't need them, and it halves the cache size)."""
    geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [[[round(x, 6), round(y, 6)] for x, y in geom.exterior.coords]]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [ring for part in geom.geoms for ring in _rings(part)]
    return []


def _lines(geom: BaseGeometry) -> list[list[list[float]]]:
    geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [[[round(x, 6), round(y, 6)] for x, y in geom.coords]]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [line for part in geom.geoms for line in _lines(part)]
    return []


def _clip_box(point: tuple[float, float]) -> box:
    """The fetch bbox as a shapely box, so a feature that merely *touches* the query
    area (e.g. a river or a park that extends well beyond it) gets cropped to it -
    `features_from_point`/`graph_from_point` return such geometries in full, which
    would otherwise blow out the poster's framing to that feature's real extent."""
    left, bottom, right, top = ox.utils_geo.bbox_from_point(point, dist=DIST_M)
    return box(left, bottom, right, top)


def _retry(fn, *args, **kwargs):
    """The public Overpass mirror occasionally refuses a connection under load - a
    few seconds' backoff clears it almost every time."""
    for attempt in range(RETRIES):
        try:
            return fn(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(8 * (attempt + 1))


def _polygons_from(point: tuple[float, float], tags: dict, *, cap: int | None = None) -> list:
    try:
        gdf = _retry(ox.features_from_point, point, tags, dist=DIST_M)
    except ox._errors.InsufficientResponseError:
        return []
    clip = _clip_box(point)
    geoms = list(gdf.geometry)
    if cap is not None and len(geoms) > cap:
        geoms = random.Random(f"{point}-{cap}").sample(geoms, cap)
    out: list[list[list[float]]] = []
    for geom in geoms:
        out.extend(_rings(geom.intersection(clip)))
    return out


def fetch_one(slug: str, query: str, label: str) -> dict:
    print(f"  geocoding {query!r}...")
    point = _retry(ox.geocode, query)  # (lat, lon) - a point lookup, not an admin polygon

    print("    streets...")
    # "drive" keeps the real street grid (the poster-defining shapes) and drops the
    # thousands of tiny footway/service segments a dense old-town core has at this
    # radius, which would just add visual noise and cache size.
    graph = _retry(ox.graph_from_point, point, dist=DIST_M, network_type="drive", simplify=True)
    _, edges = ox.graph_to_gdfs(graph)
    clip = _clip_box(point)
    streets = [line for geom in edges.geometry for line in _lines(geom.intersection(clip))]

    print("    buildings...")
    buildings = _polygons_from(point, BUILDING_TAGS, cap=MAX_BUILDINGS)
    print("    water...")
    water = _polygons_from(point, WATER_TAGS)
    print("    green space...")
    green = _polygons_from(point, GREEN_TAGS)

    return {
        "label": label,
        "center": [point[0], point[1]],
        "dist_m": DIST_M,
        "streets": streets,
        "buildings": buildings,
        "water": water,
        "green": green,
        "attribution": "Map data © OpenStreetMap contributors, ODbL",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (slug, query, label) in enumerate(CURATED):
        if i:
            time.sleep(5)  # be polite to the shared Overpass mirror between locations
        print(f"{slug}:")
        data = fetch_one(slug, query, label)
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        n = len(data["streets"]) + len(data["buildings"]) + len(data["water"]) + len(data["green"])
        print(f"  wrote {path.relative_to(OUT.parents[2])} ({n} shapes)")


if __name__ == "__main__":
    main()

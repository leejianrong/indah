"""One-time offline fetch: Singapore electoral-division boundaries + electorate counts
for the GRC-map demo (R2-10, docs/PLAN.md "Also folded in" / DEMOS-DOCS-ROUND2.md §C).

Pulls four years of official electoral-division GeoJSON boundaries (2011, 2015, 2020,
2025) and the matching "registered electors by constituency" table, both from
data.gov.sg (Elections Department, ODC-BY-SA-equivalent Singapore Open Data Licence),
joins them by division name, and writes one plain-JSON file per year to
``examples/data/grc_map/<year>.json``. ``examples/grc_map.py`` reads only that (via
``scripts/compile_grc_map_cache.py``'s embedded copy) - no network call, no geopandas/
shapely import, at demo runtime, same pattern as ``map_poster.py``.

The boundary/electorate name join isn't perfect - one 2025 division has no matching
electorate row in the source table (see the printed warning); it renders with no data
rather than a guessed number.

Re-run after data.gov.sg publishes a new electoral-boundary year:

    uv run --with shapely python scripts/fetch_grc_map_data.py
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from pathlib import Path

from shapely.geometry import shape as shapely_shape
from shapely.geometry.base import BaseGeometry

OUT = Path(__file__).resolve().parents[1] / "examples" / "data" / "grc_map"
API = "https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download"
SIMPLIFY_DEG = 0.0005  # ~50m - plenty for a country-wide choropleth thumbnail

# year -> data.gov.sg dataset id (Electoral Boundary <year> (GEOJSON), ELD).
BOUNDARY_DATASETS: dict[str, str] = {
    "2011": "d_305b03ed3c477aba648eeddaea2d4279",
    "2015": "d_1dea85025d48bc75ed566eb2696b7e0f",
    "2020": "d_6077aa5ab73d447b32f451ea224221b6",
    "2025": "d_7ddf956dfc1c59080bf95bba1c58a5d2",
}
# "Parliamentary General Election - Registered Electors, Rejected Votes and Spoilt
# Ballot Papers" (ELD) - one table covering every GE back to 1955.
ELECTORS_DATASET = "d_fdfb854fcb7428b29734d2e0c0674220"


def _request(url: str) -> urllib.request.Request:
    # data.gov.sg's API 403s a client with no User-Agent.
    return urllib.request.Request(url, headers={"User-Agent": "indah-demo-fetch/1.0"})


def _download_url(dataset_id: str) -> str:
    with urllib.request.urlopen(_request(API.format(dataset_id))) as resp:
        payload = json.loads(resp.read())
    url = payload.get("data", {}).get("url")
    if not url:
        raise RuntimeError(f"poll-download had no url for {dataset_id}: {payload}")
    return url


def _get(url: str) -> bytes:
    with urllib.request.urlopen(_request(url)) as resp:
        return resp.read()


def _rings(geom: BaseGeometry) -> list[list[list[float]]]:
    geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [[[round(x, 5), round(y, 5)] for x, y in geom.exterior.coords]]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [ring for part in geom.geoms for ring in _rings(part)]
    return []


def fetch_electors() -> dict[str, dict[str, int]]:
    """``{year: {DIVISION_NAME_UPPER: registered_electors}}``."""
    url = _download_url(ELECTORS_DATASET)
    text = _get(url).decode("utf-8-sig")
    by_year: dict[str, dict[str, int]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        by_year.setdefault(row["year"], {})[row["constituency"].strip().upper()] = int(
            row["no_of_registered_electors"]
        )
    return by_year


def fetch_boundary(year: str) -> dict:
    url = _download_url(BOUNDARY_DATASETS[year])
    return json.loads(_get(url))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("electors table...")
    electors_by_year = fetch_electors()

    for i, year in enumerate(BOUNDARY_DATASETS):
        if i:
            time.sleep(12)  # data.gov.sg's shared API rate-limits aggressively
        print(f"{year}:")
        raw = fetch_boundary(year)
        electors = electors_by_year.get(year, {})

        divisions = []
        unmatched = []
        for feature in raw["features"]:
            name = feature["properties"]["ED_DESC"].strip()
            geom = shapely_shape(feature["geometry"])
            count = electors.get(name.upper())
            if count is None:
                unmatched.append(name)
            divisions.append({"name": name, "electors": count, "rings": _rings(geom)})
        if unmatched:
            print(f"  no electorate match for: {unmatched} (kept, rendered as no-data)")

        path = OUT / f"{year}.json"
        path.write_text(json.dumps({"year": year, "divisions": divisions}), encoding="utf-8")
        print(f"  wrote {path.relative_to(OUT.parents[2])} ({len(divisions)} divisions)")


if __name__ == "__main__":
    main()

"""Compile the raw trail cache (scripts/fetch_gpx_cache.py's output) into the
gzip+base64 blob embedded directly in ``examples/gpx_viewer.py``.

Embedding beats a sibling data file for the same reason as the map-poster/grc-map
demos: the Colab notebook generator (``deploy/colab/make_colab.py``) inlines only the
one named example file, and a public Fly deploy should never need a live network call
to render the demo.

Run after ``fetch_gpx_cache.py`` (i.e. after adding/refreshing a trail):

    uv run python scripts/compile_gpx_cache.py
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "examples" / "data" / "gpx_viewer"
TARGET = ROOT / "examples" / "gpx_viewer.py"
BEGIN = "# BEGIN GENERATED CACHE (scripts/compile_gpx_cache.py) ----------------------\n"
END = "# END GENERATED CACHE -------------------------------------------------------\n"


def _entry(slug: str, data: dict) -> str:
    label = json.dumps(data["label"])
    source = json.dumps(data["source"])
    attribution = json.dumps(data["attribution"])
    blob = base64.b64encode(gzip.compress(json.dumps(data["points"]).encode("utf-8"), 9)).decode(
        "ascii"
    )
    width = 96
    lines = [blob[i : i + width] for i in range(0, len(blob), width)]
    wrapped = "\n".join(f'            "{ln}"' for ln in lines)
    return (
        f'    "{slug}": _Entry(\n'
        f"        label={label},\n"
        f"        source={source},\n"
        f"        attribution={attribution},\n"
        f"        distance_m={data['distance_m']!r},\n"
        f"        gz_b64=(\n{wrapped}\n        ),\n"
        "    ),\n"
    )


def main() -> None:
    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no cached trails in {RAW_DIR} - run fetch_gpx_cache.py first")

    body = "_CACHE: dict[str, _Entry] = {\n"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        body += _entry(path.stem, data)
    body += "}\n"

    text = TARGET.read_text(encoding="utf-8")
    start = text.index(BEGIN) + len(BEGIN)
    stop = text.index(END)
    new_text = text[:start] + body + text[stop:]
    TARGET.write_text(new_text, encoding="utf-8")
    total_kb = sum(len(p.read_bytes()) for p in files) / 1024
    print(f"embedded {len(files)} trail(s) ({total_kb:.0f}KB raw) into {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

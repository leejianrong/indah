"""Compile the raw OSM cache (scripts/fetch_map_poster_cache.py's output) into the
gzip+base64 blob embedded directly in ``examples/map_poster.py``.

Embedding beats a sibling data file because the Colab notebook generator
(``deploy/colab/make_colab.py``) inlines only the one named example file - a
``examples/data/map_poster/*.json`` sibling would not exist in the generated
notebook. Gzip shrinks the six curated locations from ~850KB of JSON to ~180KB,
manageable as a literal in one file (the same "bundle it in the script" approach
``upload_classify.py`` uses for its sample photos, just bigger data).

Run after ``fetch_map_poster_cache.py`` (i.e. after adding/refreshing a location):

    uv run python scripts/compile_map_poster_cache.py
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "examples" / "data" / "map_poster"
TARGET = ROOT / "examples" / "map_poster.py"
BEGIN = "# BEGIN GENERATED CACHE (scripts/compile_map_poster_cache.py) --------------\n"
END = "# END GENERATED CACHE -------------------------------------------------------\n"


def _entry(slug: str, data: dict) -> str:
    label = json.dumps(data["label"])
    blob = base64.b64encode(gzip.compress(json.dumps(data).encode("utf-8"), 9)).decode("ascii")
    # Wrap the base64 text so no line is absurdly long in the source file.
    width = 96
    lines = [blob[i : i + width] for i in range(0, len(blob), width)]
    wrapped = "\n".join(f'    "{ln}"' for ln in lines)
    return (
        f'    "{slug}": _Entry(\n'
        f"        label={label},\n"
        f"        gz_b64=(\n{wrapped}\n        ),\n"
        "    ),\n"
    )


def main() -> None:
    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no cached locations in {RAW_DIR} - run fetch_map_poster_cache.py first")

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
    print(f"embedded {len(files)} locations ({total_kb:.0f}KB raw) into {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

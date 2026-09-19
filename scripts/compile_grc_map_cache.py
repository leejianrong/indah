"""Compile the raw GRC-boundary cache (scripts/fetch_grc_map_data.py's output) into
the gzip+base64 blob embedded directly in ``examples/grc_map.py``.

Same rationale as ``compile_map_poster_cache.py``: embedding beats a sibling data file
because the Colab notebook generator inlines only the one named example file.

Run after ``fetch_grc_map_data.py`` (i.e. after data.gov.sg publishes a new year):

    uv run python scripts/compile_grc_map_cache.py
"""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "examples" / "data" / "grc_map"
TARGET = ROOT / "examples" / "grc_map.py"
BEGIN = "# BEGIN GENERATED CACHE (scripts/compile_grc_map_cache.py) --------------\n"
END = "# END GENERATED CACHE -----------------------------------------------------\n"


def main() -> None:
    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no cached years in {RAW_DIR} - run fetch_grc_map_data.py first")

    body = "_CACHE: dict[str, str] = {\n"
    for path in files:
        blob = base64.b64encode(gzip.compress(path.read_bytes(), 9)).decode("ascii")
        width = 96
        lines = [blob[i : i + width] for i in range(0, len(blob), width)]
        wrapped = "\n".join(f'    "{ln}"' for ln in lines)
        body += f'    "{path.stem}": (\n{wrapped}\n    ),\n'
    body += "}\n"

    text = TARGET.read_text(encoding="utf-8")
    start = text.index(BEGIN) + len(BEGIN)
    stop = text.index(END)
    TARGET.write_text(text[:start] + body + text[stop:], encoding="utf-8")
    total_kb = sum(len(p.read_bytes()) for p in files) / 1024
    print(f"embedded {len(files)} years ({total_kb:.0f}KB raw) into {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

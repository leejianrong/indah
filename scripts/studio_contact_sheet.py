"""Render a contact sheet of the Studio screenshots (``tests/e2e/test_studio.py`` writes them).

    STUDIO_SHOTS=/tmp/studio-shots uv run pytest tests/e2e/test_studio.py
    uv run --extra e2e python scripts/studio_contact_sheet.py /tmp/studio-shots

Writes ``sheet-<chapter>.png`` next to the shots: one tile per page, grouped by chapter, so a
whole chapter can be vetted at a glance.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

TILE = 400  # px wide; each shot is clipped to its top part


def main(folder: str) -> None:
    shots = sorted(p for p in Path(folder).glob("*.png") if not p.name.startswith("sheet-"))
    groups: dict[str, list[Path]] = defaultdict(list)
    for shot in shots:
        groups[shot.stem.split("-")[0]].append(shot)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for chapter, files in groups.items():
            tiles = "".join(
                f'<figure><img src="{f.resolve().as_uri()}">'
                f"<figcaption>{f.stem}</figcaption></figure>"
                for f in files
            )
            html = (
                "<style>body{margin:0;padding:12px;background:#222;font:12px system-ui;color:#eee;"
                f"display:flex;flex-wrap:wrap;gap:12px;width:{3 * (TILE + 12) + 12}px}}"
                f"figure{{margin:0;width:{TILE}px}}img{{width:{TILE}px;max-height:560px;"
                "object-fit:cover;object-position:top;display:block;border:1px solid #555}</style>"
                + tiles
            )
            page = browser.new_page(viewport={"width": 3 * (TILE + 12) + 24, "height": 600})
            sheet = Path(folder) / f"sheet-{chapter}.html"
            sheet.write_text(html)  # a file:// page may load file:// images; about:blank may not
            page.goto(sheet.resolve().as_uri())
            page.wait_for_timeout(300)
            page.screenshot(path=str(Path(folder) / f"sheet-{chapter}.png"), full_page=True)
            page.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/studio-shots")

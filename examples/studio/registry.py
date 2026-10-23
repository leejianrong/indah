"""The Studio's pages as data, for the docs (ADR-0041).

``export_pages()`` turns ``discover()`` into a list of plain dicts (``pages.json``): the id the docs
embed (``<chapter>/<page>``), the text a reader sees, the source shown under the demo, and whether
the page can run in the docs' browser runtime. It is built from the Studio itself, so it is never a
copy. ``embed_problems()`` is the fast check that every ``<indah-live page="...">`` in the docs
names a real page.

    uv run python scripts/export_studio_pages.py build/pages.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core import Chapter, discover, page_source

SHOTS_DIR = "assets/live/shots"


def screenshot_path(chapter_slug: str, slug: str) -> str:
    """Where the docs build puts a page's screenshot (the name tests/e2e/test_studio.py writes)."""
    name = re.sub(r"[^a-z0-9]+", "-", f"{chapter_slug}-{slug}")
    return f"{SHOTS_DIR}/{name}.png"


def export_pages(chapters: list[Chapter] | None = None) -> list[dict[str, Any]]:
    """Every page and whole app of the Studio, in chapter order, as JSON-ready dicts."""
    out: list[dict[str, Any]] = []
    for chapter in chapters if chapters is not None else discover():
        for kind, items in (("page", chapter.pages), ("app", chapter.apps)):
            for item in items:
                reason = item.local_only
                out.append(
                    {
                        "id": f"{chapter.slug}/{item.slug}",
                        "chapter": chapter.slug,
                        "slug": item.slug,
                        "kind": kind,
                        "title": item.title,
                        "summary": item.summary,
                        # A whole app has no single build function to show.
                        "source": page_source(item) if kind == "page" else None,
                        "covers": list(item.covers),
                        "docs": item.docs,
                        "adr": list(item.adr),
                        "runnable": reason is None,
                        "local_only": reason,
                        "screenshot": screenshot_path(chapter.slug, item.slug),
                    }
                )
    return out


def dumps(pages: list[dict[str, Any]]) -> str:
    """The registry as stable JSON text (same Studio in, same bytes out)."""
    return json.dumps(pages, indent=2, ensure_ascii=False) + "\n"


_EMBED = re.compile(r"<indah-live\b([^>]*)>", re.IGNORECASE)
_PAGE_ATTR = re.compile(r"""\bpage\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def embed_problems(docs_dir: Path, chapters: list[Chapter] | None = None) -> list[str]:
    """One line for each ``<indah-live>`` under ``docs_dir`` that names no real page."""
    known = {p["id"] for p in export_pages(chapters)}
    problems: list[str] = []
    for md in sorted(Path(docs_dir).rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        for tag in _EMBED.finditer(text):
            line = text.count("\n", 0, tag.start()) + 1
            match = _PAGE_ATTR.search(tag.group(1))
            where = f"{md}:{line}"
            if match is None:
                problems.append(f'{where}: <indah-live> needs a page="chapter/page" attribute')
                continue
            page = (match.group(1) if match.group(1) is not None else match.group(2)).strip()
            if page not in known:
                problems.append(f"{where}: no Studio page {page!r} (ids look like layout/spacing)")
    return problems

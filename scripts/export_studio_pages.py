"""Export the Studio's pages as ``pages.json`` for the docs build (ADR-0041).

    uv run python scripts/export_studio_pages.py [OUT.json]    # default: stdout
    uv run python scripts/export_studio_pages.py --check       # fail on a bad <indah-live> embed
    uv run python scripts/export_studio_pages.py --unembedded  # pages the docs never show live

``--check`` is the fast embed gate (also run by tests/unit/test_docs_embeds.py).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.studio import registry  # noqa: E402


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        problems = registry.embed_problems(ROOT / "website" / "docs")
        for line in problems:
            print(line, file=sys.stderr)
        return 1 if problems else 0
    if argv[:1] == ["--unembedded"]:
        for page_id in registry.unembedded_pages(ROOT / "website" / "docs"):
            print(page_id)
        return 0
    text = registry.dumps(registry.export_pages())
    if argv:
        out = Path(argv[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} ({len(registry.export_pages())} entries)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Generate one 'Open in Colab' notebook per demo, from the shared manifest.

Each notebook is self-contained (no clone): it pip-installs indah, downloads the
example file from GitHub, and launches it - so it embeds inline in a Colab cell
(ADR-0023, the free try-it-now tier). Reuses deploy/spaces/demos.tsv as the single
source of demos, and writes examples/colab/<slug>.ipynb (committed so the
"Open in Colab" links resolve).

Run:  python deploy/colab/make_colab.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "deploy" / "spaces" / "demos.tsv"
OUT = REPO / "examples" / "colab"
# Install the published package from PyPI (not a git clone), so the notebook is what
# a user would actually run.
INDAH_PIP = "indah"


def _code(*lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": _src(lines),
    }


def _md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def _src(lines: tuple[str, ...]) -> list[str]:
    # nbformat stores source as a list of lines, each ending in \n except the last.
    return [ln + "\n" for ln in lines[:-1]] + [lines[-1]] if lines else []


def _example_source(example: str) -> tuple[str, ...]:
    """The demo's source, laid out for the notebook (no clone, no download).

    Drops the ``if __name__ == "__main__":`` block (CLI/argparse launch) so the cell
    just defines the module-level ``app``; a separate cell launches it inline.
    """
    text = (REPO / "examples" / example).read_text(encoding="utf-8")
    idx = text.find('if __name__ == "__main__":')
    if idx != -1:
        text = text[:idx].rstrip() + "\n"
    return tuple(text.rstrip("\n").split("\n"))


def notebook(slug: str, example: str, title: str, extra: str) -> dict:
    pip = f'"{INDAH_PIP}"' + ("" if extra == "-" else " " + " ".join(extra.split()))
    cells = [
        _md(
            f"# indah - {title}",
            "",
            "A live demo of [**indah**](https://github.com/leejianrong/indah) - a "
            "reactive Python UI framework for cloud notebooks (no Node, single port, "
            "streaming over SSE).",
            "",
            "The full app is laid out below - read it, tweak it, and re-run. "
            "**Runtime -> Run all**, then use the app that appears inline in the last cell.",
        ),
        _code("# Install indah from PyPI (plus any demo extras).", f"!pip install -q {pip}"),
        _code(
            f"# {example} - the complete demo, inline (no clone, no download).",
            *_example_source(example),
        ),
        _code(
            "# Launch it - in Colab this embeds the app inline in the cell output.",
            "import indah",
            "indah.launch(app)",
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "colab": {"provenance": []},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        slug, example, title, _emoji, extra = line.split("\t")
        path = OUT / f"{slug}.ipynb"
        path.write_text(json.dumps(notebook(slug, example, title, extra), indent=1) + "\n")
        made.append(path.relative_to(REPO))
    for p in made:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()

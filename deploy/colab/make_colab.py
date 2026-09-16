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
BRANCH = "main"
OWNER_REPO = "leejianrong/indah"
INDAH_PIP = f"indah @ git+https://github.com/{OWNER_REPO}@{BRANCH}"


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


def notebook(slug: str, example: str, title: str, extra: str) -> dict:
    pip = f'"{INDAH_PIP}"' + ("" if extra == "-" else " " + " ".join(extra.split()))
    raw = f"https://raw.githubusercontent.com/{OWNER_REPO}/{BRANCH}/examples/{example}"
    cells = [
        _md(
            f"# indah - {title}",
            "",
            "A live demo of [**indah**](https://github.com/leejianrong/indah) - a "
            "reactive Python UI framework for cloud notebooks (no Node, single port, "
            "streaming over SSE).",
            "",
            "**Runtime -> Run all**, then use the app that appears inline below.",
        ),
        _code("# Install indah (and any demo extras).", f"!pip install -q {pip}"),
        _code(
            "# Fetch the example (no clone needed).",
            f"!wget -q {raw} -O demo.py",
        ),
        _code(
            "# Launch it - in Colab this embeds the app inline in the cell output.",
            "import indah, demo",
            "indah.launch(demo.app)",
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

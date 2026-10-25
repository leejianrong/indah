"""The committed Colab notebooks must match what deploy/colab/make_colab.py generates.

Each notebook embeds its demo's source, so editing a demo makes the notebook stale. Run
``make colab`` to regenerate them.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def make_colab():
    spec = importlib.util.spec_from_file_location(
        "make_colab", REPO / "deploy" / "colab" / "make_colab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["make_colab"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_committed_notebooks_match_generator(make_colab):
    expected = make_colab.render_all()
    stale = [p.name for p, text in expected.items() if not p.exists() or p.read_text() != text]
    extra = sorted(p.name for p in make_colab.OUT.glob("*.ipynb") if p not in expected)
    assert not stale and not extra, (
        f"Colab notebooks are out of date (stale or missing: {stale}; not in the manifest: "
        f"{extra}). Run `make colab` (uv run python deploy/colab/make_colab.py) and commit "
        "the result."
    )


def test_notebooks_are_valid_and_embedded_source_compiles(make_colab):
    for path, text in make_colab.render_all().items():
        nb = json.loads(text)
        assert nb["nbformat"] == 4
        for cell in nb["cells"]:
            assert cell["cell_type"] in {"code", "markdown"}
            if cell["cell_type"] == "code":
                source = "".join(cell["source"])
                if source.startswith("!pip") or "\n!pip" in source:
                    source = "\n".join(ln for ln in source.splitlines() if not ln.startswith("!"))
                ast.parse(source, filename=path.name)
        assert "—" not in text, f"{path.name}: use hyphens, not em-dashes"


def test_manifest_matches_gallery_catalog(make_colab):
    tomllib = pytest.importorskip("tomllib")  # Python 3.11 and later
    catalog = tomllib.loads((REPO / "deploy" / "fly" / "gallery.toml").read_text())["app"]
    hosted = {a["slug"]: a["module"] + ".py" for a in catalog if a["kind"] == "hosted"}
    manifest = {slug: example for slug, example, _t, _x in make_colab.manifest_rows()}
    assert manifest == hosted, (
        "deploy/spaces/demos.tsv (the Colab and Spaces demo list, which also carries the pip "
        "extras) and the hosted entries in deploy/fly/gallery.toml disagree. Add or remove "
        "the demo in both, then run `make colab`."
    )

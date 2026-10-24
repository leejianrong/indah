"""The sdist is trimmed to what a source build and its tests need (ADR-0042, IND-190).

``examples/`` and the gallery thumbnails are about 5 MB of a 6.5 MB sdist and are no part of the
installed package, so they stay in the repository only. Three things must hold: the sdist leaves
them out, the wheel built from the sdist is exactly the wheel built from the tree (so nothing the
package needs was dropped), and the tests still collect from an extracted sdist (the ones that
read ``examples/`` skip).
"""

import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
UV = shutil.which("uv")

if UV is None:  # pragma: no cover
    pytest.skip("needs uv to build", allow_module_level=True)


def _build(*args: str, cwd: Path) -> None:
    subprocess.run([UV, "build", "-q", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("sdist")
    _build("--sdist", "--out-dir", str(out), cwd=ROOT)
    sdist = next(out.glob("indah-*.tar.gz"))
    tree_wheels = out / "from-tree"
    _build("--wheel", "--out-dir", str(tree_wheels), cwd=ROOT)
    sdist_wheels = out / "from-sdist"
    _build("--wheel", str(sdist), "--out-dir", str(sdist_wheels), cwd=ROOT)
    with tarfile.open(sdist) as tar:
        names = [n.split("/", 1)[1] for n in tar.getnames() if "/" in n]
        tar.extractall(out / "unpacked", filter="data")
    root = next((out / "unpacked").iterdir())
    return {
        "names": names,
        "root": root,
        "size": sdist.stat().st_size,
        "tree_wheel": next(tree_wheels.glob("*.whl")),
        "sdist_wheel": next(sdist_wheels.glob("*.whl")),
    }


def test_the_sdist_leaves_out_the_examples_and_the_thumbnails(built):
    names = built["names"]
    assert not [n for n in names if n.startswith("examples/")]
    assert not [n for n in names if n.startswith("deploy/fly/thumbnails/")]


def test_the_sdist_keeps_what_a_build_and_the_tests_need(built):
    names = set(built["names"])
    for needed in ("pyproject.toml", "README.md", "LICENSE", "src/indah/__init__.py"):
        assert needed in names, needed
    assert "src/indah/static/index.html" in names
    assert any(n.startswith("frontend/src/") for n in names)
    assert any(n.startswith("tests/unit/") for n in names)
    assert "deploy/fly/gallery_app.py" in names


def test_the_sdist_is_much_smaller_than_before(built):
    # 6.5 MB before the trim (0.7.0); the examples were most of it.
    assert built["size"] < 3_500_000, built["size"]


def test_the_wheel_built_from_the_sdist_is_the_wheel_built_from_the_tree(built):
    def files(path):
        with zipfile.ZipFile(path) as z:
            return sorted(n for n in z.namelist() if not n.endswith("/RECORD"))

    assert files(built["sdist_wheel"]) == files(built["tree_wheel"])


def test_the_tests_still_collect_from_an_extracted_sdist(built):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            "unit or integration",
            "tests/unit",
            "tests/integration",
        ],
        cwd=built["root"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
    # Some test files read examples/ and are left out; the library's own tests are still collected.
    collected = int(re.search(r"(\d+)(?:/\d+)? tests? collected", result.stdout).group(1))
    assert collected > 500, result.stdout[-500:]

"""R4 guards: the pre-built shell ships in the package and no Node is needed.

The full clean-env proof (pip install the wheel in a fresh venv with Node/npm
tripwires on PATH, confirm zero invocations) is a manual/e2e step documented in
docs/SLICES.md. These fast checks pin the invariants that make it hold.
"""

import sys
from importlib.resources import files
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    tomllib = None

# Anything that would drag a JavaScript toolchain into install or runtime.
_JS_TOOLCHAIN = ("node", "npm", "npx", "bun", "yarn", "pnpm", "vite", "svelte", "esbuild")


@pytest.mark.unit
def test_prebuilt_shell_ships_in_the_package():
    shell = files("indah.static").joinpath("index.html").read_text(encoding="utf-8")
    # A real bundle, not a placeholder: it inlines the SPA and opens the SSE stream.
    assert len(shell) > 10_000
    assert "EventSource" in shell
    assert "api/stream" in shell


@pytest.mark.unit
@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs Python 3.11+")
def test_runtime_dependencies_are_python_only():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    for dep in deps:
        name = dep.lower()
        assert not any(tool in name for tool in _JS_TOOLCHAIN), (
            f"runtime dependency {dep!r} pulls in a JS toolchain (violates R4)"
        )

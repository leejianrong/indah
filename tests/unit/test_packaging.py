"""R4 guards: the pre-built shell ships in the package and no Node is needed.

The full clean-env proof (pip install the wheel in a fresh venv with Node/npm
tripwires on PATH, confirm zero invocations) is a manual/e2e step documented in
docs/SLICES.md. These fast checks pin the invariants that make it hold.
"""

import re
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
def test_shell_supports_password_text_inputs():
    # The shell renders TextInput(password=True) as <input type=password> - the masked
    # field for secrets like an API key (the keyed-demo path).
    shell = files("indah.static").joinpath("index.html").read_text(encoding="utf-8")
    assert '"password":"text"' in shell  # type={props.password ? "password" : "text"}


@pytest.mark.unit
def test_chat_box_is_fixed_height_and_does_not_stretch():
    """Regression: the Chat container is a fixed-height scroll viewport, not a box
    that grows message by message.

    It used to stretch because ``.chat`` set ``max-height`` with no ``height``: it
    started collapsed and expanded bubble by bubble until it finally scrolled -
    off-putting, unlike ChatGPT/Gemini where the message area is a fixed viewport
    with the input pinned below. Pin a fixed ``height`` so the space is pre-allocated
    and the box only ever scrolls.
    """
    shell = files("indah.static").joinpath("index.html").read_text(encoding="utf-8")
    match = re.search(r"\.chat\s*\{([^}]*)\}", shell)
    assert match, "no `.chat` rule found in the built shell"
    rule = match.group(1)
    assert re.search(r"\bheight:\s*\d", rule), (
        "the chat box needs a fixed `height` so its space is pre-allocated up front"
    )
    assert "max-height" not in rule, (
        "`max-height` lets the chat box grow as messages arrive; use a fixed `height`"
    )


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

"""The design contract (ADR-0031): the shell's tokens, the Theme allowlist and the
published design-system page stay in step."""

import re
from pathlib import Path

import pytest

from indah.theme import COLOUR_TOKENS

ROOT = Path(__file__).resolve().parents[2]
SHELL = (ROOT / "frontend" / "index.html").read_text()
PAGE = (ROOT / "website" / "docs" / "design-system.md").read_text()

# Identity and typography/shape tokens are documented but are not colour roles.
NOT_COLOUR = {"brand-a", "brand-b", "radius", "radius-sm", "radius-pill"}


def _block(selector: str) -> dict[str, str]:
    start = SHELL.index(selector + " {")
    body = SHELL[start : SHELL.index("\n      }", start)]
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", body))


light = _block(":root")
dark = _block(':root[data-theme="dark"]')


@pytest.mark.unit
def test_light_and_dark_define_the_same_colour_tokens():
    colour = lambda d: {k for k in d if not k.startswith("font-")} - NOT_COLOUR  # noqa: E731
    assert colour(light) - colour(dark) == set()
    assert colour(dark) - colour(light) == set()


@pytest.mark.unit
def test_every_theme_token_exists_in_both_schemes():
    assert COLOUR_TOKENS <= set(light)
    assert COLOUR_TOKENS <= set(dark)


@pytest.mark.unit
def test_every_filled_role_has_an_on_partner():
    for role in ("primary", "secondary"):
        assert f"on-{role}" in light and f"on-{role}-container" in light


@pytest.mark.unit
def test_the_published_page_names_every_token():
    for name in sorted(COLOUR_TOKENS) + ["radius", "radius-sm", "radius-pill"]:
        assert f"`{name}`" in PAGE, f"design-system.md does not document `{name}`"

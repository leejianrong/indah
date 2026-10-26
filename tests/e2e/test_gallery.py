"""Open every demo of the public gallery in a real browser (IND-167).

Two targets, one test per hosted demo in ``gallery.toml``:

* **Post-deploy** - set ``GALLERY_URL`` (for example https://indah-demos.fly.dev) and the
  tests check the live site, so a stale or broken deploy shows up before a visitor finds it.
* **Local** - with no ``GALLERY_URL``, the gallery is built from this checkout and launched. It
  needs the gallery's own dependencies (``numpy``, ``pillow``, ``onnxruntime``,
  ``huggingface_hub``, ``matplotlib``) and network for the model weights, and skips when they
  are missing, so the fast CI layers are not affected.

Each demo must leave "connecting" behind, answer its main control, and raise no console error,
failed request or CSP violation (the conftest listens for the last).
"""

import os
import sys
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "deploy" / "fly"), str(ROOT / "examples")]

LIVE = os.environ.get("GALLERY_URL", "").rstrip("/")
SLUGS = [
    "chatbot",
    "training-dashboard",
    "diffusion",
    "poster",
    "image-classify",
    "object-detection",
    "charts",
    "stocks",
    "dataframe-explorer",
    "prettymap",
    "map-poster",
    "grc-map",
    "audio-analysis",
    "gpx-viewer",
    "markov-poet",
    "sorting",
]
# A demo that fetches map tiles or fonts from a third party may log a blocked request on a
# machine with no network; only a live-site run treats that as a failure.
_ALLOWED = ("tile.openstreetmap", "favicon")


def test_catalog_matches_the_list_here():
    """Keep SLUGS in step with the gallery catalog, so a new demo gets a smoke test."""
    import gallery_catalog

    hosted = {e["slug"] for e in gallery_catalog.hosted(gallery_catalog.load_catalog())}
    assert hosted == set(SLUGS), f"gallery.toml and SLUGS differ: {hosted ^ set(SLUGS)}"


@pytest.fixture(scope="module")
def base():
    if LIVE:
        yield LIVE + "/"
        return
    for mod in ("numpy", "PIL", "onnxruntime", "huggingface_hub", "matplotlib"):
        pytest.importorskip(mod)
    from gallery_app import create_gallery

    from indah.launch import launch

    handle = launch(create_gallery(), block=False, open_inline=False)
    try:
        yield handle.url.rstrip("/") + "/"
    finally:
        handle.stop()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _main_control(page):
    """Use the first thing a visitor would touch: a slider, a select, else a button."""
    slider = page.locator("input[type=range]").first
    if slider.count():
        slider.focus()
        slider.press("ArrowRight")
        return
    select = page.locator("select").first
    if select.count():
        options = select.locator("option")
        if options.count() > 1:
            select.select_option(index=1)
            return
    buttons = page.locator("button:visible").filter(has_not_text="Source")
    if buttons.count():
        buttons.first.click()


@pytest.mark.e2e
@pytest.mark.parametrize("slug", SLUGS)
def test_demo_loads_and_responds(base, browser, slug):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    problems: list[str] = []
    page.on(
        "console",
        lambda m: (
            problems.append(f"console: {m.text}")
            if m.type == "error" and not any(a in m.text for a in _ALLOWED)
            else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on(
        "response",
        lambda r: (
            problems.append(f"http {r.status}: {r.url}")
            if r.status >= 400 and not any(a in r.url for a in _ALLOWED)
            else None
        ),
    )
    try:
        page.goto(f"{base}{slug}/", wait_until="domcontentloaded")
        body = page.locator("body")
        # The model-backed demos load weights before the first snapshot, so allow for it.
        expect(body).not_to_contain_text("connecting", timeout=60_000)
        # The header alone is a few words; a rendered demo has far more text than that.
        page.wait_for_function("document.body.innerText.length > 80", timeout=15_000)
        _main_control(page)
        page.wait_for_timeout(1500)
        expect(body).not_to_contain_text("reconnecting")
    finally:
        page.close()
    assert not problems, f"{slug}: {problems}"

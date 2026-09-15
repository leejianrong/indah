"""End-to-end through a real headless browser (Chromium via Playwright).

This is the only layer that renders the pre-built Svelte shell in a real DOM and
proves the Python core, the JSON protocol, and the shell agree - including the V4
additions (the generic Custom.svelte renderer, Select, DataFrame) that the
httpx-level e2e only exercises on the protocol side.

Heavy layer: marked `e2e`, excluded from the fast pre-push/CI gate. Needs the
browser installed:

    uv sync --extra dev --extra e2e
    uv run playwright install chromium
    uv run pytest -m e2e -q          # or: make test-e2e

The synchronous Playwright API is used deliberately: the test itself is sync (so
it never collides with pytest-asyncio's event loop), while `launch()` runs the
real uvicorn server in its own background thread.
"""

import pytest

from indah.launch import launch

# Skip cleanly (rather than erroring) where the browser layer isn't installed,
# so `-m e2e` still runs the httpx layer on a plain `--extra dev` checkout.
playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright
expect = playwright_sync.expect


@pytest.mark.e2e
def test_shell_renders_and_patches_in_a_real_browser():
    """The demo app renders in Chromium, and slider/select/custom events patch
    the live DOM through the SSE round-trip."""
    handle = launch(block=False, open_inline=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")

                # 1) The init tree renders: the heading plus one of each V4 control.
                expect(
                    page.locator("div.text", has_text="indah: starter components")
                ).to_be_visible()
                slider = page.locator("input[type=range]")
                select = page.locator("select")
                color = page.locator("input[type=color]")
                expect(slider).to_be_visible()
                expect(select).to_be_visible()
                expect(color).to_be_visible()
                expect(page.locator("table.dataframe")).to_be_visible()

                # 2) A slider event patches its dependent label live. Setting a
                # range input's value needs a dispatched input event (fill() does
                # not fire one for type=range).
                slider.evaluate(
                    "el => { el.value = '7';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(page.locator("div.text", has_text="2 x 7 = 14")).to_be_visible()

                # 3) A select event swaps the reactive DataFrame (squares -> primes).
                expect(page.locator("table.dataframe th", has_text="n^2")).to_be_visible()
                select.select_option("primes")
                expect(page.locator("table.dataframe th", has_text="prime")).to_be_visible()

                # 4) The registered custom component (colorpicker) round-trips its
                # value back into Python, which patches the accent label.
                color.evaluate(
                    "el => { el.value = '#ff0000';"
                    " el.dispatchEvent(new Event('input', { bubbles: true })); }"
                )
                expect(page.locator("div.text", has_text="accent = #ff0000")).to_be_visible()
            finally:
                browser.close()
    finally:
        handle.stop()

"""Chart demos fit a 390px phone screen without a sideways page scroll (IND-221)."""

import importlib
import sys
from pathlib import Path

import pytest

from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))

DEMOS = ["charts", "expenses", "stocks", "training_dashboard", "gpx_viewer"]


@pytest.mark.e2e
@pytest.mark.parametrize("name", DEMOS)
def test_chart_demo_has_no_horizontal_overflow_at_390(name):
    mod = importlib.import_module(name)
    handle = launch(mod.app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 390, "height": 800}).new_page()
            page.goto(handle.url)
            page.wait_for_selector(".chart canvas", timeout=30_000)
            page.wait_for_timeout(800)
            over = page.evaluate(
                """() => {
                  const de = document.documentElement;
                  const bad = [...document.querySelectorAll('.chart, .chart *')]
                    .filter(e => e.getBoundingClientRect().right > innerWidth + 1)
                    .map(e => e.className || e.tagName).slice(0, 5);
                  return {sw: de.scrollWidth, cw: de.clientWidth, bad};
                }"""
            )
            browser.close()
        assert over["sw"] <= over["cw"], over
        assert not over["bad"], over
    finally:
        handle.stop()

"""A plain table scrolls sideways on a phone and keeps its cells on one line (IND-178).

At 390px a table whose first column holds long names is wider than the screen. The owner prefers
a sideways scroll to wrapping, so the table stays as it is: one line per cell, inside a scroll box
where every column can be reached. (PR #228 wrapped the cells below 560px; that was reverted.)
"""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

NAMES = [
    "MARINE PARADE-BRADDELL HEIGHTS",
    "WEST COAST-JURONG WEST",
    "TAMPINES CHANGKAT",
    "ANG MO KIO",
]


def _build():
    rows = [[name, 150_000 - i * 1000] for i, name in enumerate(NAMES)]
    source = {"columns": ["Division", "Registered electors"], "rows": rows}
    return indah.Column(children=[indah.Table(source, label="Every division")])


@pytest.fixture(scope="module")
def server():
    handle = launch(
        indah.create_app(session_factory=lambda: Session(_build())), block=False, open_inline=False
    )
    try:
        yield handle
    finally:
        handle.stop()


def _open(server, width):
    p = playwright_sync.sync_playwright().start()
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": width, "height": 800}).new_page()
    page.goto(server.url)
    expect(page.locator("table.table tbody tr")).to_have_count(len(NAMES))
    return p, browser, page


def _row_heights(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('table.table tbody tr')].map(r => r.offsetHeight)"
    )


def _overflow(page):
    return page.evaluate(
        """() => {
          const box = document.querySelector('.table-scroll');
          return {scroll: box.scrollWidth, client: box.clientWidth};
        }"""
    )


@pytest.mark.e2e
def test_a_narrow_table_scrolls_sideways_and_every_column_is_reachable(server):
    p, browser, page = _open(server, 390)
    try:
        size = _overflow(page)
        assert size["scroll"] > size["client"], f"the table should need a sideways scroll: {size}"
        heights = _row_heights(page)
        assert max(heights) == min(heights), f"cells wrapped on a phone: {heights}"
        # Scrolling the box to its end brings the last column on screen.
        page.evaluate("document.querySelector('.table-scroll').scrollLeft = 1e6")
        last = page.locator("table.table th").last.bounding_box()
        assert 0 <= last["x"] and last["x"] + last["width"] <= 390
    finally:
        browser.close()
        p.stop()


@pytest.mark.e2e
def test_a_wide_screen_keeps_one_line_cells(server):
    p, browser, page = _open(server, 1200)
    try:
        heights = _row_heights(page)
        assert max(heights) == min(heights), f"rows wrapped on a wide screen: {heights}"
    finally:
        browser.close()
        p.stop()

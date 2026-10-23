"""A plain table fits a phone instead of hiding its second column (IND-178).

At 390px a table whose first column holds long names used to keep every cell on one line, so the
first column took the whole width and the second sat behind a sideways scroll nobody could see.
Below 560px the cells of a plain table now wrap, so both columns are on screen.
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


def _overflow(page):
    return page.evaluate(
        """() => {
          const box = document.querySelector('.table-scroll');
          return {scroll: box.scrollWidth, client: box.clientWidth};
        }"""
    )


@pytest.mark.e2e
def test_both_columns_are_on_screen_at_390px(server):
    p, browser, page = _open(server, 390)
    try:
        size = _overflow(page)
        assert size["scroll"] <= size["client"], f"the table needs a sideways scroll: {size}"
        last = page.locator("table.table th").last.bounding_box()
        assert last["x"] + last["width"] <= 390
    finally:
        browser.close()
        p.stop()


@pytest.mark.e2e
def test_a_wide_screen_keeps_one_line_cells(server):
    p, browser, page = _open(server, 1200)
    try:
        heights = page.evaluate(
            "() => [...document.querySelectorAll('table.table tbody tr')].map(r => r.offsetHeight)"
        )
        assert max(heights) == min(heights), f"rows wrapped on a wide screen: {heights}"
    finally:
        browser.close()
        p.stop()

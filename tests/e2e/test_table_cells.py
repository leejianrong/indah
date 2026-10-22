"""A composite cell in a 20,000-row virtual table (IND-148): only the rows in view are drawn,
each with its cell, and scrolling to the end shows the last row."""

import time

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

N = 20_000


def _app():
    rows = [
        {"id": f"r{i:05d}", "prompt": f"a fairly long prompt number {i} " * 3, "tier": i % 6}
        for i in range(N)
    ]
    meter = {
        "tag": "meter",
        "attrs": {"min": "0", "max": "5"},
        "bind": {"value": "tier"},
    }

    def build() -> indah.Session:
        return indah.Session(
            indah.Column(
                children=[
                    indah.Table(
                        rows=rows,
                        key="id",
                        virtual=True,
                        height="24rem",
                        search=True,
                        columns=[
                            indah.Col("id", kind="mono", width="10ch"),
                            indah.Col("tier", kind="cell", render=meter, sort_key="tier"),
                            indah.Col("prompt", truncate=True, max_width="30ch"),
                        ],
                    )
                ]
            )
        )

    return indah.create_app(session_factory=build)


@pytest.fixture(scope="module")
def server():
    handle = launch(_app(), block=False, open_inline=False)
    try:
        yield handle
    finally:
        handle.stop()


@pytest.mark.e2e
def test_virtual_scroll_keeps_working_with_cells_and_truncation(server):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        started = time.perf_counter()
        page.goto(server.url)
        rows = page.locator("tbody tr:not(.vspacer)")
        expect(rows.first.locator("meter")).to_be_visible()
        first_paint = time.perf_counter() - started
        assert rows.count() < 80  # a window, not 20,000 rows
        scroller = page.locator(".table-scroll")
        scroller.evaluate("el => el.scrollTop = el.scrollHeight")
        expect(page.get_by_text(f"r{N - 1:05d}")).to_be_visible()
        assert rows.count() < 80
        assert first_paint < 5, f"first rows took {first_paint:.1f}s"
        browser.close()

"""``Show(when)`` in a real browser, under a strict CSP (IND-253)."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect


@pytest.mark.e2e
def test_show_keeps_its_subtree_out_of_the_dom_until_the_signal_flips():
    picked = indah.Signal(False)
    root = indah.Column(
        children=[
            indah.Button("Pick", lambda: picked.set(True)),
            indah.Button("Clear", lambda: picked.set(False)),
            indah.Show(
                picked,
                [
                    indah.Card(
                        title="Answer",
                        children=[indah.TextInput(indah.Signal(""), label="Reply")],
                    )
                ],
            ),
        ]
    )
    handle = launch(indah.create_app(session=Session(root)), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.get_by_role("button", name="Pick")).to_be_visible()
                expect(page.get_by_label("Reply")).to_have_count(0)
                assert "Answer" not in page.locator("body").inner_html()
                page.get_by_role("button", name="Pick").click()
                expect(page.get_by_label("Reply")).to_be_visible()
                page.get_by_role("button", name="Clear").click()
                expect(page.get_by_label("Reply")).to_have_count(0)
            finally:
                browser.close()
    finally:
        handle.stop()

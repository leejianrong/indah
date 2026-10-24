"""A tab follows a rollout: the first server drains, a second one takes the port (IND-201).

Heavy layer (a real browser, two real servers). The tab is told to reconnect, is refused by the
draining server for as long as it still listens, and lands on the new one once it is up.
"""

import time

import pytest

import indah
from indah.launch import find_free_port, launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect


def _app(word: str, **kwargs):
    return indah.create_app(
        session_factory=lambda: indah.Session(indah.Text(f"served by the {word} server")),
        **kwargs,
    )


@pytest.mark.e2e
def test_a_tab_moves_to_the_next_server_when_the_first_drains():
    port = find_free_port()
    first = launch(_app("first", drain_seconds=2), port=port, open_inline=False, block=False)
    second = None
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(first.url, wait_until="domcontentloaded")
                expect(page.get_by_text("served by the first server")).to_be_visible()

                first.drain(wait=False)  # the tab is told to reconnect; the server still listens
                # While the first server is up but draining, the tab is refused (503) and keeps
                # trying: it shows "reconnecting", not an error, and the page is not wiped.
                expect(page.get_by_text("reconnecting")).to_be_visible(timeout=10_000)
                expect(page.get_by_text("served by the first server")).to_be_visible()

                first.stop()
                time.sleep(0.3)
                second = launch(_app("second"), port=port, open_inline=False, block=False)

                # The retry loop finds the second server and the tab shows its page, live.
                expect(page.get_by_text("served by the second server")).to_be_visible(
                    timeout=30_000
                )
                expect(page.get_by_text("live", exact=True)).to_be_visible()
            finally:
                browser.close()
    finally:
        first.stop()
        if second is not None:
            second.stop()

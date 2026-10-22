"""The tab's title and icon follow ``ctx.title`` / ``ctx.favicon`` in a real browser (IND-152).

Runs under ``csp="strict"`` (the conftest default), so a registered favicon is proved to load
under the policy, and a violation fails the test.
"""

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

ICON = (
    b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    b"<circle cx='16' cy='16' r='11' fill='#d63a3a'/></svg>"
)


@pytest.mark.e2e
def test_title_and_icon_change_survive_a_reload_and_other_tabs_are_untouched():
    ctxs: list[indah.Context] = []

    def build(ctx: indah.Context) -> indah.Session:
        ctxs.append(ctx)
        return indah.Session(indah.Column(children=[indah.Text("hello")]))

    app = indah.create_app(
        session_factory=build, title="Parked", title_suffix="", favicons={"alert": ICON}
    )
    handle = launch(app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            a = browser.new_context().new_page()
            b = browser.new_context().new_page()
            try:
                a.goto(handle.url, wait_until="domcontentloaded")
                b.goto(handle.url, wait_until="domcontentloaded")
                expect(a.get_by_text("hello")).to_be_visible()
                expect(b.get_by_text("hello")).to_be_visible()
                assert a.title() == "Parked"
                icon = a.locator('link[rel~="icon"]')
                own_icon = icon.get_attribute("href")

                mine = ctxs[0]
                mine.title.set("(2) Parked")
                mine.favicon.set("alert")
                expect(a).to_have_title("(2) Parked")
                expect(icon).to_have_attribute("href", "api/brand/favicon/alert")
                # The browser really fetched it: the registered icon, served same-origin.
                reply = a.request.get(handle.url.rstrip("/") + "/api/brand/favicon/alert")
                assert reply.status == 200 and reply.headers["content-type"] == "image/svg+xml"
                expect(b).to_have_title("Parked")  # another tab is not touched

                # A fresh init (a reload of the same session) restores the session's own values.
                a.reload(wait_until="domcontentloaded")
                expect(a).to_have_title("(2) Parked")
                expect(icon).to_have_attribute("href", "api/brand/favicon/alert")

                mine.title.set(None)
                mine.favicon.set(None)
                expect(a).to_have_title("Parked")
                expect(icon).to_have_attribute("href", own_icon)
            finally:
                browser.close()
    finally:
        handle.stop()

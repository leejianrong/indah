"""``Theme(css=)`` applies a @media rule under ``csp="strict"`` with no violation (IND-257).

The conftest fails any test whose page reports a ``securitypolicyviolation``.
"""

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

CSS = """
@media (max-width: 500px) { body { background-color: rgb(10, 20, 30); } }
@media (min-width: 501px) { body { background-color: rgb(40, 50, 60); } }
"""


@pytest.mark.e2e
def test_a_media_rule_from_theme_css_applies_under_strict_csp():
    app = indah.create_app(
        session_factory=lambda ctx: indah.Session(indah.Column(children=[indah.Text("hello")])),
        theme=indah.Theme(css=CSS),
    )
    handle = launch(app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 400, "height": 700})
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                expect(page.get_by_text("hello")).to_be_visible()
                bg = "getComputedStyle(document.body).backgroundColor"
                assert page.evaluate(bg) == "rgb(10, 20, 30)"
                page.set_viewport_size({"width": 900, "height": 700})
                assert page.evaluate(bg) == "rgb(40, 50, 60)"
            finally:
                page.close()
                browser.close()
    finally:
        handle.stop()

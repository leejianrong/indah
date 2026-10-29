"""A big square image does not run below the fold (IND-222)."""

import base64

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="2000" viewBox="0 0 100 100">'
    '<rect width="100" height="100" fill="#e0701a"/>'
    '<circle cx="50" cy="50" r="50" fill="#222"/></svg>'
)
_URI = "data:image/svg+xml;base64," + base64.b64encode(_SVG.encode()).decode()


@pytest.mark.e2e
@pytest.mark.parametrize("width,height", [(1280, 800), (390, 800)])
def test_square_image_is_capped_to_the_viewport(width, height):
    root = indah.Column(children=[indah.Image(_URI, alt="poster")])
    handle = launch(
        indah.create_app(session_factory=lambda: Session(root)), block=False, open_inline=False
    )
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": width, "height": height}).new_page()
            page.goto(handle.url)
            page.wait_for_selector("img.image")
            page.wait_for_timeout(500)
            box = page.evaluate(
                "() => { const r = document.querySelector('img.image').getBoundingClientRect();"
                " return {w: r.width, h: r.height}; }"
            )
            browser.close()
        assert box["h"] <= height * 0.7 + 1, box
        assert box["w"] <= width, box
    finally:
        handle.stop()

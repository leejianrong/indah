"""``create_app(theme=..., logo=...)``: token overrides and a custom logo (IND-88)."""

import json
import re

import httpx
import pytest

from indah.app import create_app
from indah.components import Column, Text
from indah.session import Session
from indah.theme import Theme

SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'><rect width='8' height='8'/></svg>"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _app(**kwargs):
    return create_app(session_factory=lambda: Session(Column(children=[Text("hi")])), **kwargs)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _chrome(html: str) -> dict:
    return json.loads(re.search(r"window.__INDAH_CHROME__=(\{.*?\})</script>", html).group(1))


@pytest.mark.integration
async def test_theme_is_injected_after_the_shell_styles():
    app = _app(theme=Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}))
    async with _client(app) as c:
        html = (await c.get("/")).text
    assert '<style id="indah-theme">' in html and "--primary: #1f6feb;" in html
    assert html.rindex("<style") == html.index('<style id="indah-theme">')  # last style wins


@pytest.mark.integration
async def test_no_theme_and_no_logo_leaves_the_page_and_routes_untouched():
    async with _client(_app()) as c:
        html = (await c.get("/")).text
        logo = await c.get("/api/brand/logo")
    assert '<style id="indah-theme">' not in html and "window.__INDAH_CHROME__=" not in html
    assert logo.status_code == 404


@pytest.mark.integration
async def test_logo_is_served_sandboxed_and_the_title_becomes_the_wordmark():
    app = _app(logo=SVG, title="semula")
    async with _client(app) as c:
        html = (await c.get("/")).text
        logo = await c.get("/api/brand/logo")
    chrome = _chrome(html)
    assert chrome["logoUrl"] == "api/brand/logo" and chrome["brandName"] == "semula"
    assert logo.status_code == 200 and logo.content == SVG
    assert logo.headers["content-type"] == "image/svg+xml"
    assert logo.headers["content-security-policy"] == "sandbox"
    assert logo.headers["x-content-type-options"] == "nosniff"


@pytest.mark.integration
async def test_title_alone_does_not_rebrand_the_header():
    async with _client(_app(title="Poster")) as c:
        chrome = _chrome((await c.get("/")).text)
    assert chrome.get("brandName") is None and chrome.get("logoUrl") is None


@pytest.mark.integration
async def test_logo_can_be_a_file_path(tmp_path):
    path = tmp_path / "mark.png"
    path.write_bytes(PNG)
    async with _client(_app(logo=path)) as c:
        logo = await c.get("/api/brand/logo")
    assert logo.headers["content-type"] == "image/png" and logo.content == PNG


@pytest.mark.integration
def test_bad_logos_fail_at_app_creation(tmp_path):
    with pytest.raises(ValueError):
        _app(logo=b"not an image")
    with pytest.raises(ValueError):
        _app(logo=b"<svg>" + b"x" * (600 * 1024))
    with pytest.raises(FileNotFoundError):
        _app(logo=tmp_path / "missing.svg")


@pytest.mark.integration
async def test_density_is_set_on_the_html_element_and_validated():
    async with _client(_app(density="compact")) as client:
        html = (await client.get("/")).text
    assert '<html lang="en" data-density="compact">' in html

    async with _client(_app()) as client:
        assert '<html lang="en">' in (await client.get("/")).text  # comfortable: untouched
    with pytest.raises(ValueError):
        _app(density="tiny")


DARK_SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'><circle cx='4' cy='4' r='4'/></svg>"
)


@pytest.mark.integration
async def test_logo_pair_serves_a_mark_per_colour_scheme():
    app = _app(logo=(SVG, DARK_SVG), title="semula")
    async with _client(app) as c:
        chrome = _chrome((await c.get("/")).text)
        light = await c.get("/api/brand/logo")
        dark = await c.get("/api/brand/logo", params={"scheme": "dark"})
        other = await c.get("/api/brand/logo", params={"scheme": "neon"})
    assert chrome["logoUrl"] == "api/brand/logo"
    assert chrome["logoDarkUrl"] == "api/brand/logo?scheme=dark"
    assert light.content == SVG and dark.content == DARK_SVG
    assert dark.headers["content-security-policy"] == "sandbox"
    assert other.content == SVG  # an unknown scheme falls back to the light mark


@pytest.mark.integration
async def test_a_single_logo_sends_no_dark_url_and_a_bad_pair_is_refused():
    async with _client(_app(logo=SVG, title="semula")) as c:
        chrome = _chrome((await c.get("/")).text)
    assert "logoDarkUrl" not in chrome or chrome["logoDarkUrl"] is None
    with pytest.raises(ValueError):
        _app(logo=(SVG,))  # a pair is (light, dark)
    with pytest.raises(ValueError):
        _app(logo=(SVG, b"not an image"))
    async with _client(_app(logo=(SVG, PNG))) as c:  # the two marks may differ in type
        assert (await c.get("/api/brand/logo", params={"scheme": "dark"})).headers[
            "content-type"
        ] == "image/png"

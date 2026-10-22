"""Drive every page of the Studio (``make demo``) in a real browser.

One server for the module; one test per page and per full app, generated from the registry, so a
new page is tested the moment it is added. Each test opens the page, runs the page's own
``check(pw)`` (what to click and what to expect; default: it renders), then asserts the page
raised no console errors, no failed requests and no CSP violations (the conftest listens for
those). A screenshot of every page is written to ``$STUDIO_SHOTS`` (default
``/tmp/studio-shots``) for a visual review.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from examples.studio.app import build_app
from examples.studio.core import discover
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

SHOTS = Path(os.environ.get("STUDIO_SHOTS", "/tmp/studio-shots"))


@dataclass
class StudioPage:
    """What a page's ``check(pw)`` receives."""

    page: object
    base: str  # http://127.0.0.1:PORT/
    url: str
    context: object = None


def _items():
    out = []
    for chapter in discover():
        for page in chapter.pages:
            out.append(pytest.param(("page", chapter, page), id=f"{chapter.slug}/{page.slug}"))
        for entry in chapter.apps:
            out.append(pytest.param(("app", chapter, entry), id=f"{chapter.slug}/app-{entry.slug}"))
    return out


@pytest.fixture(scope="module")
def server():
    handle = launch(build_app(), block=False, open_inline=False)
    try:
        yield handle
    finally:
        handle.stop()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _watch(page, problems, allowed):
    def ok(text: str) -> bool:
        return any(a in text for a in allowed)

    page.on(
        "console",
        lambda m: (
            problems.append(f"console: {m.text}") if m.type == "error" and not ok(m.text) else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on(
        "response",
        lambda r: (
            problems.append(f"http {r.status}: {r.url}")
            if r.status >= 400 and not ok(r.url) and not ok(str(r.status))
            else None
        ),
    )


@pytest.mark.e2e
@pytest.mark.parametrize("item", _items())
def test_studio_page(server, browser, item):
    kind, chapter, entry = item
    base = server.url.rstrip("/") + "/"
    path = (
        f"c/{chapter.slug}/{entry.slug}"
        if kind == "page"
        else f"apps/{entry.slug}/{entry.open_path}"
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base.rstrip("/"))
    page = ctx.new_page()
    problems: list[str] = []
    _watch(page, problems, entry.expected_errors)
    try:
        page.goto(base + path, wait_until="domcontentloaded")
        if kind == "page":
            expect(page.get_by_role("heading", name=entry.title).first).to_be_visible()
        else:
            expect(page.locator("body")).not_to_be_empty()
        pw = StudioPage(page=page, base=base, url=base + path, context=ctx)
        if entry.check is not None:
            entry.check(pw)
        page.wait_for_timeout(300)
        SHOTS.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-z0-9]+", "-", f"{chapter.slug}-{entry.slug}")
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    finally:
        ctx.close()
    assert not problems, f"{chapter.slug}/{entry.slug}: {problems}"


@pytest.mark.e2e
def test_studio_home_lists_every_chapter_and_navigation_works(server, browser):
    base = server.url.rstrip("/") + "/"
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    problems: list[str] = []
    _watch(page, problems, ())
    try:
        page.goto(base, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="indah Studio")).to_be_visible()
        chapters = discover()
        for chapter in chapters:
            expect(page.get_by_text(chapter.title, exact=True).first).to_be_visible()
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / "home.png"), full_page=True)
        # home -> chapter -> page -> another chapter, by clicking
        first = chapters[0]
        page.get_by_role("link", name="Open chapter").first.click()
        expect(page.get_by_role("heading", name=first.title).first).to_be_visible()
        page.get_by_role("link", name=first.pages[0].title).first.click()
        expect(page.get_by_role("heading", name=first.pages[0].title).first).to_be_visible()
        page.get_by_role("link", name=chapters[1].title, exact=True).first.click()
        expect(page.get_by_role("heading", name=chapters[1].title).first).to_be_visible()
        page.get_by_role("link", name="indah Studio").first.click()
        expect(page.get_by_role("heading", name="indah Studio")).to_be_visible()
    finally:
        ctx.close()
    assert not problems, problems

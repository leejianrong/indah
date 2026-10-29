"""Appearance leftovers (IND-233): a long Select label wraps instead of truncating, an empty
Chat says so, and the gpx elevation trace is a clean line (no hollow marker per point)."""

import importlib
import sys
from pathlib import Path

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))

LONG = "a serene mountain lake at dawn, oil painting"


def _build():
    choice = indah.Signal("a")
    return indah.Sidebar(
        children=[
            indah.Card(
                children=[
                    indah.Select(choice, options=[("a", LONG), ("b", "Short")], label="Prompt"),
                    indah.Select(indah.Signal("b"), options=[("b", "Short")], label="One line"),
                ]
            ),
            indah.Chat(indah.Signal([]), label="Conversation"),
        ]
    )


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
    page.wait_for_selector("select")
    return p, browser, page


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1280, 390])
def test_long_select_label_wraps_rather_than_truncating(server, width):
    p, browser, page = _open(server, width)
    try:
        info = page.evaluate(
            """() => {
              const [s, one] = document.querySelectorAll('select');
              const probe = document.createElement('span');
              const cs = getComputedStyle(s);
              probe.style.cssText =
                `position:absolute;visibility:hidden;white-space:nowrap;font:${cs.font}`;
              probe.textContent = s.options[s.selectedIndex].text;
              document.body.appendChild(probe);
              const natural = probe.getBoundingClientRect().width;
              return {natural, width: s.getBoundingClientRect().width,
                      height: s.getBoundingClientRect().height,
                      oneLine: one.getBoundingClientRect().height};
            }"""
        )
        assert info["natural"] > info["width"] - 40, (
            info
        )  # precondition: it would not fit on a line
        assert info["height"] > info["oneLine"] + 10, info  # so it wrapped onto a second line
    finally:
        browser.close()
        p.stop()


@pytest.mark.e2e
def test_empty_chat_says_there_are_no_messages(server):
    p, browser, page = _open(server, 1280)
    try:
        expect(page.locator(".chat").get_by_text("No messages yet")).to_be_visible()
    finally:
        browser.close()
        p.stop()


@pytest.mark.e2e
def test_gpx_elevation_trace_has_no_marker_on_every_point():
    mod = importlib.import_module("gpx_viewer")
    session = mod.build()
    chart = next(c for c in session._by_id.values() if c.type == "chart")
    props = chart.static_props()
    assert not props.get("points"), "points=True draws a hollow dot per trackpoint"
    kinds = {s.get("label"): s.get("kind") for s in props["series"] if isinstance(s, dict)}
    assert kinds.get("Position") == "scatter"

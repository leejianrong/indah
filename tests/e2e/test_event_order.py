"""A click is handled after the input typed just before it, however slow that input is (IND-261)."""

import time

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")

SEEN: list[str] = []


def _build():
    text = indah.Signal("")
    return indah.Column(
        children=[
            indah.TextArea(text, label="Note"),
            indah.Button("Send", lambda: SEEN.append(text.value)),
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


@pytest.mark.e2e
def test_a_click_after_slow_input_still_reads_the_new_text(server):
    SEEN.clear()
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server.url)

        held = []

        def hold_input(route):  # the input POST reaches the server after the click's
            if '"input"' in (route.request.post_data or ""):
                held.append(route)
            else:
                route.continue_()

        page.route("**/api/event", hold_input)
        page.get_by_label("Note").fill("hello")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(500)
        for route in held:
            route.continue_()
        deadline = time.time() + 5
        while not SEEN and time.time() < deadline:
            page.wait_for_timeout(50)
        browser.close()
    assert SEEN == ["hello"]

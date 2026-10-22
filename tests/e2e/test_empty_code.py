"""``Code``'s Copy button and ``Empty`` in a real browser, under a strict CSP (IND-158)."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

COMMAND = "semula log --follow"


def _build():
    return indah.Column(
        children=[
            indah.Empty(
                "No requests yet",
                "Start the proxy.",
                children=[indah.Code(COMMAND, language="bash", label="Start command")],
                action=indah.Button("Send a test request", lambda: None),
            ),
            indah.Code("a\n    b\n", copy=False),
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


@pytest.fixture()
def page(server):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=server.url.rstrip("/"))
        page = ctx.new_page()
        page.goto(server.url)
        yield page
        browser.close()


@pytest.mark.e2e
def test_copy_puts_the_plain_text_on_the_clipboard_and_toasts(page):
    page.get_by_role("button", name="Copy Start command").click()
    expect(page.get_by_role("status").get_by_text("Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == COMMAND


@pytest.mark.e2e
def test_copy_is_reachable_and_operable_from_the_keyboard(page):
    button = page.locator("button.code-copy")  # its name changes to "Copied" after the press
    button.focus()
    page.keyboard.press("Enter")
    expect(button).to_have_text("Copied")
    assert page.evaluate("navigator.clipboard.readText()") == COMMAND


@pytest.mark.e2e
def test_a_scrollable_code_block_can_take_focus(page):
    block = page.locator("pre.code-pre").first
    block.focus()
    expect(block).to_be_focused()


@pytest.mark.e2e
def test_without_a_clipboard_the_text_is_selected_for_ctrl_c(page):
    page.evaluate(
        "Object.defineProperty(navigator, 'clipboard',"
        " {value: {writeText: () => Promise.reject(new Error('blocked'))}})"
    )
    page.evaluate("document.execCommand = () => false")
    page.get_by_role("button", name="Copy Start command").click()
    expect(page.get_by_text("Press Ctrl+C to copy the selected text")).to_be_visible()
    assert page.evaluate("getSelection().toString()") == COMMAND


@pytest.mark.e2e
def test_code_keeps_indentation_and_copy_false_hides_the_button(page):
    assert page.locator("pre.code-pre").nth(1).inner_text() == "a\n    b\n"
    assert page.get_by_role("button", name="Copy code").count() == 0


@pytest.mark.e2e
def test_empty_shows_title_body_children_and_the_action_last(page):
    expect(page.get_by_text("No requests yet")).to_be_visible()
    box = page.locator(".empty-state")
    order = box.evaluate(
        "el => [...el.children].map(c => c.className.split(' ').find(x => x.startsWith('t-') || "
        "x.startsWith('code-') || x.startsWith('empty-')))"
    )
    assert order[-1] == "empty-action"
    assert page.locator(".empty-action").get_by_role("button", name="Send a test request")

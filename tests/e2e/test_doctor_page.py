"""The deploy doctor page in a real browser (IND-205): its own strict policy, no violations, and
the optional copy button (a script with the page's nonce)."""

import pytest

from indah import create_app
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

TOKEN = "doctor-token-0123456789"


@pytest.mark.e2e
def test_the_doctor_page_renders_under_its_own_policy_and_copies_json():
    app = create_app(doctor=TOKEN, trusted_proxies=["127.0.0.0/8"], node_header=True)
    handle = launch(app, block=False, open_inline=False)
    problems: list[str] = []
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            ctx.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin=handle.url.rstrip("/")
            )
            page = ctx.new_page()
            page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: problems.append(str(e)))
            page.goto(f"{handle.url.rstrip('/')}/_indah/doctor?token={TOKEN}")
            expect(page.get_by_role("heading", name="Deploy doctor")).to_be_visible()
            expect(page.get_by_text("Resolved client")).to_be_visible()
            button = page.get_by_role("button", name="Copy as JSON")
            expect(button).to_be_visible()  # the script ran, so its nonce was accepted
            button.click()
            expect(page.get_by_role("button", name="Copied")).to_be_visible()
            copied = page.evaluate("navigator.clipboard.readText()")
            assert '"indah_version"' in copied and TOKEN not in copied
            assert TOKEN not in page.content()
            browser.close()
    finally:
        handle.stop()
    assert not problems, problems


@pytest.mark.e2e
def test_the_doctor_page_without_javascript_still_reads():
    app = create_app(doctor=TOKEN)
    handle = launch(app, block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(java_script_enabled=False)
            page = ctx.new_page()
            page.goto(f"{handle.url.rstrip('/')}/_indah/doctor?token={TOKEN}")
            expect(page.get_by_text("Findings")).to_be_visible()
            expect(page.get_by_role("button", name="Copy as JSON")).to_be_hidden()
            browser.close()
    finally:
        handle.stop()

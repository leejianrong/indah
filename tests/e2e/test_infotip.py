"""``InfoTip`` in a real browser, under a strict CSP (IND-159)."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

TIP = "Requests counted since midnight, UTC."
LONG = "A longer note that explains where this number comes from and why it can lag. " * 4


def _build():
    note = indah.Signal(TIP)

    def reword() -> None:
        note.set("Now counted per minute.")

    return indah.Column(
        children=[
            indah.Row(
                justify="between",
                children=[
                    indah.Text("Requests", variant="label"),
                    indah.InfoTip(note, label="About requests"),
                ],
            ),
            indah.Button("Reword", reword),
            indah.Row(
                justify="end",
                children=[indah.InfoTip(LONG, label="About the edge")],
            ),
            indah.Button("After the tip", lambda: None),
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


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(server, browser):
    page = browser.new_context(viewport={"width": 1000, "height": 700}).new_page()
    page.goto(server.url)
    expect(page.get_by_role("button", name="About requests")).to_be_visible()
    yield page
    page.context.close()


def _tab_to(page, btn):
    """Tab through the shell's own header controls until ``btn`` has focus (a keyboard focus)."""
    for _ in range(12):
        page.keyboard.press("Tab")
        if btn.evaluate("(el) => el === document.activeElement"):
            return
    raise AssertionError("the icon never took keyboard focus")


def _tip(page, name="About requests"):
    btn = page.get_by_role("button", name=name)
    return btn, page.get_by_role("tooltip").filter(visible=True)


@pytest.mark.e2e
def test_the_icon_is_one_tab_stop_and_described_by_its_tip(page):
    btn = page.get_by_role("button", name="About requests")
    desc = btn.get_attribute("aria-describedby")
    assert desc and page.locator(f"#{desc}").get_attribute("role") == "tooltip"
    # The tip is in the page even while hidden, so a screen reader can read it.
    assert page.locator(f"#{desc}").inner_text() == TIP
    expect(page.get_by_role("tooltip").filter(visible=True)).to_have_count(0)
    _tab_to(page, btn)
    expect(btn).to_be_focused()
    page.keyboard.press("Tab")
    expect(btn).not_to_be_focused()  # the next stop is the Reword button: not a trap


@pytest.mark.e2e
def test_it_opens_on_keyboard_focus_and_closes_on_escape_and_blur(page):
    btn, tips = _tip(page)
    _tab_to(page, btn)
    expect(tips).to_have_text(TIP)
    expect(btn).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(tips).to_have_count(0)
    expect(btn).to_be_focused()  # Escape hides the tip, focus stays
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    expect(tips).to_have_text(TIP)
    page.keyboard.press("Tab")  # leaves: blur hides it
    expect(tips).to_have_count(0)


@pytest.mark.e2e
def test_it_opens_on_hover_and_a_click_pins_it_until_a_second_click(page):
    btn, tips = _tip(page)
    btn.hover()
    expect(tips).to_have_text(TIP)
    btn.click()  # pins
    page.mouse.move(5, 5)
    expect(tips).to_have_text(TIP)
    btn.click()  # a second click closes it, even while the pointer is still over the icon
    expect(tips).to_have_count(0)
    page.mouse.move(5, 5)
    btn.hover()
    expect(tips).to_have_text(TIP)
    page.mouse.move(5, 5)  # an unpinned hover closes on leave
    expect(tips).to_have_count(0)


@pytest.mark.e2e
def test_a_press_outside_closes_a_pinned_tip(page):
    btn, tips = _tip(page)
    btn.click()
    expect(tips).to_have_text(TIP)
    page.mouse.click(5, 400)
    expect(tips).to_have_count(0)


@pytest.mark.e2e
def test_the_tip_follows_a_signal(page):
    btn, tips = _tip(page)
    page.get_by_role("button", name="Reword").click()
    btn.click()
    expect(tips).to_have_text("Now counted per minute.")


@pytest.mark.e2e
def test_a_tap_toggles_it_on_a_touch_screen(server, browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 700}, has_touch=True)
    page = ctx.new_page()
    page.goto(server.url)
    btn = page.get_by_role("button", name="About requests")
    tips = page.get_by_role("tooltip").filter(visible=True)
    btn.tap()
    expect(tips).to_have_text(TIP)
    btn.tap()
    expect(tips).to_have_count(0)
    btn.tap()
    page.mouse.click(5, 400)
    expect(tips).to_have_count(0)
    ctx.close()


@pytest.mark.e2e
def test_a_long_tip_stays_inside_a_phone_screen_at_the_right_edge(server, browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 700}, has_touch=True)
    page = ctx.new_page()
    page.goto(server.url)
    page.get_by_role("button", name="About the edge").tap()
    tip = page.get_by_role("tooltip").filter(visible=True)
    expect(tip).to_have_count(1)
    box = tip.bounding_box()
    assert box["x"] >= 7 and box["x"] + box["width"] <= 390 - 7
    assert box["y"] >= 0 and box["y"] + box["height"] <= 700
    ctx.close()


@pytest.mark.e2e
def test_escape_closing_a_tip_does_not_also_close_a_modal_behind_it(server, browser):
    # A tip inside a modal: the first Escape closes the tip, the second the modal.
    shown = indah.Signal(True)
    app = indah.create_app(
        session_factory=lambda: Session(
            indah.Column(
                children=[
                    indah.Modal(
                        [indah.InfoTip("inside", label="About details")],
                        open=shown,
                        title="Details",
                    )
                ]
            )
        )
    )
    handle = launch(app, block=False, open_inline=False)
    try:
        ctx = browser.new_context(viewport={"width": 1000, "height": 700})
        page = ctx.new_page()
        page.goto(handle.url)
        btn = page.get_by_role("button", name="About details")
        _tab_to(page, btn)
        tip = page.get_by_role("tooltip").filter(visible=True)
        expect(tip).to_have_text("inside")
        page.keyboard.press("Escape")
        expect(tip).to_have_count(0)
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        ctx.close()
    finally:
        handle.stop()

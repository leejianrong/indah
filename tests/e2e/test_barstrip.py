"""``BarStrip`` in a real browser, under a strict CSP (IND-162)."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

LABELS = ["12:01", "12:02", "12:03", "12:04"]


def _build():
    series = indah.Signal([(2, 1), (4, 0), (0, 0), (3, 3)])

    def grow() -> None:
        series.set([*series.value, (1, 1)])

    return indah.Column(
        children=[
            indah.BarStrip(
                series,
                tones=["ok", "err"],
                names=["hit", "miss"],
                labels=lambda: [*LABELS, "12:05"][: len(series.value)],
                label="Calls per minute",
                height=40,
            ),
            indah.Button("Add a minute", grow),
            indah.Button("After the strip", lambda: None),
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
        page = browser.new_context().new_page()
        page.goto(server.url)
        expect(page.locator(".barstrip-bar")).to_have_count(4)
        yield page
        browser.close()


@pytest.mark.e2e
def test_bars_are_drawn_in_proportion_and_stacked(page):
    heights = page.evaluate(
        """() => [...document.querySelectorAll('.barstrip-bar')].map((b) =>
          [...b.querySelectorAll('.barstrip-seg')].map((s) => s.getBoundingClientRect().height)
        )"""
    )
    # The tallest total (6) fills the 40px strip; bar 2 is 4 of 6; the empty bar has no height.
    assert abs(sum(heights[3]) - 40) < 1.5 and abs(sum(heights[1]) - 40 * 4 / 6) < 1.5
    assert sum(heights[2]) < 1
    assert heights[0][0] > heights[0][1] * 1.5  # 2 over 1: hits are taller than misses


@pytest.mark.e2e
def test_segment_colours_come_from_the_theme_tones(page):
    same = page.evaluate(
        """() => {
          const probe = (v) => {
            const e = document.createElement('span');
            e.style.color = `var(${v})`;
            document.body.append(e);
            const c = getComputedStyle(e).color;
            e.remove();
            return c;
          };
          const bar = document.querySelector('.barstrip-bar');
          const bg = (cls) =>
            getComputedStyle(bar.querySelector('.barstrip-seg.' + cls)).backgroundColor;
          return [bg('tone-ok') === probe('--ok'), bg('tone-err') === probe('--err')];
        }"""
    )
    assert same == [True, True]


@pytest.mark.e2e
def test_hover_shows_a_tooltip_with_names_not_just_colour(page):
    page.locator(".barstrip-bar").nth(0).hover()
    tip = page.get_by_role("tooltip")
    expect(tip).to_have_text("12:01: 3 (hit 2, miss 1)")
    page.mouse.move(0, 0)
    expect(tip).to_have_count(0)


@pytest.mark.e2e
def test_the_strip_is_one_tab_stop_and_arrows_read_each_bar(page):
    strip = page.get_by_role("group", name="Calls per minute")
    expect(strip).to_have_attribute("tabindex", "0")
    assert page.locator(".barstrip-bar[tabindex]").count() == 0  # bars are not tab stops
    strip.focus()
    status = page.locator(".barstrip-status")
    expect(status).to_have_text("12:04: 6 (hit 3, miss 3)")  # starts on the latest bar
    page.keyboard.press("ArrowLeft")
    expect(status).to_have_text("12:03: 0")
    expect(page.get_by_role("tooltip")).to_have_text("12:03: 0")
    page.keyboard.press("Home")
    expect(status).to_have_text("12:01: 3 (hit 2, miss 1)")
    page.keyboard.press("ArrowLeft")  # stays on the first bar
    expect(status).to_have_text("12:01: 3 (hit 2, miss 1)")
    page.keyboard.press("End")
    expect(status).to_have_text("12:04: 6 (hit 3, miss 3)")
    page.keyboard.press("Escape")
    expect(page.get_by_role("tooltip")).to_have_count(0)


@pytest.mark.e2e
def test_tab_leaves_the_strip_so_the_keyboard_is_never_trapped(page):
    page.get_by_role("group", name="Calls per minute").focus()
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="Add a minute")).to_be_focused()


@pytest.mark.e2e
def test_a_new_bar_updates_in_place_without_remounting_the_others(page):
    page.evaluate("document.querySelector('.barstrip-bar').dataset.mark = 'kept'")
    page.get_by_role("button", name="Add a minute").click()
    expect(page.locator(".barstrip-bar")).to_have_count(5)
    assert page.evaluate("document.querySelector('.barstrip-bar').dataset.mark") == "kept"
    page.locator(".barstrip-bar").nth(4).hover()
    expect(page.get_by_role("tooltip")).to_have_text("12:05: 2 (hit 1, miss 1)")


@pytest.mark.e2e
def test_the_strip_names_itself_for_assistive_technology(page):
    label = page.get_by_role("group", name="Calls per minute").get_attribute("aria-label")
    assert "4 bars" in label


@pytest.mark.e2e
def test_reduced_motion_turns_off_the_height_transition(server):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(reduced_motion="reduce").new_page()
        page.goto(server.url)
        seg = page.locator(".barstrip-seg").first
        expect(seg).to_be_visible()
        assert seg.evaluate("(e) => getComputedStyle(e).transitionDuration") in ("0s", "0.0s")
        # Control: with no preference the bars do animate, so the test above proves the guard.
        plain = browser.new_context().new_page()
        plain.goto(server.url)
        assert (
            plain.locator(".barstrip-seg").first.evaluate(
                "(e) => getComputedStyle(e).transitionDuration"
            )
            == "0.2s"
        )
        browser.close()

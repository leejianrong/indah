"""A phone (390 px) fits the controls and the Diff (IND-259).

Every control is at least 44x44, `Diff(mode="auto")` opens unified, and a diff line wraps at word
boundaries instead of mid-word. The suite runs under the strict CSP (conftest).
"""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

A = {"title": "the quick brown fox jumps over the lazy dog and keeps running far away"}
B = {"title": "the quick brown fox leaps over the lazy dog and keeps running far away"}

CONTROLS = (
    "button:not(select > button), select, textarea, label.check, "
    "input:is([type=text],[type=number],[type=date],[type=search])"
)

LINES = """() => {
  const cells = [...document.querySelectorAll('td.code')];
  const td = cells.sort((x, y) => y.textContent.length - x.textContent.length)[0];
  const walker = document.createTreeWalker(td, NodeFilter.SHOW_TEXT);
  const lines = []; let top = null, cur = '';
  for (let n; (n = walker.nextNode()); ) {
    for (let i = 0; i < n.length; i++) {
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
      const t = Math.round(r.getBoundingClientRect().top);
      if (top !== null && t !== top) { lines.push(cur); cur = ''; }
      top = t; cur += n.data[i];
    }
  }
  lines.push(cur);
  return lines;
}"""


def _build():
    return indah.Column(
        children=[
            indah.Button("Run"),
            indah.Button("Cancel", variant="ghost"),
            indah.TextInput(indah.Signal("x"), label="Name"),
            indah.TextArea(indah.Signal("y"), label="Notes"),
            indah.Number(indah.Signal(1.0)),
            indah.Select(indah.Signal("a"), options=["a", "b"]),
            indah.Radio(indah.Signal("a"), options=["a", "b"]),
            indah.Checkbox(indah.Signal(True), label="Agree"),
            indah.Segmented(indah.Signal("a"), options=["a", "b", "c"]),
            indah.Diff(A, B, mode="auto"),
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


@pytest.fixture
def open_page(server):
    p = playwright_sync.sync_playwright().start()
    browser = p.chromium.launch()

    def go(width):
        page = browser.new_context(viewport={"width": width, "height": 800}).new_page()
        page.goto(server.url)
        expect(page.locator(".diffview")).to_be_visible()
        return page

    try:
        yield go
    finally:
        browser.close()
        p.stop()


@pytest.fixture
def phone(open_page):
    return open_page(390)


def test_every_control_is_44px(phone):
    assert phone.locator(CONTROLS).count() >= 15  # controls, theme toggle and Diff buttons
    small = phone.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map((e) => {
            const r = e.getBoundingClientRect();
            return [e.tagName + '.' + e.className, Math.round(r.width), Math.round(r.height)];
          }).filter(([, w, h]) => w < 44 || h < 44)""",
        CONTROLS,
    )
    assert small == []


def test_theme_switch_is_44px(phone):
    boxes = [b.bounding_box() for b in phone.locator(".theme-toggle button").all()]
    assert boxes
    assert all(b["width"] >= 44 and b["height"] >= 44 for b in boxes), boxes


def test_diff_auto_opens_unified_on_a_phone(phone):
    expect(phone.locator("table.diff.unified")).to_have_count(1)
    expect(phone.locator("table.diff.split")).to_have_count(0)


def test_diff_auto_opens_split_on_desktop(open_page):
    expect(open_page(1100).locator("table.diff.split")).to_have_count(1)


def test_diff_cells_wrap_whole_words(phone):
    css = phone.evaluate(
        "() => { const s = getComputedStyle(document.querySelector('td.code'));"
        " return [s.wordBreak, s.overflowWrap]; }"
    )
    assert css == ["normal", "anywhere"]
    lines = phone.evaluate(LINES)
    assert len(lines) > 1
    # no line is cut inside a word: each wrapped line ends in a space
    assert [ln for ln in lines[:-1] if not ln.endswith(" ")] == []

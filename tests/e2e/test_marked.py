"""``Marked`` in a real browser, under a strict CSP (IND-157): the spans are real elements that
add no characters, a live change updates them in place, and a List item and a table cell draw
the same thing from a render spec."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

TEXT = "Match the request.\nIgnored part \U0001f600 end"
CELL = {"component": "marked", "bind": {"runs": "runs"}}


def _build():
    marks = indah.Signal([(0, 5, "ok", "matched")])
    rows = [{"id": "r1", "runs": indah.marked_runs("alpha beta", [(6, 10, "warn", "beta!")])}]

    def more() -> None:
        marks.set([(0, 5, "ok", "matched"), (19, 31, "err", "ignored")])

    return indah.Column(
        children=[
            indah.Marked(TEXT, marks, label="Request"),
            indah.Button("More marks", more),
            indah.List(rows, key="id", item=CELL),
            indah.Table(
                columns=[indah.Col("id"), indah.Col("runs", kind="cell", render=CELL)],
                rows=rows,
                key="id",
            ),
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
def test_spans_are_marks_with_a_hover_label_and_the_text_is_unchanged(page):
    block = page.get_by_role("group", name="Request")
    expect(block.locator("mark")).to_have_count(1)
    expect(block.locator("mark").first).to_have_attribute("title", "matched")
    expect(block.locator("mark").first).to_have_class("mk tone-ok")
    assert block.text_content() == TEXT  # no characters added
    assert block.inner_text() == TEXT  # newlines kept


@pytest.mark.e2e
def test_selecting_across_marks_and_copying_gives_the_plain_text(page):
    block = page.get_by_role("group", name="Request")
    expect(block.locator("mark")).to_have_count(1)
    page.evaluate(
        """() => {
          const el = document.querySelector('.marked');
          const range = document.createRange();
          range.selectNodeContents(el);
          const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        }"""
    )
    assert page.evaluate("getSelection().toString()") == TEXT
    page.keyboard.press("Control+c")
    assert page.evaluate("navigator.clipboard.readText()") == TEXT


@pytest.mark.e2e
def test_a_live_change_updates_the_spans_with_a_code_point_offset(page):
    block = page.get_by_role("group", name="Request")
    page.get_by_role("button", name="More marks").click()
    expect(block.locator("mark")).to_have_count(2)
    # (19, 31) is "Ignored part": offsets are code points, counted on the server
    assert block.locator("mark").nth(1).text_content() == "Ignored part"
    expect(block.locator("mark").nth(1)).to_have_class("mk tone-err")


@pytest.mark.e2e
def test_a_list_item_and_a_table_cell_draw_it_from_a_spec(page):
    item = page.locator(".list-item mark")
    expect(item).to_have_count(1)
    assert item.text_content() == "beta"
    expect(item).to_have_attribute("title", "beta!")
    cell = page.locator("td mark")
    expect(cell).to_have_count(1)
    assert cell.text_content() == "beta"


@pytest.mark.e2e
def test_each_tone_has_a_non_colour_cue(page):
    page.get_by_role("button", name="More marks").click()
    styles = page.evaluate(
        """() => Object.fromEntries(['ok', 'err', 'warn', 'info', 'neutral'].map(t => {
          const el = document.createElement('mark');
          el.className = 'mk tone-' + t;
          document.querySelector('.marked').appendChild(el);
          const cs = getComputedStyle(el);
          const out = [t, cs.textDecorationLine + ' ' + cs.textDecorationStyle];
          el.remove();
          return out;
        }))"""
    )
    assert styles["ok"] == "underline solid"
    assert styles["warn"] == "underline dashed"
    assert styles["err"] == "underline wavy"
    assert styles["info"] == "underline dotted"
    assert styles["neutral"].startswith("none")

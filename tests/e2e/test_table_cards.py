"""``Table(narrow="cards")`` at 390 px (IND-258), under the strict CSP the e2e conftest sets.

Rows become bordered cards, the header is hidden, each cell carries its column title as a
``data-label`` (rendered by the shell, no script), the first column is the card heading, and the
keyboard and the selected row keep their ring. A table without ``narrow`` is left as it was.
"""

import contextlib
import re

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

ROWS = [
    {"id": "u1", "name": "Ada Lovelace", "role": "editor"},
    {"id": "u2", "name": "Alan Turing", "role": "viewer"},
    {"id": "u3", "name": "Grace Hopper", "role": "admin"},
]
COLS = [indah.Col("name", title="Member"), indah.Col("role", title="Role", kind="badge")]


def _build():
    cards = indah.Table(
        rows=ROWS,
        columns=COLS,
        key="id",
        label="Cards",
        narrow="cards",
        keyboard=True,
        selected=indah.Signal(None),
        checked=indah.Signal([]),
        actions=[
            indah.RowAction("Promote", lambda k: None),
            indah.RowAction("Remove", lambda k: None),
            indah.RowAction("Invite again", lambda k: None),
        ],
    )
    plain = indah.Table(rows=ROWS, columns=COLS, key="id", label="Plain")
    return indah.Column(children=[cards, plain])


@pytest.fixture(scope="module")
def server():
    handle = launch(
        indah.create_app(session_factory=lambda: Session(_build())), block=False, open_inline=False
    )
    try:
        yield handle
    finally:
        handle.stop()


@contextlib.contextmanager
def _open(server):
    p = playwright_sync.sync_playwright().start()
    browser = p.chromium.launch()
    try:
        page = browser.new_context(viewport={"width": 390, "height": 900}).new_page()
        page.goto(server.url)
        expect(page.locator("table.table tbody tr")).to_have_count(6)
        yield page
    finally:
        browser.close()
        p.stop()


@pytest.mark.e2e
def test_rows_render_as_labelled_cards(server):
    with _open(server) as page:
        table = page.locator("table.cards")
        expect(table.locator("thead")).to_be_hidden()
        row = table.locator("tbody tr").first
        assert row.evaluate("e => getComputedStyle(e).display") == "block"
        assert row.evaluate("e => getComputedStyle(e).borderTopWidth") == "1px"
        cells = row.locator("td[data-label]")
        assert [c.get_attribute("data-label") for c in cells.all()] == ["Member", "Role"]
        # the first column is the heading: bold, and it does not print its own label
        head = cells.first
        assert head.evaluate("e => getComputedStyle(e).fontWeight") in ("600", "700")
        assert head.evaluate("e => getComputedStyle(e, '::before').display") == "none"
        assert cells.nth(1).evaluate("e => getComputedStyle(e, '::before').content") == '"Role"'
        # no sideways scroll at 390 px, and the actions wrap inside the card
        box = page.locator(".table-scroll").first
        assert box.evaluate("e => e.scrollWidth <= e.clientWidth")
        actions = row.locator("td.actions-col")
        assert actions.evaluate("e => getComputedStyle(e).flexWrap") == "wrap"
        for button in actions.locator("button").all():
            b = button.bounding_box()
            assert b["x"] + b["width"] <= 390


@pytest.mark.e2e
def test_cards_keyboard_navigate_and_keep_their_rings(server):
    with _open(server) as page:
        table = page.locator("table.cards")
        rows = table.locator("tbody tr")
        table.focus()
        page.keyboard.press("ArrowDown")  # focus lands on row 0; this moves to row 1
        expect(rows.nth(1)).to_have_class("kb-active")
        ring = "e => getComputedStyle(e).boxShadow"
        assert rows.nth(1).evaluate(ring) != "none"
        page.keyboard.press("Enter")
        expect(rows.nth(1)).to_have_class(re.compile(r"selected"))
        page.keyboard.press("ArrowDown")
        expect(rows.nth(2)).to_have_class("kb-active")
        selected = table.locator("tbody tr.selected")
        expect(selected).to_have_count(1)
        assert selected.evaluate(ring) != "none"
        assert rows.nth(2).evaluate(ring) != "none"


@pytest.mark.e2e
def test_a_table_without_narrow_is_unchanged_at_390(server):
    with _open(server) as page:
        plain = page.locator("table.table").nth(1)
        assert "cards" not in plain.get_attribute("class")
        expect(plain.locator("thead")).to_be_visible()
        assert plain.locator("td[data-label]").count() == 0
        row = plain.locator("tbody tr").first
        assert row.evaluate("e => getComputedStyle(e).display") == "table-row"

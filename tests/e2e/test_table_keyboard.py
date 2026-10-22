"""Table keyboard navigation in a real browser (IND-164): a plain table, a 20,000-row virtual
table, a live Stream with ``follow``, a remote paged table, and the key-routing rule with
``Shortcuts`` and a text input. The conftest runs all of it under ``csp="strict"``."""

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

N = 20_000
OPENED: list = []
SHORTCUT: list = []


def _cols():
    return [indah.Col("id", kind="mono"), indah.Col("name")]


def _app():
    rows = [{"id": f"r{i:02d}", "name": f"row {i}"} for i in range(12)]
    big = [{"id": f"v{i:05d}", "name": f"big {i}"} for i in range(N)]
    stream = indah.Stream([{"id": f"s{i:03d}", "name": f"s {i}"} for i in range(30)], limit=200)
    counter = {"i": 30}

    def grow() -> None:
        stream.append(*[{"id": f"s{counter['i'] + k:03d}", "name": "new"} for k in range(5)])
        counter["i"] += 5

    def pages(q):
        start = q.offset
        data = [
            {"id": f"p{i:03d}", "name": f"page row {i}"}
            for i in range(start, min(start + q.limit, 25))
        ]
        return data, 25

    def build_plain() -> indah.Session:
        return indah.Session(
            indah.Column(
                children=[
                    indah.Shortcuts({"j": lambda: SHORTCUT.append("j")}),
                    indah.Text("plain"),
                    indah.Table(
                        rows=rows,
                        key="id",
                        columns=_cols(),
                        height="12rem",
                        search=True,
                        on_open=OPENED.append,
                        checked=indah.Signal([]),
                    ),
                    indah.Table(rows=rows, key="id", columns=_cols(), label="untouched"),
                ]
            )
        )

    def build(table):
        return lambda: indah.Session(indah.Column(children=[table()]))

    def big_t():
        return indah.Table(
            rows=big, key="id", columns=_cols(), height="14rem", virtual=True, on_open=OPENED.append
        )

    def live_t():
        return indah.Column(
            children=[
                indah.Button("grow", grow),
                indah.Table(
                    rows=stream,
                    key="id",
                    columns=_cols(),
                    height="12rem",
                    follow=True,
                    on_open=OPENED.append,
                ),
            ]
        )

    def remote_t():
        return indah.Table(
            columns=_cols(), key="id", remote=pages, page_size=10, on_open=OPENED.append
        )

    app = indah.create_app(session_factory=build_plain)
    return app, build(big_t), build(live_t), build(remote_t)


@pytest.fixture(scope="module")
def servers():
    apps = _app()
    handles = [launch(a, block=False, open_inline=False) for a in apps[:1]]
    handles += [
        launch(indah.create_app(session_factory=f), block=False, open_inline=False)
        for f in apps[1:]
    ]
    try:
        yield handles
    finally:
        for h in handles:
            h.stop()


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page(browser):
    OPENED.clear()
    SHORTCUT.clear()
    pg = browser.new_page(viewport={"width": 1100, "height": 800})
    yield pg
    pg.close()


def _active(page):
    return page.locator("tr.kb-active code").first


@pytest.mark.e2e
def test_j_k_arrows_home_end_and_enter_on_a_plain_table(servers, page):
    page.goto(servers[0].url)
    grid = page.get_by_role("grid")
    expect(grid).to_be_visible()
    grid.focus()
    expect(_active(page)).to_have_text("r00")
    for key in ("j", "ArrowDown", "k", "ArrowDown"):
        page.keyboard.press(key)
    expect(_active(page)).to_have_text("r02")
    page.keyboard.press("End")
    expect(_active(page)).to_have_text("r11")
    page.keyboard.press("Home")
    expect(_active(page)).to_have_text("r00")
    page.keyboard.press("PageDown")
    expect(_active(page)).not_to_have_text("r00")
    page.keyboard.press("Home")
    page.keyboard.press("j")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert OPENED == ["r01"]
    # the active row follows the focus ring and is exposed to assistive tech
    assert grid.get_attribute("aria-activedescendant")


@pytest.mark.e2e
def test_the_active_row_scrolls_into_view_below_the_sticky_header(servers, page):
    page.goto(servers[0].url)
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("End")
    row = page.locator("tr.kb-active")
    scroller = page.locator(".table-scroll").first
    box, sbox = row.bounding_box(), scroller.bounding_box()
    assert box["y"] + box["height"] <= sbox["y"] + sbox["height"] + 1
    page.keyboard.press("Home")
    head = page.locator("thead").first.bounding_box()
    box = row.bounding_box()
    assert box["y"] >= head["y"] + head["height"] - 1


@pytest.mark.e2e
def test_escape_and_tab_leave_the_table_so_there_is_no_keyboard_trap(servers, page):
    page.goto(servers[0].url)
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("Escape")
    assert not grid.evaluate("el => el === document.activeElement")
    grid.focus()
    page.keyboard.press("Tab")
    assert not grid.evaluate("el => el === document.activeElement")


@pytest.mark.e2e
def test_keys_do_not_fight_shortcuts_or_a_text_input(servers, page):
    page.goto(servers[0].url)
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("j")  # the focused table takes it: the Shortcuts "j" must not fire
    page.wait_for_timeout(300)
    assert SHORTCUT == []
    expect(_active(page)).to_have_text("r01")
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("j")  # focus is elsewhere: Shortcuts gets it again
    page.wait_for_timeout(300)
    assert SHORTCUT == ["j"]
    search = page.get_by_role("searchbox")
    search.press("j")  # typing in the filter goes to the filter: not the table, not Shortcuts
    expect(search).to_have_value("j")
    assert SHORTCUT == ["j"]
    search.fill("")
    page.get_by_role("grid").focus()
    page.keyboard.press("Home")
    page.keyboard.press("Control+j")  # a modifier combo is never the table's
    expect(_active(page)).to_have_text("r00")


@pytest.mark.e2e
def test_space_ticks_a_checkable_row_and_clicking_a_row_makes_it_active(servers, page):
    page.goto(servers[0].url)
    page.get_by_role("grid").first.focus()
    page.keyboard.press("j")
    page.keyboard.press(" ")
    expect(page.get_by_role("checkbox", name="Select row").nth(1)).to_be_checked()
    page.locator("tbody tr").nth(5).locator("td").nth(1).click()
    expect(_active(page)).to_have_text("r05")
    page.keyboard.press("j")
    expect(_active(page)).to_have_text("r06")


@pytest.mark.e2e
def test_a_table_without_keyboard_is_not_focusable(servers, page):
    page.goto(servers[0].url)
    plain = page.get_by_role("table", name="untouched")
    assert plain.count() == 0 or plain.get_attribute("tabindex") is None
    assert page.locator("table.rich:not([role=grid])").first.get_attribute("tabindex") is None


@pytest.mark.e2e
def test_virtual_table_of_20000_rows_end_home_and_page_keys(servers, page):
    page.goto(servers[1].url)
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("End")
    expect(_active(page)).to_have_text(f"v{N - 1:05d}")
    assert page.locator("tbody tr:not(.vspacer)").count() < 80
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert OPENED == [f"v{N - 1:05d}"]
    page.keyboard.press("Home")
    expect(_active(page)).to_have_text("v00000")
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    first = _active(page).inner_text()
    assert first not in ("v00000", "v00001")
    for _ in range(40):
        page.keyboard.press("j")
    expect(_active(page)).to_be_visible()


@pytest.mark.e2e
def test_stream_with_follow_keeps_the_active_row_and_pausing_resumes_on_end(servers, page):
    page.goto(servers[2].url)
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("End")
    expect(_active(page)).to_have_text("s029")
    page.get_by_role("button", name="grow").click()
    expect(page.get_by_text("s034")).to_be_visible()  # still following the tail
    grid.focus()
    for _ in range(6):
        page.keyboard.press("k")
    expect(page.get_by_role("button", name="Resume following")).to_be_visible()
    held = _active(page).inner_text()
    page.get_by_role("button", name="grow").click()
    page.wait_for_timeout(500)
    expect(_active(page)).to_have_text(held)  # the active row is held by key, not position
    grid.focus()
    page.keyboard.press("End")
    expect(page.get_by_role("button", name="Resume following")).to_have_count(0)
    expect(_active(page)).to_have_text("s039")


@pytest.mark.e2e
def test_remote_paging_arrow_past_the_last_row_loads_the_next_page(servers, page):
    page.goto(servers[3].url)
    grid = page.get_by_role("grid")
    expect(page.get_by_text("p000")).to_be_visible()
    grid.focus()
    page.keyboard.press("End")
    expect(_active(page)).to_have_text("p009")
    page.keyboard.press("ArrowDown")
    expect(page.get_by_text("Page 2 / 3")).to_be_visible()
    expect(_active(page)).to_have_text("p010")
    page.keyboard.press("ArrowUp")
    expect(page.get_by_text("Page 1 / 3")).to_be_visible()
    expect(_active(page)).to_have_text("p009")

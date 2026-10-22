"""Menu in a real browser (IND-161): keys, focus, confirm, typeahead, key routing with
``Shortcuts``, live items and the popup inside an AppShell drawer. The conftest runs all of it
under ``csp="strict"``. Set ``MENU_SHOTS`` to a directory to keep screenshots for review."""

import os
from pathlib import Path

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

RAN: list[str] = []
SHORTCUT: list[str] = []
SHOTS = os.environ.get("MENU_SHOTS")


def _items(locked):
    def say(name):
        return lambda: RAN.append(name)

    return indah.Computed(
        lambda: [
            indah.MenuItem("Alpha", say("alpha"), shortcut="F2"),
            indah.MenuItem("Beta", say("beta")),
            indah.MenuItem("Bravo", say("bravo")),
            indah.MenuItem("Off", say("off"), disabled=True),
            indah.MenuItem(
                "Delete", say("delete"), danger=True, confirm="Delete it?", disabled=locked.value
            ),
        ]
    )


def _build_plain() -> indah.Session:
    locked = indah.Signal(False)
    return indah.Session(
        indah.Column(
            children=[
                indah.Shortcuts({"a": lambda: SHORTCUT.append("a")}),
                indah.Row(
                    children=[
                        indah.Menu("Actions", _items(locked)),
                        indah.Button("after", lambda: None),
                        indah.Switch(locked, label="Locked"),
                    ]
                ),
            ]
        )
    )


def _build_shell() -> indah.Session:
    locked = indah.Signal(False)
    rail = indah.Column(children=[indah.Menu("Project", _items(locked), label="Project menu")])
    return indah.Session(indah.AppShell(rail=rail, main=indah.Text("main content")))


@pytest.fixture(scope="module")
def servers():
    handles = [
        launch(indah.create_app(session_factory=f), block=False, open_inline=False)
        for f in (_build_plain, _build_shell)
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
    RAN.clear()
    SHORTCUT.clear()
    pg = browser.new_page(viewport={"width": 1000, "height": 700})
    yield pg
    pg.close()


def _ran(page, want):
    """The handlers that ran. A choice is a POST, so wait for the server rather than race it."""
    for _ in range(60):
        if len(RAN) >= len(want):
            break
        page.wait_for_timeout(50)
    page.wait_for_timeout(150)  # and long enough for a stray extra one to show up
    return RAN


def _nothing_ran(page):
    page.wait_for_timeout(300)
    return RAN


def _open(page, servers):
    page.goto(servers[0].url)
    trigger = page.get_by_role("button", name="Actions")
    trigger.click()
    expect(page.get_by_role("menu")).to_be_visible()
    return trigger


def _item(page, name):
    return page.get_by_role("menuitem", name=name)


@pytest.mark.e2e
def test_open_move_choose_and_focus_returns(servers, page):
    trigger = _open(page, servers)
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(_item(page, "Alpha")).to_be_focused()  # a click focuses the first item
    page.keyboard.press("ArrowDown")
    expect(_item(page, "Beta")).to_be_focused()
    page.keyboard.press("End")
    expect(_item(page, "Delete")).to_be_focused()
    page.keyboard.press("ArrowDown")  # wraps
    expect(_item(page, "Alpha")).to_be_focused()
    page.keyboard.press("ArrowUp")  # wraps back
    expect(_item(page, "Delete")).to_be_focused()
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    assert _ran(page, ["beta"]) == ["beta"]


@pytest.mark.e2e
def test_arrow_keys_open_the_menu_from_the_trigger(servers, page):
    page.goto(servers[0].url)
    trigger = page.get_by_role("button", name="Actions")
    trigger.focus()
    page.keyboard.press("ArrowUp")
    expect(_item(page, "Delete")).to_be_focused()  # up opens on the last item
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(_item(page, "Alpha")).to_be_focused()
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_escape_closes_without_running_anything(servers, page):
    trigger = _open(page, servers)
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(trigger).to_be_focused()
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_tab_leaves_the_menu_and_moves_on(servers, page):
    _open(page, servers)
    page.keyboard.press("Tab")
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(page.get_by_role("button", name="after")).to_be_focused()  # no keyboard trap
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_an_outside_click_closes_it(servers, page):
    _open(page, servers)
    page.mouse.click(900, 600)
    expect(page.get_by_role("menu")).to_have_count(0)
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_typeahead_cycles_and_a_letter_never_fires_a_shortcut(servers, page):
    _open(page, servers)
    page.keyboard.press("b")
    expect(_item(page, "Beta")).to_be_focused()
    page.keyboard.press("b")  # a repeated letter cycles
    expect(_item(page, "Bravo")).to_be_focused()
    page.keyboard.press("a")  # the Shortcuts "a" binding must not fire from inside the menu
    expect(_item(page, "Alpha")).to_be_focused()
    page.wait_for_timeout(300)
    assert SHORTCUT == []
    page.keyboard.press("Escape")
    page.keyboard.press("a")  # with the menu closed the shortcut is the page's again
    page.wait_for_timeout(300)
    assert SHORTCUT == ["a"]


@pytest.mark.e2e
def test_a_disabled_item_cannot_be_chosen(servers, page):
    _open(page, servers)
    off = _item(page, "Off")
    expect(off).to_have_attribute("aria-disabled", "true")
    off.click(force=True)  # Playwright will not click an aria-disabled item unforced
    expect(page.get_by_role("menu")).to_be_visible()  # still open, nothing ran
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_confirm_asks_first_like_a_button(servers, page):
    trigger = _open(page, servers)
    _item(page, "Delete").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(trigger).to_be_focused()
    assert _nothing_ran(page) == []
    trigger.click()
    _item(page, "Delete").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert _ran(page, ["delete"]) == ["delete"]


@pytest.mark.e2e
def test_items_follow_a_signal(servers, page):
    trigger = _open(page, servers)
    expect(_item(page, "Delete")).not_to_have_attribute("aria-disabled", "true")
    page.keyboard.press("Escape")
    page.get_by_role("switch", name="Locked").click()
    trigger.click()
    expect(_item(page, "Delete")).to_have_attribute("aria-disabled", "true")
    _item(page, "Delete").click(force=True)
    expect(page.get_by_role("dialog")).to_have_count(0)  # a disabled item does not even ask
    assert _nothing_ran(page) == []


@pytest.mark.e2e
def test_the_popup_stays_at_its_trigger_inside_a_narrow_drawer(servers, page):
    page.set_viewport_size({"width": 420, "height": 700})
    page.goto(servers[1].url)
    page.get_by_role("button", name="Open the menu").click()
    trigger = page.get_by_role("button", name="Project menu")
    trigger.click()
    menu = page.get_by_role("menu")
    expect(menu).to_be_visible()
    t, m = trigger.bounding_box(), menu.bounding_box()
    # The drawer is transformed; a popup left inside it would be placed relative to the drawer.
    assert abs(m["y"] - (t["y"] + t["height"] + 4)) < 3 and abs(m["x"] - t["x"]) < 3
    assert m["x"] >= 0 and m["x"] + m["width"] <= 420


@pytest.mark.e2e
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_screenshot_for_review(servers, page, scheme):
    if not SHOTS:
        pytest.skip("set MENU_SHOTS to keep screenshots")
    page.emulate_media(color_scheme=scheme)
    _open(page, servers)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(Path(SHOTS) / f"menu-{scheme}.png"))

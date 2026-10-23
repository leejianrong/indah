"""CommandPalette in a real browser (IND-165): the shortcut, the filter and its order, keys, focus,
key routing with ``Shortcuts`` and fields, jump and confirm commands, and commands added per page.
The conftest runs all of it under ``csp="strict"``. Set ``PALETTE_SHOTS`` to a directory to keep
screenshots for review."""

import os
from pathlib import Path

import pytest

import indah
from indah.launch import launch

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

RAN: list[str] = []
SHORTCUT: list[str] = []
SHOTS = os.environ.get("PALETTE_SHOTS")


def _build(shortcut: str):
    def build(ctx: indah.Context) -> indah.Session:
        extra = indah.Signal(False)

        def say(name):
            return lambda: RAN.append(name)

        def commands():
            out = [
                indah.Command("Open log", say("open-log"), group="Actions", shortcut="g l"),
                indah.Command("Catalog", say("catalog"), group="Actions"),
                indah.Command("Log out", say("log-out"), group="Account"),
                indah.Command("Lightning order", say("lightning"), group="Actions"),
                indah.Command("Settings", say("settings"), group="Account", keywords="preferences"),
                indah.Command("Go to pending", to="/pending", group="Go to"),
                indah.Command(
                    "Delete everything",
                    say("delete"),
                    confirm="Delete everything?",
                    group="Actions",
                ),
            ]
            if extra.value:  # a page's own command, added while it is showing
                out.append(indah.Command("Clear this page", say("clear-page"), group="This page"))
            return out

        return indah.Session(
            indah.Column(
                children=[
                    indah.Shortcuts({"a": lambda: SHORTCUT.append("a")}),
                    indah.Button("Opener", lambda: None),
                    indah.TextInput(indah.Signal(""), label="Field"),
                    indah.Switch(extra, label="Page commands"),
                    indah.Text(lambda: "path=" + ctx.path.value),
                    indah.CommandPalette(commands, ctx=ctx, shortcut=shortcut),
                ]
            )
        )

    return build


@pytest.fixture(scope="module")
def servers():
    handles = [
        launch(indah.create_app(session_factory=_build(s)), block=False, open_inline=False)
        for s in ("mod+k", "/")
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
    """The handlers that ran. A run is a POST, so wait for the server rather than race it."""
    for _ in range(60):
        if len(RAN) >= len(want):
            break
        page.wait_for_timeout(50)
    page.wait_for_timeout(150)  # and long enough for a stray extra one to show up
    return RAN


def _options(page):
    return page.locator(".cp-label").all_inner_texts()


def _open(page, servers, idx=0):
    page.goto(servers[idx].url)
    opener = page.get_by_role("button", name="Opener")
    opener.focus()
    page.keyboard.press("Control+k" if idx == 0 else "/")
    expect(page.get_by_role("dialog", name="Command palette")).to_be_visible()
    return opener


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"palette-{name}.png"))


@pytest.mark.e2e
def test_the_shortcut_opens_it_and_enter_runs_then_focus_returns(servers, page):
    opener = _open(page, servers)
    box = page.get_by_role("combobox")
    expect(box).to_be_focused()
    expect(box).to_have_attribute("aria-expanded", "true")
    _shot(page, "open")
    box.fill("settings")
    page.keyboard.press("Enter")
    expect(page.get_by_role("dialog", name="Command palette")).to_have_count(0)
    expect(opener).to_be_focused()
    assert _ran(page, ["settings"]) == ["settings"]


@pytest.mark.e2e
def test_the_filter_order_is_prefix_then_word_then_substring_then_subsequence_then_keywords(
    servers, page
):
    _open(page, servers)
    box = page.get_by_role("combobox")
    assert _options(page)[:3] == ["Open log", "Catalog", "Log out"]  # empty query: as given
    box.fill("log")
    assert _options(page) == ["Log out", "Open log", "Catalog"]  # prefix, word, substring
    box.fill("lgo")
    assert _options(page) == ["Log out", "Lightning order"]  # a subsequence, as given
    box.fill("prefer")
    assert _options(page) == ["Settings"]  # a keyword the list does not show
    box.fill("zzzz")
    expect(page.get_by_text("No matching commands").first).to_be_visible()
    assert _options(page) == []
    page.keyboard.press("Enter")  # nothing to run
    page.wait_for_timeout(200)
    assert RAN == []


@pytest.mark.e2e
def test_arrows_wrap_and_the_active_option_is_announced(servers, page):
    _open(page, servers)
    box = page.get_by_role("combobox")
    options = page.get_by_role("option")
    expect(options.first).to_have_attribute("aria-selected", "true")
    first_id = options.first.get_attribute("id")
    expect(box).to_have_attribute("aria-activedescendant", first_id)
    page.keyboard.press("ArrowUp")  # wraps to the last
    expect(options.last).to_have_attribute("aria-selected", "true")
    page.keyboard.press("ArrowDown")  # and back
    expect(options.first).to_have_attribute("aria-selected", "true")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert _ran(page, ["catalog"]) == ["catalog"]


@pytest.mark.e2e
def test_escape_closes_and_returns_focus_and_tab_does_not_escape_the_dialog(servers, page):
    opener = _open(page, servers)
    page.keyboard.press("Tab")
    expect(page.get_by_role("combobox")).to_be_focused()  # a modal keeps Tab inside
    page.keyboard.press("Escape")  # the way out
    expect(page.get_by_role("dialog", name="Command palette")).to_have_count(0)
    expect(opener).to_be_focused()
    page.keyboard.press("Control+k")  # open again, and the shortcut closes it too
    expect(page.get_by_role("combobox")).to_be_focused()
    page.keyboard.press("Control+k")
    expect(page.get_by_role("dialog", name="Command palette")).to_have_count(0)


@pytest.mark.e2e
def test_key_routing_with_fields_and_shortcuts(servers, page):
    page.goto(servers[0].url)
    page.get_by_label("Field").focus()
    page.keyboard.press("Control+k")  # a mod+ combo opens it even while typing in a field
    expect(page.get_by_role("combobox")).to_be_focused()
    page.keyboard.type("a")  # a bare key in the palette is the palette's, not Shortcuts'
    page.wait_for_timeout(200)
    assert SHORTCUT == []
    page.keyboard.press("Escape")
    expect(page.get_by_label("Field")).to_be_focused()

    page.goto(servers[1].url)  # a bare "/" opens it, but not while typing in a field
    page.get_by_label("Field").focus()
    page.keyboard.type("/")
    expect(page.get_by_role("dialog", name="Command palette")).to_have_count(0)
    page.get_by_role("button", name="Opener").focus()
    page.keyboard.press("/")
    expect(page.get_by_role("dialog", name="Command palette")).to_be_visible()


@pytest.mark.e2e
def test_a_jump_command_moves_the_tab(servers, page):
    _open(page, servers)
    page.get_by_role("combobox").fill("pending")
    page.keyboard.press("Enter")
    expect(page.get_by_text("path=/pending")).to_be_visible()


@pytest.mark.e2e
def test_a_confirm_command_asks_first(servers, page):
    _open(page, servers)
    page.get_by_role("combobox").fill("delete")
    page.keyboard.press("Enter")
    ask = page.get_by_role("dialog", name="Delete everything?")
    expect(ask).to_be_visible()
    ask.get_by_role("button", name="Cancel").click()
    page.wait_for_timeout(300)
    assert RAN == []
    _open(page, servers)
    page.get_by_role("combobox").fill("delete")
    page.keyboard.press("Enter")
    page.get_by_role("dialog", name="Delete everything?").get_by_role(
        "button", name="Delete everything"
    ).click()
    assert _ran(page, ["delete"]) == ["delete"]


@pytest.mark.e2e
def test_commands_added_for_a_page_appear_without_a_reload(servers, page):
    page.goto(servers[0].url)
    page.get_by_role("button", name="Opener").focus()
    page.keyboard.press("Control+k")
    assert "Clear this page" not in _options(page)
    page.keyboard.press("Escape")
    page.get_by_role("switch", name="Page commands").click()
    page.get_by_role("button", name="Opener").focus()
    page.keyboard.press("Control+k")
    expect(page.get_by_role("option", name="Clear this page")).to_be_visible()
    page.get_by_role("combobox").fill("clear")
    page.keyboard.press("Enter")
    assert _ran(page, ["clear-page"]) == ["clear-page"]
    _shot(page, "page-commands")


@pytest.mark.e2e
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_screenshots_in_both_schemes(servers, browser, scheme):
    if not SHOTS:
        pytest.skip("set PALETTE_SHOTS to keep screenshots")
    pg = browser.new_page(viewport={"width": 1000, "height": 700}, color_scheme=scheme)
    try:
        pg.goto(servers[0].url)
        pg.get_by_role("button", name="Opener").focus()
        pg.keyboard.press("Control+k")
        pg.get_by_role("combobox").fill("lo")
        _shot(pg, scheme)
    finally:
        pg.close()

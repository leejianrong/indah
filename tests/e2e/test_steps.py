"""``Steps`` in a real browser, under a strict CSP (IND-163): five states that differ by shape as
well as colour, an accessible name for each step, a live change that updates in place, and a List
item and a Stream-fed table cell that draw the same thing from a render spec."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

SPEC = {"component": "steps", "bind": {"items": "tiers"}}
TIERS = [("exact", "done", "hit"), ("fuzzy", "current"), ("llm", "off"), ("manual", "pending")]


def _build():
    items = indah.Signal(
        [
            ("Plan", "done", "2 min"),
            ("Build", "current"),
            ("Test", "skipped"),
            ("Ship", "pending"),
            ("Later", "off"),
        ]
    )
    stream = indah.Stream(limit=50)
    stream.append({"id": "r1", "tiers": indah.steps_items(TIERS)})
    list_rows = [{"id": "a", "tiers": indah.steps_items(TIERS)}]

    def advance() -> None:
        items.set(
            [("Plan", "done", "2 min"), ("Build", "done"), ("Test", "current"), ("Ship", "pending")]
        )

    def add_row() -> None:
        stream.append(
            {"id": "r2", "tiers": indah.steps_items([("exact", "skipped"), ("llm", "done")])}
        )

    return indah.Column(
        children=[
            indah.Steps(items, label="Release"),
            indah.Steps(items, orientation="horizontal", label="Release flow"),
            indah.Button("Advance", advance),
            indah.Button("Add row", add_row),
            indah.List(list_rows, key="id", item=SPEC),
            indah.Table(
                columns=[indah.Col("id"), indah.Col("tiers", kind="cell", render=SPEC)],
                rows=stream,
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
        page = browser.new_page()
        page.goto(server.url)
        yield page
        browser.close()


def _list(page, name):
    return page.get_by_role("list", name=name, exact=True)


@pytest.mark.e2e
def test_each_step_has_a_state_class_a_glyph_and_a_spoken_position(page):
    steps = _list(page, "Release").get_by_role("listitem")
    expect(steps).to_have_count(5)
    expect(steps.nth(0)).to_have_class("step st-done")
    expect(steps.nth(2)).to_have_class("step st-skipped")
    assert "step 1 of 5, done" in steps.nth(0).text_content()
    assert "2 min" in steps.nth(0).text_content()  # the detail is read out too
    assert "step 3 of 5, skipped" in steps.nth(2).text_content()
    assert "step 5 of 5, off" in steps.nth(4).text_content()
    # the glyph is decoration: the words above carry the meaning
    expect(steps.nth(0).locator("svg")).to_have_attribute("aria-hidden", "true")


@pytest.mark.e2e
def test_only_the_current_step_is_aria_current(page):
    steps = _list(page, "Release").get_by_role("listitem")
    expect(steps.nth(1)).to_have_attribute("aria-current", "step")
    expect(page.locator("[aria-current=step]").first).to_be_visible()
    assert _list(page, "Release").locator("[aria-current=step]").count() == 1


@pytest.mark.e2e
def test_states_differ_by_shape_not_only_colour(page):
    shapes = page.evaluate(
        """() => [...document.querySelectorAll('ol[aria-label=Release] > li')].map(li => {
          const svg = li.querySelector('svg');
          return [li.className.replace('step ', ''), svg.innerHTML.replace(/\\s+/g, ' ')];
        })"""
    )
    by_state = dict(shapes)
    assert len(set(by_state.values())) == 5  # five states, five different drawings
    label = page.evaluate(
        """() => getComputedStyle(document.querySelector(
          'ol[aria-label=Release] > li.st-skipped .step-label')).textDecorationLine"""
    )
    assert label == "line-through"


@pytest.mark.e2e
def test_a_live_change_updates_in_place_and_never_remounts(page):
    steps = _list(page, "Release").get_by_role("listitem")
    first = steps.nth(0).element_handle()
    page.get_by_role("button", name="Advance").click()
    expect(steps).to_have_count(4)
    expect(steps.nth(1)).to_have_class("step st-done")
    expect(steps.nth(2)).to_have_attribute("aria-current", "step")
    assert page.evaluate("(el) => el.isConnected", first)  # the first <li> is the same node


@pytest.mark.e2e
def test_horizontal_lays_the_steps_in_a_row_and_vertical_in_a_column(page):
    h = _list(page, "Release flow").get_by_role("listitem")
    v = _list(page, "Release").get_by_role("listitem")
    hb0, hb1 = h.nth(0).bounding_box(), h.nth(1).bounding_box()
    vb0, vb1 = v.nth(0).bounding_box(), v.nth(1).bounding_box()
    assert hb1["x"] > hb0["x"] + hb0["width"] - 1 and abs(hb1["y"] - hb0["y"]) < 6
    assert vb1["y"] > vb0["y"] + vb0["height"] - 1 and abs(vb1["x"] - vb0["x"]) < 2


@pytest.mark.e2e
def test_a_list_item_draws_compact_steps_from_a_spec(page):
    item = page.locator(".list-item .steps")
    expect(item).to_have_count(1)
    expect(item).to_have_class("steps steps-h steps-compact")
    expect(item.locator("li")).to_have_count(4)
    # compact: the detail is hover text (and spoken), not a second line
    first = item.locator("li").first
    expect(first).to_have_attribute("title", "hit")
    expect(first.locator(".step-detail")).to_have_count(0)
    assert "hit" in first.text_content()


@pytest.mark.e2e
def test_a_streamed_table_cell_draws_steps_and_a_new_row_gets_its_own(page):
    cells = page.locator("td .steps")
    expect(cells).to_have_count(1)
    page.get_by_role("button", name="Add row").click()
    expect(cells).to_have_count(2)
    states = page.locator("td .steps").nth(1).locator("li")
    expect(states.nth(0)).to_have_class("step st-skipped")
    expect(states.nth(1)).to_have_class("step st-done")
    assert page.locator("td .steps").first.locator("li.st-current").count() == 1


@pytest.mark.e2e
def test_the_steps_are_not_a_tab_stop(page):
    tabbable = page.evaluate(
        """() => [...document.querySelectorAll('.steps, .steps *')]
          .filter(el => el.tabIndex >= 0).length"""
    )
    assert tabbable == 0

"""A disabled input ignores the keyboard and pointer, even while focused (IND-243)."""

import pytest

import indah
from indah.launch import launch
from indah.session import Session

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

OPTS = ["a", "b"]


def _run(root, body):
    handle = launch(indah.create_app(session=Session(root)), block=False, open_inline=False)
    try:
        with playwright_sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                page.goto(handle.url, wait_until="domcontentloaded")
                body(page)
            finally:
                browser.close()
    finally:
        handle.stop()


@pytest.mark.e2e
def test_a_focused_slider_locks_and_unlocks_live():
    value, off = indah.Signal(50.0), indah.Signal(False)
    root = indah.Column(
        children=[
            indah.Slider(value, label="Threshold", disabled=off),
            indah.Button("Lock", lambda: off.set(True)),
            indah.Button("Unlock", lambda: off.set(False)),
            indah.Button("Reset", lambda: value.set(10.0)),
        ]
    )

    def body(page):
        slider = page.get_by_label("Threshold")
        slider.focus()
        slider.press("ArrowRight")
        expect(slider).to_have_value("51")
        # lock from the server while the slider still holds focus (a click would blur it)
        off.set(True)
        expect(slider).to_be_disabled()
        slider.focus()
        page.keyboard.press("ArrowRight")
        box = slider.bounding_box()
        page.mouse.click(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2)
        assert value.value == 51.0
        expect(slider).to_have_value("51")
        # a server-side change still shows through while locked, focused or not
        value.set(10.0)
        expect(slider).to_have_value("10")
        off.set(False)
        expect(slider).to_be_enabled()
        slider.focus()
        slider.press("ArrowRight")
        expect(slider).to_have_value("11")
        assert value.value == 11.0

    _run(root, body)


def _all():
    return {
        "TextInput": (lambda v, **k: indah.TextInput(v, label="L", **k), "x", "input"),
        "TextArea": (lambda v, **k: indah.TextArea(v, label="L", **k), "x", "textarea"),
        "Checkbox": (
            lambda v, **k: indah.Checkbox(v, label="L", **k),
            False,
            "input[type=checkbox]",
        ),
        "Switch": (lambda v, **k: indah.Switch(v, label="L", **k), False, "button.switch"),
        "Number": (lambda v, **k: indah.Number(v, label="L", **k), 1.0, "input[type=number]"),
        "Date": (lambda v, **k: indah.Date(v, label="L", **k), "2026-01-01", "input[type=date]"),
        "Select": (lambda v, **k: indah.Select(v, options=OPTS, label="L", **k), "a", "select"),
        "Radio": (
            lambda v, **k: indah.Radio(v, options=OPTS, label="L", **k),
            "a",
            "input[type=radio]",
        ),
        "MultiSelect": (
            lambda v, **k: indah.MultiSelect(v, options=OPTS, label="L", **k),
            ["a"],
            ".checkbox-group input",
        ),
        "Chips": (
            lambda v, **k: indah.Chips(v, options=OPTS, label="L", **k),
            "a",
            "button.choice-opt",
        ),
        "Segmented": (
            lambda v, **k: indah.Segmented(v, options=OPTS, label="L", **k),
            "a",
            "button.choice-opt",
        ),
    }


@pytest.mark.e2e
@pytest.mark.parametrize("name", list(_all()))
def test_every_input_greys_out_and_unlocks_live(name):
    make, init, sel = _all()[name]
    off = indah.Signal(True)
    root = indah.Column(children=[make(indah.Signal(init), disabled=off)])

    def body(page):
        controls = page.locator(sel)
        expect(controls.first).to_be_visible()
        for i in range(controls.count()):
            expect(controls.nth(i)).to_be_disabled()
        off.set(False)
        for i in range(controls.count()):
            expect(controls.nth(i)).to_be_enabled()
        off.set(True)
        expect(controls.first).to_be_disabled()

    _run(root, body)

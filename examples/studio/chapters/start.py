"""Chapter 1: the reactive core and the basic inputs."""

from __future__ import annotations

import indah

from ..core import Chapter, Page


def reactive(ctx: indah.Context) -> indah.Component:
    celsius = indah.Signal(21.0)
    fahrenheit = indah.computed(lambda: round(celsius.value * 9 / 5 + 32, 1))
    return indah.Column(
        children=[
            indah.Slider(celsius, min=-20, max=45, step=0.5, label="Celsius"),
            indah.Text(lambda: f"{celsius.value} C is {fahrenheit.value} F"),
        ]
    )


def reactive_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("21.0 C is 69.8 F")).to_be_visible()
    slider = page.get_by_role("slider")
    slider.focus()
    slider.press("ArrowRight")  # one step of 0.5
    expect(page.get_by_text("21.5 C is 70.7 F")).to_be_visible()


def inputs(ctx: indah.Context) -> indah.Component:
    name = indah.Signal("Ada")
    size = indah.Signal("Medium")
    toppings = indah.Signal(["olives"])
    spicy = indah.Signal(False)
    count = indah.Signal(2.0)
    day = indah.Signal("2026-10-22")
    summary = indah.computed(
        lambda: (
            f"{name.value} orders {int(count.value)} {size.value.lower()} pizza(s) with "
            f"{', '.join(toppings.value) or 'no toppings'}"
            f"{', spicy' if spicy.value else ''}, for {day.value}."
        )
    )
    return indah.Column(
        children=[
            indah.TextInput(name, label="Name", placeholder="Who is it for?"),
            indah.Radio(size, options=["Small", "Medium", "Large"], label="Size"),
            indah.MultiSelect(toppings, options=["olives", "basil", "onion"], label="Toppings"),
            indah.Checkbox(spicy, label="Make it spicy"),
            indah.Number(count, min=1, max=9, label="How many"),
            indah.Date(day, label="Day"),
            indah.Text(lambda: summary.value),
        ]
    )


def inputs_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(
        page.get_by_text("Ada orders 2 medium pizza(s) with olives, for 2026-10-22.")
    ).to_be_visible()
    page.get_by_label("Name").fill("Grace")
    page.get_by_label("Large").check()
    page.get_by_label("Make it spicy").check()
    expect(
        page.get_by_text("Grace orders 2 large pizza(s) with olives, spicy, for 2026-10-22.")
    ).to_be_visible()


def actions(ctx: indah.Context) -> indah.Component:
    clicks = indah.Signal(0)
    log = indah.Signal("Nothing yet.")

    async def slow() -> None:
        import asyncio

        log.set("Working...")
        await asyncio.sleep(0.6)
        log.set("Done after an async handler (the page stayed live while it ran).")

    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Button("Count", lambda: clicks.set(clicks.value + 1)),
                    indah.Button("Run async work", slow, variant="tonal"),
                    indah.Button("Reset", lambda: clicks.set(0), variant="ghost"),
                ]
            ),
            indah.Text(lambda: f"Clicked {clicks.value} time(s)."),
            indah.Text(lambda: log.value),
        ]
    )


def actions_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Count").click()
    page.get_by_role("button", name="Count").click()
    expect(page.get_by_text("Clicked 2 time(s).")).to_be_visible()
    page.get_by_role("button", name="Run async work").click()
    expect(page.get_by_text("Working...")).to_be_visible()
    page.get_by_role("button", name="Count").click()  # still live mid-handler
    expect(page.get_by_text("Clicked 3 time(s).")).to_be_visible()
    expect(page.get_by_text("Done after an async handler")).to_be_visible()


CHAPTER = Chapter(
    slug="start",
    title="Start here",
    order=10,
    blurb=(
        "Signals hold state; a `computed` derives from them; components read them. Change a signal "
        "and only the parts of the page that read it update, with no rerun of your script."
    ),
    pages=[
        Page(
            slug="reactive",
            title="Signals and computed values",
            summary="Drag the slider. One signal, one derived value, one text that reads both.",
            build=reactive,
            covers=("Signal", "computed", "Slider", "Text", "Column"),
            docs="quickstart.md",
            adr=(3,),
            check=reactive_check,
        ),
        Page(
            slug="inputs",
            title="Basic inputs",
            summary="Every starter input is two-way bound to a signal; the sentence is one `computed`.",
            build=inputs,
            covers=("TextInput", "Radio", "MultiSelect", "Checkbox", "Number", "Date"),
            docs="components.md",
            check=inputs_check,
        ),
        Page(
            slug="actions",
            title="Buttons and async handlers",
            summary="A handler may be `async def`: it runs in the background, so the page stays live.",
            build=actions,
            covers=("Button", "Row"),
            docs="components.md",
            adr=(11,),
            check=actions_check,
        ),
    ],
)

"""Chapter 2: layout containers and theming."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

import indah

from ..core import AppEntry, Chapter, Page


def containers(ctx: indah.Context) -> indah.Component:
    def stat(title: str, value: str) -> indah.Component:
        return indah.Card(title=title, children=[indah.Text(value)])

    return indah.Column(
        children=[
            indah.Text("A Row puts cards side by side:"),
            indah.Row(children=[stat("Requests", "1.2k"), stat("Errors", "0")]),
            indah.Text("A Grid wraps them into columns:"),
            indah.Grid(
                columns=3,
                gap="0.75rem",
                children=[stat(f"Tile {n}", f"value {n}") for n in range(1, 7)],
            ),
        ]
    )


def containers_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("value 6")).to_be_visible()
    a = page.get_by_text("Tile 1", exact=True).bounding_box()
    b = page.get_by_text("Tile 2", exact=True).bounding_box()
    d = page.get_by_text("Tile 4", exact=True).bounding_box()
    assert abs(a["y"] - b["y"]) < 4 and b["x"] > a["x"]  # same row, next column
    assert d["y"] > a["y"] + 20  # the fourth tile wraps to a second row


def tabs(ctx: indah.Context) -> indah.Component:
    active = indah.Signal(0)
    more = indah.Signal(False)
    return indah.Column(
        children=[
            indah.Tabs(
                labels=["Overview", "Data", "About"],
                active=active,
                children=[
                    indah.Text("The overview tab."),
                    indah.Text("The data tab."),
                    indah.Text("The about tab."),
                ],
            ),
            indah.Text(lambda: f"Active tab index: {active.value}"),
            indah.Button("Jump to About", lambda: active.set(2), variant="tonal"),
            indah.Expander(
                label="More detail",
                open=more,
                children=[indah.Text("Hidden until the expander opens.")],
            ),
            indah.Text(lambda: "Expander is open." if more.value else "Expander is closed."),
        ]
    )


def tabs_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("The overview tab.")).to_be_visible()
    page.get_by_role("tab", name="Data").click()
    expect(page.get_by_text("The data tab.")).to_be_visible()
    expect(page.get_by_text("Active tab index: 1")).to_be_visible()
    page.get_by_role("button", name="Jump to About").click()  # server side change
    expect(page.get_by_text("The about tab.")).to_be_visible()
    expect(page.get_by_text("Expander is closed.")).to_be_visible()
    page.get_by_text("More detail", exact=True).click()
    expect(page.get_by_text("Expander is open.")).to_be_visible()
    expect(page.get_by_text("Hidden until the expander opens.")).to_be_visible()


def sidebar(ctx: indah.Context) -> indah.Component:
    name = indah.Signal("Ada")
    loud = indah.Signal(False)
    return indah.Sidebar(
        children=[
            indah.Column(
                children=[
                    indah.TextInput(name, label="Your name"),
                    indah.Checkbox(loud, label="Shout it"),
                ]
            ),
            indah.Card(
                title="Output",
                children=[
                    indah.Text(
                        lambda: f"Hello, {name.value.upper() if loud.value else name.value}!"
                    )
                ],
            ),
        ]
    )


def sidebar_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Hello, Ada!")).to_be_visible()
    page.get_by_label("Your name").fill("Grace")
    page.get_by_label("Shout it").check()
    expect(page.get_by_text("Hello, GRACE!")).to_be_visible()


def split(ctx: indah.Context) -> indah.Component:
    return indah.SplitPane(
        indah.Card(
            title="Left", children=[indah.Text("Drag the divider, or focus it and use the arrows.")]
        ),
        indah.Card(
            title="Right", children=[indah.Text("The ratio is remembered under key='demo'.")]
        ),
        key="demo-split",
        initial=0.4,
        height="12rem",
    )


def split_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Drag the divider")).to_be_visible()
    handle = page.get_by_role("separator").first
    expect(handle).to_be_visible()
    width_before = page.get_by_text("Drag the divider").bounding_box()["width"]
    box = handle.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 150, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    page.wait_for_timeout(200)
    width_after = page.get_by_text("Drag the divider").bounding_box()["width"]
    assert width_after > width_before + 50, (width_before, width_after)


_ROWS = {
    "Ada": "Wrote the first program.",
    "Grace": "Coined the term debugging.",
    "Linus": "Started a kernel as a hobby.",
}


def master_detail(ctx: indah.Context) -> indah.Component:
    chosen = indah.Signal("")
    is_open = indah.Signal(False)

    def pick(name: str):
        def go() -> None:
            chosen.set(name)
            is_open.set(True)

        return go

    master = indah.Column(children=[indah.Button(n, pick(n), variant="ghost") for n in _ROWS])
    detail = indah.Column(
        children=[
            indah.Text(lambda: f"### {chosen.value}", markdown=True),
            indah.Text(lambda: _ROWS.get(chosen.value, "")),
        ]
    )
    return indah.MasterDetail(master, detail, open=is_open, title="Person", key="people")


def master_detail_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Wrote the first program.")).to_have_count(0)
    page.get_by_role("button", name="Grace").click()
    expect(page.get_by_text("Coined the term debugging.")).to_be_visible()
    page.get_by_role("button", name="Linus").click()
    expect(page.get_by_text("Started a kernel as a hobby.")).to_be_visible()
    page.get_by_role("button", name="Close").first.click()
    expect(page.get_by_text("Started a kernel as a hobby.")).to_have_count(0)


_THEME_SOURCE = """
import indah

theme = indah.Theme(
    light={"primary": "#d6336c", "primary-container": "#ffe3ec"},
    dark={"primary": "#ff8fb3", "primary-container": "#5c1630"},
    radius="2px",
    font="Georgia, serif",
    # the app's own tokens: named x-<name>, read as var(--x-brand) in your CSS
    extra_light={"x-brand": "#d6336c"},
    extra_dark={"x-brand": "#ff8fb3"},
)

app = indah.create_app(
    session_factory=build,
    theme=theme,
    density="compact",      # or "comfortable" (the default): table row height and padding
    max_width="720px",      # the page frame; "none" for full width
)
"""


def theming(ctx: indah.Context) -> indah.Component:
    return indah.Column(
        children=[
            indah.Text(
                "Theme, density and max_width are options of the whole app, so they cannot flip "
                "live inside this page. The **themed app** under Full apps (linked below) runs the "
                "code shown here: pink primary, square corners, a serif font, compact tables.\n\n"
                "The dark-mode switch is the shell's own: try the three buttons at the top right "
                "(system, light, dark). The choice is kept in the browser.",
                markdown=True,
            ),
            indah.Text("[Open the themed app](/apps/themed/ui/)", markdown=True),
        ]
    )


def theming_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    html = page.locator("html")
    page.get_by_role("button", name="Dark theme").click()
    expect(html).to_have_attribute("data-theme", "dark")
    page.get_by_role("button", name="Light theme").click()
    expect(html).to_have_attribute("data-theme", "light")


def _themed_ui() -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        rows = [{"id": n, "name": f"Row {n}", "score": n * 7 % 10} for n in range(1, 9)]
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("## A themed app", markdown=True),
                    indah.Text(
                        "Pink primary, 2px radius, Georgia, compact table, 720px frame. "
                        "Toggle dark mode at the top right: the dark palette is overridden too."
                    ),
                    indah.Row(
                        children=[
                            indah.Button("Filled"),
                            indah.Button("Tonal", variant="tonal"),
                            indah.Badge("tokens", tone="info"),
                        ]
                    ),
                    indah.Table(
                        rows=rows,
                        key="id",
                        columns=[
                            indah.Col("id", kind="number"),
                            indah.Col("name"),
                            indah.Col("score", kind="number"),
                        ],
                    ),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="Themed app - indah Studio",
        title_suffix="",
        spa=True,
        csp="strict",
        proxy_flush=False,
        theme=indah.Theme(
            light={"primary": "#d6336c", "primary-container": "#ffe3ec"},
            dark={"primary": "#ff8fb3", "primary-container": "#5c1630"},
            radius="2px",
            font="Georgia, serif",
            extra_light={"x-brand": "#d6336c"},
            extra_dark={"x-brand": "#ff8fb3"},
        ),
        density="compact",
        max_width="720px",
    )


def _themed() -> Any:
    ui = _themed_ui()
    app = Starlette(routes=[Mount("/ui", app=ui)])
    app.state.ui = ui
    return app


def _themed_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_role("heading", name="A themed app")).to_be_visible()
    root = page.evaluate(
        "() => { const s = getComputedStyle(document.documentElement);"
        " return [s.getPropertyValue('--radius').trim(), s.getPropertyValue('--x-brand').trim(),"
        " s.getPropertyValue('--primary').trim(), document.documentElement.dataset.density]; }"
    )
    assert root[0] == "2px" and root[1] == "#d6336c" and root[2] == "#d6336c", root
    assert root[3] == "compact", root
    page.get_by_role("button", name="Dark theme").click()
    page.wait_for_timeout(100)
    dark = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--x-brand').trim()"
    )
    assert dark == "#ff8fb3", dark


CHAPTER = Chapter(
    slug="layout",
    title="Layout and theme",
    order=20,
    blurb=(
        "Containers arrange ordinary children, with no CSS to write: `Row`, `Grid`, `Card`, `Tabs`, "
        "`Sidebar`, `Expander` and the resizable `SplitPane` and `MasterDetail`. Theming is a token "
        "swap (`Theme`), plus `density`, `max_width` and the dark-mode switch."
    ),
    pages=[
        Page(
            slug="containers",
            title="Row, Grid and Card",
            summary="`Row` lines children up, `Grid(columns=3)` wraps them, `Card` frames a group.",
            build=containers,
            covers=("Row", "Grid", "Card", "Column"),
            docs="components.md",
            adr=(15,),
            check=containers_check,
        ),
        Page(
            slug="tabs",
            title="Tabs and Expander",
            summary="Both take a signal, so server code can switch a tab or open a section too.",
            build=tabs,
            covers=("Tabs", "Expander"),
            docs="components.md",
            adr=(15,),
            check=tabs_check,
        ),
        Page(
            slug="sidebar",
            title="Sidebar",
            summary="Inputs on the left, output on the right; on a narrow screen it stacks.",
            build=sidebar,
            covers=("Sidebar",),
            docs="components.md",
            adr=(15,),
            check=sidebar_check,
        ),
        Page(
            slug="split",
            title="SplitPane",
            summary="A draggable divider (mouse or arrow keys); the ratio is remembered per `key`.",
            build=split,
            covers=("SplitPane",),
            docs="dashboards.md",
            check=split_check,
        ),
        Page(
            slug="master-detail",
            title="MasterDetail",
            summary="Pick a row and the detail pane opens beside it; the `open` signal closes it.",
            build=master_detail,
            covers=("MasterDetail",),
            docs="dashboards.md",
            check=master_detail_check,
        ),
        Page(
            slug="theming",
            title="Theme, density and dark mode",
            summary="Token overrides per scheme, your own `x-` tokens, radius, font, density and frame width.",
            build=theming,
            source=_THEME_SOURCE,
            covers=("Theme",),
            docs="design-system.md",
            adr=(14, 31),
            check=theming_check,
        ),
    ],
    apps=[
        AppEntry(
            slug="themed",
            title="The themed app",
            summary="A small app built with the `Theme` on the Theme page: pink, square, serif, compact.",
            build=_themed,
            covers=("Theme", "Table", "Badge"),
            docs="design-system.md",
            adr=(31,),
            check=_themed_check,
        ),
    ],
)

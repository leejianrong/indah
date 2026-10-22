"""Chapter 8: extending indah with your own components, and the per-session Context."""

from __future__ import annotations

import re

import indah

from ..core import Chapter, Page

# Registration is process-global, so it happens once, at import.
indah.register_component(
    "colorpicker",
    render={
        "tag": "input",
        "attrs": {"type": "color"},
        "bind": {"value": "value"},
        "on": {"input": {"event": "input", "prop": "value"}},
    },
)
indah.register_component(
    "rangereadout",
    render={
        "tag": "div",
        "class": "rangereadout",
        "children": [
            {
                "tag": "input",
                "attrs": {"type": "range", "min": "0", "max": "100", "aria-label": "range"},
                "bind": {"value": "value"},
                "on": {"input": {"event": "input", "prop": "value"}},
            },
            {"tag": "strong", "text": "value"},
        ],
    },
)

COLOUR_SOURCE = """
indah.register_component(
    "colorpicker",
    render={
        "tag": "input",  # one allowlisted element
        "attrs": {"type": "color"},
        "bind": {"value": "value"},  # element value <- node prop
        "on": {"input": {"event": "input", "prop": "value"}},  # DOM event -> signal
    },
)


def build(ctx):
    accent = indah.Signal("#ff8800")
    return indah.Column(
        children=[
            indah.custom("colorpicker", value=accent),
            indah.Text(lambda: f"Accent: {accent.value}"),
        ]
    )
"""

RANGE_SOURCE = """
indah.register_component(
    "rangereadout",
    render={
        "tag": "div",
        "children": [  # a small composite: a slider and a readout
            {
                "tag": "input",
                "attrs": {"type": "range", "min": "0", "max": "100"},
                "bind": {"value": "value"},
                "on": {"input": {"event": "input", "prop": "value"}},
            },
            {"tag": "strong", "text": "value"},  # text content <- node prop
        ],
    },
)


def build(ctx):
    level = indah.Signal(40)
    return indah.Column(
        children=[
            indah.custom("rangereadout", value=level),
            indah.Button("Max", lambda: level.set(100)),
        ]
    )
"""


def colour(ctx: indah.Context) -> indah.Component:
    accent = indah.Signal("#ff8800")
    return indah.Column(
        children=[
            indah.custom("colorpicker", value=accent),
            indah.Text(lambda: f"Accent: {accent.value}"),
            indah.Button("Reset to orange", lambda: accent.set("#ff8800"), variant="ghost"),
        ]
    )


def colour_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    picker = page.locator("input[type=color]")
    expect(page.get_by_text("Accent: #ff8800")).to_be_visible()
    picker.fill("#00aa55")  # a real input event; the value travels to the signal
    expect(page.get_by_text("Accent: #00aa55")).to_be_visible()
    page.get_by_role("button", name="Reset to orange").click()
    expect(picker).to_have_value("#ff8800")


def range_readout(ctx: indah.Context) -> indah.Component:
    level = indah.Signal(40)
    return indah.Column(
        children=[
            indah.custom("rangereadout", value=level),
            indah.Button("Max", lambda: level.set(100)),
            indah.Text(lambda: f"Python sees {level.value}."),
        ]
    )


def range_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Python sees 40.")).to_be_visible()
    page.get_by_label("range").fill("75")
    expect(page.get_by_text("Python sees 75.")).to_be_visible()
    page.get_by_role("button", name="Max").click()
    expect(page.get_by_text("Python sees 100.")).to_be_visible()
    expect(page.locator(".rangereadout strong")).to_have_text("100")


CLOSED: list[str] = []  # session ids closed since the Studio started (process-wide)


def context_page(ctx: indah.Context) -> indah.Component:
    ctx.on_close(lambda: CLOSED.append(ctx.sid))  # runs when this session ends
    seen = sorted(k for k in ctx.conn.headers if k in {"user-agent", "accept-language", "host"})
    return indah.Column(
        children=[
            indah.Text(f"Session id: `{ctx.sid[:6]}...` (never show a full one)", markdown=True),
            indah.Text(f"Request path: `{ctx.conn.path}`, headers seen: {', '.join(seen)}"),
            indah.Text(lambda: f"Sessions closed so far: {len(CLOSED)}"),
        ]
    )


def context_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text(re.compile(r"Session id: [0-9a-z_-]{6}\.\.\."))).to_be_visible()
    expect(page.get_by_text("headers seen: ")).to_contain_text("user-agent")
    expect(page.get_by_text("Sessions closed so far: ")).to_be_visible()


CHAPTER = Chapter(
    slug="extend",
    title="Extend",
    order=80,
    blurb=(
        "Add a component the shell has never heard of with a declarative render spec (no Node, no "
        "rebuild), and read per-session facts from the `Context`."
    ),
    pages=[
        Page(
            slug="register",
            title="Register a component",
            summary=(
                "`register_component` takes a render spec (an allowlisted tag, bindings, events); "
                "`custom` makes one, two-way bound to a signal."
            ),
            build=colour,
            covers=("register_component", "custom"),
            docs="custom-components.md",
            adr=(12,),
            check=colour_check,
            source=COLOUR_SOURCE,
        ),
        Page(
            slug="composite",
            title="A composite component",
            summary="A spec may nest children: a range input and a readout that shows the same prop.",
            build=range_readout,
            covers=("custom",),
            docs="custom-components.md",
            adr=(12,),
            check=range_check,
            source=RANGE_SOURCE,
        ),
        Page(
            slug="context",
            title="Context",
            summary=(
                "`ctx.sid`, `ctx.conn` and `ctx.on_close` describe this session and its request "
                "(secrets such as cookies are left out here)."
            ),
            build=context_page,
            docs="dashboards.md",
            adr=(25,),
            check=context_check,
        ),
    ],
)

"""Chapter 8: extending indah with your own components, and the per-session Context."""

from __future__ import annotations

import re
from pathlib import Path

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
    "levelcard",
    render={
        "tag": "div",
        "class": "levelcard",
        "children": [
            {"tag": "strong", "text": "title"},
            {"tag": "meter", "attrs": {"min": "0", "max": "100"}, "bind": {"value": "value"}},
            {"tag": "span", "text": "value"},
            {  # a nested input round-trips too: its `on` writes the "value" signal
                "tag": "input",
                "attrs": {"type": "range", "min": "0", "max": "100"},
                "bind": {"value": "value"},
                "on": {"input": {"event": "input", "prop": "value"}},
            },
        ],
    },
)

# A component backed by an ES module (ADR-0039), read once, at import.
indah.register_component(
    "tier-rail",
    module=Path(__file__).resolve().parent.parent / "modules" / "tier-rail.js",
    events=["pick"],
    two_way={"value": "change"},
    fallback="steps",
)

BRIDGE_SOURCE = """
indah.register_component(
    "tier-rail",
    module="modules/tier-rail.js",  # a file or bytes, read once; never a URL
    events=["pick"],  # CustomEvents forwarded to Python
    two_way={"value": "change"},  # detail.value of "change" writes the `value` signal
    fallback="steps",  # shown as text if the module cannot run
)


def build(ctx):
    steps = indah.Signal(["Seed", "Sprout", "Bloom"])
    tier = indah.Signal(0)
    picked = indah.Signal("nothing yet")
    return indah.Column(
        children=[
            indah.custom(
                "tier-rail",
                label="Tier",
                steps=steps,
                value=tier,
                on_pick=lambda d: picked.set(d["label"]),
            ),
            indah.Text(lambda: f"Tier {tier.value}, last pick: {picked.value}"),
            indah.Button("Next tier", lambda: tier.set((tier.value + 1) % len(steps.value))),
            indah.Button("Add a tier", lambda: steps.set([*steps.value, f"Tier {len(steps.value)}"])),
        ]
    )
"""

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

CARD_SOURCE = """
indah.register_component(
    "levelcard",
    render={
        "tag": "div",
        "children": [  # a small composite: a title, a meter and a readout
            {"tag": "strong", "text": "title"},  # text content <- node prop
            {"tag": "meter", "attrs": {"min": "0", "max": "100"}, "bind": {"value": "value"}},
            {"tag": "span", "text": "value"},
            {  # a nested input round-trips too: its `on` writes the "value" signal
                "tag": "input",
                "attrs": {"type": "range", "min": "0", "max": "100"},
                "bind": {"value": "value"},
                "on": {"input": {"event": "input", "prop": "value"}},
            },
        ],
    },
)


def build(ctx):
    level = indah.Signal(40)
    return indah.Column(
        children=[
            indah.custom("levelcard", title="Battery", value=level),
            indah.Slider(level, min=0, max=100, label="Level"),
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


def level_card(ctx: indah.Context) -> indah.Component:
    level = indah.Signal(40)
    return indah.Column(
        children=[
            indah.custom("levelcard", title="Battery", value=level),
            indah.Slider(level, min=0, max=100, label="Level"),
        ]
    )


def card_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    card = page.locator(".levelcard")
    expect(card.locator("strong")).to_have_text("Battery")
    expect(card.locator("span")).to_have_text("40")
    slider = page.get_by_role("slider").last  # the Slider; the card holds a range too
    slider.focus()
    slider.press("End")
    expect(card.locator("span")).to_have_text("100")
    expect(card.locator("meter")).to_have_attribute("value", "100")
    card.locator("input[type=range]").fill("25")  # the nested input writes the signal
    expect(card.locator("span")).to_have_text("25")
    expect(card.locator("meter")).to_have_attribute("value", "25")


def bridge_page(ctx: indah.Context) -> indah.Component:
    steps = indah.Signal(["Seed", "Sprout", "Bloom"])
    tier = indah.Signal(0)
    picked = indah.Signal("nothing yet")
    return indah.Column(
        children=[
            indah.custom(
                "tier-rail",
                label="Tier",
                steps=steps,
                value=tier,
                on_pick=lambda d: picked.set(d["label"]),
            ),
            indah.Text(lambda: f"Tier {tier.value}, last pick: {picked.value}"),
            indah.Button("Next tier", lambda: tier.set((tier.value + 1) % len(steps.value))),
            indah.Button(
                "Add a tier", lambda: steps.set([*steps.value, f"Tier {len(steps.value)}"])
            ),
        ]
    )


def bridge_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    rail = page.locator("indah-x-tier-rail")
    expect(rail).to_be_visible()
    seed = rail.get_by_role("button", name="Seed")  # the shadow root pierces by role
    expect(seed).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Tier 0, last pick: nothing yet")).to_be_visible()
    rail.get_by_role("button", name="Bloom").click()  # CustomEvent -> signal and handler
    expect(page.get_by_text("Tier 2, last pick: Bloom")).to_be_visible()
    page.get_by_role("button", name="Next tier").click()  # signal -> property
    expect(rail.get_by_role("button", name="Seed")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Add a tier").click()
    expect(rail.get_by_role("button", name="Tier 3")).to_be_visible()


CLOSED: list[str] = []  # session ids closed since the Studio started (process-wide)


def context_page(ctx: indah.Context) -> indah.Component:
    ctx.on_close(lambda: CLOSED.append(ctx.sid))  # runs when this session ends
    seen = sorted(k for k in ctx.conn.headers if k in {"user-agent", "accept-language", "host"})
    return indah.Column(
        children=[
            indah.Text(f"Session id: `{ctx.sid[:6]}...` (never show a full one)", markdown=True),
            indah.Text(
                f"Request path `{ctx.conn.path}`, headers seen: {', '.join(seen)}", markdown=True
            ),
            indah.Text(lambda: f"Sessions closed so far: {len(CLOSED)}", markdown=True),
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
            summary="A spec may nest children: a title, a meter, a readout and a range input, all fed by node props. A nested input round-trips.",
            build=level_card,
            covers=("custom", "Slider"),
            docs="custom-components.md",
            adr=(12,),
            check=card_check,
            source=CARD_SOURCE,
        ),
        Page(
            slug="bridge",
            local_only="the module component's JavaScript is served from api/components/<type>.js, a route the browser runtime does not provide",
            title="A module component",
            summary=(
                "A component that ships its own ES module: props arrive as properties, "
                "CustomEvents come back as handlers and two-way values. The module is served by "
                "the app itself (`modules/tier-rail.js`), themed with the shell's variables."
            ),
            build=bridge_page,
            covers=("register_component", "custom"),
            docs="custom-components.md",
            adr=(39,),
            check=bridge_check,
            source=BRIDGE_SOURCE,
        ),
        Page(
            slug="context",
            local_only="it reads a real request's headers (ConnectionInfo), which the browser runtime does not have",
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

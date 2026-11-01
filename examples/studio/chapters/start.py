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


# The app from the quickstart (website/docs/quickstart.md). tests/unit/test_docs_embeds.py fails if
# the two drift apart, so the docs show the code that runs. (Kept above the function: the docs
# show the function's own source.)
def quickstart(ctx: indah.Context) -> indah.Component:
    a, b = indah.Signal(2), indah.Signal(3)
    total = indah.computed(lambda: f"a + b = {a.value + b.value}")
    return indah.Column(
        children=[
            indah.Slider(a, min=0, max=10, label="a"),
            indah.Slider(b, min=0, max=10, label="b"),
            indah.Text(total),
        ]
    )


def quickstart_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("a + b = 5")).to_be_visible()
    slider = page.get_by_role("slider").first
    slider.focus()
    slider.press("ArrowRight")  # a: 2 -> 3
    expect(page.get_by_text("a + b = 6")).to_be_visible()


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
    sentence = page.get_by_text("Ada orders 2 medium pizza(s)")
    expect(sentence).to_have_css("font-size", "15.2px")  # body text, not the large readout
    expect(sentence).to_have_css("font-weight", "400")
    page.get_by_label("Name").fill("Grace")
    page.get_by_label("Large").check()
    page.get_by_label("Make it spicy").check()
    expect(page.get_by_text("Grace orders 2 large pizza(s) with olives, spicy,")).to_be_visible()
    toppings = page.get_by_role("group", name="Toppings")  # a checkbox list, not a <select>
    expect(toppings.get_by_label("olives")).to_be_checked()
    toppings.get_by_label("basil").check()
    expect(page.get_by_text("with olives, basil, spicy")).to_be_visible()
    toppings.get_by_label("olives").focus()
    page.keyboard.press("Space")  # keyboard operable
    expect(page.get_by_text("with basil, spicy")).to_be_visible()
    toppings.get_by_label("basil").uncheck()
    expect(page.get_by_text("with no toppings, spicy")).to_be_visible()


def choices(ctx: indah.Context) -> indah.Component:
    level = indah.Signal("all")
    mode = indah.Signal("replay")
    kinds = indah.Signal(["tool"])
    return indah.Column(
        gap="1rem",
        children=[
            indah.Chips(
                level,
                label="Level",
                options=[
                    "all",
                    {"value": "warn", "label": "Warnings", "count": 4, "tone": "warn"},
                    {"value": "err", "label": "Errors", "count": 2, "tone": "err"},
                ],
            ),
            indah.Chips(
                kinds,
                multi=True,
                label="Kinds",
                options=[("tool", "Tool calls"), ("chat", "Chat"), ("embed", "Embeddings")],
            ),
            indah.Segmented(
                mode,
                label="Mode",
                options=[("replay", "Replay"), ("record", "Record")],
                tones={"record": "err"},
            ),
            indah.Text(
                lambda: (
                    f"Level {level.value}, kinds {', '.join(kinds.value) or 'none'}, {mode.value}."
                ),
            ),
        ],
    )


def choices_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Level all, kinds tool, replay.")).to_be_visible()
    level = page.get_by_role("radiogroup", name="Level")
    expect(level.get_by_role("radio", name="Errors 2")).to_be_visible()  # the count is shown
    level.get_by_role("radio", name="Errors 2").click()
    expect(page.get_by_text("Level err,")).to_be_visible()
    kinds = page.get_by_role("group", name="Kinds")
    kinds.get_by_role("button", name="Chat").click()  # multi chips toggle
    expect(page.get_by_text("kinds tool, chat,")).to_be_visible()
    kinds.get_by_role("button", name="Tool calls").click()
    expect(page.get_by_text("kinds chat,")).to_be_visible()
    mode = page.get_by_role("radiogroup", name="Mode")
    mode.get_by_role("radio", name="Replay").focus()
    page.keyboard.press("ArrowRight")  # arrows move and select, as a radio group does
    expect(page.get_by_text(", record.")).to_be_visible()
    expect(mode.get_by_role("radio", name="Record")).to_have_attribute("aria-checked", "true")
    assert mode.get_by_role("radio", name="Replay").get_attribute("tabindex") == "-1"
    page.keyboard.press("ArrowLeft")
    expect(page.get_by_text(", replay.")).to_be_visible()
    page.keyboard.press("End")
    expect(page.get_by_text(", record.")).to_be_visible()


def live_options(ctx: indah.Context) -> indah.Component:
    projects = indah.Signal(["alpha", "beta"])
    current = indah.Signal("beta")
    tags = indah.Signal(["alpha", "beta"])

    def add() -> None:
        projects.set([*projects.value, f"project-{len(projects.value) + 1}"])

    def drop() -> None:
        if len(projects.value) > 1:
            projects.set(projects.value[:-1])

    return indah.Column(
        gap="1rem",
        children=[
            indah.Select(current, options=projects, label="Project"),
            indah.Segmented(current, options=projects, label="The same signal"),
            indah.Chips(tags, options=projects, multi=True, label="Tags"),
            indah.Row(
                children=[
                    indah.Button("Add a project", on_click=add),
                    indah.Button("Remove the last", on_click=drop, variant="ghost"),
                ]
            ),
            indah.Text(
                lambda: f"Project {current.value}; tags {', '.join(tags.value) or 'none'}.",
            ),
        ],
    )


def live_options_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    select = page.get_by_label("Project")
    expect(select.locator("option")).to_have_count(2)
    expect(select).to_have_value("beta")
    page.get_by_role("button", name="Add a project").click()
    expect(select.locator("option")).to_have_count(3)  # no reload
    expect(select).to_have_value("beta")  # the selection survives
    expect(
        page.get_by_role("radiogroup", name="The same signal").get_by_role("radio")
    ).to_have_count(3)
    expect(page.get_by_role("group", name="Tags").get_by_role("button")).to_have_count(3)
    page.get_by_role("button", name="Remove the last").click()
    page.get_by_role("button", name="Remove the last").click()
    expect(select.locator("option")).to_have_count(1)
    expect(
        page.get_by_text("tags alpha.")
    ).to_be_visible()  # a multi value is pruned to what is offered


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


def first_app(ctx: indah.Context) -> indah.Component:
    n = indah.Signal(0)
    return indah.Column(
        children=[
            indah.Button("Add one", lambda: n.set(n.value + 1)),
            indah.Text(lambda: f"n = {n.value}"),
        ]
    )


FIRST_APP_SOURCE = """
import indah

def build(ctx):                       # called once per browser tab: state is per tab
    n = indah.Signal(0)
    return indah.Session(indah.Column(children=[
        indah.Button("Add one", lambda: n.set(n.value + 1)),
        indah.Text(lambda: f"n = {n.value}"),
    ]))

app = indah.create_app(session_factory=build)   # an ASGI app: mount it anywhere
indah.launch(app)                               # or run it, in a script or a notebook cell
"""


def text_roles(ctx: indah.Context) -> indah.Component:
    return indah.Column(
        gap="0.5rem",
        children=[
            indah.Text("Body: the default, for paragraphs, status lines and notes."),
            indah.Text("Title: a heading for a block", variant="title"),
            indah.Text("Label: the name of a field", variant="label"),
            indah.Text("Caption: help text and fine print", variant="caption"),
            indah.Text("mono: ids, paths, aligned numbers", variant="mono"),
            indah.Text("1,284", variant="readout"),
            indah.Text("Two lines,\nkept as written."),
        ],
    )


def text_roles_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    body = page.get_by_text("Body: the default")
    expect(body).to_have_css("font-size", "15.2px")
    expect(page.get_by_text("1,284")).to_have_css("font-size", "22.4px")  # the readout, 1.4rem
    expect(page.get_by_text("Title: a heading")).to_have_css("font-weight", "600")


def first_app_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Add one").click()
    page.get_by_role("button", name="Add one").click()
    expect(page.get_by_text("n = 2")).to_be_visible()


def form_demo(ctx: indah.Context) -> indah.Component:
    invited = {"ada@example.org"}  # pretend this address is taken
    done = indah.Signal("")

    def invite(values: dict[str, str]):
        if values["email"] in invited:
            return {"email": "Already invited"}  # a server-side error, beside the field
        invited.add(values["email"])
        done.set(f"Invited {values['email']} as {values['role']}")

    form = indah.Form(on_submit=invite)
    email = form.text(
        "email",
        label="Email",
        placeholder="name@example.org",
        validate=[indah.validators.required(), indah.validators.email()],
    )
    role = form.select("role", label="Role", options=["viewer", "editor", "admin"])
    return indah.Column(
        children=[
            email,
            role,
            form.submit("Send invite"),
            indah.Text(
                lambda: "Ready to send" if form.valid.value else "Not ready yet", variant="caption"
            ),
            indah.Text(lambda: done.value),
        ]
    )


def form_demo_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    send = page.get_by_role("button", name="Send invite")
    box = page.get_by_label("Email")
    expect(send).to_be_disabled()  # invalid on load, and no error shouting yet
    expect(page.get_by_role("alert")).to_have_count(0)
    box.fill("not-an-email")
    expect(page.get_by_role("alert")).to_have_text("Enter a valid email address")
    expect(send).to_be_disabled()
    box.fill("ada@example.org")
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(send).to_be_enabled()
    send.click()
    expect(page.get_by_role("alert")).to_have_text("Already invited")  # the server's answer
    expect(send).to_be_disabled()
    box.fill("grace@example.org")
    expect(page.get_by_role("alert")).to_have_count(0)
    send.click()
    expect(page.get_by_text("Invited grace@example.org as viewer")).to_be_visible()


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
            slug="form",
            title="A form: disabled until valid",
            summary=(
                "`Form` groups inputs with a validator each. The button stays disabled while the "
                "form is invalid, an error appears beside the field once it has been touched, and "
                "`on_submit` can answer with a server-side error (try `ada@example.org`)."
            ),
            build=form_demo,
            covers=("Form", "validators"),
            docs="forms.md",
            adr=(47,),
            check=form_demo_check,
        ),
        Page(
            slug="text-roles",
            title="Text roles",
            summary="Plain `Text` is body text. `variant=` picks a role: title, label, caption, mono, or the large readout for a figure.",
            build=text_roles,
            covers=("Text",),
            docs="components.md",
            check=text_roles_check,
        ),
        Page(
            slug="first-app",
            title="Your first app",
            summary="The whole program: a session factory, `create_app`, `launch`. Each tab gets its own session; the code below is the complete file.",
            build=first_app,
            source=FIRST_APP_SOURCE,
            covers=("Session", "create_app", "launch"),
            docs="quickstart.md",
            adr=(2, 10),
            check=first_app_check,
        ),
        Page(
            slug="quickstart",
            title="The quickstart app",
            summary="Two sliders and a computed sum: the first app of the quickstart, running here.",
            build=quickstart,
            covers=("Signal", "computed", "Slider", "Text", "Column"),
            docs="quickstart.md",
            adr=(3,),
            check=quickstart_check,
        ),
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
            slug="choices",
            title="Chips and segmented controls",
            summary="Filter chips (single or multi, with counts and tones) and a segmented control; arrow keys work.",
            build=choices,
            covers=("Chips", "Segmented"),
            docs="components.md",
            check=choices_check,
        ),
        Page(
            slug="live-options",
            title="Options that change",
            summary="`options=` takes a signal, a computed or a callable: a new project appears with no reload.",
            build=live_options,
            covers=(),
            docs="components.md",
            check=live_options_check,
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

"""Chapter 3: overlays, feedback, text editing and the session Context."""

from __future__ import annotations

import json

import indah

from ..core import Chapter, Page


def modal_drawer(ctx: indah.Context) -> indah.Component:
    modal = indah.Signal(False)
    drawer = indah.Signal(False)
    closed = indah.Signal("Nothing closed yet.")
    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Button("Open modal", lambda: modal.set(True)),
                    indah.Button("Open drawer", lambda: drawer.set(True), variant="tonal"),
                ]
            ),
            indah.Text(lambda: closed.value),
            indah.Modal(
                title="A modal",
                open=modal,
                size="sm",
                on_close=lambda: closed.set("The modal closed."),
                children=[indah.Text("Esc, the backdrop or the x closes it.")],
            ),
            indah.Drawer(
                title="A drawer",
                open=drawer,
                side="right",
                on_close=lambda: closed.set("The drawer closed."),
                children=[indah.Text("Same behaviour, sliding in from the side.")],
            ),
        ]
    )


def modal_drawer_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Open modal").click()
    dialog = page.get_by_role("dialog", name="A modal")
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(page.get_by_text("The modal closed.")).to_be_visible()
    page.get_by_role("button", name="Open drawer").click()
    expect(page.get_by_role("dialog", name="A drawer")).to_be_visible()
    page.get_by_role("button", name="Close").click()
    expect(page.get_by_text("The drawer closed.")).to_be_visible()


def toasts(ctx: indah.Context) -> indah.Component:
    def show(kind: str):
        return lambda: ctx.toast(f"This is a {kind} toast", kind=kind)

    return indah.Row(
        children=[
            *[
                indah.Button(k, show(k), variant="tonal")
                for k in ("info", "success", "warn", "error")
            ],
            indah.Button(
                "sticky",
                lambda: ctx.toast("Click me to dismiss", kind="info", ttl=0),
                variant="ghost",
            ),
        ]
    )


def toasts_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    for kind in ("info", "success", "warn", "error"):
        page.get_by_role("button", name=kind, exact=True).click()
        expect(page.get_by_text(f"This is a {kind} toast")).to_be_visible()
    page.get_by_role("button", name="sticky").click()
    sticky = page.get_by_text("Click me to dismiss")
    expect(sticky).to_be_visible()
    page.wait_for_timeout(4500)  # the others time out (4 s); the sticky one stays
    expect(page.get_by_text("This is a info toast")).to_have_count(0)
    expect(sticky).to_be_visible()
    sticky.click()
    expect(sticky).to_have_count(0)


def toast_action(ctx: indah.Context) -> indah.Component:
    pending = indah.Signal(["alpha", "beta", "gamma"])
    done = indah.Signal([])

    def approve() -> None:
        if not pending.value:
            return
        name = pending.value[0]
        pending.set(pending.value[1:])
        done.set([*done.value, name])

        def undo() -> None:  # runs once, when the button is clicked
            done.set([d for d in done.value if d != name])
            pending.set([name, *pending.value])

        ctx.toast(f"Approved {name}", kind="success", ttl=8, action=("Undo", undo))

    return indah.Column(
        children=[
            indah.Text(lambda: f"Pending: {', '.join(pending.value) or 'none'}"),
            indah.Text(lambda: f"Approved: {', '.join(done.value) or 'none'}"),
            indah.Button("Approve next", approve, variant="tonal"),
        ]
    )


def toast_action_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Approve next").click()
    expect(page.get_by_text("Approved: alpha")).to_be_visible()
    expect(page.get_by_text("Approved alpha")).to_be_visible()  # the toast
    page.get_by_role("button", name="Undo").click()
    expect(page.get_by_text("Pending: alpha, beta, gamma")).to_be_visible()
    expect(page.get_by_text("Approved: none")).to_be_visible()
    expect(page.get_by_text("Approved alpha")).to_have_count(0)  # clicking the action dismissed it
    page.get_by_role("button", name="Approve next").click()
    expect(page.get_by_role("button", name="Undo")).to_be_visible()  # a fresh toast, a fresh button
    page.get_by_role("button", name="Dismiss").click()
    expect(page.get_by_role("button", name="Undo")).to_have_count(0)
    expect(page.get_by_text("Approved: alpha")).to_be_visible()  # dismissing does not undo


def confirm(ctx: indah.Context) -> indah.Component:
    items = indah.Signal(["alpha", "beta", "gamma"])
    return indah.Column(
        children=[
            indah.Text(lambda: f"Entries: {', '.join(items.value) or 'none'}"),
            indah.Button(
                "Delete all",
                lambda: items.set([]),
                variant="ghost",
                confirm="Delete all entries?",
            ),
        ]
    )


def confirm_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Delete all").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(page.get_by_text("Entries: alpha, beta, gamma")).to_be_visible()  # nothing ran
    page.get_by_role("button", name="Delete all").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete all").click()
    expect(page.get_by_text("Entries: none")).to_be_visible()


def menu(ctx: indah.Context) -> indah.Component:
    status = indah.Signal("Nothing chosen yet.")
    locked = indah.Signal(False)

    def say(text: str):
        return lambda: status.set(text)

    # The items are a function of `locked`, so the menu follows the switch with no reload.
    items = indah.Computed(
        lambda: [
            indah.MenuItem("Rename", say("Renamed."), shortcut="F2"),
            indah.MenuItem("Duplicate", say("Duplicated.")),
            indah.MenuItem("Archive", say("Archived."), disabled=True),
            indah.MenuItem(
                "Delete",
                say("Deleted."),
                danger=True,
                confirm="Delete this project?",
                disabled=locked.value,
            ),
        ]
    )
    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Menu("Actions", items),
                    indah.Switch(locked, label="Locked"),
                ]
            ),
            indah.Text(lambda: status.value),
        ]
    )


def menu_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    trigger = page.get_by_role("button", name="Actions")
    trigger.click()
    expect(page.get_by_role("menu")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Rename")).to_be_focused()  # a click focuses item 1
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")  # Duplicate
    expect(page.get_by_text("Duplicated.")).to_be_visible()
    expect(page.get_by_role("menu")).to_have_count(0)
    expect(trigger).to_be_focused()  # focus returns to the trigger
    trigger.press("ArrowUp")  # opens on the last item
    expect(page.get_by_role("menuitem", name="Delete")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).to_have_count(0)
    trigger.click()
    page.get_by_role("menuitem", name="Delete").click()  # asks first
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Cancel").click()
    expect(page.get_by_text("Duplicated.")).to_be_visible()  # Delete did not run
    page.get_by_role("switch", name="Locked").click()
    trigger.click()
    expect(page.get_by_role("menuitem", name="Delete")).to_have_attribute("aria-disabled", "true")


def command_palette(ctx: indah.Context) -> indah.Component:
    status = indah.Signal("Press Ctrl+K (or Cmd+K), type, and press Enter.")
    on_log_page = indah.Signal(False)

    def say(text: str):
        return lambda: status.set(text)

    # The list is a function of `on_log_page`: a page's own commands join the app's while it shows,
    # and leave with it. A jump command (`Command("Log", to="/log")`) takes `ctx=` on the palette.
    commands = indah.Computed(
        lambda: [
            indah.Command("Open the log", say("Opened the log."), group="Go to", shortcut="g l"),
            indah.Command("Open pending", say("Opened pending."), group="Go to"),
            indah.Command(
                "Pause intake", say("Paused."), group="Actions", keywords="stop halt freeze"
            ),
            indah.Command(
                "Delete all entries",
                say("Deleted."),
                group="Actions",
                confirm="Delete every entry?",
            ),
            *(
                [indah.Command("Clear the log", say("Cleared."), group="This page")]
                if on_log_page.value
                else []
            ),
        ]
    )
    return indah.Column(
        children=[
            indah.CommandPalette(commands, ctx=ctx),
            indah.Switch(on_log_page, label="On the log page"),
            indah.Text(lambda: status.value),
        ]
    )


def command_palette_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("switch", name="On the log page").focus()
    page.keyboard.press("Control+k")
    box = page.get_by_role("combobox")
    expect(box).to_be_focused()
    box.fill("halt")  # a keyword the list does not show
    page.keyboard.press("Enter")
    expect(page.get_by_text("Paused.")).to_be_visible()
    page.get_by_role("switch", name="On the log page").click()
    page.keyboard.press("Control+k")
    expect(page.get_by_role("option", name="Clear the log")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="Command palette")).to_have_count(0)


def badges(ctx: indah.Context) -> indah.Component:
    pinned = indah.Signal(False)
    waiting = indah.Signal(3)
    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Badge("neutral"),
                    indah.Badge("ok", tone="ok"),
                    indah.Badge("warn", tone="warn"),
                    indah.Badge("err", tone="err"),
                    indah.Badge("info", tone="info"),
                ]
            ),
            indah.Row(
                children=[
                    indah.Badge(lambda: f"{waiting.value} waiting", tone="warn"),
                    indah.Button("Take one", lambda: waiting.set(max(0, waiting.value - 1))),
                ]
            ),
            indah.Switch(pinned, label="Pinned"),
            indah.Text(lambda: "Pinned." if pinned.value else "Not pinned."),
            indah.Text("Hover or focus me", tooltip="Shown on hover and on keyboard focus"),
        ]
    )


def badges_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("3 waiting")).to_be_visible()
    page.get_by_role("button", name="Take one").click()
    expect(page.get_by_text("2 waiting")).to_be_visible()
    expect(page.get_by_text("Not pinned.")).to_be_visible()
    page.get_by_role("switch", name="Pinned").click()
    expect(page.get_by_text("Pinned.", exact=True)).to_be_visible()
    page.get_by_text("Hover or focus me").hover()
    expect(page.get_by_role("tooltip")).to_have_text("Shown on hover and on keyboard focus")


def shortcuts(ctx: indah.Context) -> indah.Component:
    count = indah.Signal(0)
    return indah.Column(
        children=[
            indah.Text("Click the page body, then press a, r or g c. Press ? for the help."),
            indah.Text(lambda: f"Count: {count.value}"),
            indah.Shortcuts(
                {
                    "a": (lambda: count.set(count.value + 1), "Add one"),
                    "r": (lambda: count.set(0), "Reset the count"),
                    "g c": (lambda: count.set(100), "Jump to one hundred"),
                }
            ),
        ]
    )


def shortcuts_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_text("Count: 0").click()
    page.keyboard.press("a")
    page.keyboard.press("a")
    expect(page.get_by_text("Count: 2")).to_be_visible()
    page.keyboard.press("g")
    page.keyboard.press("c")
    expect(page.get_by_text("Count: 100")).to_be_visible()
    page.keyboard.press("r")
    expect(page.get_by_text("Count: 0")).to_be_visible()
    page.keyboard.press("?")
    help_ = page.get_by_role("dialog")
    expect(help_).to_be_visible()
    expect(help_.get_by_text("Jump to one hundred")).to_be_visible()
    page.keyboard.press("Escape")
    expect(help_).to_have_count(0)


def text_inputs(ctx: indah.Context) -> indah.Component:
    note = indah.Signal("Line one\nLine two")
    level = indah.Signal("info")
    return indah.Column(
        children=[
            indah.TextArea(note, label="Notes", rows=4),
            indah.Select(level, options=["info", "warn", "error"], label="Level"),
            indah.Text(
                lambda: (
                    f"{level.value.upper()}: {len(note.value.splitlines())} line(s), "
                    f"{len(note.value)} characters."
                )
            ),
        ]
    )


def text_inputs_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("INFO: 2 line(s), 17 characters.")).to_be_visible()
    page.get_by_label("Notes").fill("a\nb\nc")
    page.get_by_label("Level").select_option("error")
    expect(page.get_by_text("ERROR: 3 line(s), 5 characters.")).to_be_visible()


def code_editor(ctx: indah.Context) -> indah.Component:
    doc = indah.Signal('{"name":"indah","tags":["ui","python"]}')
    notes = indah.Signal("# YAML works too\nname: indah\nkeys: [a, b]\n")
    fixed = indah.Signal('{"read_only": true}')
    parsed = indah.computed(lambda: _describe(doc.value))
    return indah.Column(
        children=[
            indah.CodeEditor(doc, language="json", format_button=True, height="8rem", label="JSON"),
            indah.Text(lambda: parsed.value),
            indah.CodeEditor(notes, language="yaml", height="6rem", label="YAML"),
            indah.CodeEditor(
                fixed, language="json", read_only=True, height="4rem", label="Read only"
            ),
        ]
    )


def _describe(text: str) -> str:
    try:
        return f"Valid JSON with {len(json.loads(text))} key(s)."
    except ValueError as exc:
        return f"Not valid JSON yet: {exc}"


def code_editor_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Valid JSON with 2 key(s).")).to_be_visible(timeout=15000)
    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("End")
    page.keyboard.type(",")  # now invalid
    expect(page.get_by_text("Not valid JSON yet")).to_be_visible()
    page.keyboard.press("Backspace")
    expect(page.get_by_text("Valid JSON with 2 key(s).")).to_be_visible()
    page.get_by_role("button", name="Format").click()  # the server pretty-prints it
    expect(page.locator(".cm-line", has_text='"name": "indah"').first).to_be_visible()
    assert page.locator(".cm-content").nth(2).get_attribute("contenteditable") == "false"


def context(ctx: indah.Context) -> indah.Component:
    return indah.Column(
        children=[
            indah.Text(f"Session id: {ctx.sid[:8]}... (one per browser tab)"),
            indah.Text(f"Arrived from client {ctx.conn.client} at app path {ctx.conn.app_path}"),
            indah.Text(lambda: f"Current in-app path: {ctx.path.value}"),
            indah.Text(f"Signed-in user: {ctx.user.id if ctx.user else 'nobody (auth is off)'}"),
            indah.Button("Toast this session", lambda: ctx.toast(f"Hello, tab {ctx.sid[:4]}")),
        ]
    )


def context_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("Session id: ")).to_be_visible()
    expect(page.get_by_text("Signed-in user: nobody")).to_be_visible()
    expect(page.get_by_text("Current in-app path: /context")).to_be_visible()
    page.get_by_role("button", name="Toast this session").click()
    expect(page.get_by_text("Hello, tab ")).to_be_visible()


CHAPTER = Chapter(
    slug="overlays",
    title="Overlays and feedback",
    order=30,
    blurb=(
        "Dialogs, drawers, toasts, confirmations, keyboard shortcuts and the text-editing inputs, "
        "all driven by signals. `Context` is the per-session handle a session factory receives."
    ),
    pages=[
        Page(
            slug="modal-drawer",
            title="Modal and Drawer",
            summary="Each is an `open` signal plus children. Esc, the backdrop or the x closes it and runs `on_close`.",
            build=modal_drawer,
            covers=("Modal", "Drawer"),
            docs="dashboards.md",
            adr=(30,),
            check=modal_drawer_check,
        ),
        Page(
            slug="toasts",
            title="Toasts",
            summary="`ctx.toast(message, kind=..., ttl=...)` reaches this tab only. `ttl=0` keeps it until clicked.",
            build=toasts,
            covers=("Context", "Button"),
            docs="dashboards.md",
            adr=(30,),
            check=toasts_check,
        ),
        Page(
            slug="toast-action",
            title="Toast with an action",
            summary=(
                '`ctx.toast(msg, action=("Undo", fn), ttl=8)` adds a button. Clicking it runs `fn` '
                "once and dismisses the toast; it goes to this tab only. `guard()` is checked when "
                "the button is clicked."
            ),
            build=toast_action,
            covers=("Context", "Button", "Text"),
            docs="dashboards.md",
            adr=(30,),
            check=toast_action_check,
        ),
        Page(
            slug="confirm",
            title="Confirm before acting",
            summary="`Button(confirm=...)` asks first and posts the click only if you accept. It is a UX guard, not authorization.",
            build=confirm,
            covers=("Button",),
            docs="dashboards.md",
            adr=(30,),
            check=confirm_check,
        ),
        Page(
            slug="menu",
            title="Menu",
            summary=(
                "`Menu(trigger, items)` is a menu button: arrow keys, Home/End, a letter to jump, Escape back "
                "to the trigger. An item can be a `danger`, ask to `confirm`, be `disabled` or show a "
                "`shortcut` (text only). The items may follow a signal."
            ),
            build=menu,
            covers=("Menu", "MenuItem", "Switch"),
            docs="dashboards.md",
            adr=(30,),
            check=menu_check,
        ),
        Page(
            slug="command-palette",
            title="Command palette",
            summary=(
                "`CommandPalette(commands)` opens on Ctrl/Cmd+K: type to filter (a prefix first, then a word, "
                "a substring, a subsequence, then keywords), arrows move, Enter runs, Escape closes. Commands "
                "can run a function, jump to a page (`to=`), ask to `confirm`, and a page can add its own."
            ),
            build=command_palette,
            covers=("CommandPalette", "Command", "Switch"),
            docs="dashboards.md",
            adr=(30,),
            check=command_palette_check,
        ),
        Page(
            slug="badges",
            title="Badge, Switch and tooltips",
            summary="A `Badge` tone and text may be reactive, a `Switch` is a boolean input, and any component takes `tooltip=`.",
            build=badges,
            covers=("Badge", "Switch", "Button"),
            docs="dashboards.md",
            adr=(30,),
            check=badges_check,
        ),
        Page(
            slug="shortcuts",
            title="Keyboard shortcuts",
            summary="`Shortcuts` maps keys (and sequences like `g c`) to handlers; `?` opens a help overlay built from the labels.",
            build=shortcuts,
            covers=("Shortcuts",),
            docs="dashboards.md",
            adr=(30,),
            check=shortcuts_check,
        ),
        Page(
            slug="text-inputs",
            title="TextArea and Select",
            summary="Two more two-way inputs: a multi-line box and a dropdown.",
            build=text_inputs,
            covers=("TextArea", "Select"),
            docs="components.md",
            check=text_inputs_check,
        ),
        Page(
            slug="code-editor",
            local_only="the editor module is served from api/editor.js, a route the browser runtime does not provide",
            title="CodeEditor",
            summary="JSON and YAML editing with linting, a server-side Format button and a read-only mode.",
            build=code_editor,
            covers=("CodeEditor",),
            docs="dashboards.md",
            adr=(32,),
            check=code_editor_check,
        ),
        Page(
            slug="context",
            local_only="it shows the Studio's own URL paths and a real request's headers, which a page in the docs does not have",
            title="The session Context",
            summary="A session factory gets a `Context`: the session id, the connection, the user, the in-app path and `toast`.",
            build=context,
            covers=("Context",),
            docs="dashboards.md",
            adr=(25,),
            check=context_check,
        ),
    ],
)

"""Chapter: the playground. Type indah code, run it, open the result in its own tab."""

from __future__ import annotations

import asyncio

import indah

from ..core import Chapter, Page
from ..playground import run_snippet

STARTERS = {
    "Counter": """def build():
    n = indah.Signal(0)
    return indah.Column(children=[
        indah.Button("Add one", lambda: n.set(n.value + 1)),
        indah.Text(lambda: f"n = {n.value}"),
    ])
""",
    "Celsius to Fahrenheit": """def build():
    c = indah.Signal(21.0)
    f = indah.computed(lambda: round(c.value * 9 / 5 + 32, 1))
    return indah.Card(title="Converter", children=[
        indah.Slider(c, min=-20, max=45, step=0.5, label="Celsius"),
        indah.Text(lambda: f"{c.value} C = {f.value} F"),
    ])
""",
    "Searchable table": """def build():
    rows = [{"n": i, "square": i * i, "even": "yes" if i % 2 == 0 else "no"} for i in range(1, 201)]
    return indah.Table(
        rows=rows, key="n", search=True, height="22rem",
        columns=[indah.Col("n", kind="number"), indah.Col("square", kind="number"),
                 indah.Col("even", kind="badge", tones={"yes": "ok", "no": "neutral"})],
    )
""",
    "Name tag (two inputs)": """def build():
    first = indah.Signal("Ada")
    last = indah.Signal("Lovelace")
    return indah.Column(children=[
        indah.TextInput(first, label="First name"),
        indah.TextInput(last, label="Last name"),
        indah.Text(lambda: f"## {first.value} {last.value}", markdown=True),
    ])
""",
}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def playground(ctx: indah.Context) -> indah.Component:
    allowed = (ctx.conn.client or "") in LOOPBACK
    starter = indah.Signal("Counter")
    code = indah.Signal(STARTERS["Counter"])
    error = indah.Signal("")
    result = indah.Signal("")
    busy = indah.Signal(False)

    def load_starter() -> None:
        code.set(STARTERS[starter.value])
        error.set("")
        result.set("")

    indah.effect(load_starter)

    async def run() -> None:
        if not allowed:
            error.set("The playground only runs for a browser on the same machine as the server.")
            return
        busy.set(True)
        try:
            run_id, problem = await asyncio.to_thread(run_snippet, code.value)
        finally:
            busy.set(False)
        error.set(problem)
        result.set("" if problem else f"Running. **[Open the result](/play/{run_id}/)**")

    banner = (
        "**This runs the code you type on the machine that serves the Studio.** Only a browser on "
        "that machine may use it. Define `def build(): return <component>`; `indah` is already imported."
        if allowed
        else "The playground is switched off: it runs code on the server, so it only works for a "
        "browser on the same machine."
    )
    return indah.Column(
        children=[
            indah.Text(banner, markdown=True),
            indah.Select(starter, options=list(STARTERS), label="Start from"),
            indah.CodeEditor(code, language="text", lint=False, height="20rem", label="Your code"),
            indah.Row(
                children=[
                    indah.Button("Run", run),
                    indah.Spinner(active=busy, label="Running"),
                ]
            ),
            indah.Text(lambda: result.value, markdown=True),
            indah.CodeEditor(
                error, language="text", read_only=True, lint=False, height="8rem", label="Problems"
            ),
        ]
    )


def playground_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Run", exact=True).click()
    link = page.get_by_role("link", name="Open the result")
    expect(link).to_be_visible()
    # the run is its own app: open it, click its button
    run_page = pw.context.new_page()
    run_page.goto(pw.base.rstrip("/") + link.get_attribute("href"))
    expect(run_page.get_by_text("n = 0")).to_be_visible()
    run_page.get_by_role("button", name="Add one").click()
    expect(run_page.get_by_text("n = 1")).to_be_visible()
    run_page.close()
    # a broken snippet is reported, not fatal
    editor = page.locator(".cm-content").first
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.type("def build(:\n")
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.get_by_text("SyntaxError").first).to_be_visible()
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.type("def build():\n    return 5\n")
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.get_by_text("not an indah component").first).to_be_visible()


CHAPTER = Chapter(
    slug="playground",
    title="Playground",
    order=95,
    blurb="Write a few lines of indah, run them, and open the result in its own tab.",
    pages=[
        Page(
            slug="run",
            title="Try indah code",
            summary="Pick a starting point, edit it, press Run. Each run becomes its own app under `/play/`.",
            build=playground,
            covers=("CodeEditor",),
            docs="quickstart.md",
            check=playground_check,
            source="""
            # What the Run button does (server side):
            namespace = {"indah": indah}
            exec(compile(code, "<playground>", "exec"), namespace)   # in a thread, with a timeout
            root = namespace["build"]()                              # must be an indah component
            app = indah.create_app(session_factory=lambda: indah.Session(namespace["build"]()))
            # ...mounted at /play/<id>/, one per run (the last 16 are kept)
            """,
        )
    ],
)

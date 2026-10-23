"""Chapter 5: showing and editing data (tables, lists, viewers)."""

from __future__ import annotations

import json
import random
from typing import Any

import indah

from ..core import Chapter, Page

# -- Generated data (module level, seeded, so every page is deterministic) --------------------

BASE_MS = 1_792_660_462_000  # 2026-10-22 09:14:22 UTC
ROUTES = ["/search", "/login", "/orders", "/orders/{id}", "/health", "/export", "/upload"]
STATUS_TONES = {"ok": "ok", "slow": "warn", "error": "err", "queued": "info"}


def make_calls(n: int, seed: int = 7) -> list[dict[str, Any]]:
    """``n`` fake API calls, oldest first, with a stable ``id`` each."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        status = rng.choices(["ok", "slow", "error", "queued"], [6, 2, 1, 1])[0]
        rows.append(
            {
                "id": f"call-{i + 1:04d}",
                "ts": BASE_MS + i * 7_000,
                "route": rng.choice(ROUTES),
                "status": status,
                "ms": rng.randint(8, 90) if status == "ok" else rng.randint(300, 2500),
            }
        )
    return rows


def make_nodes(n: int, seed: int = 3) -> list[dict[str, Any]]:
    """``n`` fake cluster nodes for the remote table."""
    rng = random.Random(seed)
    zones = ["eu-west", "us-east", "ap-south"]
    return [
        {
            "id": f"node-{i:05d}",
            "zone": rng.choice(zones),
            "cpu": rng.randint(1, 99),
            "state": rng.choices(["up", "drain", "down"], [8, 1, 1])[0],
        }
        for i in range(1, n + 1)
    ]


NODES = make_nodes(5000)
PEOPLE = [
    {"name": "Ada Lovelace", "role": "Analyst", "city": "London"},
    {"name": "Grace Hopper", "role": "Admiral", "city": "New York"},
    {"name": "Alan Turing", "role": "Cryptanalyst", "city": "Wilmslow"},
    {"name": "Katherine Johnson", "role": "Mathematician", "city": "Hampton"},
    {"name": "Margaret Hamilton", "role": "Engineer", "city": "Boston"},
    {"name": "Edsger Dijkstra", "role": "Professor", "city": "Nuenen"},
]
ENTRY = {
    "id": "e_01JABC",
    "model": "gpt-4o",
    "tags": ["billing", "faq"],
    "usage": {"prompt": 412, "completion": 96, "cached": True},
    "messages": [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "What is the refund window?"},
    ],
}
CACHED = {"answer": "Refunds are open for 30 days.", "score": 0.97, "tier": "exact"}
INCOMING = {"tier": "exact", "score": 0.97, "answer": "Refunds are open for 14 days."}
TASK_SPEC = {
    "tag": "div",
    "class": "pg-row",
    "children": [
        {"tag": "input", "bind": {"value": "title"}, "on": {"input": {"event": "title"}}},
        {"tag": "button", "literal": "Remove", "on": {"click": {"event": "remove"}}},
    ],
}


# -- Classic table ------------------------------------------------------------------------------


def table_classic(ctx: indah.Context) -> indah.Component:
    picked = indah.Signal(None)
    return indah.Column(
        children=[
            indah.Table(PEOPLE, selected=picked, page_size=4, label="People"),
            indah.Text(
                lambda: (
                    "Click a row."
                    if picked.value is None
                    else f"Selected row {picked.value}: {PEOPLE[picked.value]['name']}"
                )
            ),
        ]
    )


def table_classic_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(4)  # paged
    page.get_by_role("cell", name="Alan Turing").click()
    expect(page.get_by_text("Selected row 2: Alan Turing")).to_be_visible()
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_role("cell", name="Edsger Dijkstra")).to_be_visible()
    page.get_by_role("button", name="Name").click()  # sort by the Name header
    expect(page.locator("tbody tr").first).to_contain_text("Ada Lovelace")


# -- Rich table ---------------------------------------------------------------------------------


def table_rich(ctx: indah.Context) -> indah.Component:
    calls = make_calls(40)
    picked = indah.Signal(None)
    density = indah.Signal("comfortable")
    return indah.Column(
        children=[
            indah.Radio(density, options=["comfortable", "compact"], label="Density"),
            indah.Table(
                rows=calls,
                key="id",
                selected=picked,
                height="18rem",
                search=True,
                column_toggle=True,
                density=density,
                columns=[
                    indah.Col("ts", "When", kind="time", time_format="clock"),
                    indah.Col("id", kind="mono"),
                    indah.Col("route"),
                    indah.Col("status", kind="badge", tones=STATUS_TONES),
                    indah.Col("ms", "Latency (ms)", kind="number"),
                ],
            ),
            indah.Text(lambda: f"Selected key: {picked.value}"),
        ]
    )


def table_rich_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(40)
    page.get_by_label("Filter rows").fill("/health")
    expect(page.locator("tbody tr").first).to_contain_text("/health")
    assert 0 < page.locator("tbody tr").count() < 40
    page.get_by_label("Filter rows").fill("")
    page.get_by_text("Columns", exact=True).click()
    page.get_by_label("Latency (ms)").uncheck()
    expect(page.get_by_role("columnheader", name="Latency (ms)")).to_have_count(0)
    page.get_by_text("Columns", exact=True).click()  # close the menu again
    page.get_by_label("compact").check()
    page.locator("tbody tr").nth(2).click()
    expect(page.get_by_text("Selected key: call-0003")).to_be_visible()


# -- Composite cells and truncation (IND-148) ----------------------------------------------------

PROMPTS = [
    ("Summarise the incident report and list the three follow-up actions for the on-call team", 5),
    ("Translate the onboarding guide into French, keeping every code block untouched", 3),
    ("Why does the nightly export fail only on the first day of the month?", 4),
    ("Draft a polite reply declining the meeting and proposing two other times next week", 2),
    ("Classify these 400 support tickets by product area and urgency, then export a CSV", 5),
    ("What is the capital of Australia?", 1),
    ("Rewrite this paragraph for a nine-year-old without losing the numbers in it", 3),
    ("Explain the difference between a mutex and a semaphore, with a short C example", 4),
]


def table_cells(ctx: indah.Context) -> indah.Component:
    rows = [
        {
            "id": f"req-{i:02d}",
            "who": ["ana", "bo", "cy", "dee"][i % 4],
            "route": ["/chat", "/summarise", "/classify"][i % 3],
            "prompt": text,
            "note": "Matched on the first try. " * (1 + i % 3),
            "tier": tier,
        }
        for i, (text, tier) in enumerate(PROMPTS)
    ]
    match = {
        "tag": "meter",
        "attrs": {"min": "0", "max": "5", "aria-label": "Match tier"},
        "bind": {"value": "tier"},
    }
    who = {
        "tag": "div",
        "children": [
            {"tag": "strong", "text": "who"},
            {"tag": "small", "text": "route", "class": "muted"},
        ],
    }
    return indah.Table(
        rows=rows,
        key="id",
        search=True,
        height="20rem",
        columns=[
            indah.Col("id", kind="mono"),
            indah.Col("who", "Caller", kind="cell", render=who),
            indah.Col("tier", "Match", kind="cell", render=match, sort_key="tier", width="9rem"),
            indah.Col("prompt", "Prompt", truncate=True, max_width="26ch"),
            indah.Col("note", "Notes", wrap=True, width="14rem"),
        ],
    )


def table_cells_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(len(PROMPTS))
    expect(page.locator("tbody tr").first.locator("meter")).to_be_visible()
    prompt = page.locator("tbody tr").first.locator("td.trunc")
    assert prompt.get_attribute("title") == PROMPTS[0][0]  # the full text is on hover
    assert prompt.evaluate("el => el.scrollWidth > el.clientWidth")  # and clipped on screen
    page.get_by_role("button", name="Match").click()  # a cell column sorts by its sort_key
    expect(page.locator("tbody tr").first).to_contain_text("What is the capital")
    page.get_by_label("Filter rows").fill("mutex")
    expect(page.locator("tbody tr")).to_have_count(1)


# -- Row actions and multi-select ---------------------------------------------------------------


def table_actions(ctx: indah.Context) -> indah.Component:
    rows = indah.Signal(make_calls(8, seed=1))
    checked = indah.Signal([])

    def archive(key) -> None:  # the row may be gone already: tolerate that
        rows.set([r for r in rows.value if r["id"] != key])
        ctx.toast(f"Archived {key}", kind="success")

    def archive_checked() -> None:
        gone = set(checked.value)
        rows.set([r for r in rows.value if r["id"] not in gone])
        checked.set([])
        ctx.toast(f"Archived {len(gone)} rows", kind="success")

    return indah.Column(
        children=[
            indah.Table(
                rows=rows,
                key="id",
                checked=checked,
                actions=[indah.RowAction("Archive", archive, confirm="Archive this call?")],
                columns=[
                    indah.Col("id", kind="mono"),
                    indah.Col("route"),
                    indah.Col("status", kind="badge", tones=STATUS_TONES),
                ],
            ),
            indah.Row(
                children=[
                    indah.Button("Archive checked", archive_checked, variant="tonal"),
                    indah.Text(lambda: f"{len(checked.value)} checked, {len(rows.value)} rows"),
                ]
            ),
        ]
    )


def table_actions_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(8)
    page.get_by_role("button", name="Archive", exact=True).first.click()
    expect(page.get_by_text("Archive this call?")).to_be_visible()  # the confirm dialog
    page.get_by_role("button", name="Cancel").click()
    expect(page.locator("tbody tr")).to_have_count(8)  # cancelled: nothing happened
    page.get_by_role("button", name="Archive", exact=True).first.click()
    page.locator(".confirm-yes").click()
    expect(page.locator("tbody tr")).to_have_count(7)
    expect(page.get_by_text("Archived call-0001")).to_be_visible()  # a toast
    page.get_by_label("Select row").nth(0).check()
    page.get_by_label("Select row").nth(1).check()
    expect(page.get_by_text("2 checked, 7 rows")).to_be_visible()
    page.get_by_role("button", name="Archive checked").click()
    expect(page.locator("tbody tr")).to_have_count(5)


# -- Remote table -------------------------------------------------------------------------------


def table_remote(ctx: indah.Context) -> indah.Component:
    checked = indah.Signal([])

    def loader(q: indah.TableQuery):  # the loader owns search and sort
        rows = [n for n in NODES if q.search.lower() in n["id"] + n["zone"]]
        if q.sort:
            rows.sort(key=lambda n: n[q.sort[0]], reverse=q.sort[1] == "desc")
        return rows[q.offset : q.offset + q.limit], len(rows)

    return indah.Column(
        children=[
            indah.Table(
                key="id",
                remote=loader,
                virtual=True,
                height="20rem",
                search=True,
                checked=checked,
                density="compact",
                columns=[
                    indah.Col("id", kind="mono"),
                    indah.Col("zone"),
                    indah.Col("cpu", "CPU %", kind="number"),
                    indah.Col(
                        "state", kind="badge", tones={"up": "ok", "drain": "warn", "down": "err"}
                    ),
                ],
            ),
            indah.Text(lambda: f"{len(checked.value)} node(s) checked"),
        ]
    )


def table_remote_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("5000 rows")).to_be_visible(timeout=15000)
    expect(page.locator("tbody tr:not(.vspacer)").first).to_contain_text("node-00001")
    assert page.locator("tbody tr:not(.vspacer)").count() < 80  # virtual: only the rows in view
    page.get_by_role("button", name="CPU %").click()  # server-side sort
    page.get_by_role("button", name="CPU %").click()
    expect(page.locator("tbody tr:not(.vspacer)").first).to_contain_text("99")
    page.get_by_label("Filter rows").fill("ap-south")  # server-side search
    expect(page.get_by_text("5000 rows")).to_have_count(0)
    page.get_by_label("Select the rows on screen").check()
    expect(page.get_by_role("button", name="Select all")).to_be_visible()
    page.get_by_role("button", name="Select all").click()
    expect(page.get_by_text(" node(s) checked")).not_to_have_text("0 node(s) checked")


# -- Follow the tail ----------------------------------------------------------------------------


def table_follow(ctx: indah.Context) -> indah.Component:
    stream = indah.Stream(make_calls(12), limit=30)  # keeps only the newest 30
    calls = make_calls(100, seed=9)
    cursor = {"i": 0}

    def add(n: int) -> None:
        batch = calls[cursor["i"] : cursor["i"] + n]
        cursor["i"] += n
        stream.append(
            *[
                {**r, "id": f"live-{cursor['i'] - len(batch) + k + 1:03d}"}
                for k, r in enumerate(batch)
            ]
        )

    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Button("Add 5 rows", lambda: add(5)),
                    indah.Button("Add 40 rows", lambda: add(40), variant="tonal"),
                    indah.Text(lambda: f"{len(stream.value)} rows kept (limit {stream.limit})"),
                ]
            ),
            indah.Table(
                rows=stream,
                key="id",
                height="16rem",
                follow=True,
                columns=[
                    indah.Col("id", kind="mono"),
                    indah.Col("route"),
                    indah.Col("status", kind="badge", tones=STATUS_TONES),
                ],
            ),
        ]
    )


def table_keyboard(ctx: indah.Context) -> indah.Component:
    calls = make_calls(40, seed=3)
    opened = indah.Signal("nothing opened yet")
    bells = indah.Signal(0)
    checked = indah.Signal([])

    def open_call(key: str) -> None:
        opened.set(f"opened {key}")

    return indah.Column(
        children=[
            indah.Shortcuts({"j": (lambda: bells.set(bells.value + 1), "Ring the bell")}),
            indah.Text(
                lambda: f"{opened.value}. The page-wide j shortcut fired {bells.value} times."
            ),
            indah.Table(
                rows=calls,
                key="id",
                height="16rem",
                checked=checked,
                on_open=open_call,
                columns=[
                    indah.Col("id", kind="mono"),
                    indah.Col("route"),
                    indah.Col("status", kind="badge", tones=STATUS_TONES),
                ],
            ),
        ]
    )


def table_keyboard_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    grid = page.get_by_role("grid")
    grid.focus()
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(page.locator("tr.kb-active")).to_have_count(1)
    expect(page.get_by_text("fired 0 times")).to_be_visible()  # the focused table took the j
    page.keyboard.press("Enter")
    expect(page.get_by_text("nothing opened yet")).to_have_count(0)  # Enter called on_open
    page.keyboard.press("Escape")
    page.keyboard.press("j")  # focus left the table: the shortcut gets the key
    expect(page.get_by_text("fired 1 times")).to_be_visible()
    grid.focus()
    page.keyboard.press("End")  # leave the active row at the bottom for the screenshot


def table_follow_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(12)
    page.get_by_role("button", name="Add 5 rows").click()
    expect(page.get_by_role("cell", name="live-005")).to_be_visible()  # scrolled to the newest
    page.get_by_role("button", name="Add 40 rows").click()
    expect(page.get_by_text("30 rows kept (limit 30)")).to_be_visible()
    expect(page.locator("tbody tr")).to_have_count(30)  # the oldest were trimmed
    expect(page.get_by_role("cell", name="live-045")).to_be_visible()


# -- DataFrame ----------------------------------------------------------------------------------


def dataframe(ctx: indah.Context) -> indah.Component:
    rows = indah.Signal(3.0)
    table = indah.computed(lambda: PEOPLE[: int(rows.value)])  # a list of dicts, or a pandas frame
    return indah.Column(
        children=[
            indah.Slider(rows, min=1, max=6, step=1, label="Rows"),
            indah.DataFrame(lambda: table.value, label="People"),
        ]
    )


def dataframe_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr")).to_have_count(3)
    slider = page.get_by_role("slider")
    slider.focus()
    slider.press("ArrowRight")
    slider.press("ArrowRight")
    expect(page.locator("tbody tr")).to_have_count(5)
    expect(page.get_by_role("cell", name="Margaret Hamilton")).to_be_visible()


# -- Stat ---------------------------------------------------------------------------------------


def empty_and_code(ctx: indah.Context) -> indah.Component:
    output = indah.Signal("")

    def send() -> None:
        output.set("GET /v1/models 200 12ms")

    return indah.Column(
        children=[
            indah.Empty(
                "No requests yet",
                "Start the proxy and every request appears here.",
                children=[indah.Code("semula log --follow", language="bash")],
                action=indah.Button("Send a test request", send),
            ),
            indah.Code(lambda: output.value or "(nothing yet)", language="output", copy=False),
        ]
    )


def empty_and_code_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("No requests yet")).to_be_visible()
    page.get_by_role("button", name="Copy").first.click()
    expect(page.get_by_text("Copied", exact=True).first).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == "semula log --follow"
    page.get_by_role("button", name="Send a test request").click()
    expect(page.get_by_text("GET /v1/models 200 12ms")).to_be_visible()


def barstrip(ctx: indah.Context) -> indah.Component:
    rng = random.Random(7)  # the same minutes every time
    minutes = indah.Signal([(rng.randint(2, 9), rng.randint(0, 3)) for _ in range(24)])
    clock = indah.Signal(24)  # minutes shown so far, for the labels

    def tick() -> None:
        clock.set(clock.value + 1)
        minutes.set([*minutes.value[-29:], (rng.randint(2, 9), rng.randint(0, 3))])

    ctx.every(1.0, tick)  # a new "minute" each second; stops with the tab
    return indah.Column(
        children=[
            indah.Text(
                lambda: "Latest minute: hits {}, misses {}".format(*minutes.value[-1]),
                variant="label",
            ),
            indah.BarStrip(
                minutes,
                tones=["ok", "err"],
                names=["hit", "miss"],
                labels=lambda: [
                    f"min {clock.value - len(minutes.value) + i + 1}"
                    for i in range(len(minutes.value))
                ],
                label="Calls per minute",
                height=48,
            ),
            indah.Text("One series, a single tone:", variant="caption"),
            indah.BarStrip([3, 5, 2, 8, 6, 0, 4], tones=["info"], label="Queue depth", height=24),
REQUEST = "Summarise the attached report in three bullet points. Ignore the template header above."


def marked(ctx: indah.Context) -> indah.Component:
    ignored = indah.Signal(True)
    # Offsets count characters (Unicode code points); the last item is a label shown on hover.
    start = REQUEST.index("Ignore")
    marks = indah.Computed(
        lambda: (
            [(0, 9, "info", "the task")]
            + ([(start, len(REQUEST), "warn", "ignored")] if ignored.value else [])
        )
    )
    cell = {"component": "marked", "bind": {"runs": "runs"}}
    rows = [
        {"id": "a", "runs": indah.marked_runs("GET /v1/models 200", [(4, 14, "ok")])},
        {"id": "b", "runs": indah.marked_runs("POST /v1/chat 500", [(5, 13, "err", "failed")])},
    ]
    return indah.Column(
        children=[
            indah.Marked(REQUEST, marks, label="Request"),
            indah.Button(
                lambda: "Stop ignoring the header" if ignored.value else "Ignore the header",
                lambda: ignored.set(not ignored.value),
            ),
            indah.List(rows, key="id", item=cell),
            indah.Table(
                columns=[
                    indah.Col("id"),
                    indah.Col("runs", title="Request", kind="cell", render=cell),
                ],
                rows=rows,
                key="id",
            ),
        ]
    )


def barstrip_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    strip = page.get_by_role("group", name="Calls per minute")
    expect(strip).to_be_visible()
    bars = strip.locator(".barstrip-bar")
    expect(bars).to_have_count(24)
    page.wait_for_timeout(1300)  # a new minute arrives and the strip grows in place
    assert bars.count() >= 25
    bars.last.hover()
    expect(page.get_by_role("tooltip")).to_contain_text("hit")
    strip.focus()
    page.keyboard.press("Home")
    expect(page.get_by_role("tooltip")).to_contain_text("min ")
def marked_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    block = page.get_by_role("group", name="Request")
    expect(block.locator("mark")).to_have_count(2)
    # Selecting and copying gives back the plain text: the spans add no characters.
    assert block.inner_text() == REQUEST
    page.get_by_role("button", name="Stop ignoring the header").click()
    expect(block.locator("mark")).to_have_count(1)
    expect(page.locator(".list-item mark")).to_have_count(2)
    expect(page.locator("td mark")).to_have_count(2)


def stat(ctx: indah.Context) -> indah.Component:
    hour = indah.Signal(0)
    requests = [1200, 1340, 1105, 1580]
    errors = [12, 9, 31, 7]
    pick = lambda xs: xs[hour.value % len(xs)]  # noqa: E731
    delta = lambda xs: f"{xs[hour.value % len(xs)] - xs[(hour.value - 1) % len(xs)]:+d}"  # noqa: E731
    return indah.Column(
        children=[
            indah.Row(
                children=[
                    indah.Stat(
                        lambda: f"{pick(requests):,}",
                        label="Requests",
                        delta=lambda: delta(requests),
                    ),
                    indah.Stat(
                        lambda: pick(errors),
                        label="Errors",
                        delta=lambda: delta(errors),
                        help="Per hour",
                    ),
                ]
            ),
            indah.Button("Next hour", lambda: hour.set(hour.value + 1)),
        ]
    )


def stat_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("1,200")).to_be_visible()
    page.get_by_role("button", name="Next hour").click()
    expect(page.get_by_text("1,340")).to_be_visible()
    expect(page.get_by_text("+140")).to_be_visible()


# -- Keyed list ---------------------------------------------------------------------------------


def keyed_list(ctx: indah.Context) -> indah.Component:
    tasks = indah.Signal(
        [
            {"id": "t1", "title": "Write docs"},
            {"id": "t2", "title": "Ship it"},
        ]
    )
    nxt = {"n": 2}

    def on_item(key, event, value) -> None:  # sync or async; `key` is the row's id
        if event == "remove":
            tasks.set([t for t in tasks.value if t["id"] != key])
        elif event == "title":
            tasks.set([{**t, "title": value} if t["id"] == key else t for t in tasks.value])

    def add() -> None:
        nxt["n"] += 1
        tasks.set(
            [
                *tasks.value,
                {"id": f"t{nxt['n']}", "title": f"Task {nxt['n']}"},
            ]
        )

    return indah.Column(
        children=[
            indah.List(tasks, key="id", item=TASK_SPEC, on_item=on_item, empty="Nothing to do"),
            indah.Button("Add task", add, variant="tonal"),
            indah.Text(lambda: " | ".join(t["title"] for t in tasks.value) or "(empty)"),
        ]
    )


def keyed_list_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    first = page.get_by_role("textbox").first
    first.fill("Write the docs")
    expect(page.get_by_text("Write the docs | Ship it")).to_be_visible()
    page.get_by_role("button", name="Add task").click()
    expect(page.get_by_text("Write the docs | Ship it | Task 3")).to_be_visible()
    page.get_by_role("button", name="Remove").first.click()
    expect(page.get_by_text("Ship it | Task 3")).to_be_visible()
    expect(page.get_by_role("textbox")).to_have_count(2)


# -- JsonTree -----------------------------------------------------------------------------------


def json_tree(ctx: indah.Context) -> indah.Component:
    return indah.JsonTree(ENTRY, expanded=1, label="A cache entry")


def json_tree_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("gpt-4o")).to_be_visible()
    page.get_by_label("Search JSON").fill("refund")
    expect(page.get_by_text("What is the refund window?")).to_be_visible()  # opened to the match


# -- Diff ---------------------------------------------------------------------------------------


def diff(ctx: indah.Context) -> indah.Component:
    incoming = indah.Signal(json.dumps(INCOMING))
    return indah.Column(
        children=[
            indah.TextArea(incoming, label="Incoming (edit me)", rows=3),
            indah.Diff(CACHED, lambda: incoming.value, labels=("cached", "incoming")),
        ]
    )


def diff_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("14 days").first).to_be_visible()
    page.get_by_label("Incoming (edit me)").fill(json.dumps(CACHED))  # now identical
    expect(page.get_by_text("14 days")).to_have_count(0)


CHAPTER = Chapter(
    slug="data",
    title="Data",
    order=50,
    blurb=(
        "Tables for every size of data, plus the small display parts around them: stat tiles, "
        "keyed lists, and viewers for JSON and diffs."
    ),
    pages=[
        Page(
            slug="table-classic",
            title="Table: the classic form",
            summary="Pass rows, get a sortable, paged table. A click sets a signal with the row index.",
            build=table_classic,
            covers=("Table",),
            docs="components.md",
            adr=(21,),
            check=table_classic_check,
        ),
        Page(
            slug="table-rich",
            title="Table: typed columns",
            summary=(
                "Dict rows with a stable key and typed `Col`s: time, mono, badge, number. Try the "
                "filter box, the column menu and the density switch."
            ),
            build=table_rich,
            covers=("Table", "Col"),
            docs="dashboards.md",
            adr=(27,),
            check=table_rich_check,
        ),
        Page(
            slug="table-cells",
            title="Table: composite cells",
            summary=(
                'A `Col(kind="cell", render=...)` draws a cell from the row\'s fields (a meter, a '
                "two-line caller); `truncate=` clips a long prompt with a tooltip, `wrap=` lets a "
                "note wrap. Sort the Match column and search."
            ),
            build=table_cells,
            covers=("Col",),
            docs="dashboards.md",
            adr=(27,),
            check=table_cells_check,
        ),
        Page(
            slug="table-actions",
            title="Table: row actions and checkboxes",
            summary="A `RowAction` per row (this one asks first) and a `checked` signal for bulk work.",
            build=table_actions,
            covers=("Table", "RowAction"),
            docs="dashboards.md",
            adr=(27,),
            check=table_actions_check,
        ),
        Page(
            slug="table-remote",
            title="Table: 5,000 rows, remote and virtual",
            summary=(
                "The table holds no rows: it asks a loader for the window in view, with the "
                "search and sort. Scroll, sort, filter, then use Select all."
            ),
            build=table_remote,
            covers=("Table", "TableQuery", "Col"),
            docs="dashboards.md",
            adr=(27,),
            check=table_remote_check,
        ),
        Page(
            slug="table-keyboard",
            title="Table: keyboard navigation",
            summary=(
                "Tab into the table, then j/k or the arrows move the active row, Home/End jump, "
                "Space ticks, Enter opens (`on_open=`). The `j` below is also a `Shortcuts` key: "
                "it moves the row while the table has focus and rings the bell anywhere else."
            ),
            build=table_keyboard,
            covers=("Table", "Shortcuts"),
            docs="dashboards.md",
            adr=(27, 30),
            check=table_keyboard_check,
        ),
        Page(
            slug="table-follow",
            title="Table: follow a Stream",
            summary=(
                "A `Stream` sends only new rows and keeps the newest `limit`. The table follows "
                "the tail; scroll up and it pauses."
            ),
            build=table_follow,
            covers=("Table", "Stream"),
            docs="dashboards.md",
            adr=(26,),
            check=table_follow_check,
        ),
        Page(
            slug="dataframe",
            title="DataFrame",
            summary="The plain display table: a pandas frame, a dict or a list of rows, in a signal.",
            build=dataframe,
            covers=("DataFrame", "Slider"),
            docs="components.md",
            check=dataframe_check,
        ),
        Page(
            slug="empty-code",
            title="Empty state and Code",
            summary=(
                "`Empty(title, body, action=, children=)` says what to do when there is nothing "
                "yet. `Code(text, language=, copy=True)` is a read-only block whose Copy button "
                "puts the plain text on the clipboard and shows a toast."
            ),
            build=empty_and_code,
            covers=("Empty", "Code", "Button"),
            docs="components.md",
            check=empty_and_code_check,
        ),
        Page(
            slug="barstrip",
            title="Activity strip",
            summary=(
                "`BarStrip(series, tones=, names=, labels=)`: one bar per interval, stacked when a "
                "bar is a tuple. It updates in place as minutes arrive. Hover a bar, or focus the "
                "strip and use the arrow keys, to read it."
            ),
            build=barstrip,
            covers=("BarStrip", "Text"),
            docs="components.md",
            check=barstrip_check,
        ),
        Page(
            slug="marked",
            title="Marked text",
            summary=(
                "`Marked(text, marks=[(start, end, tone)])` shades spans of a text, for the part "
                "that is ignored or flagged. The spans add no characters, so copying gives back "
                "the plain text, and each tone has its own underline as well as its colour. In a "
                "list item or a table cell, put `marked_runs(text, marks)` in a field and name "
                '`{"component": "marked"}` in the render spec.'
            ),
            build=marked,
            covers=("Marked", "marked_runs", "List", "Table", "Col", "Button"),
            docs="components.md",
            adr=(16,),
            check=marked_check,
        ),
        Page(
            slug="stat",
            title="Stat tiles",
            summary="A big value with a label and a delta (green if it does not start with `-`).",
            build=stat,
            covers=("Stat",),
            docs="components.md",
            adr=(21,),
            check=stat_check,
        ),
        Page(
            slug="list",
            title="Keyed, editable lists",
            summary=(
                "`List(key=, on_item=)`: rows keep their place and the cursor while you type, "
                "add or remove. Each row is a small render spec."
            ),
            build=keyed_list,
            covers=("List",),
            docs="dashboards.md",
            adr=(16,),
            check=keyed_list_check,
        ),
        Page(
            slug="json-tree",
            title="JSON tree",
            summary="A collapsible viewer with search and copy-path. Search opens the way to a match.",
            build=json_tree,
            covers=("JsonTree",),
            docs="dashboards.md",
            adr=(28,),
            check=json_tree_check,
        ),
        Page(
            slug="diff",
            title="Diff",
            summary="Two documents side by side; key order and formatting never show as changes.",
            build=diff,
            covers=("Diff", "TextArea"),
            docs="dashboards.md",
            adr=(28,),
            check=diff_check,
        ),
    ],
)

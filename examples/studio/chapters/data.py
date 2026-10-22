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

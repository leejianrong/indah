"""Support desk: a small internal tool with real pages, in one Python file.

Four pages with their own addresses: an **Inbox** of tickets, a **ticket** page (change its status
or assignee, add a note), **Reports** (charts of the same tickets) and **Settings**. A link
pasted into a new tab opens the same page, and the browser's Back button works.

What it shows off:
- ``Router`` + ``Link`` + ``ctx.params`` + ``ctx.navigate`` with ``spa=True`` (see
  ``examples/semula_routes.py`` for the same machinery under a parent app);
- one shared state, the ticket list, read by three pages, so a change on the ticket page shows up
  in the Inbox and the charts at once, with no refresh and no save button;
- a ``Table`` whose row click opens a page, a ``Select`` bound to a field of the open ticket,
  charts and ``Stat`` cards computed from the same list, and an undo in a toast.

The tickets are made up, generated from a fixed seed, and live in this visitor's session only
(``session_factory``): nobody else sees your edits, and *Reset the demo* puts them back.

Run it with:  python examples/support_desk.py   (prints a URL; open it and click around).
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

import indah

STATUSES = ["open", "pending", "resolved"]
PRIORITIES = ["low", "normal", "urgent"]
AGENTS = ["Unassigned", "Maya", "Jonas", "Priya", "Tomas"]
STATUS_TONES = {"open": "err", "pending": "warn", "resolved": "ok"}
PRIORITY_TONES = {"urgent": "err", "normal": "info", "low": "neutral"}
SUBJECTS = [
    "Cannot reset my password",
    "Invoice shows the wrong amount",
    "Export to CSV is empty",
    "App is slow after the update",
    "How do I add a teammate?",
    "Refund for a duplicate charge",
    "Dashboard will not load",
    "Two-factor code never arrives",
    "Change the billing email",
    "Feature request: dark mode",
    "Webhook returns a 500",
    "Cancel my subscription",
]
MAX_NOTE = 300


def make_tickets(n: int = 24, seed: int = 11) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    tickets = []
    for i in range(n):
        tickets.append(
            {
                "id": f"T-{1001 + i}",
                "subject": SUBJECTS[i % len(SUBJECTS)],
                "status": rng.choices(STATUSES, weights=[5, 3, 4])[0],
                "priority": rng.choices(PRIORITIES, weights=[3, 6, 2])[0],
                "assignee": rng.choice(AGENTS),
                "age_days": rng.randint(0, 14),
                "notes": [],
            }
        )
    return tickets


def counts(tickets: list[dict[str, Any]], field: str, order: list[str]) -> list[list]:
    seen = Counter(t[field] for t in tickets)
    return [[name, seen.get(name, 0)] for name in order]


def build(ctx: indah.Context) -> indah.Session:
    tickets: indah.Signal[list[dict[str, Any]]] = indah.Signal(make_tickets())
    ticket_id = indah.computed(lambda: ctx.params.value.get("ticket_id"))
    ticket = indah.computed(
        lambda: next((t for t in tickets.value if t["id"] == ticket_id.value), None)
    )

    def change(tid: str, **fields: Any) -> None:
        tickets.set([{**t, **fields} if t["id"] == tid else t for t in tickets.value])

    # ---- inbox -------------------------------------------------------------------------
    picked: indah.Signal[Any] = indah.Signal(None)
    show = indah.Signal("open")

    def inbox_rows() -> list[dict[str, Any]]:
        rows = tickets.value
        if show.value != "all":
            rows = [t for t in rows if t["status"] == show.value]
        return [{k: v for k, v in t.items() if k != "notes"} for t in rows]

    def open_picked() -> None:
        if picked.value is not None:
            ctx.navigate(f"/tickets/{picked.value}")
            picked.set(None)

    indah.effect(open_picked)

    def stat(label: str, fn) -> indah.Component:
        return indah.Stat(value=lambda: str(fn(tickets.value)), label=label)

    inbox = indah.Column(
        children=[
            indah.Text("# Inbox", markdown=True),
            indah.Row(
                children=[
                    stat("Open", lambda ts: sum(t["status"] == "open" for t in ts)),
                    stat(
                        "Urgent and open",
                        lambda ts: sum(
                            t["status"] == "open" and t["priority"] == "urgent" for t in ts
                        ),
                    ),
                    stat("Unassigned", lambda ts: sum(t["assignee"] == "Unassigned" for t in ts)),
                ]
            ),
            indah.Radio(show, options=["open", "pending", "resolved", "all"], label="Show"),
            indah.Table(
                rows=inbox_rows,
                key="id",
                selected=picked,
                search=True,
                height="24rem",
                columns=[
                    indah.Col("id", "Ticket", kind="mono", width="9ch"),
                    indah.Col("subject", "Subject"),
                    indah.Col("status", "Status", kind="badge", tones=STATUS_TONES),
                    indah.Col("priority", "Priority", kind="badge", tones=PRIORITY_TONES),
                    indah.Col("assignee", "Assignee"),
                    indah.Col("age_days", "Age (days)", kind="number", sortable=True),
                ],
            ),
        ]
    )

    # ---- one ticket --------------------------------------------------------------------
    status = indah.Signal("open")
    assignee = indah.Signal("Unassigned")
    draft = indah.Signal("")

    def sync_from_ticket() -> None:
        t = ticket.value
        if t is not None:
            if status.peek() != t["status"]:
                status.set(t["status"])
            if assignee.peek() != t["assignee"]:
                assignee.set(t["assignee"])

    def status_to_ticket() -> None:
        value, t = status.value, ticket.peek()
        if t is not None and t["status"] != value:
            change(t["id"], status=value)

    def assignee_to_ticket() -> None:
        value, t = assignee.value, ticket.peek()
        if t is not None and t["assignee"] != value:
            change(t["id"], assignee=value)

    indah.effect(sync_from_ticket)
    indah.effect(status_to_ticket)
    indah.effect(assignee_to_ticket)

    def add_note() -> None:
        text, t = draft.value.strip()[:MAX_NOTE], ticket.value
        if not text or t is None:
            return
        change(t["id"], notes=[*t["notes"], text])
        draft.set("")
        ctx.toast("Note added.", kind="success")

    def heading() -> str:
        t = ticket.value
        if t is None:
            return f"### No ticket `{ticket_id.value}`"
        age = f"open {t['age_days']} days"
        return f"### {t['id']}: {t['subject']}\n\n**Priority** {t['priority']}, {age}"

    def note_items() -> list[dict[str, str]]:
        t = ticket.value
        return [{"id": str(i), "text": n} for i, n in enumerate(t["notes"])] if t else []

    ticket_page = indah.Column(
        children=[
            indah.Link(ctx, "Back to the inbox", to="/"),
            indah.Card(
                children=[
                    indah.Text(heading, markdown=True),
                    indah.Row(
                        children=[
                            indah.Select(status, options=STATUSES, label="Status"),
                            indah.Select(assignee, options=AGENTS, label="Assignee"),
                        ]
                    ),
                ]
            ),
            indah.Card(
                title="Notes",
                children=[
                    indah.List(
                        note_items,
                        item={"tag": "p", "text": "text"},
                        key="id",
                        empty="No notes yet.",
                    ),
                    indah.TextInput(draft, placeholder="Add a note", on_submit=add_note),
                    indah.Button("Add note", on_click=add_note),
                ],
            ),
        ]
    )

    # ---- reports -----------------------------------------------------------------------
    reports = indah.Column(
        children=[
            indah.Text("# Reports", markdown=True),
            indah.Chart(
                lambda: counts(tickets.value, "status", STATUSES),
                series=[{"label": "tickets", "kind": "bars", "stroke": "var(--primary)"}],
                title="Tickets by status",
                x_scale="category",
                y_range=(0, 25),
                legend="off",
                height=220,
            ),
            indah.Chart(
                lambda: counts(
                    [t for t in tickets.value if t["status"] != "resolved"], "assignee", AGENTS
                ),
                series=[{"label": "not resolved", "kind": "bars", "stroke": "var(--primary)"}],
                title="Work waiting on each person",
                x_scale="category",
                y_range=(0, 25),
                legend="off",
                height=220,
            ),
        ]
    )

    # ---- settings ----------------------------------------------------------------------
    email_urgent = indah.Signal(True)

    def reset() -> None:
        before = tickets.value
        tickets.set(make_tickets())
        ctx.toast(
            "The demo data was reset.",
            kind="info",
            ttl=8,
            action=("Undo", lambda: tickets.set(before)),
        )

    settings = indah.Column(
        children=[
            indah.Text("# Settings", markdown=True),
            indah.Card(
                children=[
                    indah.Checkbox(email_urgent, label="Email me when a ticket turns urgent"),
                    indah.Text(
                        "_This switch does nothing here: it is a place to put a form._",
                        markdown=True,
                    ),
                ]
            ),
            indah.Card(
                title="Demo data",
                children=[
                    indah.Text("Your edits live in this tab only. Reset puts the tickets back."),
                    indah.Button("Reset the demo", on_click=reset, variant="tonal"),
                ],
            ),
        ]
    )

    # ---- shell -------------------------------------------------------------------------
    nav = indah.Column(
        children=[
            indah.Text("**Support desk**", markdown=True),
            indah.Link(ctx, "Inbox", to="/"),
            indah.Link(ctx, "Reports", to="/reports"),
            indah.Link(ctx, "Settings", to="/settings"),
        ]
    )
    pages = indah.Router(
        ctx,
        routes={
            "/": inbox,
            "/tickets/{ticket_id}": ticket_page,
            "/reports": reports,
            "/settings": settings,
        },
        not_found=indah.Column(
            children=[
                indah.Text("# 404", markdown=True),
                indah.Text("There is no page at this address."),
                indah.Link(ctx, "Go to the inbox", to="/"),
            ]
        ),
    )
    return indah.Session(indah.Sidebar(children=[nav, pages]))


app = indah.create_app(session_factory=build, title="Support desk", spa=True)

if __name__ == "__main__":
    indah.launch(app)

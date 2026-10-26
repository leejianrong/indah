"""Expense tracker: a small ledger that survives a reload, built on ``ctx.persist``.

Add an expense (description, amount, category), see the entries in a ``Table`` with a
delete button per row, the total, a per-category ``BarStrip`` and a running-total
``Chart``. "Clear all" asks first, in a ``Modal``.

The point is **restorable sessions** (0.9.0): the list of expenses is one ``Signal`` that
``ctx.persist("expenses", ...)`` saves to the app's *state store* and puts back when the
tab's session is rebuilt, before the first paint. Reload the page and your rows are still
there. Run it with a durable store and they also survive a restart of the process::

    create_app(session_factory=build, state_store="sqlite:///state.db")

The default store is in memory, which is what the public gallery uses: the data lives for
the visit only, is private to your tab, and is not shared or stored for good.

Only plain JSON is persisted, and it is bounded: at most 50 rows, 40 characters of
description, amounts from 0.01 to 100,000 (the saved value stays far below the 16 KB cap).
A restored value is checked again, so a damaged one falls back to the sample rows.

Run it with:  python examples/expenses.py   (prints a URL; embeds inline in a cell).
"""

from __future__ import annotations

import math
from typing import Any

import indah

CATEGORIES = ["Food", "Transport", "Home", "Fun", "Other"]
MAX_ROWS = 50
MAX_DESCRIPTION = 40
MIN_AMOUNT = 0.01
MAX_AMOUNT = 100_000.0

SAMPLE: list[dict[str, Any]] = [
    {"id": 1, "description": "Groceries", "amount": 62.40, "category": "Food"},
    {"id": 2, "description": "Train pass", "amount": 38.00, "category": "Transport"},
    {"id": 3, "description": "Electricity", "amount": 74.15, "category": "Home"},
    {"id": 4, "description": "Cinema", "amount": 24.50, "category": "Fun"},
    {"id": 5, "description": "Lunch with Mei", "amount": 18.90, "category": "Food"},
    {"id": 6, "description": "Bus top-up", "amount": 15.00, "category": "Transport"},
]


def parse_amount(raw: Any) -> float | None:
    """A valid amount rounded to cents, or ``None`` (not a number, out of range)."""
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    value = round(value, 2)
    return value if MIN_AMOUNT <= value <= MAX_AMOUNT else None


def add_expense(
    rows: list[dict[str, Any]], description: Any, amount: Any, category: Any
) -> tuple[list[dict[str, Any]], str]:
    """``(new rows, "")`` on success, or ``(rows unchanged, the reason)``."""
    text = " ".join(str(description or "").split())
    if not text:
        return rows, "Give the expense a description."
    if len(text) > MAX_DESCRIPTION:
        return rows, f"Keep the description to {MAX_DESCRIPTION} characters."
    value = parse_amount(amount)
    if value is None:
        return rows, f"The amount must be between {MIN_AMOUNT:.2f} and {MAX_AMOUNT:,.0f}."
    if category not in CATEGORIES:
        return rows, "Pick one of the categories."
    if len(rows) >= MAX_ROWS:
        return rows, f"This demo keeps at most {MAX_ROWS} expenses. Delete one first."
    new_id = max((r["id"] for r in rows), default=0) + 1
    row = {"id": new_id, "description": text, "amount": value, "category": category}
    return [*rows, row], ""


def delete_expense(rows: list[dict[str, Any]], key: Any) -> list[dict[str, Any]]:
    return [r for r in rows if r["id"] != key]


def total(rows: list[dict[str, Any]]) -> float:
    return round(sum(r["amount"] for r in rows), 2)


def totals_by_category(rows: list[dict[str, Any]]) -> list[float]:
    """One total per entry of ``CATEGORIES``, in that order."""
    return [round(sum(r["amount"] for r in rows if r["category"] == c), 2) for c in CATEGORIES]


def running_total(rows: list[dict[str, Any]]) -> list[list[float]]:
    """Chart rows ``[entry number, spent so far]``; a lone origin point when empty."""
    out: list[list[float]] = [[0, 0.0]]
    spent = 0.0
    for i, row in enumerate(rows, start=1):
        spent = round(spent + row["amount"], 2)
        out.append([i, spent])
    return out


def valid_rows(value: Any) -> bool:
    """Veto a restored value that is not a list of well-formed, in-bounds rows."""
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        return False
    seen: set[Any] = set()
    for r in value:
        if not isinstance(r, dict) or set(r) != {"id", "description", "amount", "category"}:
            return False
        if not isinstance(r["id"], int) or isinstance(r["id"], bool) or r["id"] in seen:
            return False
        seen.add(r["id"])
        if (
            not isinstance(r["description"], str)
            or not 0 < len(r["description"]) <= MAX_DESCRIPTION
        ):
            return False
        if parse_amount(r["amount"]) is None or r["category"] not in CATEGORIES:
            return False
    return True


def build(ctx: indah.Context) -> indah.Session:
    rows = indah.Signal([dict(r) for r in SAMPLE])
    ctx.persist("expenses", rows, validate=valid_rows)  # restored now, saved on every change

    description = indah.Signal("")
    amount = indah.Signal(0.0)
    category = indah.Signal(CATEGORIES[0])
    message = indah.Signal("")
    confirming = indah.Signal(False)

    def on_add() -> None:
        updated, problem = add_expense(rows.value, description.value, amount.value, category.value)
        message.set(problem)
        if not problem:
            rows.set(updated)
            description.set("")
            amount.set(0.0)

    def on_delete(key: Any) -> None:  # a stale key (already deleted) is simply a no-op
        rows.set(delete_expense(rows.value, key))
        message.set("")

    def on_clear() -> None:
        rows.set([])
        message.set("")
        confirming.set(False)

    form = indah.Card(
        title="Add an expense",
        children=[
            indah.TextInput(description, placeholder="e.g. Coffee", label="Description"),
            indah.Number(amount, min=0, max=MAX_AMOUNT, step=0.5, label="Amount"),
            indah.Select(category, options=CATEGORIES, label="Category"),
            indah.Button("Add expense", on_click=on_add),
            indah.Text(lambda: message.value),
        ],
    )

    table = indah.Table(
        rows=lambda: rows.value,
        key="id",
        columns=[
            indah.Col("description", "Description"),
            indah.Col("category", "Category", kind="badge"),
            indah.Col("amount", "Amount", kind="number"),
        ],
        actions=[indah.RowAction("Delete", on_delete)],
        height="20rem",
        label="Expenses",
    )

    summary = indah.Grid(
        columns=2,
        children=[
            indah.Stat(lambda: f"{total(rows.value):,.2f}", label="Total spent"),
            indah.Stat(lambda: str(len(rows.value)), label=f"Entries (max {MAX_ROWS})"),
        ],
    )
    by_category = indah.BarStrip(
        lambda: totals_by_category(rows.value),
        labels=CATEGORIES,
        height=96,
        label="Spending by category",
    )
    category_table = indah.Table(
        rows=lambda: [
            {"category": c, "total": t}
            for c, t in zip(CATEGORIES, totals_by_category(rows.value), strict=True)
        ],
        key="category",
        columns=[indah.Col("category", "Category"), indah.Col("total", "Total", kind="number")],
    )
    running = indah.Chart(
        lambda: running_total(rows.value),
        series=["Spent so far"],
        title="Running total",
        x_label="Entry",
        y_label="Total",
        height=200,
    )

    confirm = indah.Modal(
        title="Clear all expenses?",
        open=confirming,
        size="sm",
        children=[
            indah.Text("This removes every row from this visit. It cannot be undone."),
            indah.Row(
                children=[
                    indah.Button("Clear all", on_click=on_clear),
                    indah.Button("Keep them", lambda: confirming.set(False), variant="ghost"),
                ]
            ),
        ],
    )

    intro = indah.Text(
        "# Expense tracker\n\n"
        "Add a few expenses, then **reload the page**: your list comes back, because the app "
        "saves it with `ctx.persist` and restores it when the session is rebuilt. "
        "Here the state lives in memory, for this visit only: it is private to your tab, not "
        "shared with anyone and not stored for good. A self-hosted app can pass "
        '`state_store="sqlite:///state.db"` to keep it across restarts too. '
        f"The demo is bounded to {MAX_ROWS} entries.",
        markdown=True,
    )
    left = indah.Column(
        children=[
            form,
            indah.Button("Clear all", lambda: confirming.set(True), variant="ghost"),
        ]
    )
    right = indah.Column(
        children=[
            indah.Card(children=[summary]),
            indah.Card(children=[table]),
            indah.Card(title="By category", children=[by_category, category_table]),
            indah.Card(children=[running]),
        ]
    )
    return indah.Session(
        indah.Column(children=[intro, indah.Sidebar(children=[left, right]), confirm])
    )


app = indah.create_app(session_factory=build)

if __name__ == "__main__":
    indah.launch(app)

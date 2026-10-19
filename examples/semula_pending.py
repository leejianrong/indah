"""A semula-shaped pending queue: parked calls that a human releases from a drawer.

semula can hold a call until someone answers it. This demo stands in for that: a
background task "parks" fake calls (each one waits on an ``asyncio.Event``) and every
open tab shows the same live queue. Review one in a drawer, write a reply, and Submit:
the parked call is released, a toast confirms it, and the row disappears in *every* tab.

    python examples/semula_pending.py        # prints a URL; open /ui/ in two tabs

Keyboard: ``j``/``k`` move the cursor, ``Enter`` opens the drawer, ``a`` approves and
``r`` rejects the cursor row (``?`` lists them). Tick rows to approve in bulk.

What it shows (IND-E21): ``Drawer`` + ``TextArea``, ``Button(confirm=)``, ``ctx.toast``,
``Badge``, ``Shortcuts``, and ``Table`` row actions and multi-select, all fed by one
app-level ``Topic`` so the queue stays in step across tabs.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import indah

PROJECTS = ["support-bot", "docs-qa", "code-review", "eval-suite"]
SNIPPETS = [
    "Summarise this ticket in two sentences.",
    "What is our refund policy for annual plans?",
    "Write a unit test for parse_date().",
    "Translate the following paragraph into French.",
    "List the action items from this meeting.",
]
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def make_id(rng: random.Random) -> str:
    return "".join(rng.choice(_CROCKFORD) for _ in range(26))


def fake_call(rng: random.Random) -> dict[str, Any]:
    return {
        "id": make_id(rng),
        "ts": int(time.time() * 1000),
        "project": rng.choice(PROJECTS),
        "snippet": rng.choice(SNIPPETS),
    }


@dataclass
class Parked:
    call: dict[str, Any]
    event: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: str = ""  # "released" or "rejected" once resolved
    reply: str = ""


class PendingQueue:
    """The parked calls, in arrival order. Every change publishes the whole pending
    list (small by design) on ``topic``, so each tab's ``ctx.latest`` follows it."""

    def __init__(self) -> None:
        self.topic: indah.Topic[list[dict[str, Any]]] = indah.Topic("pending", replay=1)
        self._items: dict[str, Parked] = {}
        self.resolved: list[Parked] = []

    def snapshot(self) -> list[dict[str, Any]]:
        return [p.call for p in self._items.values()]

    def __len__(self) -> int:
        return len(self._items)

    def park(self, call: dict[str, Any]) -> Parked:
        parked = Parked(call)
        self._items[call["id"]] = parked
        self.topic.publish(self.snapshot())
        return parked

    def resolve(self, call_id: str, outcome: str, reply: str = "") -> bool:
        """Release or reject a parked call. False if it is already gone (another tab
        got there first), so a stale click is harmless."""
        parked = self._items.pop(call_id, None)
        if parked is None:
            return False
        parked.outcome, parked.reply = outcome, reply
        self.resolved.append(parked)
        parked.event.set()  # wakes the task holding the call
        self.topic.publish(self.snapshot())
        return True


async def hold(parked: Parked) -> None:
    """Stand-in for a parked HTTP call: wait until a human answers."""
    await parked.event.wait()


async def produce(
    queue: PendingQueue, *, rate: float, max_pending: int, seed: int | None = None
) -> None:
    rng = random.Random(seed)
    holders: set[asyncio.Task[None]] = set()
    try:
        while True:
            if len(queue) < max_pending:
                task = asyncio.create_task(hold(queue.park(fake_call(rng))))
                holders.add(task)
                task.add_done_callback(holders.discard)
            await asyncio.sleep(rng.expovariate(rate))
    finally:
        for task in holders:
            task.cancel()


def _detail(call: dict[str, Any] | None) -> str:
    if call is None:
        return "This call was already handled."
    return f"- **id** `{call['id']}`\n- **project** {call['project']}\n\n> {call['snippet']}"


def build_pending_app(queue: PendingQueue) -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        pending = ctx.latest(queue.topic, initial=queue.snapshot())

        def rows() -> list[dict[str, Any]]:
            return pending.value or []

        cursor: indah.Signal[Any] = indah.Signal(None)  # the highlighted row's id
        checked: indah.Signal[list[Any]] = indah.Signal([])
        drawer_open = indah.Signal(False)
        reply = indah.Signal("")

        def by_id(call_id: Any) -> dict[str, Any] | None:
            return next((r for r in rows() if r["id"] == call_id), None)

        def settle() -> None:
            # A row resolved anywhere leaves this tab's cursor, ticks and drawer.
            ids = {r["id"] for r in rows()}
            if cursor.value is not None and cursor.value not in ids:
                cursor.set(None)
                drawer_open.set(False)
            if any(k not in ids for k in checked.value):
                checked.set([k for k in checked.value if k in ids])

        indah.effect(settle)

        def release(call_id: Any, text: str = "") -> None:
            if queue.resolve(call_id, "released", text or "Approved"):
                ctx.toast(f"Released {str(call_id)[:8]}", kind="success")
            else:
                ctx.toast("Already handled in another tab", kind="warn")

        def reject(call_id: Any) -> None:
            if queue.resolve(call_id, "rejected"):
                ctx.toast(f"Rejected {str(call_id)[:8]}", kind="info")
            else:
                ctx.toast("Already handled in another tab", kind="warn")

        def open_drawer(call_id: Any = None) -> None:
            if call_id is not None:
                cursor.set(call_id)
            if cursor.value is not None and by_id(cursor.value) is not None:
                reply.set("")
                drawer_open.set(True)

        def step(delta: int) -> None:
            ids = [r["id"] for r in rows()]
            if not ids:
                return
            at = ids.index(cursor.value) if cursor.value in ids else -1
            cursor.set(ids[max(0, min(len(ids) - 1, at + delta))])

        def approve_cursor() -> None:
            if cursor.value is not None:
                release(cursor.value)

        def reject_cursor() -> None:
            if cursor.value is not None:
                reject(cursor.value)

        def reject_and_close() -> None:
            reject_cursor()
            drawer_open.set(False)

        def submit() -> None:
            if cursor.value is not None:
                release(cursor.value, reply.value)
                drawer_open.set(False)

        def approve_checked() -> None:
            for call_id in list(checked.value):
                release(call_id)

        count = indah.computed(lambda: len(rows()))
        return indah.Session(
            indah.Column(
                children=[
                    indah.Shortcuts(
                        {
                            "j": (lambda: step(1), "Next call"),
                            "k": (lambda: step(-1), "Previous call"),
                            "enter": (open_drawer, "Review the call"),
                            "a": (approve_cursor, "Approve"),
                            "r": (reject_cursor, "Reject"),
                        }
                    ),
                    indah.Row(
                        children=[
                            indah.Text("# Pending calls", markdown=True),
                            indah.Badge(
                                lambda: f"{count.value} waiting",
                                tone="warn" if count.value else "ok",
                            ),
                            indah.Button(
                                "Approve checked",
                                approve_checked,
                                variant="tonal",
                                tooltip="Release every ticked call",
                            ),
                        ],
                        align="center",
                    ),
                    indah.Table(
                        rows=rows,
                        key="id",
                        selected=cursor,
                        checked=checked,
                        height="22rem",
                        columns=[
                            indah.Col("ts", title="Parked", kind="time", width="9ch"),
                            indah.Col("id", kind="mono", width="14ch"),
                            indah.Col("project"),
                            indah.Col("snippet"),
                        ],
                        actions=[
                            indah.RowAction("Review", open_drawer, variant="tonal"),
                            indah.RowAction("Reject", reject, confirm="Reject this call?"),
                        ],
                    ),
                    indah.Drawer(
                        title="Review call",
                        open=drawer_open,
                        children=[
                            indah.Text(lambda: _detail(by_id(cursor.value)), markdown=True),
                            indah.TextArea(reply, label="Reply", rows=5),
                            indah.Row(
                                children=[
                                    indah.Button("Submit", submit),
                                    indah.Button(
                                        "Reject",
                                        reject_and_close,
                                        variant="ghost",
                                        confirm="Reject this call?",
                                    ),
                                ]
                            ),
                        ],
                    ),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="semula",
        theme=indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}),
        spa=True,
        proxy_flush=False,
    )


def build_app(*, rate: float = 1.0, max_pending: int = 12, seed: int | None = None) -> Starlette:
    """A semula-shaped parent app: ``/v1/health``, the dashboard at ``/ui`` and a
    lifespan that keeps parking fake calls."""
    queue = PendingQueue()
    ui = build_pending_app(queue)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(produce(queue, rate=rate, max_pending=max_pending, seed=seed))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "pending": len(queue)})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("ui/")

    app = Starlette(
        routes=[Route("/", root), Route("/v1/health", health), Mount("/ui", app=ui)],
        lifespan=lifespan,
    )
    app.state.queue = queue
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

"""A semula-shaped live request log: a fake LLM-cache server's calls, live in every tab.

semula is a local fake-LLM server; its dashboard is mounted as an indah sub-app under
``/ui`` and shows calls as they arrive (hit or miss, which matching tier, score,
latency). This demo stands in for semula: a background task publishes fake calls to a
``Topic`` and every open tab follows it with ``ctx.tail``, so each tab shows the same
live rows while its own selection stays its own.

    python examples/semula_log.py            # prints a URL; open /ui/ in two tabs

What it shows (IND-E20): ``Topic`` + ``ctx.tail`` (push to every tab), a ``Stream``-fed
rich ``Table`` (keyed rows, badge / mono / relative-time / number cells, sticky header,
client search, column toggle, follow-the-tail) and the ``/ui`` mount under a parent app
with its own lifespan, like semula's.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import indah

TIERS = ["exact", "normalised", "bm25", "embedding", "miss"]
TIER_WEIGHTS = [0.35, 0.2, 0.2, 0.1, 0.15]
PROJECTS = ["support-bot", "docs-qa", "code-review", "eval-suite"]
SNIPPETS = [
    "Summarise this ticket in two sentences.",
    "What is our refund policy for annual plans?",
    "Write a unit test for parse_date().",
    "Translate the following paragraph into French.",
    "List the action items from this meeting.",
    "Explain the difference between a mutex and a semaphore.",
]
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

TONES_RESULT = {"hit": "ok", "miss": "warn"}
TONES_TIER = {
    "exact": "ok",
    "normalised": "ok",
    "bm25": "info",
    "embedding": "info",
    "miss": "warn",
}


def make_ulid(ts_ms: int, rng: random.Random) -> str:
    """A 26-character, time-ordered, ULID-shaped id (10 time + 16 random Crockford chars)."""
    t = ts_ms
    head = ""
    for _ in range(10):
        head = _CROCKFORD[t % 32] + head
        t //= 32
    return head + "".join(rng.choice(_CROCKFORD) for _ in range(16))


def fake_call(rng: random.Random, now_ms: int | None = None) -> dict[str, Any]:
    """One fake cache lookup, shaped like a semula request-log row."""
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    tier = rng.choices(TIERS, TIER_WEIGHTS)[0]
    hit = tier != "miss"
    return {
        "id": make_ulid(ts, rng),
        "ts": ts,
        "project": rng.choice(PROJECTS),
        "tier": tier,
        "result": "hit" if hit else "miss",
        "score": round(rng.uniform(0.82, 1.0), 3) if hit else round(rng.uniform(0.1, 0.55), 3),
        "latency_ms": round(rng.uniform(1, 9) if hit else rng.uniform(900, 2400)),
        "snippet": rng.choice(SNIPPETS),
    }


async def produce(topic: indah.Topic, *, rate: float, seed: int | None = None) -> None:
    """Publish ``rate`` fake calls a second, forever (until cancelled)."""
    rng = random.Random(seed)
    while True:
        topic.publish(fake_call(rng))
        await asyncio.sleep(rng.expovariate(rate))  # Poisson-ish arrivals


def _detail(row: dict[str, Any] | None) -> str:
    if row is None:
        return "Select a row to see the call."
    return (
        f"### {row['result'].upper()} via {row['tier']}\n\n"
        f"- **id** `{row['id']}`\n- **project** {row['project']}\n"
        f"- **score** {row['score']}  -  **latency** {row['latency_ms']} ms\n\n"
        f"> {row['snippet']}"
    )


def build_log_app(topic: indah.Topic, *, limit: int = 1000) -> Any:
    """The dashboard: one live log per tab, all fed by ``topic``."""

    def build(ctx: indah.Context) -> indah.Session:
        rows = ctx.tail(topic, limit=limit)
        picked: indah.Signal[Any] = indah.Signal(None)
        # The selected call, remembered: a busy log trims old rows from the tail, and the
        # panel should keep showing the call the viewer clicked after it scrolls away.
        remembered: dict[str, dict[str, Any]] = {}

        def selected_row() -> dict[str, Any] | None:
            row = next((r for r in rows.value if r["id"] == picked.value), None)
            if row is not None:
                remembered.clear()
                remembered[row["id"]] = row
            return remembered.get(picked.value)

        # A computed notifies its readers only when the text changes, so the panel does
        # not re-send a patch for every row that streams in.
        detail = indah.computed(lambda: _detail(selected_row()))
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("# Live request log", markdown=True),
                    indah.Table(
                        rows=rows,
                        key="id",
                        selected=picked,
                        height="24rem",
                        search=True,
                        column_toggle=True,
                        follow=True,
                        columns=[
                            indah.Col("ts", title="When", kind="time", width="9ch"),
                            indah.Col("id", kind="mono", width="14ch"),
                            indah.Col("project"),
                            indah.Col("tier", kind="badge", tones=TONES_TIER),
                            indah.Col("result", kind="badge", tones=TONES_RESULT),
                            indah.Col("score", kind="number"),
                            indah.Col("latency_ms", title="ms", kind="number"),
                            indah.Col("snippet"),
                        ],
                    ),
                    indah.Card(
                        title="Call", children=[indah.Text(lambda: detail.value, markdown=True)]
                    ),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="semula",
        theme=indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}),
        spa=True,
        # A local container has no window-buffering proxy; pad only if you need to.
        proxy_flush=False,
    )


def build_app(*, rate: float = 8.0, limit: int = 1000, seed: int | None = None) -> Starlette:
    """A semula-shaped parent app: a JSON ``/v1`` route, the dashboard mounted at
    ``/ui``, and a lifespan that runs the producer, as semula's core would."""
    topic: indah.Topic = indah.Topic("requests", replay=limit)
    ui = build_log_app(topic, limit=limit)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(produce(topic, rate=rate, seed=seed))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "subscribers": topic.subscriber_count})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("ui/")

    app = Starlette(
        routes=[Route("/", root), Route("/v1/health", health), Mount("/ui", app=ui)],
        lifespan=lifespan,
    )
    app.state.topic = topic
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app(rate=20.0))

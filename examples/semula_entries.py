"""A semula-shaped entries browser: 20,000 cached entries, searched and sorted by SQLite.

semula keeps its cached answers in a database; this demo stands in for that store. The
table never holds more than the rows in view: the shell asks for windows as you scroll, the
loader runs ``SELECT ... LIMIT/OFFSET`` in a worker thread, and the scrollbar is sized from
``COUNT(*)``. Pick a project, search, sort by hits, click a row to preview it beside the
table (a drawer on a phone), pin it, and flip the density.

    python examples/semula_entries.py        # prints a URL; open /ui/

What it shows (IND-E22): ``Table(remote=, virtual=True)``, ``TableQuery`` with a whitelisted
sort, ``reload_on``, ``MasterDetail``, density and the ``/ui`` mount under a parent app.
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import indah

PROJECTS = ["support-bot", "docs-qa", "code-review", "eval-suite"]
PROMPTS = [
    "Summarise this ticket in two sentences.",
    "What is our refund policy for annual plans?",
    "Write a unit test for parse_date().",
    "Translate the following paragraph into French.",
    "List the action items from this meeting.",
    "Explain the difference between a mutex and a semaphore.",
    "Draft a polite reply declining the meeting.",
    "Which regions does the free tier cover?",
]
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# The columns a client may sort by. A sort on anything else is ignored before it gets here,
# and this map is what turns a field name into SQL, so nothing client-supplied is ever
# pasted into a query.
SORT_SQL = {"ts": "ts", "hits": "hits", "project": "project", "prompt": "prompt"}


def _ulid(ts_ms: int, rng: random.Random) -> str:
    head, t = "", ts_ms
    for _ in range(10):
        head, t = _CROCKFORD[t % 32] + head, t // 32
    return head + "".join(rng.choice(_CROCKFORD) for _ in range(16))


class EntryStore:
    """The cached entries, in stdlib SQLite. One connection behind a lock: the loader is
    called from worker threads (the table runs a sync loader off the event loop)."""

    def __init__(self, n: int = 20_000, seed: int = 1) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            "CREATE TABLE entries (id TEXT PRIMARY KEY, project TEXT, ts INTEGER, prompt TEXT,"
            " response TEXT, hits INTEGER, pinned INTEGER, fuzzy INTEGER)"
        )
        self._db.execute("CREATE INDEX entries_project ON entries (project)")
        rng = random.Random(seed)
        base = int(time.time() * 1000) - n * 60_000
        rows = []
        for i in range(n):
            prompt = f"{rng.choice(PROMPTS)} (case {i})"
            rows.append(
                (
                    _ulid(base + i * 60_000, rng),
                    rng.choice(PROJECTS),
                    base + i * 60_000,
                    prompt,
                    f"Cached answer for: {prompt}",
                    int(rng.expovariate(1 / 6)),
                    int(rng.random() < 0.03),
                    int(rng.random() < 0.25),
                )
            )
        self._db.executemany("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)", rows)
        self._db.commit()

    def __len__(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def page(self, project: str, q: indah.TableQuery) -> tuple[list[dict[str, Any]], int]:
        """One window of the entries matching ``project`` and ``q.search``."""
        where, args = ["1=1"], []
        if project != "all":
            where.append("project = ?")
            args.append(project)
        if q.search:
            like = (
                "%" + q.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            where.append("(prompt LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')")
            args += [like, like]
        clause = " AND ".join(where)
        order = "ts DESC"
        if q.sort and q.sort[0] in SORT_SQL:
            order = f"{SORT_SQL[q.sort[0]]} {'DESC' if q.sort[1] == 'desc' else 'ASC'}, id"
        with self._lock:
            total = self._db.execute(
                f"SELECT COUNT(*) FROM entries WHERE {clause}", args
            ).fetchone()[0]
            cur = self._db.execute(
                f"SELECT id, project, ts, prompt, hits, pinned, fuzzy FROM entries WHERE {clause}"
                f" ORDER BY {order} LIMIT ? OFFSET ?",
                [*args, q.limit, q.offset],
            )
            rows = [
                {
                    **dict(r),
                    "pinned": "pinned" if r["pinned"] else "",
                    "fuzzy": "fuzzy" if r["fuzzy"] else "",
                }
                for r in cur
            ]
        return rows, total

    def get(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM entries WHERE id = ?", [entry_id]).fetchone()
        return dict(row) if row else None

    def set_pinned(self, entry_id: str, pinned: bool) -> None:
        with self._lock:
            self._db.execute("UPDATE entries SET pinned = ? WHERE id = ?", [int(pinned), entry_id])
            self._db.commit()


def _preview(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "Select an entry to preview it."
    return (
        f"### {entry['project']}\n\n- **id** `{entry['id']}`\n"
        f"- **hits** {entry['hits']}  -  **pinned** {'yes' if entry['pinned'] else 'no'}"
        f"  -  **fuzzy** {'yes' if entry['fuzzy'] else 'no'}\n\n"
        f"**Prompt**\n\n> {entry['prompt']}\n\n**Cached response**\n\n> {entry['response']}"
    )


def build_entries_app(store: EntryStore) -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        project: indah.Signal[str] = indah.Signal("all")
        picked: indah.Signal[Any] = indah.Signal(None)
        detail_open = indah.Signal(False)
        version = indah.Signal(0)  # bumped after a write so the table re-runs its query
        compact = indah.Signal(False)

        def loader(q: indah.TableQuery) -> tuple[list[dict[str, Any]], int]:
            return store.page(project.value, q)

        def on_pick() -> None:
            if picked.value is not None:
                detail_open.set(True)

        indah.effect(on_pick)

        def toggle_pin() -> None:
            entry = store.get(picked.value) if picked.value else None
            if entry is not None:
                store.set_pinned(entry["id"], not entry["pinned"])
                version.set(version.value + 1)
                ctx.toast("Unpinned" if entry["pinned"] else "Pinned", kind="success", ttl=2)

        preview = indah.computed(
            lambda: (
                _preview(store.get(picked.value) if picked.value else None)
                + f"\n\n<!--{version.value}-->"
            )
        )
        density = indah.computed(lambda: "compact" if compact.value else "comfortable")
        table = indah.Table(
            columns=[
                indah.Col("ts", title="When", kind="time", sortable=True, width="9ch"),
                indah.Col("id", kind="mono", width="14ch"),
                indah.Col("project", sortable=True, width="12ch"),
                indah.Col("prompt", sortable=True),
                indah.Col("hits", kind="number", sortable=True, width="7ch"),
                indah.Col("pinned", kind="badge", tones={"pinned": "info"}, width="9ch"),
                indah.Col("fuzzy", kind="badge", tones={"fuzzy": "warn"}, width="8ch"),
            ],
            key="id",
            remote=loader,
            reload_on=[project, version],
            selected=picked,
            search=True,
            virtual=True,
            height="30rem",
            density=density,
        )
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("# Cached entries", markdown=True),
                    indah.Row(
                        align="end",
                        children=[
                            indah.Select(
                                project,
                                options=[{"value": "all", "label": "All projects"}, *PROJECTS],
                                label="Project",
                            ),
                            indah.Switch(compact, label="Compact"),
                        ],
                    ),
                    indah.MasterDetail(
                        table,
                        indah.Card(
                            title="Entry",
                            children=[
                                indah.Text(lambda: preview.value, markdown=True),
                                indah.Button(
                                    "Pin / unpin",
                                    toggle_pin,
                                    variant="tonal",
                                    tooltip="Toggle the pinned flag on the selected entry",
                                ),
                            ],
                        ),
                        open=detail_open,
                        key="entries",
                        title="Entry",
                        initial=0.62,
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


def build_app(*, n: int = 20_000, seed: int = 1) -> Starlette:
    """A semula-shaped parent app: ``/v1/health`` and the browser mounted at ``/ui``."""
    store = EntryStore(n, seed)
    ui = build_entries_app(store)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "entries": len(store)})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("ui/")

    app = Starlette(routes=[Route("/", root), Route("/v1/health", health), Mount("/ui", app=ui)])
    app.state.store = store
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

"""One server for reviewing every semula demo (``make demo-review``).

An index page at ``/`` links to each demo, each mounted under its own prefix
(``/log/ui/``, ``/pending/ui/``, ``/entries/ui/``, ``/routes/ui/``), plus a small
component showcase at ``/showcase/ui/``: Modal, Drawer, toast, Badge, Switch, tooltip,
Shortcuts, JsonTree, Diff, SplitPane and table density.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route

import indah

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semula_editor  # noqa: E402
import semula_entries  # noqa: E402
import semula_hosted  # noqa: E402
import semula_log  # noqa: E402
import semula_pending  # noqa: E402
import semula_routes  # noqa: E402

THEME = indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"})

INCOMING = {"model": "gpt-4o", "temperature": 0.2, "tags": ["a", "b"], "limits": {"rpm": 60}}
CANDIDATE = {"model": "gpt-4o", "temperature": 0.7, "tags": ["a", "c"], "limits": {"rpm": 120}}
TREE = {
    "project": "auth",
    "entries": [{"id": "01J1", "status": "ok", "latency_ms": 41}, {"id": "01J2", "status": "slow"}],
    "meta": {"owner": "semula", "flags": {"beta": True, "retries": 3}},
}
ROWS = [{"id": i, "name": f"entry-{i}", "state": "ok" if i % 3 else "slow"} for i in range(1, 13)]


def build_showcase_app() -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        modal_open = indah.Signal(False)
        drawer_open = indah.Signal(False)
        beta = indah.Signal(False)
        compact = indah.Signal(False)
        presses = indah.Signal(0)
        density = indah.computed(lambda: "compact" if compact.value else "comfortable")
        status = indah.computed(lambda: "beta ON" if beta.value else "beta off")

        def press() -> None:
            presses.set(presses.value + 1)
            ctx.toast(f"Shortcut p pressed {presses.value} time(s)", kind="info")

        overlays = indah.Card(
            title="Overlays, toasts, badge, switch",
            children=[
                indah.Row(
                    children=[
                        indah.Button("Open modal", lambda: modal_open.set(True)),
                        indah.Button("Open drawer", lambda: drawer_open.set(True), variant="tonal"),
                        indah.Button(
                            "Toast: success",
                            lambda: ctx.toast("Saved", kind="success"),
                            variant="ghost",
                        ),
                        indah.Button(
                            "Toast: error (sticky)",
                            lambda: ctx.toast("Something failed", kind="error", ttl=0),
                            variant="ghost",
                        ),
                        indah.Button(
                            "Confirm me",
                            lambda: ctx.toast("Confirmed", kind="warn"),
                            confirm="Really do it?",
                        ),
                    ]
                ),
                indah.Row(
                    children=[indah.Switch(beta, label="Beta"), indah.Badge(status, tone="ok")]
                ),
                indah.Text("Hover this line for a tooltip.", tooltip="A tooltip from tooltip="),
                indah.Text("Press p (shortcut) or ? (shortcut help).", tooltip="Shortcuts"),
                indah.Shortcuts({"p": (press, "Press counter + toast")}),
                indah.Modal(
                    title="A modal",
                    open=modal_open,
                    children=[
                        indah.Text("Esc or the close button dismisses it."),
                        indah.Button("Close", lambda: modal_open.set(False)),
                    ],
                ),
                indah.Drawer(
                    title="A drawer",
                    open=drawer_open,
                    children=[indah.Text("Side panel content."), indah.JsonTree(INCOMING)],
                ),
            ],
        )
        viewers = indah.Card(
            title="JsonTree, Diff, SplitPane",
            children=[
                indah.SplitPane(
                    indah.JsonTree(TREE, expanded=2, label="Tree (try the search box)"),
                    indah.Diff(INCOMING, CANDIDATE),
                    height="22rem",
                )
            ],
        )
        table = indah.Card(
            title="Table density",
            children=[
                indah.Switch(compact, label="Compact"),
                indah.Table(rows=ROWS, key="id", density=density, label="Entries"),
            ],
        )
        return indah.Session(indah.Column(children=[overlays, viewers, table]))

    return indah.create_app(
        session_factory=build, title="semula showcase", theme=THEME, spa=True, proxy_flush=False
    )


# What to click through on each screen, shown on the index page.
DEMOS: list[tuple[str, str, str]] = [
    (
        "log",
        "Live request log",
        "Watch rows stream in; open two tabs; search, toggle columns, pause/follow.",
    ),
    (
        "pending",
        "Pending queue",
        "Two tabs: release a call in one, it leaves both. j/k/a/r/Enter and ? for keys.",
    ),
    (
        "entries",
        "Entries browser (20k rows)",
        "Scroll fast, sort, search; pin a row to the side pane; flip density.",
    ),
    (
        "routes",
        "Routed dashboard",
        "Click through projects/entries; paste a deep link in a new tab; use Back.",
    ),
    (
        "hosted",
        "Hosted: two users, one app",
        "Sign in as alice in one browser profile and bob in another; reload, sign out, audit trail.",
    ),
    (
        "showcase",
        "Component showcase",
        "Modal, Drawer, toasts, Badge, Switch, tooltip, Shortcuts, JsonTree, Diff, SplitPane.",
    ),
]


def _index_html() -> str:
    items = "".join(
        f'<li><a href="{key}/ui/">{title}</a><br><small>{hint}</small></li>'
        for key, title, hint in DEMOS
    )
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>semula review</title>"
        "<style>body{font:16px system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem}"
        "li{margin:1rem 0}small{color:#666}</style>"
        f"<h1>semula demos</h1><ul>{items}</ul>"
    )


def build_app(*, seed: int | None = 1) -> Starlette:
    log = semula_log.build_app(rate=20.0, seed=seed)
    pending = semula_pending.build_app(seed=seed)
    entries = semula_entries.build_app()
    routes = semula_routes.build_app()
    editor = semula_editor.build_app()
    hosted = semula_hosted.build_app()
    children = {
        "log": log,
        "pending": pending,
        "entries": entries,
        "routes": routes,
        "editor": editor,
        "hosted": hosted,
    }

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Mount does not run a sub-app's lifespan, so enter the ones that have a producer.
        async with contextlib.AsyncExitStack() as stack:
            for child in (log, pending):
                await stack.enter_async_context(child.router.lifespan_context(child))
            yield

    async def index(request: Request) -> HTMLResponse:
        return HTMLResponse(_index_html())

    return Starlette(
        routes=[
            Route("/", index),
            *(Mount(f"/{name}", app=child) for name, child in children.items()),
            Mount("/showcase", app=Starlette(routes=[Mount("/ui", app=build_showcase_app())])),
        ],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    indah.launch(build_app())

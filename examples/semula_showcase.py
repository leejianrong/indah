"""A component showcase in one screen: overlays, toasts, badge, switch, tooltips, shortcuts,
JsonTree, Diff, SplitPane and table density.

It is a chapter of the Studio (``make demo``, under Full apps); run it alone with
``python examples/semula_showcase.py``.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

import indah

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


def build_app() -> Starlette:
    ui = build_showcase_app()
    app = Starlette(routes=[Mount("/ui", app=ui)])
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

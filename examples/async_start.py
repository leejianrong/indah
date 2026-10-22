"""A dashboard whose first data takes a moment to load: an ``async`` session factory (IND-153).

    python examples/async_start.py        # prints a URL; open /ui/

The factory awaits its data before it returns, so a fast load puts the numbers in the very first
paint (no dash, then the number). A slow load (here 2.5 s, over the app's 1 s limit) lets the tab
start on a `Skeleton`, and the real page replaces it on the same stream when the data arrives.
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

import indah


async def load_overview(delay: float) -> dict[str, Any]:
    """Stands in for a database or HTTP call."""
    await asyncio.sleep(delay)
    return {"projects": 3, "entries": 20_000, "errors": 12}


def build_ui(delay: float = 2.5, timeout: float = 1.0) -> Any:
    async def build(ctx: indah.Context) -> indah.Session:
        data = await load_overview(delay)
        refreshed = indah.Signal(0)
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("Overview"),
                    indah.Row(
                        children=[
                            indah.Stat(data["projects"], label="Projects"),
                            indah.Stat(f"{data['entries']:,}", label="Entries"),
                            indah.Stat(data["errors"], label="Errors today"),
                        ]
                    ),
                    indah.Button("Refresh", lambda: refreshed.set(refreshed.value + 1)),
                    indah.Text(lambda: f"Refreshed {refreshed.value} time(s)"),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="Async start",
        factory_timeout=timeout,
        factory_placeholder=lambda: indah.Column(
            children=[indah.Skeleton(lines=1, height="1.6rem"), indah.Skeleton(lines=4)]
        ),
        spa=True,
    )


def build_app(*, delay: float = 2.5, timeout: float = 1.0) -> Starlette:
    ui = build_ui(delay, timeout)
    app = Starlette(routes=[Mount("/ui", app=ui)])
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

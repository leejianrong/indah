"""A semula-shaped dashboard with real URLs: projects, entries and a working Back button.

semula mounts its dashboard under ``/ui`` and wants links it can paste: an entry should open
from ``/ui/projects/support-bot/entries/01J...`` in a fresh tab. This demo has a sidebar, a
project page listing its entries, an entry page, a project switcher that lives in the URL
and a 404 page, all mounted at ``/ui`` in a parent app.

    python examples/semula_routes.py        # prints a URL; open /ui/

What it shows (IND-E23): ``Router`` + ``Link`` + ``ctx.params`` + ``ctx.navigate`` with
``spa=True`` under a ``Mount``. The parent here is Starlette; ``fastapi.FastAPI().mount(
"/ui", ui)`` is the same mechanism.
"""

from __future__ import annotations

import random
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

import indah

PROJECTS = ["support-bot", "docs-qa", "code-review"]
PROMPTS = [
    "Summarise this ticket in two sentences.",
    "What is our refund policy for annual plans?",
    "Write a unit test for parse_date().",
    "Translate the following paragraph into French.",
    "List the action items from this meeting.",
]
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def make_entries(per_project: int = 25, seed: int = 1) -> dict[str, dict[str, dict[str, Any]]]:
    """``{project: {entry_id: entry}}`` with stable ids, so links in a test or a bookmark
    keep working from one run to the next."""
    rng = random.Random(seed)
    data: dict[str, dict[str, dict[str, Any]]] = {}
    for project in PROJECTS:
        entries = {}
        for _ in range(per_project):
            entry_id = "".join(rng.choice(_CROCKFORD) for _ in range(10))
            prompt = rng.choice(PROMPTS)
            entries[entry_id] = {
                "id": entry_id,
                "prompt": prompt,
                "response": f"Cached answer for: {prompt}",
                "hits": rng.randint(0, 40),
            }
        data[project] = entries
    return data


def build_routes_app(data: dict[str, dict[str, dict[str, Any]]]) -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        project = indah.computed(lambda: ctx.params.value.get("project"))
        entry_id = indah.computed(lambda: ctx.params.value.get("entry_id"))
        entries = indah.computed(lambda: list(data.get(project.value or "", {}).values()))
        entry = indah.computed(lambda: data.get(project.value or "", {}).get(entry_id.value or ""))

        # The project switcher lives in the URL: choosing one navigates, and the URL (a
        # pasted link, Back) sets the choice. Each side only acts when the other differs.
        chosen: indah.Signal[str] = indah.Signal(project.value or PROJECTS[0])
        picked: indah.Signal[Any] = indah.Signal(None)

        def sync_from_url() -> None:
            if project.value in data and chosen.peek() != project.value:
                chosen.set(project.value)

        armed = False

        def sync_from_switcher() -> None:
            # Reads only `chosen` (peek on the URL side), so it runs when the *viewer* picks
            # a project, never because the page changed, and skips its first run.
            nonlocal armed
            picked_name = chosen.value
            if armed and picked_name in data and picked_name != project.peek():
                ctx.navigate(f"/projects/{picked_name}")
            armed = True

        def open_picked() -> None:
            if picked.value is not None and project.value:
                ctx.navigate(f"/projects/{project.value}/entries/{picked.value}")
                picked.set(None)

        indah.effect(sync_from_url)
        indah.effect(sync_from_switcher)
        indah.effect(open_picked)

        def project_text() -> str:
            if project.value not in data:
                return f"### No project called `{project.value}`"
            return (
                f"### {project.value}\n\n{len(entries.value)} cached entries. Click one to open it."
            )

        def entry_text() -> str:
            e = entry.value
            if e is None:
                return f"### No entry `{entry_id.value}` in `{project.value}`"
            return (
                f"### Entry `{e['id']}`\n\n**Project** {project.value}  -  **hits** {e['hits']}"
                f"\n\n**Prompt**\n\n> {e['prompt']}\n\n**Cached response**\n\n> {e['response']}"
            )

        nav = indah.Column(
            children=[
                indah.Link(ctx, "Overview", to="/"),
                *[
                    indah.Link(ctx, name, to=f"/projects/{name}", match="prefix")
                    for name in PROJECTS
                ],
            ]
        )
        pages = indah.Router(
            ctx,
            routes={
                "/": indah.Column(
                    children=[
                        indah.Text("# Overview", markdown=True),
                        indah.Text(f"{len(PROJECTS)} projects. Pick one from the sidebar."),
                    ]
                ),
                "/projects/{project}": indah.Column(
                    children=[
                        indah.Select(chosen, options=PROJECTS, label="Project"),
                        indah.Text(project_text, markdown=True),
                        indah.Table(
                            rows=entries,
                            key="id",
                            selected=picked,
                            height="22rem",
                            columns=[
                                indah.Col("id", kind="mono", width="14ch"),
                                indah.Col("prompt"),
                                indah.Col("hits", kind="number", sortable=True),
                            ],
                        ),
                    ]
                ),
                "/projects/{project}/entries/{entry_id}": indah.Column(
                    children=[
                        indah.Link(
                            ctx,
                            "Back to the project",
                            to=lambda: f"/projects/{project.value or ''}".rstrip("/") or "/",
                        ),
                        indah.Card(children=[indah.Text(entry_text, markdown=True)]),
                    ]
                ),
            },
            not_found=indah.Column(
                children=[
                    indah.Text("# 404", markdown=True),
                    indah.Text("There is no page at this address."),
                    indah.Link(ctx, "Go to the overview", to="/"),
                ]
            ),
        )
        return indah.Session(indah.Sidebar(children=[nav, pages]))

    return indah.create_app(
        session_factory=build,
        title="semula",
        theme=indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}),
        spa=True,
        proxy_flush=False,
    )


def build_app(*, per_project: int = 25, seed: int = 1) -> Starlette:
    """A semula-shaped parent app: ``/v1/health`` and the dashboard mounted at ``/ui``."""
    data = make_entries(per_project, seed)
    ui = build_routes_app(data)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "projects": list(data)})

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("ui/")

    app = Starlette(routes=[Route("/", root), Route("/v1/health", health), Mount("/ui", app=ui)])
    app.state.data = data
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

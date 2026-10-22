"""The Studio app: a home page, one app per chapter, whole example apps, and the playground.

    make demo                     # = uv run python -m examples.studio

URLs: ``/`` the home page, ``/c/<chapter>/<page>`` a feature demo, ``/apps/<app>/ui/`` a full
example app, ``/hosted/`` the multi-user demo, ``/play/<id>/`` a playground run.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

import indah

from .core import AppEntry, Chapter, build_chapter_app, covered_names, discover

# The example apps import each other as top-level modules (``import semula_hosted``).
_EXAMPLES = str(Path(__file__).resolve().parents[1])
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

THEME = indah.Theme(light={"primary": "#b0236b"}, dark={"primary": "#f08cc0"})


def build_home(chapters: list[Chapter]) -> Any:
    """The home page: what indah is, and a card per chapter listing its pages."""
    pages = sum(len(c.pages) for c in chapters)
    apps = sum(len(c.apps) for c in chapters)
    names = covered_names(chapters)

    def build(ctx: indah.Context) -> indah.Session:
        cards = []
        for chapter in chapters:
            lines = [chapter.blurb, ""]
            lines += [f"- [{p.title}](/c/{chapter.slug}/{p.slug})" for p in chapter.pages]
            lines += [
                f"- [{a.title}](/apps/{a.slug}/{a.open_path}) *(full app)*" for a in chapter.apps
            ]
            cards.append(
                indah.Card(
                    title=chapter.title,
                    children=[
                        indah.Text("\n".join(lines), markdown=True),
                        indah.Text(f"[Open chapter](/c/{chapter.slug}/)", markdown=True),
                    ],
                )
            )
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text("# indah Studio", markdown=True),
                    indah.Text(
                        "Every part of indah, live. Each page is a small working demo with its "
                        "source underneath; the full apps are the realistic ones. "
                        f"**{pages} feature pages, {apps} full apps, {len(names)} public names "
                        "demonstrated.**",
                        markdown=True,
                    ),
                    indah.Grid(children=cards, columns=3),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="indah Studio",
        title_suffix="",
        theme=THEME,
        csp="strict",
        proxy_flush=False,
        max_width="1280px",
    )


@contextlib.contextmanager
def _default_csp() -> Iterator[None]:
    """While an example app is built, ``indah.create_app`` defaults to ``csp="strict"``, so the
    whole Studio runs under the policy (an app that sets its own ``csp`` keeps it)."""
    real = indah.create_app

    def with_csp(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("csp", "strict")
        return real(*args, **kwargs)

    indah.create_app = with_csp  # type: ignore[assignment]
    try:
        yield
    finally:
        indah.create_app = real  # type: ignore[assignment]


def _mount_entry(entry: AppEntry) -> tuple[Any, Any]:
    with _default_csp():
        app = entry.build()
    ui = getattr(app, "state", None)
    ui = getattr(ui, entry.ui_attr, None) if entry.ui_attr else None
    while ui is not None and not hasattr(ui, "state") and hasattr(ui, "app"):
        ui = ui.app  # a wrapper such as the hosted demo's fake login
    if ui is not None:
        ui.state.home_url = "/"  # the logo leads back to the Studio
    return app, entry.lifespan


def build_app(*, playground: bool = True) -> Starlette:
    chapters = discover()
    for chapter in chapters:
        chapter.app_kwargs.setdefault("theme", THEME)
    routes: list[Any] = [
        Mount("/c/" + c.slug, app=build_chapter_app(c, chapters)) for c in chapters
    ]
    lifespans: list[Any] = []
    children: dict[str, Any] = {}
    for chapter in chapters:
        if chapter.lifespan is not None:
            lifespans.append((chapter, chapter.lifespan))
        for entry in chapter.apps:
            app, life = _mount_entry(entry)
            children[entry.slug] = app
            routes.append(Mount(f"/apps/{entry.slug}", app=app))
            if life is not None:
                lifespans.append((app, life))
    if playground:
        from .playground import PLAY

        routes.append(Mount("/play", app=PLAY))
    routes.append(Mount("/", app=build_home(chapters)))

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for target, make in lifespans:
                await stack.enter_async_context(make(target))
            yield

    studio = Starlette(routes=routes, lifespan=lifespan)
    studio.state.chapters = chapters
    studio.state.apps = children
    return studio


def main() -> None:
    indah.launch(build_app())


if __name__ == "__main__":
    main()

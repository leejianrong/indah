"""The Studio's building blocks: ``Page``, ``Chapter``, ``AppEntry`` and the shell around them.

A **page** is one small live demo of one feature: a function that takes the session ``Context``
and returns a component. Its source is shown under the demo (taken from the function itself, so
it cannot drift), together with the names it ``covers`` and links to the docs. A **chapter**
groups pages and becomes one indah app (so a chapter's reactive state and producers are its own).
An **app entry** is a whole example app mounted as-is (the realistic, composed demos).

To add a feature: write a ``Page`` in the right chapter (or a new module in ``chapters/``) and
list what it ``covers``. ``tests/unit/test_studio_coverage.py`` fails when a public name in
``indah.__all__`` has no page and is not exempt, so the Studio cannot fall behind the library.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import textwrap
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any

import indah

DOCS_URL = "https://indah.abangai.dev/docs/"
ADR_URL = "https://github.com/leejianrong/indah/blob/main/docs/adr/"


@dataclass(frozen=True)
class Page:
    """One live demo of one feature."""

    slug: str  # URL segment, unique within the chapter
    title: str
    summary: str  # markdown; one or two sentences on what the viewer is looking at
    build: Callable[[indah.Context], indah.Component]
    covers: tuple[str, ...] = ()  # public names from ``indah.__all__`` this page demonstrates
    docs: str | None = None  # a docs page ("components.md", "hosting.md#identity")
    adr: tuple[int, ...] = ()
    # Playwright hook: ``check(pw)`` receives a ``StudioPage`` (tests/e2e/studio_driver.py) with
    # the page already open. Leave it None for "renders, no errors".
    check: Callable[[Any], None] | None = None
    # Console errors / failed requests this page is *meant* to cause (a refused upload ...).
    expected_errors: tuple[str, ...] = ()
    source: str | None = None  # shown instead of the build function's source, if set
    # Why this page cannot run in the docs' browser runtime (ADR-0041): a short reason, or None
    # when it can. A page that sets it is still shown (source and screenshot), without Run it.
    # Keep pages Session-shaped (no ``api/*`` file fetches, no request headers, no ``ctx.app``)
    # and they stay runnable; see docs/STUDIO.md.
    local_only: str | None = None


# Why every whole app is local only: it is an ASGI app with its own data files and dependencies,
# not a Session the browser runtime can build.
APP_LOCAL_ONLY = "a whole ASGI app with its own data and dependencies, not a single Session"


@dataclass(frozen=True)
class AppEntry:
    """A whole example app, mounted as-is at ``/apps/<slug>/``."""

    slug: str
    title: str
    summary: str
    build: Callable[[], Any]  # returns an ASGI app (a Starlette parent, as the example's main does)
    open_path: str = "ui/"  # where the viewer lands, relative to the mount
    covers: tuple[str, ...] = ()
    docs: str | None = None
    adr: tuple[int, ...] = ()
    check: Callable[[Any], None] | None = None
    expected_errors: tuple[str, ...] = ()
    # Starts producers etc. while the studio runs; receives the built app.
    lifespan: Callable[[Any], AbstractAsyncContextManager[None]] | None = None
    # The app's indah UI (for the logo's "back to the Studio" link): attribute path on the app.
    ui_attr: str | None = "ui"
    local_only: str = APP_LOCAL_ONLY  # a whole app never runs in the docs' browser runtime


@dataclass
class Chapter:
    slug: str
    title: str
    blurb: str
    order: int
    pages: list[Page] = field(default_factory=list)
    apps: list[AppEntry] = field(default_factory=list)
    # Runs for the life of the studio (a chapter's own producers, say).
    lifespan: Callable[[Any], AbstractAsyncContextManager[None]] | None = None
    # Extra create_app() options for this chapter's app (limits, theme ...).
    app_kwargs: dict[str, Any] = field(default_factory=dict)


# Names in ``indah.__all__`` that need no page of their own, each with the reason. Anything
# else public must be covered by some page: the coverage test enforces it.
EXEMPT: dict[str, str] = {
    "__version__": "a string",
    "build_demo_session": "the old built-in demo; the Studio replaces it",
    "mock_llm": "a test double used by the chatbot demos",
    "Camera": "needs a webcam and a live-enabled server; the live-detection gallery demo covers it",
    "Microphone": "needs a microphone and a live-enabled server; examples/mic_transcribe.py covers it",
    "AudioChunk": "the value a Microphone handler receives; shown by the same demo",
    "Frame": "the value a Camera handler receives; shown by the same demo",
    "Live": "an option of create_app(live=) (ADR-0045); documented in the hosting guide",
    "SessionStore": "an extension seam (ADR-0010), documented in the docs",
    "SessionHandle": "an extension seam (ADR-0010)",
    "InMemorySessionStore": "internal default store",
    "SharedSessionStore": "internal store for a single shared Session",
    "DispatchResult": "internal result of dispatching an event",
    "ConnectionInfo": "shown through ctx.conn on the Context page",
    "Authenticator": "a type alias, shown on the Identity page",
    "Environment": "notebook detection helper",
    "detect_environment": "notebook detection helper",
    "public_url": "notebook detection helper",
    "LaunchHandle": "returned by launch()",
    "Component": "the base class, shown on the Custom component page",
    "CustomComponent": "the base for custom(), shown on the Custom component page",
    "Computed": "the class behind computed(), covered there",
}


def discover() -> list[Chapter]:
    """Every ``CHAPTER`` in ``studio/chapters/*.py``, ordered by ``Chapter.order``."""
    from . import chapters

    found: list[Chapter] = []
    for info in pkgutil.iter_modules(chapters.__path__):
        module = importlib.import_module(f"{chapters.__name__}.{info.name}")
        chapter = getattr(module, "CHAPTER", None)
        if chapter is not None:
            found.append(chapter)
    found.sort(key=lambda c: (c.order, c.slug))
    seen: set[str] = set()
    for chapter in found:
        if chapter.slug in seen:
            raise ValueError(f"two chapters are called {chapter.slug!r}")
        seen.add(chapter.slug)
        slugs = [p.slug for p in chapter.pages] + [a.slug for a in chapter.apps]
        if len(slugs) != len(set(slugs)):
            raise ValueError(f"chapter {chapter.slug!r} repeats a page slug")
    return found


def covered_names(chapters: list[Chapter]) -> set[str]:
    names: set[str] = set()
    for chapter in chapters:
        for item in [*chapter.pages, *chapter.apps]:
            names.update(item.covers)
    return names


def page_source(page: Page) -> str:
    """The code shown under a demo: ``page.source``, else the build function, dedented."""
    if page.source is not None:
        return textwrap.dedent(page.source).strip("\n")
    return textwrap.dedent(inspect.getsource(page.build)).rstrip("\n")


def _links(item: Page | AppEntry) -> str:
    bits = []
    if item.docs:
        bits.append(f"[Docs]({DOCS_URL}{item.docs.replace('.md', '/', 1)})")
    bits += [f"[ADR-{n:04d}]({ADR_URL}{n:04d}.md)" for n in item.adr]
    if item.covers:
        bits.append("Covers: " + ", ".join(f"`{n}`" for n in item.covers))
    return "  |  ".join(bits)


def chapter_nav(chapters: list[Chapter], current: str | None) -> str:
    """The top bar, as markdown: the Studio, then each chapter (the current one in bold)."""
    parts = ["**[indah Studio](/)**"]
    for chapter in chapters:
        label = f"**{chapter.title}**" if chapter.slug == current else chapter.title
        parts.append(f"[{label}](/c/{chapter.slug}/)")
    return "  ·  ".join(parts)


def frame(ctx: indah.Context, page: Page) -> indah.Component:
    """A page's standard layout: heading, summary, the live demo, its source, its links."""
    live = page.build(ctx)
    source = indah.Signal(page_source(page))
    return indah.Column(
        children=[
            indah.Text(f"## {page.title}", markdown=True),
            indah.Text(page.summary, markdown=True),
            indah.Card(title="Live", children=[live]),
            indah.Expander(
                label="Source",
                open=False,
                children=[
                    indah.CodeEditor(
                        source, language="text", read_only=True, lint=False, height="22rem"
                    )
                ],
            ),
            indah.Text(_links(page), markdown=True),
        ]
    )


def overview(chapter: Chapter) -> str:
    lines = [f"## {chapter.title}", "", chapter.blurb, ""]
    for page in chapter.pages:
        lines.append(f"- [{page.title}](/c/{chapter.slug}/{page.slug}): {page.summary}")
    for entry in chapter.apps:
        lines.append(
            f"- [{entry.title}](/apps/{entry.slug}/{entry.open_path}) (a full app): {entry.summary}"
        )
    return "\n".join(lines)


def build_chapter_app(chapter: Chapter, chapters: list[Chapter]) -> Any:
    """One chapter as an indah app: a top bar, a sidebar of its pages, the page on show."""

    def build(ctx: indah.Context) -> indah.Session:
        nav = indah.Column(
            children=[
                indah.Link(ctx, "Overview", to="/"),
                *[indah.Link(ctx, p.title, to=f"/{p.slug}") for p in chapter.pages],
            ]
        )
        routes: dict[str, indah.Component] = {
            "/": indah.Text(overview(chapter), markdown=True),
            **{f"/{p.slug}": frame(ctx, p) for p in chapter.pages},
        }
        pages = indah.Router(
            ctx,
            routes=routes,
            not_found=indah.Text("### No such page in this chapter.", markdown=True),
        )
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text(chapter_nav(chapters, chapter.slug), markdown=True),
                    indah.Sidebar(children=[nav, pages]),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title=f"{chapter.title} - indah Studio",
        title_suffix="",
        spa=True,
        csp="strict",
        proxy_flush=False,
        max_width="1280px",
        **chapter.app_kwargs,
    )

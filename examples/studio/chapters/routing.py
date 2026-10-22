"""Chapter 4: routing and deep links."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

import indah

from ..core import AppEntry, Chapter, Page

_USERS = {"ada": "Analytical engines", "grace": "Compilers", "linus": "Kernels"}


def links(ctx: indah.Context) -> indah.Component:
    return indah.Column(
        children=[
            indah.Text(lambda: f"ctx.path is {ctx.path.value!r}"),
            indah.Text("These links drive this chapter's own Router (see the sidebar):"),
            indah.Row(
                children=[
                    indah.Link(ctx, "This page", to="/links"),
                    indah.Link(ctx, "Prefix match", to="/links", match="prefix"),
                    indah.Link(ctx, "Overview", to="/"),
                ]
            ),
            indah.Text(
                "The active link carries `aria-current=page`. `match='prefix'` also lights up for "
                "pages below the target, which matters for `/projects/{name}` style trees.",
                markdown=True,
            ),
        ]
    )


def links_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("ctx.path is '/links'")).to_be_visible()
    main = page.get_by_role("link", name="This page")
    expect(main).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("link", name="Prefix match")).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("link", name="Overview").first).not_to_have_attribute(
        "aria-current", "page"
    )
    page.get_by_role("link", name="Overview").last.click()
    expect(page).to_have_url(pw.base + "c/routing/")  # the address bar moved, no reload
    expect(page.get_by_role("heading", name="Routing")).to_be_visible()


def navigate(ctx: indah.Context) -> indah.Component:
    return indah.Column(
        children=[
            indah.Text(lambda: f"ctx.path is {ctx.path.value!r}"),
            indah.Row(
                children=[
                    indah.Button("Go to Links", lambda: ctx.navigate("/links")),
                    indah.Button(
                        "Go somewhere unknown",
                        lambda: ctx.navigate("/no-such-page"),
                        variant="tonal",
                    ),
                ]
            ),
            indah.Text(
                "`ctx.navigate(path)` moves the tab from server code and adds a history entry.",
                markdown=True,
            ),
        ]
    )


def navigate_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Go somewhere unknown").click()
    expect(page.get_by_text("No such page in this chapter.")).to_be_visible()  # not_found
    expect(page).to_have_url(pw.base + "c/routing/no-such-page")
    page.go_back()  # a real history entry
    expect(page.get_by_text("ctx.path is '/navigate'")).to_be_visible()
    page.get_by_role("button", name="Go to Links").click()
    expect(page.get_by_text("ctx.path is '/links'")).to_be_visible()


def _users_ui() -> Any:
    def build(ctx: indah.Context) -> indah.Session:
        name = indah.computed(lambda: ctx.params.value.get("name", ""))
        post = indah.computed(lambda: ctx.params.value.get("n", ""))
        nav = indah.Column(
            children=[
                indah.Link(ctx, "Home", to="/"),
                *[indah.Link(ctx, u.title(), to=f"/users/{u}", match="prefix") for u in _USERS],
            ]
        )
        pages = indah.Router(
            ctx,
            routes={
                "/": indah.Text("### Home\n\nPick a user.", markdown=True),
                "/users/{name}": indah.Column(
                    children=[
                        indah.Text(
                            lambda: (
                                f"### User {name.value}\n\nKnown for: "
                                f"{_USERS.get(name.value, 'nothing we know of')}"
                            ),
                            markdown=True,
                        ),
                        indah.Button(
                            "Open post 2",
                            lambda: ctx.navigate(f"/users/{name.value}/posts/2"),
                        ),
                    ]
                ),
                "/users/{name}/posts/{n}": indah.Column(
                    children=[
                        indah.Text(lambda: f"### Post {post.value} by {name.value}", markdown=True),
                        indah.Link(ctx, "Back to the user", to=lambda: f"/users/{name.value}"),
                    ]
                ),
            },
            not_found=indah.Text("### 404: nothing at this address", markdown=True),
        )
        return indah.Session(indah.Sidebar(children=[nav, pages]))

    return indah.create_app(
        session_factory=build,
        title="Router demo - indah Studio",
        title_suffix="",
        spa=True,
        csp="strict",
        proxy_flush=False,
    )


def _users() -> Any:
    ui = _users_ui()
    app = Starlette(routes=[Mount("/ui", app=ui)])
    app.state.ui = ui
    return app


def _users_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("link", name="Grace").click()
    expect(page.get_by_text("User grace")).to_be_visible()
    expect(page.get_by_text("Known for: Compilers")).to_be_visible()
    expect(page.get_by_role("link", name="Grace")).to_have_attribute("aria-current", "page")
    page.get_by_role("button", name="Open post 2").click()
    expect(page.get_by_text("Post 2 by grace")).to_be_visible()
    # match="prefix" keeps the sidebar link lit on the post page below it
    expect(page.get_by_role("link", name="Grace")).to_have_attribute("aria-current", "page")
    page.go_back()
    expect(page.get_by_text("User grace")).to_be_visible()
    # a deep link in a fresh load resolves from the URL alone
    page.goto(pw.base + "apps/users/ui/users/linus/posts/7")
    expect(page.get_by_text("Post 7 by linus")).to_be_visible()
    page.goto(pw.base + "apps/users/ui/nowhere/at/all")
    expect(page.get_by_text("404: nothing at this address")).to_be_visible()


CHAPTER = Chapter(
    slug="routing",
    title="Routing",
    order=40,
    blurb=(
        "A `Router` maps URL patterns to pages, `Link` navigates and shows where you are, and "
        "`ctx.params` reads the `{placeholders}`. A session has one `Router`, and each chapter "
        "here already uses it, so the two pages show links and `ctx.navigate` on this chapter's "
        "own routes and the full app below shows parameters, `not_found` and deep links."
    ),
    pages=[
        Page(
            slug="links",
            title="Link and active state",
            summary="A `Link` is a real anchor: middle-click opens a tab, a plain click navigates without a reload.",
            build=links,
            covers=("Link", "Router", "Context"),
            docs="dashboards.md",
            adr=(29,),
            check=links_check,
        ),
        Page(
            slug="navigate",
            title="ctx.navigate and not_found",
            summary="Server code can move the tab. A path with no route shows the router's `not_found` page.",
            build=navigate,
            covers=("Context", "Router"),
            docs="dashboards.md",
            adr=(29,),
            check=navigate_check,
        ),
    ],
    apps=[
        AppEntry(
            slug="users",
            title="Params and deep links",
            summary="Routes with `{name}` and `{n}` placeholders, `ctx.params`, prefix links, `not_found`. Paste any URL.",
            build=_users,
            covers=("Router", "Link", "Context"),
            docs="dashboards.md",
            adr=(29,),
            check=_users_check,
        ),
    ],
)

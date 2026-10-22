"""Full apps: the realistic, composed dashboards (each is also a runnable example file)."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

from ..core import AppEntry, Chapter


def _lifespan_of(app: Any) -> Any:
    """Run a mounted app's own lifespan (a Mount does not), so its producers feed it."""
    return app.router.lifespan_context(app)


def _log() -> Any:
    import semula_log

    return semula_log.build_app(rate=6.0, seed=1)


def _pending() -> Any:
    import semula_pending

    return semula_pending.build_app(seed=1)


def _entries() -> Any:
    import semula_entries

    return semula_entries.build_app()


def _routes() -> Any:
    import semula_routes

    return semula_routes.build_app()


def _editor() -> Any:
    import semula_editor

    return semula_editor.build_app()


def _hosted() -> Any:
    import semula_hosted

    return semula_hosted.build_app()


def _showcase() -> Any:
    import semula_review

    ui = semula_review.build_showcase_app()
    app = Starlette(routes=[Mount("/ui", app=ui)])
    app.state.ui = ui
    return app


def _check_log(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr").first).to_be_visible()
    before = page.locator("tbody tr").count()
    page.wait_for_timeout(1500)
    assert page.locator("tbody tr").count() >= before  # rows keep arriving


def _check_pending(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr").first).to_be_visible(timeout=15000)


def _check_entries(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator("tbody tr:not(.vspacer)").first).to_be_visible(timeout=15000)


def _check_routes(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("link", name="support-bot").first.click()
    expect(page.get_by_text("cached entries").first).to_be_visible()


def _check_editor(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.locator(".cm-content").first).to_be_visible(timeout=15000)


def _check_hosted(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.goto(pw.base + "apps/hosted/login?user=carol")
    expect(page.get_by_text("API tokens (admins only)")).to_be_visible()
    expect(page.get_by_role("button", name="Create token")).to_be_visible()


def _check_showcase(pw: Any) -> None:
    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Open modal").click()
    expect(page.get_by_text("A modal")).to_be_visible()


CHAPTER = Chapter(
    slug="apps",
    title="Full apps",
    order=90,
    blurb=(
        "The realistic ones: whole dashboards built from the same parts as the feature pages. "
        "Each is also a file in `examples/` you can run on its own."
    ),
    apps=[
        AppEntry(
            slug="log",
            title="Live request log",
            summary="A `Topic` feeds every open tab; the table follows the tail, with search and column toggles.",
            build=_log,
            lifespan=_lifespan_of,
            covers=("Topic", "Stream"),
            check=_check_log,
        ),
        AppEntry(
            slug="pending",
            title="Pending queue",
            summary="Review parked calls in a drawer; release one and it leaves every tab. Keys: j k a r Enter ?.",
            build=_pending,
            lifespan=_lifespan_of,
            covers=("Drawer", "Shortcuts", "RowAction"),
            check=_check_pending,
        ),
        AppEntry(
            slug="entries",
            title="Entries browser (20,000 rows)",
            summary="A remote table over SQLite: virtual scroll, server-side sort and search, a pinned side pane.",
            build=_entries,
            covers=("TableQuery", "SplitPane"),
            check=_check_entries,
        ),
        AppEntry(
            slug="routes",
            title="Routed dashboard",
            summary="Real URLs for every screen: deep links, Back, a project switcher that lives in the address bar.",
            build=_routes,
            covers=("Router", "Link"),
            check=_check_routes,
        ),
        AppEntry(
            slug="editor",
            title="Entry editor",
            summary="Edit JSON with `CodeEditor`, resolve a conflict in a `Diff`, review a response, try a playground.",
            build=_editor,
            covers=("CodeEditor", "Diff", "JsonTree"),
            check=_check_editor,
        ),
        AppEntry(
            slug="hosted",
            title="Hosted: roles and API tokens",
            summary=(
                "Sign in as bob (viewer), alice (editor) or carol (admin) in separate browser profiles. "
                "Roles decide what is even built; the admin creates, lists and revokes tokens."
            ),
            build=_hosted,
            open_path="login",
            ui_attr="ui",
            covers=("Principal", "Policy", "guard", "Forbidden", "Limits", "Rate", "SecretReveal"),
            docs="hosting.md",
            adr=(33, 34, 35, 36, 37, 38),
            check=_check_hosted,
        ),
        AppEntry(
            slug="showcase",
            title="Component showcase",
            summary="Modal, drawer, toasts, badge, switch, tooltips, shortcuts, JSON tree, diff and split pane.",
            build=_showcase,
            covers=("Modal", "Badge", "Switch"),
            check=_check_showcase,
        ),
    ],
)

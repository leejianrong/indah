"""Chapter: hosting for real users. The identity-aware parts that can run in a plain demo."""

from __future__ import annotations

import secrets

import indah
from indah.authz import can

from ..core import Chapter, Page

POLICY = indah.Policy(
    {"viewer": ["entries:read"], "editor": ["entries:*"], "admin": ["*"]},
)
PERMISSIONS = ["entries:read", "entries:write", "entries:delete", "tokens:manage"]
ROLES = ["viewer", "editor", "admin"]


def secret_reveal(ctx: indah.Context) -> indah.Component:
    token: indah.Signal[str | None] = indah.Signal(None)

    def create() -> None:
        token.set("ind_" + secrets.token_urlsafe(24))  # in a real app: store only a hash

    return indah.Column(
        children=[
            indah.Button("Create token", create),
            indah.SecretReveal(token, label="New API token"),
            indah.Text("Reload the page: the token is gone, and it was never in the snapshot."),
        ]
    )


def secret_reveal_check(pw) -> None:
    import re

    from playwright.sync_api import expect

    page = pw.page
    page.get_by_role("button", name="Create token").click()
    value = page.locator(".secret-value")
    expect(value).to_have_text(re.compile(r"ind_[A-Za-z0-9_-]{20,}"))
    secret = value.inner_text()
    page.get_by_role("button", name="Copy", exact=True).click()
    expect(page.get_by_role("button", name="Copied")).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == secret
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Create token")).to_be_visible()
    page.wait_for_timeout(300)
    assert page.locator(".secret").count() == 0 and secret not in page.content()
    page.get_by_role("button", name="Create token").click()
    expect(value).to_be_visible()
    page.get_by_role("button", name="I have saved it").click()
    expect(page.locator(".secret")).to_have_count(0)


def policy_explorer(ctx: indah.Context) -> indah.Component:
    roles = indah.Signal(["viewer"])

    def who() -> indah.Principal:
        return indah.Principal(id="visitor", roles=frozenset(roles.value))

    return indah.Column(
        children=[
            indah.MultiSelect(roles, options=ROLES, label="Roles of the visitor"),
            indah.Text(
                lambda: ", ".join(
                    f"{p}: {'yes' if can(who(), p, POLICY) else 'no'}" for p in PERMISSIONS
                )
            ),
        ]
    )


def policy_check(pw) -> None:
    from playwright.sync_api import expect

    page = pw.page
    expect(page.get_by_text("entries:read: yes, entries:write: no")).to_be_visible()
    page.get_by_label("Roles of the visitor").select_option(["viewer", "admin"])
    expect(page.get_by_text("tokens:manage: yes")).to_be_visible()


CHAPTER = Chapter(
    slug="hosted",
    title="Hosting",
    order=85,
    blurb=(
        "What indah adds for apps with real users: identity, roles, one-time secrets, limits and a "
        'strict CSP (this whole Studio runs under `csp="strict"`). The multi-user parts need '
        "several logins, so the full demo is the **Hosted** app in *Full apps*."
    ),
    pages=[
        Page(
            slug="secret-reveal",
            title="Show a secret once",
            summary="`SecretReveal` shows a new API token with Copy and dismiss. It goes to this tab only and is never replayed on reload or reconnect.",
            build=secret_reveal,
            covers=("SecretReveal",),
            docs="hosting.md",
            adr=(36,),
            check=secret_reveal_check,
        ),
        Page(
            slug="policy",
            title="Roles and permissions",
            summary="A `Policy` maps roles to permissions; `ctx.can` and `guard` ask it. Pick roles and see what they may do. In a real app the roles come from the login (`Principal`).",
            build=policy_explorer,
            covers=("Policy", "Principal"),
            docs="hosting.md",
            adr=(35,),
            check=policy_check,
        ),
    ],
)

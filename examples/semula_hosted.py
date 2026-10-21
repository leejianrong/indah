"""Two users, one app: signed sessions, isolation and an audit trail (ADR-0033, ADR-0034).

A hosted indah app lets a parent app log people in and then refuses to mix their sessions. The
parent here is a fake identity provider: ``/login?user=alice`` sets a cookie (a real one would
be OIDC or semula's own login), a middleware turns the cookie (or an ``X-User`` header) into
Starlette's ``scope["user"]``, and ``create_app(secure=True)`` does the rest.

    python examples/semula_hosted.py     # open the URL in two browser profiles
    # profile 1: /login?user=alice      profile 2: /login?user=bob

What it shows (IND-E25): ``ctx.user`` in the session factory, one signed session per login
(a reload keeps its counter and notes), another user's session id refused, ``ctx.sign_out()``
ending every tab of one user (and the fake login with it), cross-origin POSTs refused, and an
audit hook feeding a per-user table.

And (IND-E26): three roles with a ``Policy``. The viewer (bob) has no "Add entry" button and no
token screen in their page at all (omitted when the tree is built, not hidden); the editor
(alice) may add entries; the admin (carol) also gets an API-tokens screen: create a token (it is
revealed once, with Copy, and never replayed on a reload), list the tokens, revoke one with a
confirm. Every action is also guarded where it runs, so a role revoked mid-session fails the next
click. The app runs with the hardening switched on: a strict CSP, security headers, rate and
stream limits. The login is a stand-in: never use a cookie like this for real. For a real login
see ``examples/oidc_login.py``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import secrets
import time
from typing import Any

from starlette.applications import Starlette
from starlette.authentication import SimpleUser
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

import indah

SECRET = "demo-only-secret-change-me-0123456789"  # a real app reads this from its environment

# name -> (display name, roles). Roles drive what each page contains (see POLICY).
USERS: dict[str, tuple[str, frozenset[str]]] = {
    "alice": ("Alice Tan", frozenset({"editor"})),
    "bob": ("Bob Lim", frozenset({"viewer"})),
    "carol": ("Carol Ng", frozenset({"admin"})),
}
COOKIE = "demo_user"

# Roles to permissions (ADR-0035): viewers read, editors do anything to entries, admins manage
# tokens too. indah supplies the mechanism; this table is the app's policy.
POLICY = indah.Policy(
    {"viewer": ["entries:read"], "editor": ["entries:*"], "admin": ["*"]},
)


class FakeIdp:
    """A login in front of the dashboard: cookie or ``X-User`` header -> ``scope["user"]``.

    ``revoked`` models a server-side logout: after ``ctx.sign_out()`` the login is gone until
    the person signs in again at ``/login``."""

    def __init__(self, app: ASGIApp, revoked: set[str]) -> None:
        self.app = app
        self.revoked = revoked

    def _who(self, scope: Scope) -> str | None:
        headers = dict(scope["headers"])
        name = headers.get(b"x-user", b"").decode()
        if not name:
            for part in headers.get(b"cookie", b"").decode().split(";"):
                key, _, value = part.strip().partition("=")
                if key == COOKIE:
                    name = value
        return name if name in USERS and name not in self.revoked else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            name = self._who(scope)
            if name:
                scope["user"] = SimpleUser(name)
            elif scope["method"] == "GET" and scope["path"].endswith("/ui/"):
                # An anonymous visitor to the dashboard goes to the login page next door.
                await RedirectResponse("../login", status_code=302)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _authenticator(request: Request) -> indah.Principal | None:
    user = request.scope.get("user")
    if user is None:
        return None
    display, roles = USERS[user.username]
    return indah.Principal(id=user.username, name=display, roles=roles, workspace="demo")


class TokenRegistry:
    """API tokens for the whole app (semula's core would own these). Only a hash is kept: the
    secret exists in the page of whoever created it, once, and nowhere else."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.digests: dict[str, str] = {}
        self.topic: indah.Topic = indah.Topic("tokens", replay=1)

    def snapshot(self) -> list[dict[str, Any]]:
        return sorted(self.rows.values(), key=lambda r: -r["created"])

    def create(self, name: str, owner: str) -> str:
        secret = "ind_" + secrets.token_urlsafe(24)
        token_id = secret[4:12]
        self.digests[token_id] = hashlib.sha256(secret.encode()).hexdigest()
        self.rows[token_id] = {
            "id": token_id,
            "name": name,
            "owner": owner,
            "created": int(time.time() * 1000),
            "status": "active",
        }
        self.topic.publish(self.snapshot())
        return secret

    def revoke(self, token_id: str) -> bool:
        row = self.rows.get(token_id)  # a stale row may name a token that is gone: tolerate it
        if row is None or row["status"] == "revoked":
            return False
        self.rows[token_id] = {**row, "status": "revoked"}
        self.topic.publish(self.snapshot())
        return True


def build_ui(
    topics: dict[str, indah.Topic], revoked: set[str], registry: TokenRegistry | None = None
) -> Any:
    registry = registry or TokenRegistry()

    def build(ctx: indah.Context) -> indah.Session:
        me = ctx.user
        assert me is not None  # secure=True: a factory only ever runs for a signed-in user
        roles = ", ".join(sorted(me.roles))
        count = indah.Signal(0)
        notes = indah.Signal("")
        topic = topics.setdefault(me.id, indah.Topic(f"audit-{me.id}", replay=50))
        audit = ctx.tail(topic, limit=50)

        entries: indah.Signal[list[str]] = indah.Signal([])

        @indah.guard("entries:write")
        def add_entry() -> None:
            entries.set([*entries.value, f"entry {len(entries.value) + 1}"])

        def tokens_card() -> indah.Component:
            """The admin-only screen: create (revealed once), list, revoke with a confirm."""
            label = indah.Signal("")
            revealed: indah.Signal[str | None] = indah.Signal(None)
            rows = ctx.latest(registry.topic, initial=registry.snapshot())

            @indah.guard("tokens:manage")
            def create() -> None:
                revealed.set(registry.create(label.value.strip() or "unnamed", me.id))
                label.set("")
                ctx.toast("Token created. Copy it now: it is shown once.", kind="success")

            @indah.guard("tokens:manage")
            def revoke(token_id: str) -> None:
                if registry.revoke(token_id):
                    ctx.toast("Token revoked.", kind="warn")

            return indah.Card(
                title="API tokens (admins only)",
                children=[
                    indah.TextInput(
                        label, label="Name", placeholder="ci-pipeline", on_submit=create
                    ),
                    indah.Button("Create token", create),
                    indah.SecretReveal(revealed, label="New API token"),
                    indah.Table(
                        rows=rows,
                        key="id",
                        height="12rem",
                        columns=[
                            indah.Col("name"),
                            indah.Col("id", "Token id", kind="mono"),
                            indah.Col("owner"),
                            indah.Col("created", "Created", kind="time", time_format="clock"),
                            indah.Col(
                                "status", kind="badge", tones={"active": "ok", "revoked": "err"}
                            ),
                        ],
                        actions=[
                            indah.RowAction("Revoke", revoke, confirm="Revoke this token?"),
                        ],
                    ),
                ],
            )

        def sign_out() -> None:
            revoked.add(me.id)  # the fake login ends too; a real app clears its own cookie
            ctx.sign_out()

        return indah.Session(
            indah.Column(
                children=[
                    indah.Card(
                        title="Who you are",
                        children=[
                            indah.Text(f"**{me.name}** (`{me.id}`), roles: {roles}", markdown=True),
                            indah.Text(
                                f"This tab's session: `{ctx.sid[:8]}...` (a signed token)",
                                markdown=True,
                            ),
                            indah.Button(
                                "Sign out everywhere",
                                sign_out,
                                variant="ghost",
                                confirm="End all your tabs?",
                            ),
                        ],
                    ),
                    indah.Card(
                        title="Your state (per login, per tab, survives a reload)",
                        children=[
                            indah.Button("Count", lambda: count.set(count.value + 1)),
                            indah.Text(lambda: f"count = {count.value}"),
                            indah.TextArea(notes, label="Private notes", rows=3),
                        ],
                    ),
                    indah.Card(
                        title="Your audit trail (keys only, never what you typed)",
                        children=[
                            indah.Table(
                                rows=audit,
                                key="id",
                                height="14rem",
                                follow=True,
                                columns=[
                                    indah.Col(
                                        "ts", "When", kind="time", time_format="clock", width="11ch"
                                    ),
                                    indah.Col(
                                        "event",
                                        kind="badge",
                                        tones={
                                            "click": "info",
                                            "input": "neutral",
                                            "upload": "warn",
                                        },
                                    ),
                                    indah.Col("component", kind="mono"),
                                    indah.Col("keys", "Payload keys"),
                                ],
                            )
                        ],
                    ),
                    indah.Card(
                        title="Entries",
                        children=[
                            indah.Text(lambda: f"{len(entries.value)} entries (you can read)"),
                            # omitted from a viewer's page entirely, and guarded where it runs
                            *ctx.only(
                                "entries:write",
                                lambda: indah.Button("Add entry", add_entry, variant="tonal"),
                            ),
                        ],
                    ),
                    *ctx.only("tokens:manage", lambda: tokens_card()),
                ]
            )
        )

    return indah.create_app(
        session_factory=build,
        title="semula (hosted)",
        theme=indah.Theme(light={"primary": "#1f6feb"}, dark={"primary": "#79b8ff"}),
        spa=True,
        secure=True,
        secret=SECRET,
        auth=_authenticator,
        policy=POLICY,
        # hardening for a hosted app (ADR-0037, ADR-0038): the public rate limits plus a stream
        # cap, security headers and a strict CSP. Behind a gateway also set trusted_proxies.
        limits=dataclasses.replace(indah.Limits.public(), max_streams_per_ip=10),
        security_headers=True,
        csp="strict",
        proxy_flush=False,
        audit=lambda e: _record(topics, e),
    )


_seq = 0


def _record(topics: dict[str, indah.Topic], event: Any) -> None:
    """The audit hook: one row per event on the user's own topic."""
    global _seq
    if event.user is None or event.user not in topics:
        return
    _seq += 1
    topics[event.user].publish(
        {
            "id": _seq,
            "ts": int(event.ts * 1000),
            "event": event.event,
            "component": event.component,
            "keys": ", ".join(event.payload_keys) or "none",
        }
    )


def _login_page() -> str:
    rows = "".join(
        f'<li><a href="login?user={name}">{html.escape(display)}</a> '
        f"<small>{html.escape(', '.join(sorted(roles)))}</small></li>"
        for name, (display, roles) in USERS.items()
    )
    return (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Sign in</title><style>body{font:16px system-ui;max-width:32rem;margin:3rem auto;"
        "padding:0 1rem}li{margin:.8rem 0}small{color:#666}</style>"
        "<h1>Sign in (fake identity provider)</h1><p>Pick a user. Use a second browser profile "
        "for a second user: each gets its own session and cannot open the other's.</p>"
        f"<ul>{rows}</ul>"
    )


def build_app() -> Starlette:
    revoked: set[str] = set()
    topics: dict[str, indah.Topic] = {}
    registry = TokenRegistry()
    ui = FakeIdp(build_ui(topics, revoked, registry), revoked)

    async def login(request: Request) -> Response:
        name = request.query_params.get("user")
        if name not in USERS:
            return HTMLResponse(_login_page())
        revoked.discard(name)
        response = RedirectResponse("ui/", status_code=302)
        response.set_cookie(COOKIE, name, httponly=True, samesite="lax", path="/")
        return response

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("login", status_code=302)

    app = Starlette(routes=[Route("/", root), Route("/login", login), Mount("/ui", app=ui)])
    app.state.revoked = revoked
    app.state.topics = topics
    app.state.tokens = registry
    app.state.ui = ui
    return app


if __name__ == "__main__":
    indah.launch(build_app())

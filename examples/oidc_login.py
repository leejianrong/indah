"""Log in with OpenID Connect in the parent app, and hand the result to indah (a recipe).

indah does not log anyone in (ADR-0033). The parent app owns the login; indah is told who the
caller is through an ``Authenticator`` and then keeps sessions apart. This file is the whole
pattern with `authlib <https://docs.authlib.org>`_ (``pip install authlib itsdangerous``), against
any OIDC provider (Google, Okta, Keycloak, Auth0, Entra ID...):

    OIDC_ISSUER=https://accounts.example.com \\
    OIDC_CLIENT_ID=... OIDC_CLIENT_SECRET=... SESSION_SECRET=$(openssl rand -hex 32) \\
    python examples/oidc_login.py

Register ``<your url>/callback`` as the redirect URI with the provider. The flow:

1. An anonymous visit to ``/ui/`` is sent to ``/login``, which sends the browser to the provider
   (authorization code flow with PKCE, ``state`` and ``nonce``, all done by authlib).
2. The provider sends the browser back to ``/callback``. authlib swaps the code for tokens,
   checks the ID token's signature (against the provider's published keys), issuer, audience,
   expiry and nonce, and returns its claims.
3. We keep a few claims in Starlette's signed session cookie, and ``who`` turns them into a
   :class:`indah.Principal` on every request. ``Principal.expires_at`` ends an open stream when
   the login lapses; the roles feed ``ctx.can`` and ``guard`` (ADR-0035).
4. ``/logout`` clears the cookie and ends every indah session that user holds.

Nothing here is indah-specific except ``who`` and the ``create_app`` call; swap authlib for any
library that can answer "who is this request?". For production set ``https_only=True`` on the
session cookie (it is off here so the recipe runs on http://localhost) and keep ``SESSION_SECRET``
in your secret store.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from authlib.integrations.starlette_client import OAuth
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

import indah

logger = logging.getLogger("indah")

# Which ID-token claim carries the roles (Keycloak and Auth0 differ; "groups" is common too).
ROLES_CLAIM = "roles"
WORKSPACE_CLAIM = "workspace"


def who(request: Request) -> indah.Principal | None:
    """The :class:`indah.Principal` for this request, from the login stored in the session."""
    user: dict[str, Any] | None = request.session.get("user")
    if not user:
        return None
    return indah.Principal(
        id=user["sub"],
        name=user.get("name", ""),
        email=user.get("email", ""),
        roles=frozenset(user.get("roles", ())),
        workspace=user.get("workspace"),
        expires_at=user.get("exp"),  # past this, indah treats the caller as nobody
    )


def build_dashboard(secret: str) -> Any:
    """The indah app: everything it needs from the login is ``auth=who``."""

    def build(ctx: indah.Context) -> indah.Session:
        me = ctx.user
        assert me is not None  # secure=True: only a signed-in user reaches the factory
        return indah.Session(
            indah.Column(
                children=[
                    indah.Text(f"Signed in as **{me.name or me.id}** ({me.email})", markdown=True),
                    indah.Text(f"Roles: {', '.join(sorted(me.roles)) or 'none'}"),
                    *ctx.only("admin", lambda: indah.Text("Only admins see this line.")),
                ]
            )
        )

    return indah.create_app(
        session_factory=build, auth=who, secure=True, secret=secret, spa=True, title="OIDC demo"
    )


class _LoginRequired:
    """Send an anonymous visitor to ``/login`` instead of showing the dashboard's 401."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"].endswith("/ui/"):
            if not scope.get("session", {}).get("user"):
                await RedirectResponse("../login", status_code=302)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    session_secret: str,
    indah_secret: str | None = None,
    https_only: bool = False,
) -> Starlette:
    oauth = OAuth()
    oauth.register(
        "idp",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=f"{issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )
    dashboard = build_dashboard(indah_secret or session_secret)

    async def login(request: Request) -> Response:
        return await oauth.idp.authorize_redirect(request, str(request.url_for("callback")))

    async def callback(request: Request) -> Response:
        try:
            token = await oauth.idp.authorize_access_token(request)  # verifies the ID token
        except Exception as exc:  # fail closed: any token that does not verify is no login
            # (a bad signature, issuer, audience, nonce or expiry; authlib raises its own
            # OAuthError and, for a bad signature, a JOSE error). Log it, tell the user nothing.
            logger.warning("OIDC login refused: %s", type(exc).__name__)
            return PlainTextResponse("Login failed.", status_code=400)
        claims = token["userinfo"]
        request.session["user"] = {
            "sub": claims["sub"],
            "name": claims.get("name", ""),
            "email": claims.get("email", ""),
            "roles": list(claims.get(ROLES_CLAIM, [])),
            "workspace": claims.get(WORKSPACE_CLAIM),
            "exp": claims.get("exp"),
        }
        return RedirectResponse("ui/", status_code=302)  # relative to /callback

    async def logout(request: Request) -> Response:
        user = request.session.pop("user", None)
        if user:  # end this person's open indah tabs too, not just the cookie
            request.app.state.dashboard.state.store.discard_where(owner=user["sub"])
        return RedirectResponse(request.url_for("login"), status_code=302)

    async def ui_root(request: Request) -> Response:  # name for url_for; Mount serves /ui/
        return RedirectResponse("ui/", status_code=302)

    app = Starlette(
        routes=[
            Route("/", ui_root, name="ui_root"),
            Route("/login", login, name="login"),
            Route("/callback", callback, name="callback"),
            Route("/logout", logout, name="logout"),
            Mount("/ui", app=_LoginRequired(dashboard)),
        ],
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key=session_secret,
                https_only=https_only,
                same_site="lax",
            )
        ],
    )
    app.state.dashboard = dashboard
    return app


if __name__ == "__main__":
    indah.launch(
        build_app(
            issuer=os.environ["OIDC_ISSUER"],
            client_id=os.environ["OIDC_CLIENT_ID"],
            client_secret=os.environ["OIDC_CLIENT_SECRET"],
            session_secret=os.environ["SESSION_SECRET"],
        )
    )

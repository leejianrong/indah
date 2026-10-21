"""A tiny in-process OpenID Connect provider for testing login flows (IND-122).

Just enough of the authorization-code flow for authlib's client: discovery, ``/authorize``
(auto-approves as the configured user), ``/token`` (PKCE checked) and ``/jwks``. The ID token is
RS256-signed. ``misbehave`` makes it issue a bad token so a client's checks can be tested:
``"key"`` (signed by another key), ``"aud"`` (wrong audience), ``"nonce"``, ``"expired"``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from authlib.jose import JsonWebKey, jwt
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route


class TestIdp:
    __test__ = False  # not a pytest class

    def __init__(self, *, client_id: str = "indah-test", client_secret: str = "shh") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer = ""  # set once the server is listening and its URL is known
        self.user: dict[str, Any] = {"sub": "dana", "name": "Dana Ho", "email": "dana@example.com"}
        self.misbehave: str | None = None
        self.key = JsonWebKey.generate_key("RSA", 2048, {"kid": "k1"}, is_private=True)
        self.other_key = JsonWebKey.generate_key("RSA", 2048, {"kid": "k1"}, is_private=True)
        self._codes: dict[str, dict[str, Any]] = {}
        self.app = Starlette(
            routes=[
                Route("/.well-known/openid-configuration", self._discovery),
                Route("/authorize", self._authorize),
                Route("/token", self._token, methods=["POST"]),
                Route("/jwks", self._jwks),
            ]
        )

    async def _discovery(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    async def _jwks(self, request: Request) -> JSONResponse:
        return JSONResponse({"keys": [self.key.as_dict(is_private=False)]})

    async def _authorize(self, request: Request) -> RedirectResponse:
        q = request.query_params
        code = secrets.token_urlsafe(16)
        self._codes[code] = {
            "nonce": q.get("nonce"),
            "challenge": q.get("code_challenge"),
            "redirect_uri": q["redirect_uri"],
        }
        back = {"code": code, "state": q.get("state", "")}
        return RedirectResponse(f"{q['redirect_uri']}?{urlencode(back)}", status_code=302)

    async def _token(self, request: Request) -> JSONResponse:
        form = await request.form()
        entry = self._codes.pop(str(form.get("code")), None)
        if entry is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if entry["challenge"]:
            digest = hashlib.sha256(str(form.get("code_verifier")).encode()).digest()
            want = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if want != entry["challenge"]:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": "someone-else" if self.misbehave == "aud" else self.client_id,
            "iat": now,
            "exp": now - 3600 if self.misbehave == "expired" else now + 3600,
            "nonce": "wrong" if self.misbehave == "nonce" else entry["nonce"],
            **self.user,
        }
        key = self.other_key if self.misbehave == "key" else self.key
        id_token = jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key).decode()
        return JSONResponse(
            {
                "access_token": secrets.token_urlsafe(16),
                "token_type": "Bearer",
                "id_token": id_token,
            }
        )

"""The OIDC recipe (examples/oidc_login.py) against a test provider (IND-122).

Both the provider and the app run as real servers: the flow is a browser redirect dance with a
server-to-server token exchange, which an in-process transport cannot stand in for. A login that
fails any of authlib's checks must leave the caller with no indah session.
"""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("authlib")

from indah import launch  # noqa: E402
from tests.oidc_idp import TestIdp  # noqa: E402

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "oidc_login.py"
spec = importlib.util.spec_from_file_location("oidc_login_example", _EXAMPLE)
ex = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ex
spec.loader.exec_module(ex)


@pytest.fixture
def stack():
    idp = TestIdp()
    idp_handle = launch(idp.app, block=False, open_inline=False)
    idp.issuer = idp_handle.url.rstrip("/")
    app = ex.build_app(
        issuer=idp.issuer,
        client_id=idp.client_id,
        client_secret=idp.client_secret,
        session_secret="a-long-random-session-secret-0123456789",
    )
    handle = launch(app, block=False, open_inline=False)
    base = handle.url.rstrip("/")
    try:
        yield idp, app, base
    finally:
        handle.stop()
        idp_handle.stop()


def _connect(client, base, token):
    """What the shell does before it clicks: open the stream (the session is built), then let go."""
    with client.stream("GET", f"{base}/ui/api/stream", params={"sid": token}, timeout=5):
        pass


def _session(client: httpx.Client, base: str):
    return client.post(f"{base}/ui/api/session", json={})


@pytest.mark.integration
def test_login_through_the_provider_gives_indah_a_principal_with_roles(stack):
    idp, app, base = stack
    idp.user = {**idp.user, "roles": ["admin"], "workspace": "acme"}
    with httpx.Client(follow_redirects=True) as client:
        assert _session(client, base).status_code == 401  # not logged in: nobody
        page = client.get(f"{base}/ui/")  # anonymous -> /login -> provider -> /callback -> /ui/
        assert page.status_code == 200 and str(page.url) == f"{base}/ui/"
        reply = _session(client, base)
        assert reply.status_code == 200 and reply.json()["user"] == {
            "id": "dana",
            "name": "Dana Ho",
        }
        token = reply.json()["token"]
        # the factory ran for dana with her roles: an admin-only line is in her tree
        assert app.state.dashboard.state.store.get(token.split(".")[0]) is None  # lazily made
        _connect(client, base, token)
        client.post(f"{base}/ui/api/event", json={"sid": token, "component": "n0", "event": "x"})
        tree = str(app.state.dashboard.state.store.get(token.split(".")[0]).session.snapshot())
        assert "Dana Ho" in tree and "Only admins see this line." in tree


@pytest.mark.integration
def test_a_login_without_the_admin_role_does_not_get_the_admin_subtree(stack):
    idp, app, base = stack
    idp.user = {**idp.user, "roles": ["viewer"]}
    with httpx.Client(follow_redirects=True) as client:
        client.get(f"{base}/ui/")
        token = _session(client, base).json()["token"]
        _connect(client, base, token)
        client.post(f"{base}/ui/api/event", json={"sid": token, "component": "n0", "event": "x"})
    tree = str(app.state.dashboard.state.store.get(token.split(".")[0]).session.snapshot())
    assert "Only admins see this line." not in tree and "viewer" in tree


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["key", "aud", "nonce", "expired"])
def test_a_bad_id_token_is_refused_and_creates_no_session(stack, fault):
    idp, app, base = stack
    idp.misbehave = fault
    with httpx.Client(follow_redirects=True) as client:
        result = client.get(f"{base}/ui/")
        assert result.status_code == 400 and "Login failed" in result.text
        assert _session(client, base).status_code == 401
    assert len(app.state.dashboard.state.store) == 0


@pytest.mark.integration
def test_logout_ends_the_login_and_the_indah_sessions(stack):
    idp, app, base = stack
    with httpx.Client(follow_redirects=True) as client:
        client.get(f"{base}/ui/")
        token = _session(client, base).json()["token"]
        _connect(client, base, token)
        client.post(f"{base}/ui/api/event", json={"sid": token, "component": "n0", "event": "x"})
        assert len(app.state.dashboard.state.store) == 1
        out = client.get(f"{base}/logout")  # then it redirects to /login and logs in again
        assert out.status_code == 200
        # the old session was ended by logout (a fresh login makes a new token, not this one)
        assert app.state.dashboard.state.store.get(token.split(".")[0]) is None

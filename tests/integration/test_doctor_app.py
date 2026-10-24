"""The deploy doctor page in a real app (IND-205): gated, off by default, and it never leaks."""

import json
import re

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

import indah
from indah import Policy, Principal, create_app

pytestmark = pytest.mark.integration

TOKEN = "doctor-token-0123456789"
PATH = "/_indah/doctor"


def client(app, peer="172.16.1.2"):
    return TestClient(app, client=(peer, 50000))


def plain(**kw):
    return create_app(session_factory=lambda: indah.Session(indah.Text("hi")), **kw)


def test_off_by_default():
    assert client(plain()).get(PATH).status_code == 404


def test_a_token_gate_refuses_everything_else_with_a_plain_404(monkeypatch):
    monkeypatch.delenv("INDAH_DOCTOR_TOKEN", raising=False)
    c = client(plain(doctor=TOKEN))
    nothing = c.get(PATH)
    wrong = c.get(PATH, headers={"Authorization": "Bearer nope-nope-nope-nope"})
    bare = c.get(PATH, params={"token": "nope-nope-nope-nope"})
    for r in (nothing, wrong, bare):
        assert r.status_code == 404
        assert r.text == "Not Found"  # the same body as any missing route: it does not advertise
    assert client(plain()).get("/no/such/route").text == "Not Found"


def test_the_right_token_by_header_or_query_gets_the_page():
    c = client(plain(doctor=TOKEN))
    by_header = c.get(PATH, headers={"Authorization": f"Bearer {TOKEN}"})
    by_query = c.get(PATH, params={"token": TOKEN})
    for r in (by_header, by_query):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["cache-control"] == "no-store"
        assert "noindex" in r.headers["x-robots-tag"]
        assert r.headers["referrer-policy"] == "no-referrer"


def test_json_format_is_valid_and_shaped():
    c = client(plain(doctor=TOKEN, trusted_proxies=["172.16.0.0/12"]))
    r = c.get(PATH, params={"format": "json"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["indah_version"] == indah.__version__
    assert data["request"]["socket_peer"] == "172.16.1.2"
    assert data["trusted_proxies"] == ["172.16.0.0/12"]
    assert data["drain"]["draining"] is False
    assert data["sessions"]["open_streams"] == 0
    assert isinstance(data["warnings"], list)


def test_the_token_and_the_secret_never_appear_in_the_output():
    secret = "app-secret-not-for-output-0123"
    app = create_app(
        session_factory=lambda: indah.Session(indah.Text("hi")),
        secure=True,
        secret=secret,
        auth=lambda request: None,
        doctor=TOKEN,
    )
    c = client(app)
    for kwargs in (
        {"headers": {"Authorization": f"Bearer {TOKEN}"}},
        {"params": {"token": TOKEN}},
        {"params": {"token": TOKEN, "format": "json"}},
    ):
        r = c.get(PATH, **kwargs)
        assert r.status_code == 200
        assert TOKEN not in r.text and secret not in r.text


def test_environment_variable_values_are_not_shown_only_names(monkeypatch):
    monkeypatch.setenv("INDAH_DOCTOR_TOKEN", TOKEN)
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "172.16.0.0/12")
    c = client(plain())
    r = c.get(PATH, params={"format": "json", "token": TOKEN})
    assert r.status_code == 200
    data = r.json()
    assert "INDAH_DOCTOR_TOKEN" in data["settings"]["environment_variables_used"]
    assert TOKEN not in r.text


def test_an_explicit_off_beats_the_environment(monkeypatch):
    monkeypatch.setenv("INDAH_DOCTOR_TOKEN", TOKEN)
    for off in (None, False):
        assert client(plain(doctor=off)).get(PATH, params={"token": TOKEN}).status_code == 404


def test_only_allowlisted_headers_are_echoed_and_values_are_escaped():
    c = client(plain(doctor=TOKEN))
    r = c.get(
        PATH,
        params={"format": "json"},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Cookie": "session=SECRET-COOKIE",
            "X-Evil": "should-not-show",
            "Via": "1.1 <script>alert(1)</script>",
            "X-Forwarded-For": "1.2.3.4",
        },
    )
    body = r.text
    assert "SECRET-COOKIE" not in body and "should-not-show" not in body
    assert r.json()["request"]["cookie_sent"] is True  # a flag, never the cookie
    page = c.get(
        PATH,
        headers={"Authorization": f"Bearer {TOKEN}", "Via": "1.1 <script>alert(1)</script>"},
    ).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_page_sets_its_own_strict_csp_and_the_inline_script_carries_the_nonce():
    for app_csp in (None, "strict"):
        c = client(plain(doctor=TOKEN, csp=app_csp))
        r = c.get(PATH, headers={"Authorization": f"Bearer {TOKEN}"})
        policy = r.headers["content-security-policy"]
        nonce = re.search(r"'nonce-([^']+)'", policy).group(1)
        assert "default-src 'none'" in policy and "frame-ancestors 'none'" in policy
        assert f'<script nonce="{nonce}">' in r.text and f'<style nonce="{nonce}">' in r.text
    # a fresh nonce per response
    first = c.get(PATH, params={"token": TOKEN}).headers["content-security-policy"]
    second = c.get(PATH, params={"token": TOKEN}).headers["content-security-policy"]
    assert first != second


def test_repeated_wrong_tokens_lock_the_address_out_even_for_the_right_one():
    app = plain(doctor=TOKEN)
    c = client(app, peer="203.0.113.9")
    for _ in range(app.state.doctor.MAX_FAILURES):
        assert c.get(PATH, params={"token": "wrong-wrong-wrong-wrong"}).status_code == 404
    assert c.get(PATH, params={"token": TOKEN}).status_code == 404  # locked out
    other = client(app, peer="203.0.113.10")
    assert other.get(PATH, params={"token": TOKEN}).status_code == 200


def principal_from_header(request):
    who = request.headers.get("x-user")
    if not who:
        return None
    roles = {"admin"} if who == "ada" else {"viewer"}
    return Principal(id=who, roles=roles)


def secure_app(**kw):
    return create_app(
        session_factory=lambda: indah.Session(indah.Text("hi")),
        secure=True,
        secret="s" * 24,
        auth=principal_from_header,
        policy=Policy({"admin": ["doctor"], "viewer": ["read"]}),
        **kw,
    )


def test_the_permission_gate_admits_only_a_principal_holding_doctor():
    c = client(secure_app(doctor=True))
    assert c.get(PATH).status_code == 404  # nobody
    assert c.get(PATH, headers={"x-user": "bob"}).status_code == 404  # no permission
    assert c.get(PATH, headers={"x-user": "ada"}).status_code == 200


def test_a_token_app_with_a_policy_accepts_either_door():
    c = client(secure_app(doctor=TOKEN))
    assert c.get(PATH, params={"token": TOKEN}).status_code == 200
    assert c.get(PATH, headers={"x-user": "ada"}).status_code == 200
    assert c.get(PATH, headers={"x-user": "bob"}).status_code == 404


def test_doctor_true_without_a_login_is_refused_at_startup():
    with pytest.raises(ValueError, match="secure=True"):
        plain(doctor=True)


def test_a_short_environment_token_names_the_variable(monkeypatch):
    monkeypatch.setenv("INDAH_DOCTOR_TOKEN", "short")
    with pytest.raises(ValueError, match="INDAH_DOCTOR_TOKEN"):
        plain()


def test_it_works_under_a_mount_prefix_and_beats_the_spa_catch_all():
    inner = plain(doctor=TOKEN, spa=True)
    parent = Starlette(routes=[Mount("/ui", app=inner)])
    c = client(parent)
    r = c.get("/ui/_indah/doctor", params={"token": TOKEN})
    assert r.status_code == 200 and "Deploy doctor" in r.text
    # and still the shell for any other in-app path
    assert "Deploy doctor" not in c.get("/ui/projects/auth").text


def test_it_reads_the_resolved_client_and_the_real_peer_behind_a_trusted_proxy():
    c = client(plain(doctor=TOKEN, trusted_proxies=["172.16.0.0/12", "66.241.124.81"]))
    r = c.get(
        PATH,
        params={"format": "json"},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Forwarded-For": "6.6.6.6, 122.11.212.50, 66.241.124.81",
            "X-Forwarded-Proto": "https",
            "Fly-Client-IP": "122.11.212.50",
        },
    )
    req = r.json()["request"]
    assert req["resolved_client"] == "122.11.212.50"  # not the forged 6.6.6.6
    assert req["socket_peer"] == "172.16.1.2"  # the peer survives the rewrite
    assert req["resolved_scheme"] == "https" and req["socket_scheme"] == "http"
    assert r.json()["warnings"] == [] or all(w["level"] != "warn" for w in r.json()["warnings"])


def test_the_default_fly_mistake_is_called_out():
    c = client(plain(doctor=TOKEN, trusted_proxies=["172.16.0.0/12"]))
    r = c.get(
        PATH,
        params={"format": "json"},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Forwarded-For": "122.11.212.50, 66.241.124.81",
            "Fly-Client-IP": "122.11.212.50",
        },
    )
    assert r.json()["request"]["resolved_client"] == "66.241.124.81"
    assert any("fly ips list" in w["text"] for w in r.json()["warnings"])


def test_drain_state_and_counts_are_live():
    app = plain(doctor=TOKEN)
    c = client(app)
    one = c.get(PATH, params={"token": TOKEN, "format": "json"}).json()
    two = c.get(PATH, params={"token": TOKEN, "format": "json"}).json()
    assert two["process"]["requests_answered"] == one["process"]["requests_answered"] + 1
    app.state.drain.draining = True
    r = c.get(PATH, params={"token": TOKEN, "format": "json"}).json()
    assert r["drain"]["draining"] is True
    assert any("draining" in w["text"] for w in r["warnings"])
    assert "node" in r and r["node"] == app.state.node


def test_session_counts_follow_the_store():
    app = plain(doctor=TOKEN)
    c = client(app)
    app.state.store.get_or_create("s1")
    app.state.store.get_or_create("s2")
    got = c.get(PATH, params={"token": TOKEN, "format": "json"}).json()["sessions"]
    assert got["open"] == 2 and got["open_streams"] == 0 and got["max_sessions"] is None


def test_the_html_page_has_the_sections_a_deployer_looks_for():
    c = client(plain(doctor=TOKEN, trusted_proxies=["172.16.0.0/12"]))
    page = c.get(PATH, params={"token": TOKEN}).text
    for text in ("Deploy doctor", "Resolved client", "Socket peer", "trusted_proxies", "Drain"):
        assert text in page
    json.loads(
        re.search(r'<pre id="facts-json"[^>]*>(.*?)</pre>', page, re.S)
        .group(1)
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )

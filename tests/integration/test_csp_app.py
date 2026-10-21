"""``create_app(csp=...)`` end to end (ADR-0038, IND-121)."""

import re

import httpx
import pytest

from indah import Theme, create_app
from indah.components import Column, Map, Text
from indah.session import Session


def _build():
    return Session(Column(children=[Text("hi")]))


def _client(asgi) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), base_url="http://test")


def _nonce(policy: str) -> str:
    return re.search(r"script-src 'nonce-([^']+)'", policy).group(1)


@pytest.mark.integration
async def test_off_by_default_no_header_and_no_nonce_and_no_report_route():
    app = create_app(session_factory=_build)
    async with _client(app) as client:
        page = await client.get("/")
        report = await client.post("/api/csp-report", content=b"{}")
    assert "content-security-policy" not in page.headers
    assert "nonce=" not in page.text
    assert report.status_code in (404, 405)


@pytest.mark.integration
async def test_strict_policy_nonces_every_inline_tag_with_a_fresh_nonce_per_response():
    app = create_app(session_factory=_build, csp="strict", theme=Theme(radius="4px"), title="x")
    async with _client(app) as client:
        a, b = await client.get("/"), await client.get("/")
    na, nb = (
        _nonce(a.headers["content-security-policy"]),
        _nonce(b.headers["content-security-policy"]),
    )
    assert na != nb
    tags = re.findall(r"<(?:script|style)\b[^>]*>", a.text)
    assert len(tags) >= 5  # the shell's own, the theme style and the chrome script
    assert all(f'nonce="{na}"' in t for t in tags)
    assert f'nonce="{nb}"' not in a.text
    assert a.headers["cache-control"] == "no-store"  # a cached nonce would be reused


@pytest.mark.integration
async def test_the_report_uri_resolves_from_a_deep_link():
    app = create_app(session_factory=_build, csp="strict", spa=True)
    async with _client(app) as client:
        root = await client.get("/")
        deep = await client.get("/projects/auth/entries/01J")
    assert "report-uri api/csp-report" in root.headers["content-security-policy"]
    assert "report-uri ../../../api/csp-report" in deep.headers["content-security-policy"]
    assert "content-security-policy" in deep.headers


@pytest.mark.integration
async def test_violation_reports_are_recorded_and_capped_not_trusted():
    app = create_app(session_factory=_build, csp="strict")
    report = (
        b'{"csp-report":{"violated-directive":"script-src-elem","blocked-uri":"inline",'
        b'"document-uri":"http://t/"}}'
    )
    async with _client(app) as client:
        ok = await client.post(
            "/api/csp-report", content=report, headers={"Content-Type": "application/csp-report"}
        )
        junk = await client.post("/api/csp-report", content=b"\xff\xfenot json")
        huge = await client.post("/api/csp-report", content=b"x" * 100_000)
        for _ in range(150):
            await client.post("/api/csp-report", content=report)
    assert ok.status_code == 204 and junk.status_code == 204 and huge.status_code == 204
    assert 1 <= len(app.state.csp_violations) <= 100
    assert app.state.csp_violations[0]["violated-directive"] == "script-src-elem"


@pytest.mark.integration
async def test_extra_image_hosts_and_a_maps_tile_host_are_allowed():
    Map(center=(1, 1), tile_url="https://tiles.maps-test.example/{z}/{x}/{y}.png")
    app = create_app(
        session_factory=_build, csp="strict", csp_media_hosts=["https://img.cdn-test.example"]
    )
    async with _client(app) as client:
        policy = (await client.get("/")).headers["content-security-policy"]
    img = re.search(r"img-src ([^;]+)", policy).group(1)
    assert "https://img.cdn-test.example" in img
    assert "https://tiles.maps-test.example" in img
    assert "https://tile.openstreetmap.org" in img


@pytest.mark.integration
async def test_a_custom_policy_string_is_used_with_the_nonce_filled_in():
    app = create_app(session_factory=_build, csp="default-src 'self'; script-src 'nonce-{nonce}'")
    async with _client(app) as client:
        page = await client.get("/")
    policy = page.headers["content-security-policy"]
    n = _nonce(policy)
    assert policy.startswith("default-src 'self'") and f'nonce="{n}"' in page.text
    assert "csp-report" not in policy  # a custom policy is the operator's, verbatim


@pytest.mark.integration
def test_csp_must_be_none_strict_or_a_string():
    for bad in (True, 3, ""):
        with pytest.raises(ValueError):
            create_app(session_factory=_build, csp=bad)

"""Trusted proxies and the audit hook over HTTP (ADR-0034, IND-116).

The failure cases carry the weight: forwarded headers from a peer that was not named must be
ignored, and the audit log must never hold what a user typed unless the app asked for it.
"""

import asyncio

import httpx
import pytest

from indah import create_app
from indah.components import Button, Column, Text, TextInput
from indah.reactive import Signal
from indah.session import Session

SECRET = "a-long-random-secret-value-0123456789"


def _client(app, peer="203.0.113.50") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(peer, 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://app.internal")


def _capture_app(**kw):
    seen = []

    def build(ctx) -> Session:
        seen.append(ctx.conn)
        return Session(Column(children=[Button("go", on_click=lambda: None), Text("x")]))

    return create_app(session_factory=build, **kw), seen


async def _click(client, sid="t", **kw):
    return await client.post(
        "/api/event", json={"sid": sid, "component": "n1", "event": "click"}, **kw
    )


FORGED = {
    "X-Forwarded-For": "6.6.6.6",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "evil.example",
    "X-Forwarded-Prefix": "/evil",
}


@pytest.mark.integration
async def test_forwarded_headers_from_an_untrusted_peer_are_ignored():
    for kw in ({}, {"trusted_proxies": ["10.0.0.0/8"]}):  # none named / someone else named
        app, seen = _capture_app(**kw)
        async with _client(app, peer="203.0.113.50") as client:
            assert (await _click(client, headers=FORGED)).status_code == 200
        conn = seen[0]
        assert conn.client == "203.0.113.50" and conn.prefix == ""
        assert conn.headers["host"] == "app.internal"


@pytest.mark.integration
async def test_forwarded_headers_from_a_trusted_peer_are_believed_and_sanitised():
    app, seen = _capture_app(trusted_proxies=["10.0.0.0/8"])
    async with _client(app, peer="10.1.2.3") as client:
        hdrs = {
            "X-Forwarded-For": "6.6.6.6, 198.51.100.4, 10.9.9.9",
            "X-Forwarded-Host": "portal.example.com",
            "X-Forwarded-Prefix": "/ui/",
        }
        assert (await _click(client, headers=hdrs)).status_code == 200
        conn = seen[0]
        assert conn.client == "198.51.100.4"  # not the 6.6.6.6 the caller prepended
        assert conn.prefix == "/ui" and conn.headers["host"] == "portal.example.com"
        # junk prefix and host from a trusted peer are dropped, not repaired
        junk = {"X-Forwarded-Prefix": "//evil.example", "X-Forwarded-Host": "a b/c"}
        assert (await _click(client, sid="t2", headers=junk)).status_code == 200
        assert seen[1].prefix == "" and seen[1].headers["host"] == "app.internal"


@pytest.mark.integration
async def test_the_public_scheme_reaches_the_origin_guard_only_through_a_trusted_proxy():
    # TLS ends at the proxy, so the app sees http while the browser's Origin says https
    hdrs = {"Origin": "https://portal.example.com", "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "portal.example.com", "X-User": "x"}  # fmt: skip
    for peer, expected in (("10.1.2.3", 200), ("203.0.113.50", 403)):
        app = create_app(
            session_factory=lambda: Session(Column(children=[Text("x")])),
            secure=True,
            secret=SECRET,
            auth=lambda r: __import__("indah").Principal(id="u"),
            trusted_proxies=["10.0.0.0/8"],
        )
        async with _client(app, peer=peer) as client:
            resp = await client.post("/api/session", json={}, headers=hdrs)
        assert resp.status_code == expected, peer


@pytest.mark.integration
def test_trusted_proxies_refuses_wildcards_at_startup():
    for bad in (["*"], ["0.0.0.0/0"], ["nope"]):
        with pytest.raises(ValueError, match="trusted_proxies"):
            create_app(trusted_proxies=bad)


def _audited_app(**kw):
    events: list = []
    text, secret = Signal(""), Signal("")
    root = Column(
        children=[
            Button("go", on_click=lambda: None),
            TextInput(text, label="note"),
            TextInput(secret, label="key", password=True),
        ]
    )
    app = create_app(session_factory=lambda: Session(root), audit=events.append, **kw)
    return app, events


async def _post(client, component, event, payload, sid="s1"):
    resp = await client.post(
        "/api/event", json={"sid": sid, "component": component, "event": event, "payload": payload}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
async def test_audit_names_who_and_what_but_not_the_values_by_default():
    app, events = _audited_app()
    async with _client(app) as client:
        await _post(client, "n1", "click", {})
        await _post(client, "n2", "input", {"value": "my private note"})
    click, typed = events
    assert (click.component, click.event, click.payload_keys, click.sid) == (
        "n1",
        "click",
        (),
        "s1",
    )
    assert typed.payload_keys == ("value",) and typed.payload is None
    assert "private" not in repr(events) and typed.user is None and typed.ts > 0


@pytest.mark.integration
async def test_audit_payloads_opt_in_still_never_includes_a_password_field():
    app, events = _audited_app(audit_payloads=True)
    async with _client(app) as client:
        await _post(client, "n2", "input", {"value": "visible by request"})
        await _post(client, "n3", "input", {"value": "hunter2-api-key"})
    note, key = events
    assert note.payload == {"value": "visible by request"}
    assert key.payload_keys == ("value",) and key.payload is None
    assert "hunter2" not in repr(events)


@pytest.mark.integration
async def test_audit_records_the_principal_and_skips_rejected_events():
    from indah import Principal

    app, events = _audited_app(auth=lambda r: Principal(id="alice"))
    async with _client(app) as client:
        await _post(client, "n1", "click", {})
        bad = await client.post(
            "/api/event", json={"sid": "s1", "component": "nope", "event": "click"}
        )
        assert bad.status_code == 400
    assert [e.user for e in events] == ["alice"] and len(events) == 1


@pytest.mark.integration
async def test_a_failing_audit_hook_never_breaks_the_request_and_async_hooks_run():
    def boom(event):
        raise RuntimeError("log shipper down")

    app = create_app(
        session_factory=lambda: Session(Column(children=[Button("g", on_click=lambda: None)])),
        audit=boom,
    )
    async with _client(app) as client:
        assert (await _click(client)).status_code == 200

    got = []

    async def slow(event):
        await asyncio.sleep(0)
        got.append(event.component)

    app = create_app(
        session_factory=lambda: Session(Column(children=[Button("g", on_click=lambda: None)])),
        audit=slow,
    )
    async with _client(app) as client:
        assert (await _click(client)).status_code == 200
        await asyncio.sleep(0.01)
    assert got == ["n1"]


@pytest.mark.integration
async def test_uploads_are_audited_with_keys_not_file_names_unless_asked():
    from indah.components import Upload

    for opt_in in (False, True):
        events: list = []
        app = create_app(
            session_factory=lambda: Session(
                Column(children=[Upload(on_upload=lambda files: None)])
            ),
            audit=events.append,
            audit_payloads=opt_in,
        )
        async with _client(app) as client:
            resp = await client.post(
                "/api/upload",
                data={"component": "n1", "sid": "s1"},
                files={"file": ("tax-return.pdf", b"x")},
            )
        assert resp.status_code == 200
        (up,) = events
        assert (up.event, up.payload_keys) == ("upload", ("files",))
        assert (up.payload is not None) == opt_in
        assert ("tax-return" in repr(events)) == opt_in

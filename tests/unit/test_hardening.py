"""Rate limit, security headers, stream cap and Limits (ADR-0037, IND-120)."""

import pytest

from indah.hardening import (
    Limits,
    Rate,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    StreamLimiter,
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _call(app, path="/api/event", client=("1.1.1.1", 1), headers=()):
    out = {}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = dict(message["headers"])

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": list(headers),
        "client": client,
    }
    await app(scope, receive, send)
    return out


@pytest.mark.unit
async def test_a_burst_is_allowed_then_429_with_retry_after_then_it_refills():
    clock = Clock()
    app = RateLimitMiddleware(_ok_app, {"/api/event": Rate(per_second=1, burst=3)}, clock=clock)
    codes = [(await _call(app))["status"] for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = await _call(app)
    assert int(blocked["headers"][b"retry-after"]) >= 1
    clock.now += 2.0
    assert (await _call(app))["status"] == 200


@pytest.mark.unit
async def test_buckets_are_per_address_and_per_route_and_other_paths_are_free():
    clock = Clock()
    rates = {"/api/event": Rate(1, 1), "/api/upload": Rate(1, 1)}
    app = RateLimitMiddleware(_ok_app, rates, clock=clock)
    assert (await _call(app, client=("1.1.1.1", 1)))["status"] == 200
    assert (await _call(app, client=("1.1.1.1", 1)))["status"] == 429
    assert (await _call(app, client=("2.2.2.2", 1)))["status"] == 200  # another address
    assert (await _call(app, "/api/upload", client=("1.1.1.1", 1)))["status"] == 200  # route
    for _ in range(10):
        assert (await _call(app, "/health"))["status"] == 200  # not a limited route


@pytest.mark.unit
async def test_the_address_is_the_socket_peer_and_x_forwarded_for_is_ignored():
    app = RateLimitMiddleware(_ok_app, {"/api/event": Rate(1, 1)}, clock=Clock())
    spoof = [(b"x-forwarded-for", b"9.9.9.9")]
    assert (await _call(app, headers=spoof))["status"] == 200
    # a different claimed address does not buy a fresh bucket
    again = [(b"x-forwarded-for", b"8.8.8.8")]
    assert (await _call(app, headers=again))["status"] == 429


@pytest.mark.unit
async def test_a_client_ip_hook_can_name_the_address():
    def fly(scope):
        return dict(scope["headers"]).get(b"fly-client-ip", b"?").decode()

    app = RateLimitMiddleware(_ok_app, {"/api/event": Rate(1, 1)}, client_ip=fly, clock=Clock())
    a = [(b"fly-client-ip", b"1.2.3.4")]
    b = [(b"fly-client-ip", b"5.6.7.8")]
    assert (await _call(app, headers=a))["status"] == 200
    assert (await _call(app, headers=a))["status"] == 429
    assert (await _call(app, headers=b))["status"] == 200


@pytest.mark.unit
async def test_idle_buckets_are_pruned():
    clock = Clock()
    app = RateLimitMiddleware(
        _ok_app, {"/api/event": Rate(1, 2)}, clock=clock, max_buckets=5, prune_every=1
    )
    for i in range(20):
        await _call(app, client=(f"10.0.0.{i}", 1))
        clock.now += 10  # long enough for every earlier bucket to have refilled
    assert len(app._buckets) <= 6  # noqa: SLF001


@pytest.mark.unit
async def test_security_headers_default_replace_and_drop():
    plain = await _call(SecurityHeadersMiddleware(_ok_app))
    assert plain["headers"][b"x-content-type-options"] == b"nosniff"
    assert plain["headers"][b"x-frame-options"] == b"DENY"
    assert plain["headers"][b"referrer-policy"] == b"strict-origin-when-cross-origin"
    custom = await _call(
        SecurityHeadersMiddleware(_ok_app, {"X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": ""})
    )
    assert custom["headers"][b"x-frame-options"] == b"SAMEORIGIN"
    assert b"referrer-policy" not in custom["headers"]
    assert custom["headers"][b"x-content-type-options"] == b"nosniff"  # untouched default


@pytest.mark.unit
def test_stream_limiter_counts_per_address_and_releases_once():
    lim = StreamLimiter(2)
    assert lim.acquire("a") and lim.acquire("a")
    assert not lim.acquire("a")  # a third from the same address
    assert lim.acquire("b")
    lim.release("a")
    lim.release("a")  # idempotent per ticket is the caller's job; extra release floors at 0
    lim.release("a")
    assert lim.count("a") == 0 and lim.acquire("a")
    assert StreamLimiter(None).acquire("a")  # no cap: always yes


@pytest.mark.unit
def test_limits_defaults_are_all_unset_and_values_are_validated():
    d = Limits()
    assert (d.rate, d.max_event_bytes, d.max_upload_mb, d.max_streams_per_ip) == (None,) * 4
    assert (d.max_sessions, d.session_idle_seconds) == (None, None)
    for bad in (
        {"max_event_bytes": 0},
        {"max_streams_per_ip": 0},
        {"max_sessions": -1},
        {"rate": {"/api/event": Rate(0, 1)}},
        {"rate": {"api/event": Rate(1, 1)}},  # suffixes start with a slash
    ):
        with pytest.raises(ValueError):
            Limits(**bad)
    pub = Limits.public()
    assert pub.max_sessions == 200 and pub.session_idle_seconds == 1800
    assert set(pub.rate) == {"/api/event", "/api/upload", "/api/stream"}

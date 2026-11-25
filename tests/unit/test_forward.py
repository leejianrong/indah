"""The signed hint, the forward signature and the replay cache (IND-209, ADR-0043)."""

import time

import pytest

from indah.auth import Principal
from indah.forward import (
    HINT_MAX_AGE,
    PeerConfig,
    ReplayCache,
    forward_signature,
    is_peer_address,
    principal_blob,
    principal_from_blob,
    resolve_peers,
    sign_hint,
    verify_hint,
)

pytestmark = pytest.mark.unit
KEY = b"a-cluster-secret-of-some-length"


def test_a_good_hint_names_its_owner():
    hint = sign_hint(KEY, "10.1.2.3", 8000, time.time())
    assert verify_hint(KEY, hint, own_port=8000) == ("10.1.2.3", 8000)


@pytest.mark.parametrize(
    "address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "example.com", "0.0.0.0"]
)
def test_a_public_or_non_ip_address_is_refused_even_when_signed(address):
    assert not is_peer_address(address)
    assert verify_hint(KEY, sign_hint(KEY, address, 8000, time.time()), own_port=8000) is None


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "172.16.4.4", "192.168.1.9", "169.254.1.1", "127.0.0.1", "fd00::5"]
)
def test_private_and_link_local_addresses_are_accepted(address):
    assert is_peer_address(address)


def test_tamper_wrong_key_wrong_port_and_age_are_refused():
    now = time.time()
    hint = sign_hint(KEY, "10.1.2.3", 8000, now)
    body, mac = hint.split(".")
    assert verify_hint(KEY, hint, own_port=9000) is None  # not this app's port
    assert verify_hint(b"another-secret-entirely-here", hint, own_port=8000) is None
    assert (
        verify_hint(KEY, sign_hint(KEY, "10.1.2.3", 8000, now - HINT_MAX_AGE - 5), own_port=8000)
        is None
    )
    assert verify_hint(KEY, sign_hint(KEY, "10.1.2.3", 8000, now + 3600), own_port=8000) is None
    forged = (
        sign_hint(KEY, "10.9.9.9", 8000, now).split(".")[0] + "." + mac
    )  # a payload with a stolen mac
    assert verify_hint(KEY, forged, own_port=8000) is None
    for junk in ("", ".", "a.b", body, hint + "x", "!!!.???"):
        assert verify_hint(KEY, junk, own_port=8000) is None


def test_the_principal_survives_the_blob():
    p = Principal(
        id="u1",
        name="Ada",
        email="a@x.y",
        roles={"admin", "dev"},
        workspace="w",
        claims={"team": ["a", "b"]},
        expires_at=time.time() + 60,
    )
    back = principal_from_blob(principal_blob(p))
    assert back == p
    assert principal_from_blob(principal_blob(None)) is None


def test_the_signature_covers_every_part():
    base = dict(
        timestamp="1",
        nonce="n",
        sender="a",
        kind="event",
        content_type="application/json",
        body=b"{}",
        blob="",
    )
    sig = forward_signature(KEY, **base)
    assert forward_signature(KEY, **base) == sig
    for field, other in (
        ("timestamp", "2"),
        ("nonce", "m"),
        ("sender", "b"),
        ("kind", "upload"),
        ("content_type", "text/plain"),
        ("body", b"{ }"),
        ("blob", "x"),
    ):
        assert forward_signature(KEY, **{**base, field: other}) != sig
    assert forward_signature(b"different-key-different-key", **base) != sig


def test_a_signature_is_good_once():
    cache = ReplayCache(window=60)
    assert cache.seen("s1", now=0) is False
    assert cache.seen("s1", now=10) is True
    assert (
        cache.seen("s1", now=100) is False
    )  # forgotten after the window (the timestamp window refuses it)


def test_the_replay_cache_is_bounded():
    cache = ReplayCache(window=1000, limit=10)
    for n in range(50):
        cache.seen(f"s{n}", now=n)
    assert len(cache._seen) <= 10


def test_forwarding_needs_peers_and_a_cluster_secret_and_a_private_address():
    env = {"INDAH_ADVERTISE_ADDRESS": "10.0.0.7"}
    assert resolve_peers(None, None, env) is None  # no peers
    assert resolve_peers("self", None, env) is None  # no secret: stays off
    got = resolve_peers("self", "s3cret-s3cret-s3cret", env)
    assert (got.address, got.port, got.timeout) == ("10.0.0.7", 8000, 2.0)
    with pytest.raises(ValueError, match="private address"):
        resolve_peers("self", "s3cret-s3cret-s3cret", {"INDAH_ADVERTISE_ADDRESS": "8.8.8.8"})
    with pytest.raises(ValueError, match="INDAH_PEER_PORT"):
        resolve_peers("self", "s3cret-s3cret-s3cret", {**env, "INDAH_PEER_PORT": "abc"})
    env2 = {
        **env,
        "INDAH_PEERS": "app-headless",
        "INDAH_PEER_PORT": "9000",
        "INDAH_FORWARD_TIMEOUT": "0.5",
    }
    got = resolve_peers(None, "s3cret-s3cret-s3cret", env2)
    assert (got.peers, got.port, got.timeout) == ("app-headless", 9000, 0.5)
    cfg = PeerConfig(peers="x", address="10.0.0.8", port=7, timeout=1)
    assert resolve_peers(cfg, "s3cret-s3cret-s3cret", {}).port == 7

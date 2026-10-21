"""Trusted-proxy handling (ADR-0034, IND-116) as pure functions: who the client really is,
and which forwarded prefix is safe to believe."""

import pytest

from indah.proxy import client_from_forwarded, parse_trusted, safe_prefix

TRUSTED = parse_trusted(["10.0.0.0/8", "192.168.1.7"])


@pytest.mark.unit
def test_trusted_proxies_accept_ips_and_cidrs_and_refuse_wildcards_and_junk():
    assert parse_trusted(None) == () and parse_trusted([]) == ()
    assert len(TRUSTED) == 2
    for bad in ["*", "0.0.0.0/0", "::/0", "not-an-ip", "10.0.0.0/33", ""]:
        with pytest.raises(ValueError, match="trusted_proxies"):
            parse_trusted([bad])


@pytest.mark.unit
def test_the_client_is_the_rightmost_address_that_is_not_a_trusted_proxy():
    # left of the first untrusted hop is whatever the client claimed: never believed
    xff = "6.6.6.6, 203.0.113.9, 10.1.1.1, 10.2.2.2"
    assert client_from_forwarded(xff, TRUSTED) == "203.0.113.9"
    assert client_from_forwarded("203.0.113.9", TRUSTED) == "203.0.113.9"
    assert client_from_forwarded("203.0.113.9, 192.168.1.7", TRUSTED) == "203.0.113.9"


@pytest.mark.unit
@pytest.mark.parametrize(
    "xff", ["", "10.1.1.1", "garbage", "203.0.113.9, garbage", "203.0.113.9, , 10.0.0.2", None]
)
def test_unusable_forwarded_for_gives_no_client(xff):
    # all trusted, empty, or an unparseable hop on the way: do not guess, keep the peer
    assert client_from_forwarded(xff, TRUSTED) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [("/ui", "/ui"), ("/ui/", "/ui"), ("/a/b-c_d.e", "/a/b-c_d.e"), ("/", ""), ("", "")],
)
def test_a_forwarded_prefix_is_a_plain_absolute_path(raw, expected):
    assert safe_prefix(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "ui",
        "//evil.example",
        "/a/../b",
        "/a/./b",
        "/x?y=1",
        "/x#f",
        "/a b",
        "/a//b",
        "/‮",
        "/" + "a" * 300,
        "http://x",
        "/a\\b",
    ],
)
def test_anything_else_is_ignored_rather_than_repaired(raw):
    assert safe_prefix(raw) == ""

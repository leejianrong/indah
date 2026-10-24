"""trusted_proxies presets (IND-204): names that expand to explicit, documented lists.

A preset is shorthand for a list you could have typed. It is never automatic ("auto" and "*" are
refused), it composes with explicit entries, and the expansion is a plain list of IPs and CIDRs
that ``parse_trusted`` accepts. Nothing here touches the network except the one DNS lookup the
``fly`` preset makes, and the tests inject that.
"""

import ipaddress
from datetime import date

import pytest

from indah import cloudflare_ips
from indah.proxy import parse_trusted
from indah.proxy_presets import (
    PRESET_NAMES,
    PRIVATE,
    check_entries,
    expand_trusted,
    fly_gap,
)

FLY_V4 = "66.241.124.81"
FLY_V6 = "2a09:8280:1::1c9:9684:0"


def _no_dns(host):
    raise AssertionError(f"unexpected DNS lookup for {host}")


@pytest.mark.unit
def test_the_preset_names_are_the_documented_four():
    assert PRESET_NAMES == ("cloudflare", "fly", "k8s", "private")


@pytest.mark.unit
def test_private_is_rfc1918_only():
    assert expand_trusted(["private"], environ={}, resolve=_no_dns).entries == (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    )
    assert PRIVATE == ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


@pytest.mark.unit
def test_k8s_adds_the_cgnat_and_unique_local_ranges_to_private():
    got = expand_trusted(["k8s"], environ={}, resolve=_no_dns).entries
    assert got == (*PRIVATE, "100.64.0.0/10", "fc00::/7")


@pytest.mark.unit
def test_cloudflare_expands_to_the_vendored_list():
    got = expand_trusted(["cloudflare"], environ={}, resolve=_no_dns).entries
    assert got == tuple(cloudflare_ips.IPV4 + cloudflare_ips.IPV6)
    assert len(parse_trusted(got)) == len(got)


@pytest.mark.unit
def test_fly_is_the_private_range_plus_the_ips_in_indah_fly_ips():
    env = {"INDAH_FLY_IPS": f"{FLY_V4}, {FLY_V6}"}
    got = expand_trusted(["fly"], environ=env, resolve=_no_dns)
    assert got.entries == ("172.16.0.0/12", FLY_V4, FLY_V6)
    assert got.presets == ("fly",)


@pytest.mark.unit
def test_fly_without_the_variable_resolves_the_apps_own_hostname():
    asked = []

    def resolve(host):
        asked.append(host)
        return [FLY_V6, FLY_V4]

    got = expand_trusted(["fly"], environ={"FLY_APP_NAME": "indah-probe"}, resolve=resolve)
    assert asked == ["indah-probe.fly.dev"]
    assert got.entries == ("172.16.0.0/12", FLY_V6, FLY_V4)


@pytest.mark.unit
def test_indah_fly_ips_wins_over_dns():
    env = {"FLY_APP_NAME": "indah-probe", "INDAH_FLY_IPS": FLY_V4}
    got = expand_trusted(["fly"], environ=env, resolve=_no_dns)
    assert got.entries == ("172.16.0.0/12", FLY_V4)


@pytest.mark.unit
def test_fly_that_cannot_find_the_ips_says_what_to_run_and_what_to_set():
    for env, resolve in [
        ({}, _no_dns),  # not on Fly, no variable
        ({"FLY_APP_NAME": "indah-probe"}, lambda host: []),  # DNS gave nothing
        ({"FLY_APP_NAME": "indah-probe"}, lambda host: (_ for _ in ()).throw(OSError("no dns"))),
    ]:
        with pytest.raises(ValueError) as err:
            expand_trusted(["fly"], environ=env, resolve=resolve)
        text = str(err.value)
        assert "fly ips list" in text
        assert "INDAH_FLY_IPS" in text
        assert 'trusted_proxies=["fly"' in text


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["not-an-ip", "0.0.0.0/0", "10.0.0.0/8", "::/0"])
def test_a_bad_indah_fly_ips_is_refused_and_names_the_variable(bad):
    # public ingress addresses are single IPs: a network here would trust far too much
    with pytest.raises(ValueError, match="INDAH_FLY_IPS"):
        expand_trusted(["fly"], environ={"INDAH_FLY_IPS": bad}, resolve=_no_dns)


@pytest.mark.unit
def test_presets_compose_with_explicit_entries_without_duplicates():
    env = {"INDAH_FLY_IPS": FLY_V4}
    got = expand_trusted(
        ["fly", "172.16.0.0/12", "203.0.113.7", "private"], environ=env, resolve=_no_dns
    )
    assert got.entries == (
        "172.16.0.0/12",
        FLY_V4,
        "203.0.113.7",
        "10.0.0.0/8",
        "192.168.0.0/16",
    )
    assert got.presets == ("fly", "private")


@pytest.mark.unit
def test_a_bare_string_is_one_entry_or_a_comma_list():
    assert expand_trusted("private", environ={}, resolve=_no_dns).entries == PRIVATE
    got = expand_trusted("private, 203.0.113.7", environ={}, resolve=_no_dns)
    assert got.entries == (*PRIVATE, "203.0.113.7")


@pytest.mark.unit
def test_names_are_case_insensitive_and_plain_entries_pass_through():
    got = expand_trusted(["K8S", "203.0.113.0/24"], environ={}, resolve=_no_dns)
    assert got.presets == ("k8s",)
    assert got.entries[-1] == "203.0.113.0/24"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["auto", "AUTO", "*", "cloudflair", "all"])
def test_auto_wildcard_and_unknown_names_are_refused_with_the_valid_list(name):
    with pytest.raises(ValueError) as err:
        expand_trusted([name], environ={}, resolve=_no_dns)
    text = str(err.value)
    for preset in PRESET_NAMES:
        assert preset in text


@pytest.mark.unit
def test_auto_is_refused_for_a_reason_the_message_gives():
    with pytest.raises(ValueError, match="spoof"):
        expand_trusted(["auto"], environ={}, resolve=_no_dns)


@pytest.mark.unit
def test_a_wildcard_network_is_still_refused_by_parse_trusted_after_expansion():
    got = expand_trusted(["0.0.0.0/0"], environ={}, resolve=_no_dns).entries
    with pytest.raises(ValueError, match="trust every address"):
        parse_trusted(got)


@pytest.mark.unit
def test_check_entries_validates_without_resolving_anything():
    check_entries(["fly", "cloudflare", "k8s", "private", "10.0.0.0/8"])  # no DNS, no env
    with pytest.raises(ValueError, match="auto"):
        check_entries(["auto"])
    with pytest.raises(ValueError, match="not an IP"):
        check_entries(["10.0.0.0/33"])


@pytest.mark.unit
def test_fly_gap_names_the_public_ips_the_list_does_not_cover():
    resolve = lambda host: [FLY_V4, FLY_V6]  # noqa: E731
    env = {"FLY_APP_NAME": "indah-probe"}
    # the classic mistake: only the private range
    assert fly_gap(["172.16.0.0/12"], environ=env, resolve=resolve) == (FLY_V4, FLY_V6)
    # one covered, one not
    assert fly_gap(["172.16.0.0/12", FLY_V4], environ=env, resolve=resolve) == (FLY_V6,)
    # covered by a network entry
    assert fly_gap(["172.16.0.0/12", "66.241.124.0/24", FLY_V6], environ=env, resolve=resolve) == ()
    # not on Fly: never asks DNS
    assert fly_gap(["172.16.0.0/12"], environ={}, resolve=_no_dns) == ()
    # on Fly but with no trusted_proxies: the IND-200 warning covers that case
    assert fly_gap([], environ=env, resolve=_no_dns) == ()
    # DNS down: say nothing rather than guess
    assert fly_gap(["172.16.0.0/12"], environ=env, resolve=lambda host: []) == ()


@pytest.mark.unit
def test_the_vendored_cloudflare_list_is_well_formed():
    entries = cloudflare_ips.IPV4 + cloudflare_ips.IPV6
    assert len(cloudflare_ips.IPV4) >= 10 and len(cloudflare_ips.IPV6) >= 5
    for entry in entries:
        net = ipaddress.ip_network(entry)  # strict: a malformed or host-bit entry raises
        assert net.prefixlen > 0
    assert all(ipaddress.ip_network(e).version == 4 for e in cloudflare_ips.IPV4)
    assert all(ipaddress.ip_network(e).version == 6 for e in cloudflare_ips.IPV6)
    assert cloudflare_ips.SOURCE.startswith("https://www.cloudflare.com/ips")


@pytest.mark.unit
def test_the_vendored_cloudflare_list_is_not_older_than_a_year():
    fetched = date.fromisoformat(cloudflare_ips.FETCHED)
    age = (date.today() - fetched).days
    assert 0 <= age <= 365, (
        f"the Cloudflare ranges in indah/cloudflare_ips.py were fetched {age} days ago "
        "(on " + cloudflare_ips.FETCHED + "): run `python scripts/refresh_cloudflare_ips.py`, "
        "review the diff and commit it"
    )

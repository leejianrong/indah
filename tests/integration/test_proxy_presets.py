"""trusted_proxies presets through create_app (IND-204, IND-198).

The unit tests cover the expansion. These check the wiring: a preset reaches the proxy handling
as an explicit list, the environment variable accepts names, the Fly case resolves the real
visitor (the measured IND-170 facts), and the Fly mistake is called out at startup.
"""

import logging

import httpx
import pytest

import indah
from indah import create_app
from indah.components import Button, Column, Text
from indah.proxy import parse_trusted
from indah.proxy_presets import PRIVATE
from indah.session import Session

FLY_V4 = "66.241.124.81"
FLY_V6 = "2a09:8280:1::1c9:9684:0"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("INDAH_TRUSTED_PROXIES", "INDAH_FLY_IPS", "FLY_APP_NAME"):
        monkeypatch.delenv(name, raising=False)


def _client(app, peer) -> httpx.AsyncClient:
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


@pytest.mark.integration
def test_a_preset_reaches_the_proxy_handling_as_an_explicit_list():
    app = indah.create_app(trusted_proxies=["private", "203.0.113.7"])
    assert app.state.trusted_proxies == parse_trusted([*PRIVATE, "203.0.113.7"])
    assert app.state.trusted_proxies_presets == ("private",)


@pytest.mark.integration
def test_no_preset_means_nothing_changes():
    app = indah.create_app()
    assert app.state.trusted_proxies == ()
    assert app.state.trusted_proxies_presets == ()
    other = indah.create_app(trusted_proxies=["10.0.0.0/8"])
    assert other.state.trusted_proxies_presets == ()


@pytest.mark.integration
def test_a_bare_string_works_and_presets_are_logged_by_name_only(caplog):
    with caplog.at_level(logging.INFO, logger="indah"):
        app = indah.create_app(trusted_proxies="k8s")
    assert app.state.trusted_proxies_presets == ("k8s",)
    messages = [r.getMessage() for r in caplog.records if "preset" in r.getMessage()]
    assert messages and "k8s" in messages[0]
    assert "10.0.0.0/8" not in messages[0]  # names and a count, not the list


@pytest.mark.integration
@pytest.mark.parametrize("bad", ["auto", "*", "nonsense"])
def test_create_app_refuses_auto_wildcard_and_unknown_names(bad):
    with pytest.raises(ValueError, match="fly, k8s, private"):
        indah.create_app(trusted_proxies=[bad])


@pytest.mark.integration
def test_the_environment_variable_accepts_preset_names(monkeypatch):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", "cloudflare, 203.0.113.7")
    app = indah.create_app()
    assert app.state.trusted_proxies_presets == ("cloudflare",)
    assert parse_trusted(["203.0.113.7"])[0] in app.state.trusted_proxies
    assert "INDAH_TRUSTED_PROXIES" in app.state.env_used


@pytest.mark.integration
@pytest.mark.parametrize("value", ["auto", "private, *", "fly-ish"])
def test_the_environment_variable_still_refuses_the_same_things(monkeypatch, value):
    monkeypatch.setenv("INDAH_TRUSTED_PROXIES", value)
    with pytest.raises(ValueError, match="INDAH_TRUSTED_PROXIES"):
        indah.create_app()


@pytest.mark.integration
async def test_the_fly_preset_resolves_the_real_visitor_and_ignores_a_forged_hop(monkeypatch):
    # the measured IND-170 facts: Fly's proxy is the peer (172.16.x), and the forwarded list ends
    # with the app's own ingress address, which must be trusted too or it is taken for the client
    monkeypatch.setenv("INDAH_FLY_IPS", f"{FLY_V4},{FLY_V6}")
    app, seen = _capture_app(trusted_proxies=["fly"])
    async with _client(app, peer="172.16.1.226") as client:
        headers = {"X-Forwarded-For": f"122.11.212.50, {FLY_V4}", "X-Forwarded-Proto": "https"}
        assert (await _click(client, headers=headers)).status_code == 200
        forged = {"X-Forwarded-For": f"6.6.6.6, 122.11.212.50, {FLY_V4}"}
        assert (await _click(client, sid="t2", headers=forged)).status_code == 200
    assert seen[0].client == "122.11.212.50"
    assert seen[1].client == "122.11.212.50"  # not the 6.6.6.6 the visitor prepended


@pytest.mark.integration
async def test_the_private_range_alone_on_fly_is_the_mistake_the_preset_fixes():
    app, seen = _capture_app(trusted_proxies=["172.16.0.0/12"])
    async with _client(app, peer="172.16.1.226") as client:
        headers = {"X-Forwarded-For": f"122.11.212.50, {FLY_V4}"}
        assert (await _click(client, headers=headers)).status_code == 200
    assert seen[0].client == FLY_V4  # every visitor looks like the ingress address


@pytest.mark.integration
def test_fly_without_its_ips_fails_at_startup_with_what_to_run(monkeypatch):
    monkeypatch.setattr("indah.proxy_presets._resolve_dns", lambda host: [])
    monkeypatch.setenv("FLY_APP_NAME", "my-app")
    with pytest.raises(ValueError) as err:
        indah.create_app(trusted_proxies=["fly"])
    text = str(err.value)
    assert "fly ips list -a my-app" in text and "INDAH_FLY_IPS" in text


@pytest.mark.integration
def test_the_fly_preset_asks_dns_for_the_apps_hostname(monkeypatch):
    asked = []

    def resolve(host):
        asked.append(host)
        return [FLY_V6, FLY_V4]

    monkeypatch.setattr("indah.proxy_presets._resolve_dns", resolve)
    monkeypatch.setenv("FLY_APP_NAME", "indah-probe")
    app = indah.create_app(trusted_proxies=["fly"])
    assert asked == ["indah-probe.fly.dev"]
    assert parse_trusted([FLY_V4])[0] in app.state.trusted_proxies


@pytest.mark.integration
def test_trusting_only_the_private_range_on_fly_warns_at_startup(monkeypatch, caplog):
    monkeypatch.setattr("indah.proxy_presets._resolve_dns", lambda host: [FLY_V4, FLY_V6])
    monkeypatch.setenv("FLY_APP_NAME", "indah-probe")
    with caplog.at_level(logging.WARNING, logger="indah"):
        indah.create_app(trusted_proxies=["172.16.0.0/12"])
    found = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(found) == 1
    text = found[0]
    assert FLY_V4 in text and "trusted_proxies" in text
    assert 'trusted_proxies=["fly"]' in text  # the fix, spelled out
    assert "rate-limit bucket" in text


@pytest.mark.integration
def test_no_gap_warning_when_the_list_covers_the_ingress_or_off_fly(monkeypatch, caplog):
    monkeypatch.setattr("indah.proxy_presets._resolve_dns", lambda host: [FLY_V4, FLY_V6])
    with caplog.at_level(logging.WARNING, logger="indah"):
        indah.create_app(trusted_proxies=["172.16.0.0/12"])  # not on Fly: no FLY_APP_NAME
        monkeypatch.setenv("FLY_APP_NAME", "indah-probe")
        indah.create_app(trusted_proxies=["172.16.0.0/12", FLY_V4, FLY_V6])
        monkeypatch.setenv("INDAH_FLY_IPS", f"{FLY_V4},{FLY_V6}")
        indah.create_app(trusted_proxies=["fly"])
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


@pytest.mark.integration
def test_the_untrusted_forwarding_warning_names_the_presets_and_the_fly_fix(caplog, monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setenv("FLY_APP_NAME", "indah-probe")
    app = indah.create_app()
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(app) as client:
            client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    found = [r.getMessage() for r in caplog.records if "trusted_proxies" in r.getMessage()]
    assert len(found) == 1
    assert 'trusted_proxies=["fly"]' in found[0]
    assert "203.0.113.9" not in found[0]  # still never a header value
    other = indah.create_app()
    monkeypatch.delenv("FLY_APP_NAME")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="indah"):
        with TestClient(other) as client:
            client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
    found = [r.getMessage() for r in caplog.records if "trusted_proxies" in r.getMessage()]
    assert "cloudflare" in found[0] and "k8s" in found[0]  # the presets, off Fly too

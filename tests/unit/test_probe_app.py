"""The IND-170/IND-171 probe (deploy/probe): its facts are only worth reading if they are right."""

import importlib.util
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit

PROBE = Path(__file__).resolve().parents[2] / "deploy" / "probe"


def load(monkeypatch, trusted: str):
    monkeypatch.setenv("PROBE_TRUSTED_PROXIES", trusted)
    monkeypatch.setenv("FLY_MACHINE_ID", "m-test")
    spec = importlib.util.spec_from_file_location("probe_app_under_test", PROBE / "probe_app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def whoami(module, peer: str, headers: dict[str, str]) -> dict:
    client = TestClient(module.app, client=(peer, 1234))
    response = client.get("/whoami", headers=headers)
    assert response.status_code == 200
    assert response.headers["x-probe-machine"] == "m-test"
    return response.json()


def test_nothing_is_believed_by_default(monkeypatch):
    probe = load(monkeypatch, "")
    got = whoami(probe, "172.16.1.2", {"x-forwarded-for": "9.9.9.9, 66.1.1.1"})
    assert got["resolved_client"] == "172.16.1.2"
    assert got["socket_peer"] == "172.16.1.2"
    assert got["trusted_proxies"] == []


def test_the_rightmost_untrusted_hop_is_the_client(monkeypatch):
    probe = load(monkeypatch, "172.16.0.0/12,66.1.1.1")
    got = whoami(
        probe,
        "172.16.1.2",
        {"x-forwarded-for": "6.6.6.6, 122.1.2.3, 66.1.1.1", "x-forwarded-proto": "https"},
    )
    assert got["resolved_client"] == "122.1.2.3"  # not the spoofed 6.6.6.6
    assert got["resolved_scheme"] == "https"
    assert got["socket_peer"] == "172.16.1.2"  # the real peer survives the rewrite


def test_trusting_only_the_private_range_picks_the_ingress_address(monkeypatch):
    """What Fly really sends: XFF is "<client>, <app ingress ip>" (IND-170)."""
    probe = load(monkeypatch, "172.16.0.0/12")
    got = whoami(probe, "172.16.1.2", {"x-forwarded-for": "122.1.2.3, 66.241.124.81"})
    assert got["resolved_client"] == "66.241.124.81"


def test_a_client_cannot_fake_the_probe_headers(monkeypatch):
    probe = load(monkeypatch, "")
    got = whoami(probe, "203.0.113.5", {"x-probe-raw-peer": "evil", "x-probe-raw-scheme": "evil"})
    assert got["socket_peer"] == "203.0.113.5"
    assert got["socket_scheme"] == "http"


def test_only_allowlisted_headers_are_echoed(monkeypatch):
    probe = load(monkeypatch, "")
    got = whoami(probe, "203.0.113.5", {"cookie": "secret=1", "authorization": "Bearer x"})
    assert "cookie" not in got["headers"] and "authorization" not in got["headers"]


def test_the_page_builds_and_a_wildcard_is_refused(monkeypatch):
    probe = load(monkeypatch, "172.16.0.0/12")
    assert TestClient(probe.app, client=("172.16.1.2", 1)).get("/").status_code == 200
    with pytest.raises(ValueError):
        load(monkeypatch, "*")


def test_the_sticky_check_finds_the_button():
    spec = importlib.util.spec_from_file_location("sticky_check", PROBE / "sticky_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = {
        "id": "n0",
        "type": "column",
        "children": [{"id": "n3", "type": "button", "props": {"label": "Send an event"}}],
    }
    assert module.find_button(tree, "Send an event") == "n3"
    assert module.find_button(tree, "Other") is None
